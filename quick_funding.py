import requests
import time
import json
import os
from web3 import Web3, HTTPProvider
from web3.middleware import simple_cache_middleware
import logging
import threading
from queue import Queue
from collections import defaultdict

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class SequentialHighSpeedFunder:
    def __init__(self):
        # Configuration
        self.accounts_folder = "exorde_accounts"
        self.accounts_file = os.path.join(self.accounts_folder, "accounts.json")
        self.funding_amount = int(0.01 * 10**18)  # 0.01 sFuel per account
        
        # Network configuration
        self.w3 = None
        self.chain_id = None
        
        # Account management
        self.funding_accounts = []  # First 200 accounts
        self.target_accounts = []   # Remaining 1800 accounts
        self.all_accounts = []      # All 2000 accounts
        
        # Sequential nonce management
        self.funding_nonces = {}
        self.nonce_locks = defaultdict(threading.Lock)
        
        # Sequential scheduling
        self.funding_queue = Queue()
        self.funding_schedule = defaultdict(list)  # Each funder gets a list of targets
        
        # Performance tracking
        self.funding_attempts = 0
        self.successful_fundings = 0
        self.failed_fundings = 0
        self.start_time = None

    def initialize_network(self):
        """Initialize network configuration"""
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

    def load_accounts(self):
        """Load accounts and split into funding sources and targets"""
        try:
            if not os.path.exists(self.accounts_file):
                raise FileNotFoundError(f"Accounts file not found: {self.accounts_file}")
            
            with open(self.accounts_file, 'r') as f:
                self.all_accounts = json.load(f)
            
            if len(self.all_accounts) < 2000:
                raise ValueError(f"Need at least 2000 accounts, found {len(self.all_accounts)}")
            
            # Split accounts: first 200 as funding sources, rest as targets
            self.funding_accounts = self.all_accounts[:200]
            self.target_accounts = self.all_accounts[200:2000]
            
            logger.info(f"📋 Loaded {len(self.all_accounts)} total accounts")
            logger.info(f"💳 Funding sources: {len(self.funding_accounts)} accounts (indices 0-199)")
            logger.info(f"🎯 Funding targets: {len(self.target_accounts)} accounts (indices 200-1999)")
            
        except Exception as e:
            logger.error(f"❌ Failed to load accounts: {e}")
            raise

    def initialize_funding_nonces_and_schedule(self):
        """Initialize nonces for all funding accounts and create sequential schedule"""
        logger.info("🔢 Fetching current nonces for all funding accounts...")
        
        # Fetch all nonces first with small delays to avoid overwhelming the node
        for account in self.funding_accounts:
            address = account['address']
            try:
                current_nonce = self.w3.eth.get_transaction_count(address)
                self.funding_nonces[address] = current_nonce
                if account['index'] % 20 == 0:  # Log every 20th to reduce spam
                    logger.info(f"   Account {account['index']:03d}: {address} - nonce: {current_nonce}")
                # Small delay between nonce fetches
                time.sleep(0.05)
            except Exception as e:
                logger.error(f"❌ Failed to get nonce for {address}: {e}")
                self.funding_nonces[address] = 0
        
        logger.info("✅ All funding account nonces fetched")
        
        # Create sequential schedule - distribute targets evenly across funding accounts
        logger.info("📋 Creating sequential funding schedule...")
        
        for i, target_account in enumerate(self.target_accounts):
            # Sequential round-robin assignment
            funder_index = i % len(self.funding_accounts)
            funding_account = self.funding_accounts[funder_index]
            self.funding_schedule[funding_account['address']].append(target_account)
        
        # Log schedule summary
        for i, funding_account in enumerate(self.funding_accounts[:5]):  # Show first 5
            targets_count = len(self.funding_schedule[funding_account['address']])
            first_targets = self.funding_schedule[funding_account['address']][:3]
            target_indices = [t['index'] for t in first_targets]
            logger.info(f"   Funder {funding_account['index']:03d}: {targets_count} targets (first 3: {target_indices})")
        
        logger.info(f"✅ Schedule created: {len(self.funding_accounts)} funders, ~{len(self.target_accounts)//len(self.funding_accounts)} targets each")

    def get_next_nonce(self, funding_address):
        """Get next nonce for funding account (thread-safe)"""
        with self.nonce_locks[funding_address]:
            current_nonce = self.funding_nonces[funding_address]
            self.funding_nonces[funding_address] += 1
            return current_nonce

    def check_funding_account_balances(self):
        """Check balances of funding accounts"""
        logger.info("💰 Checking funding account balances...")
        
        print("\n" + "="*60)
        print("💳 FUNDING ACCOUNT BALANCES")
        print("="*60)
        
        total_balance = 0
        ready_count = 0
        
        for account in self.funding_accounts:
            try:
                balance = self.w3.eth.get_balance(account['address'])
                balance_eth = self.w3.from_wei(balance, 'ether')
                total_balance += balance_eth
                
                # Each funding account needs to fund ~9 target accounts (1800/200)
                targets_count = len(self.funding_schedule.get(account['address'], []))
                required_balance = targets_count * self.w3.from_wei(self.funding_amount, 'ether')
                status = "✅ Ready" if balance_eth > required_balance else "⚠️  Low funds"
                
                if balance_eth > required_balance:
                    ready_count += 1
                
                if account['index'] % 40 == 0:  # Show every 40th account to reduce output
                    print(f"Account {account['index']:03d}: {status}")
                    print(f"  Balance: {balance_eth:.4f} sFUEL")
                    print(f"  Will fund: {targets_count} accounts")
                    print()
                
            except Exception as e:
                logger.error(f"❌ Failed to check balance for funding account {account['index']}: {e}")
        
        print(f"📊 Summary: {ready_count}/{len(self.funding_accounts)} funding accounts ready")
        print(f"💰 Total funding power: {total_balance:.4f} sFUEL")
        print("="*60)
        
        return ready_count, total_balance

    def fund_single_target(self, target_account, funding_account):
        """Fund a single target account from a funding account"""
        try:
            target_address = target_account['address']
            funding_address = funding_account['address']
            funding_private_key = funding_account['private_key']
            
            # Get nonce for funding account
            nonce = self.get_next_nonce(funding_address)
            
            # Get current gas price
            gas_price = self.w3.eth.gas_price
            
            # Build transaction
            transaction = {
                'nonce': nonce,
                'gasPrice': gas_price,
                'gas': 21000,  # Standard transfer
                'to': self.w3.to_checksum_address(target_address),
                'value': self.funding_amount,
                'chainId': int(self.chain_id),
            }
            
            # Sign and send transaction (no receipt waiting)
            signed_txn = self.w3.eth.account.sign_transaction(transaction, funding_private_key)
            tx_hash = self.w3.eth.send_raw_transaction(signed_txn.rawTransaction)
            
            # Update counters
            self.funding_attempts += 1
            self.successful_fundings += 1
            
            return True, tx_hash.hex()
            
        except Exception as e:
            self.failed_fundings += 1
            logger.error(f"❌ Failed to fund target {target_account['index']} from funder {funding_account['index']}: {e}")
            return False, None

    def fund_sequential_worker(self, funding_account, delay_between_tx=0.3, startup_delay=0):
        """Worker function to fund all targets for a specific funding account"""
        # Staggered startup to prevent initial rush
        if startup_delay > 0:
            time.sleep(startup_delay)
        
        targets = self.funding_schedule[funding_account['address']]
        funder_success = 0
        funder_failed = 0
        
        logger.info(f"🚀 Worker started for funder {funding_account['index']:03d}: {len(targets)} targets")
        
        for i, target_account in enumerate(targets):
            try:
                success, tx_hash = self.fund_single_target(target_account, funding_account)
                
                if success:
                    funder_success += 1
                else:
                    funder_failed += 1
                
                # Progress logging for this funder every 3 transactions (reduced frequency)
                if (i + 1) % 3 == 0:
                    logger.info(f"   Funder {funding_account['index']:03d}: {i+1}/{len(targets)} | Success: {funder_success} | Failed: {funder_failed}")
                
                # Increased delay to give blockchain time to process
                if delay_between_tx > 0 and i < len(targets) - 1:
                    time.sleep(delay_between_tx)
                    
            except Exception as e:
                logger.error(f"❌ Worker error for funder {funding_account['index']}: {e}")
                funder_failed += 1
        
        logger.info(f"✅ Worker completed for funder {funding_account['index']:03d}: {funder_success} success, {funder_failed} failed")
        return funder_success, funder_failed

    def sequential_funding_process(self, max_workers=15, delay_between_tx=0.2):
        """Fund all targets using sequential workers for each funding account"""
        logger.info("🚀 Starting sequential funding process with increased delays...")
        
        self.start_time = time.time()
        
        print("\n" + "="*80)
        print("⚡ SEQUENTIAL MODERATE-SPEED FUNDING")
        print("="*80)
        print(f"💳 Funding sources: {len(self.funding_accounts)} accounts")
        print(f"🎯 Funding targets: {len(self.target_accounts)} accounts")
        print(f"💰 Amount per target: {self.w3.from_wei(self.funding_amount, 'ether')} sFUEL")
        print(f"🔧 Max concurrent workers: {max_workers}")
        print(f"⏱️  Delay between tx per funder: {delay_between_tx*1000:.0f}ms")
        print(f"📋 Sequential scheduling with improved spacing")
        print(f"🎯 Expected completion: ~90-150 seconds")
        print("="*80)
                
        # Process all funding accounts sequentially - NO THREADS
        completed_funders = 0
        total_funding_success = 0
        total_funding_failed = 0

        for i, funding_account in enumerate(self.funding_accounts):
            try:
                # Apply startup delay (staggered processing)
                startup_delay = (i // 15) * 0.5  # 0.5 second delay per batch of 15
                if startup_delay > 0:
                    logger.info(f"⏳ Startup delay: {startup_delay:.1f}s before processing funder {funding_account['index']:03d}")
                    time.sleep(startup_delay)
                
                # Process this funding account sequentially
                logger.info(f"🚀 Processing funder {funding_account['index']:03d} ({i+1}/{len(self.funding_accounts)})")
                
                funder_success, funder_failed = self.fund_sequential_worker(
                    funding_account, 
                    delay_between_tx,
                    0  # No additional startup delay since we handle it above
                )
                
                # Update totals
                total_funding_success += funder_success
                total_funding_failed += funder_failed
                completed_funders += 1
                
                # Progress updates every 20 completed funders
                if completed_funders % 20 == 0:
                    elapsed_time = time.time() - self.start_time
                    avg_rate = self.funding_attempts / elapsed_time if elapsed_time > 0 else 0
                    print(f"📊 Funders completed: {completed_funders}/{len(self.funding_accounts)} | Total attempts: {self.funding_attempts} | Rate: {avg_rate:.1f} tx/s")
                
                # Small delay between funding accounts to prevent overwhelming
                if i < len(self.funding_accounts) - 1:  # Don't sleep after the last one
                    time.sleep(0.1)  # 100ms between funding accounts
                    
            except Exception as e:
                logger.error(f"❌ Error processing funding account {funding_account['index']:03d}: {e}")
                total_funding_failed += 1
                completed_funders += 1

        # Final summary
        logger.info(f"✅ Sequential processing completed: {completed_funders} funders processed")
        logger.info(f"📊 Total results: {total_funding_success} successful, {total_funding_failed} failed")

        
        # Final statistics
        elapsed_time = time.time() - self.start_time
        avg_rate = self.funding_attempts / elapsed_time if elapsed_time > 0 else 0
        
        print("\n" + "="*80)
        print("📊 SEQUENTIAL FUNDING COMPLETED")
        print("="*80)
        print(f"⏱️  Total time: {elapsed_time:.2f} seconds")
        print(f"📨 Total attempts: {self.funding_attempts}")
        print(f"✅ Successful: {self.successful_fundings}")
        print(f"❌ Failed: {self.failed_fundings}")
        print(f"⚡ Average rate: {avg_rate:.2f} tx/s")
        print(f"🎯 Success rate: {(self.successful_fundings/self.funding_attempts*100):.1f}%" if self.funding_attempts > 0 else "N/A")
        print("="*80)

    def check_all_balances(self):
        """Check balances of all accounts to verify funding results"""
        logger.info("🔍 Checking balances of all accounts...")
        
        print("\n" + "="*80)
        print("📊 FINAL BALANCE VERIFICATION")
        print("="*80)
        
        funded_count = 0
        total_balance = 0
        
        # Check funding accounts
        print("💳 FUNDING ACCOUNTS (0-199):")
        for account in self.funding_accounts:
            try:
                balance = self.w3.eth.get_balance(account['address'])
                balance_eth = self.w3.from_wei(balance, 'ether')
                total_balance += balance_eth
                
                if balance > 0:
                    funded_count += 1
                
                if account['index'] % 50 == 0:  # Show every 50th account
                    status = "✅" if balance > 0 else "❌"
                    print(f"  {status} Account {account['index']:03d}: {balance_eth:.4f} sFUEL")
                    
            except Exception as e:
                logger.error(f"❌ Failed to check balance for account {account['index']}: {e}")
        
        print(f"\n🎯 TARGET ACCOUNTS (200-1999):")
        target_funded = 0
        
        for account in self.target_accounts:
            try:
                balance = self.w3.eth.get_balance(account['address'])
                balance_eth = self.w3.from_wei(balance, 'ether')
                total_balance += balance_eth
                
                if balance > 0:
                    target_funded += 1
                
                if account['index'] % 200 == 0:  # Show every 200th account
                    status = "✅" if balance > 0 else "❌"
                    print(f"  {status} Account {account['index']:04d}: {balance_eth:.4f} sFUEL")
                    
            except Exception as e:
                logger.error(f"❌ Failed to check balance for account {account['index']}: {e}")
        
        print("\n" + "="*80)
        print("📈 FINAL SUMMARY")
        print("="*80)
        print(f"💳 Funding accounts with balance: {len(self.funding_accounts)}/200")
        print(f"🎯 Target accounts funded: {target_funded}/{len(self.target_accounts)}")
        print(f"📊 Total accounts with balance: {funded_count + target_funded}/{len(self.all_accounts)}")
        print(f"💰 Total system balance: {total_balance:.4f} sFUEL")
        print(f"🎯 Target funding success rate: {(target_funded/len(self.target_accounts)*100):.1f}%")
        print("="*80)
        
        return target_funded, total_balance

    def run(self):
        """Main execution function"""
        try:
            print("⚡ SEQUENTIAL MODERATE-SPEED ACCOUNT FUNDER")
            print("="*60)
            
            # Initialize everything
            self.initialize_network()
            self.load_accounts()
            self.initialize_funding_nonces_and_schedule()
            
            # # Check funding account readiness
            # ready_count, total_funding_power = self.check_funding_account_balances()
            
            # if ready_count < 100:  # Need at least 50% of funding accounts ready
            #     logger.warning(f"⚠️  Only {ready_count}/200 funding accounts have sufficient balance")
            #     proceed = input("🤔 Proceed anyway? (y/n): ").lower().strip()
            #     if proceed != 'y':
            #         logger.info("🚫 Process cancelled")
            #         return
            
            # Confirmation
            print(f"\n❓ Ready to fund {len(self.target_accounts)} accounts:")
            print(f"   • Funding sources: First 200 accounts (0-199)")
            print(f"   • Funding targets: Accounts 200-1999 ({len(self.target_accounts)} accounts)")
            print(f"   • Amount per account: {self.w3.from_wei(self.funding_amount, 'ether')} sFUEL")
            print(f"   • Mode: Sequential scheduling with moderate speed")
            print(f"   • Delay between transactions: 200ms per funder")
            print(f"   • Max concurrent workers: 15 (reduced from 20)")
            print(f"   • Estimated time: ~90-150 seconds (slower but more reliable)")
            
            start_choice = input("\n🚀 Start moderate-speed sequential funding? (y/n): ").lower().strip()
            
            if start_choice == 'y':
                # Execute sequential funding with increased delays
                self.sequential_funding_process(max_workers=15, delay_between_tx=0.2)
                
                # Wait longer for transactions to propagate
                logger.info("⏳ Waiting 45 seconds for transactions to propagate...")
                time.sleep(45)
                
                # Check all balances
                target_funded, total_balance = self.check_all_balances()
                
                # Final result
                success_rate = (target_funded / len(self.target_accounts)) * 100
                if success_rate > 95:
                    print(f"\n🎉 EXCELLENT! {success_rate:.1f}% of target accounts funded successfully!")
                elif success_rate > 90:
                    print(f"\n✅ VERY GOOD! {success_rate:.1f}% of target accounts funded successfully!")
                elif success_rate > 80:
                    print(f"\n✅ GOOD! {success_rate:.1f}% of target accounts funded successfully!")
                else:
                    print(f"\n⚠️  PARTIAL SUCCESS: {success_rate:.1f}% of target accounts funded")
                    print("💡 The slower pace should reduce nonce collisions significantly")
                
            else:
                logger.info("🚫 Funding cancelled by user")
                
        except Exception as e:
            logger.error(f"💥 Fatal error: {e}")
            raise

def main():
    funder = SequentialHighSpeedFunder()
    funder.run()

if __name__ == "__main__":
    main()
