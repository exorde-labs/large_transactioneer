import requests
import time
import json
import os
from web3 import Web3, HTTPProvider
from web3.middleware import simple_cache_middleware
import logging
from collections import defaultdict

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# TARGET CONFIGURATION
TARGET_MASTER_ADDRESS = "XXXXXXXXXXX YOUR WALLET HERE XXXXXXXXXXXXXXXXXXXX"
ADDRESS_MANAGER_CONTRACT = "0x797E0E87aDCf9845D2af2c5eee6F226feA3f0eFc"

class SimpleClaimMasterScript:
    def __init__(self):
        # Configuration
        self.accounts_folder = "exorde_accounts"
        self.accounts_file = os.path.join(self.accounts_folder, "accounts.json")
        self.target_master_address = TARGET_MASTER_ADDRESS
        self.address_manager_contract = ADDRESS_MANAGER_CONTRACT
        
        # Network configuration
        self.w3 = None
        self.chain_id = None
        self.address_manager_obj = None
        
        # Account management
        self.all_accounts = []
        self.account_nonces = defaultdict(int)
        
        # Performance tracking
        self.total_claims_attempted = 0
        self.total_claims_successful = 0
        self.total_claims_failed = 0

    def initialize_network(self):
        """Initialize network configuration and Web3 connection"""
        try:
            logger.info("🔄 Fetching network configuration...")
            net_configs = requests.get(
                "https://raw.githubusercontent.com/exorde-labs/TestnetProtocol/main/NetworkConfig.json",
                timeout=30
            ).json()
            
            # Extract configuration for testnet-A
            for network in net_configs['testnet']:
                if network['_networkId'] == 'testnet-A':
                    self.chain_id = network['_chainID']
                    rpc_url = network["_urlTxSkale"]
                    logger.info(f"🌐 Using RPC endpoint: {rpc_url}")
                    logger.info(f"⛓️  Chain ID: {self.chain_id}")
                    break
            
            # Initialize Web3 instance
            self.w3 = Web3(Web3.HTTPProvider(rpc_url))
            try:
                self.w3.middleware_onion.add(simple_cache_middleware)
                logger.info("✅ Web3 middleware added successfully")
            except Exception as e:
                logger.warning(f"⚠️  Middleware error: {e}")
                
        except Exception as e:
            logger.error(f"❌ Failed to initialize network: {e}")
            raise

    def initialize_address_manager_contract(self):
        """Initialize AddressManager contract with ABI"""
        try:
            logger.info("📄 Fetching AddressManager contract ABI...")
            
            # Fetch ABI from GitHub
            abi_response = requests.get(
                "https://raw.githubusercontent.com/exorde-labs/TestnetProtocol/main/ABIs/AddressManager.sol/AddressManager.json",
                timeout=30
            )
            
            if abi_response.status_code == 200:
                self.abi_address_manager = abi_response.json()
                logger.info("✅ AddressManager ABI fetched successfully")
            else:
                # Fallback ABI with ClaimMaster function
                logger.warning("⚠️  Failed to fetch ABI, using fallback ABI")
                self.abi_address_manager = {
                    "abi": [
                        {
                            "inputs": [{"name": "target_", "type": "address"}],
                            "name": "ClaimMaster",
                            "outputs": [],
                            "stateMutability": "nonpayable",
                            "type": "function"
                        }
                    ]
                }
            
            # Initialize contract
            logger.info(f"🔗 Initializing AddressManager contract at {self.address_manager_contract}")
            self.address_manager_obj = self.w3.eth.contract(
                address=self.w3.to_checksum_address(self.address_manager_contract),
                abi=self.abi_address_manager.get('abi', self.abi_address_manager)
            )
            logger.info("✅ AddressManager contract initialized")
            
        except Exception as e:
            logger.error(f"❌ Failed to initialize AddressManager contract: {e}")
            raise

    def load_all_accounts(self):
        """Load all accounts from JSON file"""
        try:
            if not os.path.exists(self.accounts_file):
                raise FileNotFoundError(f"❌ Accounts file not found: {self.accounts_file}")
            
            with open(self.accounts_file, 'r') as f:
                self.all_accounts = json.load(f)
            
            logger.info(f"📋 Loaded {len(self.all_accounts)} accounts for ClaimMaster processing")
            
        except Exception as e:
            logger.error(f"❌ Failed to load accounts: {e}")
            raise

    def initialize_account_nonces(self):
        """Initialize current nonces for all accounts"""
        logger.info("🔢 Fetching current nonces for all accounts...")
        
        for i, account in enumerate(self.all_accounts):
            address = account['address']
            try:
                current_nonce = self.w3.eth.get_transaction_count(address)
                self.account_nonces[address] = current_nonce
                
                # Log progress every 200 accounts
                if (i + 1) % 200 == 0:
                    logger.info(f"   Nonces fetched: {i+1}/{len(self.all_accounts)}")
                
            except Exception as e:
                logger.error(f"❌ Failed to get nonce for {address}: {e}")
                self.account_nonces[address] = 0
        
        logger.info(f"✅ Initialized nonces for {len(self.all_accounts)} accounts")

    def claim_master_single_account(self, account):
        """Claim master for a single account"""
        try:
            address = account['address']
            private_key = account['private_key']
            index = account['index']
            
            # Get and increment nonce for this account
            nonce = self.account_nonces[address]
            self.account_nonces[address] += 1
            
            # Get current gas price
            gas_price = self.w3.eth.gas_price
            
            # Build ClaimMaster transaction
            transaction = self.address_manager_obj.functions.ClaimMaster(
                self.w3.to_checksum_address(self.target_master_address)
            ).build_transaction({
                'from': address,
                'nonce': nonce,
                'gas': 200000,  # Generous gas limit for ClaimMaster
                'gasPrice': gas_price,
                'chainId': int(self.chain_id),
            })
            
            # Sign and send transaction
            signed_tx = self.w3.eth.account.sign_transaction(transaction, private_key)
            tx_hash = self.w3.eth.send_raw_transaction(signed_tx.rawTransaction)
            
            # Update counters
            self.total_claims_attempted += 1
            self.total_claims_successful += 1
            
            return True, tx_hash.hex()
            
        except Exception as e:
            self.total_claims_failed += 1
            logger.error(f"❌ ClaimMaster failed for account {index:04d}: {e}")
            return False, None

    def sequential_claim_master_all_accounts(self):
        """Claim master for all accounts sequentially with 0.1s delays"""
        logger.info("🚀 Starting sequential ClaimMaster for all accounts...")
        
        start_time = time.time()
        
        print("\n" + "="*80)
        print("🏆 SEQUENTIAL CLAIM MASTER EXECUTION")
        print("="*80)
        print(f"🎯 Target master address: {self.target_master_address}")
        print(f"📄 Contract: {self.address_manager_contract}")
        print(f"👥 Processing: {len(self.all_accounts)} accounts")
        print(f"⏱️  Delay between transactions: 100ms")
        print(f"🔄 Processing: Sequential, one after another")
        print("="*80)
        
        for i, account in enumerate(self.all_accounts):
            try:
                # Process this account
                success, tx_hash = self.claim_master_single_account(account)
                
                if success:
                    if (i + 1) % 100 == 0:  # Log every 100 successful transactions
                        print(f"✅ Account {account['index']:04d}: ClaimMaster successful - TX: {tx_hash}")
                else:
                    print(f"❌ Account {account['index']:04d}: ClaimMaster failed")
                
                # Progress logging every 100 accounts
                if (i + 1) % 100 == 0:
                    elapsed = time.time() - start_time
                    rate = (i + 1) / elapsed if elapsed > 0 else 0
                    print(f"📊 Progress: {i+1}/{len(self.all_accounts)} | Success: {self.total_claims_successful} | Failed: {self.total_claims_failed} | Rate: {rate:.1f} tx/s")
                
                # 0.1 second delay between transactions
                if i < len(self.all_accounts) - 1:  # Don't sleep after the last transaction
                    time.sleep(0.1)
                    
            except Exception as e:
                logger.error(f"❌ Error processing account {account['index']}: {e}")
                self.total_claims_failed += 1
        
        # Final statistics
        elapsed_time = time.time() - start_time
        avg_rate = len(self.all_accounts) / elapsed_time if elapsed_time > 0 else 0
        
        print("\n" + "="*80)
        print("📊 SEQUENTIAL CLAIM MASTER COMPLETED")
        print("="*80)
        print(f"⏱️  Total time: {elapsed_time:.2f} seconds")
        print(f"📨 Total attempts: {self.total_claims_attempted}")
        print(f"✅ Successful: {self.total_claims_successful}")
        print(f"❌ Failed: {self.total_claims_failed}")
        print(f"⚡ Average rate: {avg_rate:.2f} tx/s")
        print(f"🎯 Success rate: {(self.total_claims_successful/self.total_claims_attempted*100):.1f}%" if self.total_claims_attempted > 0 else "N/A")
        print("="*80)
        
        logger.info(f"🎉 ClaimMaster completed: {self.total_claims_successful} successful, {self.total_claims_failed} failed")

    def run(self):
        """Main execution function"""
        try:
            print("🏆 SIMPLE SEQUENTIAL CLAIM MASTER SCRIPT")
            print("="*60)
            print(f"🎯 Target Master Address: {self.target_master_address}")
            print(f"📄 AddressManager Contract: {self.address_manager_contract}")
            print("="*60)
            
            # Initialize everything
            self.initialize_network()
            self.initialize_address_manager_contract()
            self.load_all_accounts()
            self.initialize_account_nonces()
            
            # Confirmation before proceeding
            print(f"\n❓ Ready to execute ClaimMaster for all accounts:")
            print(f"   • Total accounts: {len(self.all_accounts)}")
            print(f"   • Each account will claim master to: {self.target_master_address}")
            print(f"   • Sequential processing with 0.1s delays")
            print(f"   • Estimated time: ~{len(self.all_accounts) * 0.1 / 60:.1f} minutes")
            # Execute sequential ClaimMaster
            self.sequential_claim_master_all_accounts()
            
            print(f"\n🎉 SUCCESS! Sequential ClaimMaster execution completed!")
            print(f"🏆 All accounts have claimed master to {self.target_master_address}")
            
        except Exception as e:
            logger.error(f"💥 Fatal error: {e}")
            raise

def main():
    claimer = SimpleClaimMasterScript()
    claimer.run()

if __name__ == "__main__":
    main()
