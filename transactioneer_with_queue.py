import requests
import time
import json
import os
from web3 import Web3, HTTPProvider
import logging
import threading
from collections import defaultdict
import queue

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Optimal delay for high-speed transaction submission
INTER_TX_DELAY = 0.02  # 20 milliseconds (50 TPS max)
NONCE_REALIGNMENT_ITERATIONS = 10000
MAX_ACCOUNTS_TO_USE = 2000

class ExordeHighSpeedSender:
    def __init__(self):
        # Configuration
        self.accounts_folder = "exorde_accounts"
        self.accounts_file = os.path.join(self.accounts_folder, "accounts.json")
        self.dataspotting_address = "0xC9FCBEd3a27666c539EE00f7a3D2b3ae6F0fa22E"
        
        # Transaction settings
        self.gas_limit = 800_000
        self.gas_price = 200_000 
        
        # Network configuration
        self.sync_nodes = []
        self.w3_instances = []
        self.chain_id = None
        self.abi_dataspotting = None
        
        # Contract instances
        self.contracts = {}
        
        # Round robin management
        self.accounts = []
        self.current_account_index = 0
        self.current_sync_node_index = 0
        self.account_nonces = defaultdict(int)
        
        # Thread safety
        self.account_lock = threading.Lock()
        self.sync_node_lock = threading.Lock()
        self.nonce_locks = defaultdict(threading.Lock)
        
        # Transaction queue - NEW: Replace hardcoded parameters
        self.transaction_queue = queue.Queue(maxsize=1000000)

        self.queue_empty_timeout = 1.0  # Seconds to wait when queue is empty
        self.running = False
        
        # Performance tracking (submission-based, not confirmation-based)
        self.submissions_count = 0
        self.successful_submissions = 0
        self.failed_submissions = 0
        self.start_time = None
        self.last_nonce_check = 0
        self.nonce_realignments = 0

    def add_transaction(self, file_hashs, url_domains, item_counts, extra=""):
        """
        External interface to add a transaction to the queue
        
        Args:
            file_hashs (list): List of file hashes
            url_domains (list): List of URL domains  
            item_counts (list): List of item counts
            extra (str): Extra data string
        """
        transaction_params = {
            'file_hashs': file_hashs,
            'url_domains': url_domains,
            'item_counts': item_counts,
            'extra': extra
        }
        self.transaction_queue.put(transaction_params)
        logger.info(f"📥 Added transaction to queue. Queue size: {self.transaction_queue.qsize()}")

    def add_transactions_batch(self, transactions_list):
        """
        Add multiple transactions at once
        
        Args:
            transactions_list (list): List of transaction parameter dictionaries
        """
        for tx_params in transactions_list:
            self.transaction_queue.put(tx_params)
        logger.info(f"📥 Added {len(transactions_list)} transactions to queue. Queue size: {self.transaction_queue.qsize()}")

    def get_queue_size(self):
        """Get current queue size"""
        return self.transaction_queue.qsize()

    def initialize_sync_nodes(self):
        """Initialize all sync nodes from network config"""
        try:
            logger.info("🔄 Fetching network configuration...")
            net_configs = requests.get(
                "https://raw.githubusercontent.com/exorde-labs/TestnetProtocol/main/NetworkConfig.json",
                timeout=30
            ).json()
            
            # Extract sync nodes for testnet-A
            for network in net_configs['testnet']:
                if network['_networkId'] == 'testnet-A':
                    self.chain_id = network['_chainID']
                    
                    # Collect all sync nodes
                    for key in network:
                        if "_urlSkale" in key:
                            self.sync_nodes.append(network[key])
                    break
            
            logger.info(f"🌐 Initialized {len(self.sync_nodes)} sync nodes")
            logger.info(f"⛓️  Chain ID: {self.chain_id}")
            
            # Initialize Web3 instances
            for node_url in self.sync_nodes:
                w3 = Web3(Web3.HTTPProvider(node_url))
                self.w3_instances.append(w3)
                
        except Exception as e:
            logger.error(f"❌ Failed to initialize sync nodes: {e}")
            raise

    def initialize_dataspotting_contract(self):
        """Initialize DataSpotting contract with ABI"""
        try:
            logger.info("📄 Fetching DataSpotting contract ABI...")
            
            # Fetch ABI
            abi_response = requests.get(
                "https://raw.githubusercontent.com/exorde-labs/TestnetProtocol/main/ABIs/DataSpotting.sol/DataSpotting.json",
                timeout=30
            )
            
            if abi_response.status_code == 200:
                self.abi_dataspotting = abi_response.json()
            else:
                # Fallback ABI
                self.abi_dataspotting = {
                    "abi": [
                        {
                            "inputs": [
                                {"name": "file_hashs_", "type": "string[]"},
                                {"name": "URL_domains_", "type": "string[]"},
                                {"name": "item_counts_", "type": "uint64[]"},
                                {"name": "extra_", "type": "string"}
                            ],
                            "name": "SpotData",
                            "outputs": [],
                            "stateMutability": "nonpayable",
                            "type": "function"
                        }
                    ]
                }
            
            # Initialize contract instances
            self.contracts["DataSpotting"] = []
            for w3 in self.w3_instances:
                contract = w3.eth.contract(
                    address=w3.to_checksum_address(self.dataspotting_address),
                    abi=self.abi_dataspotting.get('abi', self.abi_dataspotting)
                )
                self.contracts["DataSpotting"].append(contract)
            
            logger.info("✅ DataSpotting contract initialized")
            
        except Exception as e:
            logger.error(f"❌ Failed to initialize contract: {e}")
            raise

    def load_accounts(self):
        """Load funded accounts"""
        try:
            with open(self.accounts_file, 'r') as f:
                self.accounts = json.load(f)
                # cut to MAX_ACCOUNTS_TO_USE first accounts
                self.accounts = self.accounts[:MAX_ACCOUNTS_TO_USE]
            
            logger.info(f"📋 Loaded {len(self.accounts)} accounts for high-speed submission")
            
        except Exception as e:
            logger.error(f"❌ Failed to load accounts: {e}")
            raise

    def initialize_nonces(self):
        """Initialize nonces for all accounts"""
        logger.info("🔢 Initializing account nonces...")
        
        for account in self.accounts:
            address = account['address']
            try:
                w3 = self.get_next_sync_node()
                current_nonce = w3.eth.get_transaction_count(address)
                self.account_nonces[address] = current_nonce
            except Exception as e:
                logger.error(f"❌ Failed to get nonce for {address}: {e}")
                self.account_nonces[address] = 0
        
        logger.info(f"✅ Initialized nonces for {len(self.accounts)} accounts")

    def realign_all_nonces(self):
        """Realign nonces with blockchain state every 100 transactions"""
        logger.info("🔄 Performing nonce realignment...")
        # first we wait 30s to let the network catch up
        logger.info("   ⏳ Waiting for network to catch up before realigning nonces...")
        time.sleep(30)
        logger.info("   🔄 Realigning nonces with blockchain state...")
        
        realigned_accounts = 0
        for account in self.accounts:
            address = account['address']
            try:
                w3 = self.get_next_sync_node()
                blockchain_nonce = w3.eth.get_transaction_count(address)
                
                with self.nonce_locks[address]:
                    local_nonce = self.account_nonces[address]
                    
                    if blockchain_nonce != local_nonce:
                        logger.info(f"   📍 Account {account['index']:02d}: {local_nonce} → {blockchain_nonce}")
                        self.account_nonces[address] = blockchain_nonce
                        realigned_accounts += 1
                        
            except Exception as e:
                logger.error(f"❌ Failed to realign nonce for {address}: {e}")
        
        self.nonce_realignments += 1
        if realigned_accounts > 0:
            logger.info(f"✅ Realigned {realigned_accounts} accounts")
        else:
            logger.info("✅ All nonces already aligned")

    def get_next_account(self):
        """Get next account using round robin"""
        with self.account_lock:
            account = self.accounts[self.current_account_index]
            self.current_account_index = (self.current_account_index + 1) % len(self.accounts)
            return account

    def get_next_sync_node(self):
        """Get next sync node using round robin"""
        with self.sync_node_lock:
            w3 = self.w3_instances[self.current_sync_node_index]
            self.current_sync_node_index = (self.current_sync_node_index + 1) % len(self.w3_instances)
            return w3

    def get_next_contract(self):
        """Get next contract instance using round robin"""
        with self.sync_node_lock:
            contract = self.contracts["DataSpotting"][self.current_sync_node_index]
            return contract

    def get_next_nonce(self, address):
        """Get next nonce for account"""
        with self.nonce_locks[address]:
            current_nonce = self.account_nonces[address]
            self.account_nonces[address] += 1
            return current_nonce

    def submit_spotdata_transaction(self, account, transaction_params, max_retries=3):
        """Submit SpotData transaction with sync node retry mechanism"""
        try:
            address = account['address']
            private_key = account['private_key']
            index = account['index']
            
            # Get nonce and contract
            nonce = self.get_next_nonce(address)
            contract = self.get_next_contract()
            
            # Get dynamic gas price
            w3_read = self.get_next_sync_node()
            
            # Build transaction with parameters from queue
            transaction = contract.functions.SpotData(
                transaction_params['file_hashs'],
                transaction_params['url_domains'], 
                transaction_params['item_counts'],
                transaction_params['extra']
            ).build_transaction({
                'from': address,
                'nonce': nonce,
                'value': 0,
                'gas': self.gas_limit,
                'gasPrice': self.gas_price,
                'chainId': int(self.chain_id)
            })
            
            # Sign transaction once
            signed_tx = w3_read.eth.account.sign_transaction(transaction, private_key)
            
            # Try up to max_retries different sync nodes
            last_error = None
            for retry_attempt in range(max_retries):
                try:
                    # Get different sync node for each attempt
                    w3_write = self.get_next_sync_node()
                    
                    # Attempt submission
                    tx_hash = w3_write.eth.send_raw_transaction(signed_tx.rawTransaction)
                            
                    print(f"✅ Submitted transaction from account {index:02d}: {tx_hash.hex()}")
                    
                    # Success - update counters and return
                    self.submissions_count += 1
                    self.successful_submissions += 1
                    
                    if retry_attempt > 0:
                        logger.info(f"✅ Account {index:02d} succeeded on retry {retry_attempt + 1}")
                    
                    return True, tx_hash.hex()
                    
                except Exception as e:
                    last_error = e
                    error_msg = str(e)
                    
                    # Check if it's a nonce collision error
                    if "same nonce already exists" in error_msg:
                        if retry_attempt < max_retries - 1:
                            logger.warning(f"⚠️  Account {index:02d} nonce collision on sync node {retry_attempt + 1}, trying next node...")
                            continue  # Try next sync node
                        else:
                            logger.error(f"❌ Account {index:02d} nonce collision on all {max_retries} sync nodes")
                    else:
                        # Non-nonce error, don't retry
                        logger.error(f"❌ Account {index:02d} non-nonce error: {error_msg}")
                        break
            
            # All retries failed
            self.failed_submissions += 1
            return False, None
            
        except Exception as e:
            self.failed_submissions += 1
            logger.error(f"❌ Transaction building failed for account {index:02d}: {e}")
            return False, None

    def run_high_speed_loop(self, num_transactions=None, delay=INTER_TX_DELAY):
        """Main high-speed transaction submission loop - now queue-driven"""
        logger.info("🚀 Starting queue-driven high-speed transaction submission...")
        
        self.start_time = time.time()
        self.running = True
        
        print("\n" + "="*80)
        print("⚡ QUEUE-DRIVEN HIGH-SPEED TRANSACTION SUBMISSION")
        print("="*80)
        print(f"📄 Contract: DataSpotting SpotData")
        print(f"👥 Accounts: {len(self.accounts)} in round robin")
        print(f"🌐 Sync nodes: {len(self.sync_nodes)} in round robin")
        print(f"⏱️  Submission delay: {delay*1000:.0f}ms")
        print(f"🔄 Nonce realignment: every {NONCE_REALIGNMENT_ITERATIONS} submissions")
        print(f"📥 Queue timeout: {self.queue_empty_timeout}s when empty")
        if num_transactions:
            print(f"🎯 Target submissions: {num_transactions}")
        else:
            print(f"🔄 Running indefinitely (Ctrl+C to stop)")
        print("="*80)
        
        try:
            while self.running:
                if num_transactions and self.submissions_count >= num_transactions:
                    logger.info("🎯 Reached target submission count")
                    break
                
                # Nonce realignment every NONCE_REALIGNMENT_ITERATIONS transactions
                if self.submissions_count > 0 and self.submissions_count % NONCE_REALIGNMENT_ITERATIONS == 0:
                    if self.submissions_count != self.last_nonce_check:
                        self.realign_all_nonces()
                        self.last_nonce_check = self.submissions_count
                
                # Get transaction parameters from queue
                try:
                    transaction_params = self.transaction_queue.get(timeout=self.queue_empty_timeout)
                except queue.Empty:
                    logger.info(f"📭 Queue empty, waiting {self.queue_empty_timeout}s...")
                    continue
                
                # Submit transaction with parameters from queue
                account = self.get_next_account()
                success, tx_hash = self.submit_spotdata_transaction(account, transaction_params)

                # Mark task as done in queue
                self.transaction_queue.task_done()
                
                # Progress logging every 10 submissions
                if self.submissions_count % 10 == 0:
                    elapsed_time = time.time() - self.start_time
                    submission_rate = self.submissions_count / elapsed_time if elapsed_time > 0 else 0
                    success_rate = (self.successful_submissions / self.submissions_count * 100) if self.submissions_count > 0 else 0
                    
                    print(f"📊 Submitted: {self.submissions_count} | Success: {self.successful_submissions} | Failed: {self.failed_submissions} | Queue: {self.transaction_queue.qsize()}")
                    print(f"⚡ Submission Rate: {submission_rate:.2f} TPS | Success Rate: {success_rate:.1f}% | Realignments: {self.nonce_realignments}")
                    print("-" * 50)
                
                # Delay between submissions
                if delay > 0:
                    time.sleep(delay)
                
        except KeyboardInterrupt:
            logger.info("🛑 Stopped by user")
            self.running = False
        except Exception as e:
            logger.error(f"❌ Error in submission loop: {e}")
            self.running = False
        
        # Final statistics
        elapsed_time = time.time() - self.start_time
        avg_submission_rate = self.submissions_count / elapsed_time if elapsed_time > 0 else 0
        
        print("\n" + "="*80)
        print("📊 FINAL SUBMISSION STATISTICS")
        print("="*80)
        print(f"⏱️  Total runtime: {elapsed_time:.2f} seconds")
        print(f"📨 Total submissions: {self.submissions_count}")
        print(f"✅ Successful submissions: {self.successful_submissions}")
        print(f"❌ Failed submissions: {self.failed_submissions}")
        print(f"📥 Remaining in queue: {self.transaction_queue.qsize()}")
        print(f"⚡ Average submission rate: {avg_submission_rate:.2f} TPS")
        print(f"🎯 Success rate: {(self.successful_submissions/self.submissions_count*100):.1f}%" if self.submissions_count > 0 else "N/A")
        print(f"🔄 Nonce realignments performed: {self.nonce_realignments}")
        print("="*80)
        print("📝 Note: These are SUBMISSION metrics, not confirmation metrics")
        print("📝 Actual confirmation rate may vary based on network conditions")

    def stop(self):
        """Stop the transaction loop gracefully"""
        logger.info("🛑 Stopping transaction sender...")
        self.running = False

    # DO NOT CHANGE num_transactions parameter in run method for production use
    def run(self, num_transactions=None, delay=INTER_TX_DELAY):
        """Main execution function"""
        try:
            print("⚡ EXORDE QUEUE-DRIVEN HIGH-SPEED TRANSACTION SUBMITTER")
            print("="*70)
            
            # Initialize everything
            self.initialize_sync_nodes()
            self.initialize_dataspotting_contract()
            self.load_accounts()
            self.initialize_nonces()
            
            # Confirmation
            print(f"\n❓ Ready to start queue-driven high-speed submission:")
            print(f"   • Mode: Fire-and-forget (no receipt waiting)")
            print(f"   • Target submission rate: ~{1/delay:.1f} TPS")
            print(f"   • Nonce realignment: every {NONCE_REALIGNMENT_ITERATIONS} submissions")
            print(f"   • Accounts: {len(self.accounts)} in round robin")
            print(f"   • Sync nodes: {len(self.sync_nodes)} for load balancing")
            print(f"   • Queue empty timeout: {self.queue_empty_timeout}s")

            self.run_high_speed_loop(num_transactions=num_transactions, delay=delay)
            print("✅ Queue-driven transactioneer ENDED")
                
        except Exception as e:
            logger.error(f"💥 Fatal error: {e}")
            raise


##############################################
######## EXAMPLE USAGE ##########
##############################################
def main():
    """Main function - can be run independently"""
    sender = ExordeHighSpeedSender()
    
    # Add some example transactions to queue before starting
    example_transactions = [
        {
            'file_hashs': ["QmUtQJK2YncnLcBL6W9d8xeJzSmThb2CU7mpbdiC4CpkcE"],
            'url_domains': [""],
            'item_counts': [40],
            'extra': ""
        },
        {
            'file_hashs': ["QmUtQJK2YncnLcBL6W9d8xeJzSmThb2CU7mpbdiC4CAAAA"],
            'url_domains': [""],
            'item_counts': [30],
            'extra': ""
        },
    ]

    # duplicate this 1000 times
    example_transactions = example_transactions * 1000
    
    sender.add_transactions_batch(example_transactions)
    
    # Run with queue-driven approach
    sender.run(delay=INTER_TX_DELAY)


if __name__ == "__main__":
    main()
