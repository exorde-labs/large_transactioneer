import requests
import time
import json
import os
from web3 import Web3, HTTPProvider
from web3.middleware import simple_cache_middleware
import logging
import threading

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class ExordeAccountFunder:
    def __init__(self):
        # Configuration
        self.nb_senders = 50  # Number of sending addresses
        self.transactioneer_pk_base = "deaddeaddeaddeaddead2d83ed54c0ff1ebffeffa84ef980d42953cabef" # to CHANGE
        self.main_faucet_pk = "283f433b788b8eb60ca27fc7c5a21efec37d5cb698dc47b364731058fe5ffb85"
        self.accounts_folder = "exorde_accounts"
        self.accounts_file = os.path.join(self.accounts_folder, "accounts.json")
        self.VALUE_FUNDING = int(1 * 10**18)  # 0.5 sFuel in wei
        
        # Network configuration
        self.w3 = None
        self.chain_id = None
        self.main_address = None
        
        # Nonce management
        self.nonce_lock = threading.Lock()
        self.main_nonce = None

    def initialize_network_config(self):
        """Initialize network configuration"""
        try:
            logger.info("🔄 Fetching network configuration...")
            netConfigs = requests.get("https://raw.githubusercontent.com/exorde-labs/TestnetProtocol/main/NetworkConfig.json", timeout=30).json()
            
            # Extract configuration for testnet-A
            for network in netConfigs['testnet']:
                if network['_networkId'] == 'testnet-A':
                    self.chain_id = network['_chainID']
                    # Use the main RPC endpoint
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
            
            # Get main faucet address
            self.main_address = self.w3.eth.account.from_key(self.main_faucet_pk).address
            logger.info(f"💳 Main faucet address: {self.main_address}")
            
            # Check main account balance
            balance = self.w3.eth.get_balance(self.main_address)
            balance_eth = self.w3.from_wei(balance, 'ether')
            logger.info(f"💰 Main account balance: {balance_eth:.4f} sFUEL")
            
            # Initialize main nonce
            self.main_nonce = self.w3.eth.get_transaction_count(self.main_address)
            logger.info(f"🔢 Initial main account nonce: {self.main_nonce}")
            
        except Exception as e:
            logger.error(f"❌ Failed to initialize network config: {e}")
            raise

    def create_accounts_folder(self):
        """Create accounts folder if it doesn't exist"""
        if not os.path.exists(self.accounts_folder):
            os.makedirs(self.accounts_folder)
            logger.info(f"📁 Created accounts folder: {self.accounts_folder}")
        else:
            logger.info(f"📁 Accounts folder already exists: {self.accounts_folder}")

    def check_existing_accounts(self):
        """Check if accounts already exist and load them"""
        if os.path.exists(self.accounts_file) and os.path.getsize(self.accounts_file) > 0:
            try:
                with open(self.accounts_file, 'r') as f:
                    existing_accounts = json.load(f)
                logger.info(f"📋 Found {len(existing_accounts)} existing accounts")
                return existing_accounts
            except Exception as e:
                logger.error(f"❌ Failed to load existing accounts: {e}")
                return None
        return None

    def generate_sender_addresses(self):
        """Generate sender addresses using the provided format"""
        sender_data = []
        
        logger.info(f"🔧 Generating {self.nb_senders} sender addresses...")
        for i in range(self.nb_senders):
            hex_digit = "%0.4x" % i
            # randomly
            private_key = self.transactioneer_pk_base + hex_digit
            address = self.w3.eth.account.from_key(private_key).address
            
            account_data = {
                'index': i,
                'private_key': private_key,
                'address': address,
                'hex_suffix': hex_digit
            }
            sender_data.append(account_data)
            
            logger.info(f"  🆕 Generated sender {i:02d}: {address}")
        
        return sender_data

    def save_accounts_to_file(self, accounts_data):
        """Save accounts to JSON file"""
        try:
            with open(self.accounts_file, 'w') as f:
                json.dump(accounts_data, f, indent=2)
            logger.info(f"💾 Saved {len(accounts_data)} accounts to {self.accounts_file}")
            
            # Also save individual account files for easy access
            for account in accounts_data:
                account_file = os.path.join(self.accounts_folder, f"account_{account['index']:03d}.json")
                with open(account_file, 'w') as f:
                    json.dump(account, f, indent=2)
            
            logger.info(f"💾 Saved individual account files in {self.accounts_folder}")
            
        except Exception as e:
            logger.error(f"❌ Failed to save accounts: {e}")
            raise

    def get_next_main_nonce(self):
        """Get next nonce for main funding account"""
        with self.nonce_lock:
            current_nonce = self.main_nonce
            self.main_nonce += 1
            return current_nonce

    def check_account_balances(self, accounts_data, title="ACCOUNT BALANCES"):
        """Check and display balances of all accounts"""
        logger.info(f"💰 Checking {title.lower()}...")
        
        print("\n" + "="*80)
        print(f"📊 {title}")
        print("="*80)
        
        total_balance = 0
        funded_count = 0
        
        for account in accounts_data:
            try:
                balance = self.w3.eth.get_balance(account['address'])
                balance_eth = self.w3.from_wei(balance, 'ether')
                total_balance += balance_eth
                
                status = "✅ FUNDED" if balance > 0 else "❌ EMPTY"
                if balance > 0:
                    funded_count += 1
                
                print(f"Account {account['index']:02d}: {account['address']}")
                print(f"  Status: {status}")
                print(f"  Balance: {balance_eth:.6f} sFUEL")
                print()
                
            except Exception as e:
                logger.error(f"❌ Failed to check balance for account {account['index']}: {e}")
                print(f"Account {account['index']:02d}: ERROR - {e}")
                print()
        
        print(f"📈 Summary: {funded_count}/{len(accounts_data)} accounts funded")
        print(f"💰 Total balance: {total_balance:.6f} sFUEL")
        print("="*80)
        
        return funded_count, total_balance

    def fund_single_address(self, account, attempt_number):
        """Fund a single address with detailed logging"""
        try:
            target_address = account['address']
            index = account['index']
            
            logger.info(f"🚀 Starting funding for account {index:02d} (attempt {attempt_number})")
            logger.info(f"   📍 Target address: {target_address}")
            
            # Get next nonce
            nonce = self.get_next_main_nonce()
            logger.info(f"   🔢 Using nonce: {nonce}")
            
            # Ensure target address is checksummed
            target_address = self.w3.to_checksum_address(target_address)
            
            # Get current gas price
            gas_price = 150_000
            
            # Build transaction
            transaction = {
                'nonce': nonce,
                'gasPrice': gas_price,
                'gas': 21000,  # Standard gas limit for simple transfer
                'to': target_address,
                'value': self.VALUE_FUNDING, 
                'chainId': int(self.chain_id),
            }
            
            # Sign transaction
            signed_txn = self.w3.eth.account.sign_transaction(transaction, self.main_faucet_pk)
            logger.info(f"   ✍️  Transaction signed")
            
            # Send transaction
            logger.info(f"   📡 Sending transaction...")
            tx_hash = self.w3.eth.send_raw_transaction(signed_txn.rawTransaction)
            tx_hash_hex = tx_hash.hex()
            logger.info(f"   🔗 Transaction sent! Hash: {tx_hash_hex}")
            
            # Wait for transaction receipt
            logger.info(f"   ⏳ Waiting for transaction confirmation...")
            tx_receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=20)
            
            if tx_receipt.status == 1:
                logger.info(f"   ✅ Transaction confirmed successfully!")
                logger.info(f"   📦 Block number: {tx_receipt.blockNumber}")
                logger.info(f"   ⛽ Gas used: {tx_receipt.gasUsed}")
                
                # Verify the balance
                time.sleep(1)  # Small delay to ensure balance is updated
                new_balance = self.w3.eth.get_balance(target_address)
                new_balance_eth = self.w3.from_wei(new_balance, 'ether')
                logger.info(f"   💰 New balance: {new_balance_eth:.6f} sFUEL")
                
                print(f"✅ SUCCESS: Account {index:02d} funded successfully!")
                print(f"   TX Hash: {tx_hash_hex}")
                print(f"   Balance: {new_balance_eth:.6f} sFUEL")
                
                return True, tx_hash_hex
            else:
                logger.error(f"   ❌ Transaction failed! Status: {tx_receipt.status}")
                return False, tx_hash_hex
                
        except Exception as e:
            logger.error(f"   ❌ Failed to fund account {index:02d}: {e}")
            print(f"❌ FAILED: Account {index:02d} funding failed - {e}")
            return False, None

    def fund_all_addresses_sequential(self, accounts_data):
        """Fund all addresses sequentially with detailed progress tracking"""
        logger.info("🚀 Starting sequential funding process...")
        
        print("\n" + "="*80)
        print("💰 SEQUENTIAL FUNDING PROCESS")
        print("="*80)
        
        successful_funding = 0
        failed_accounts = []
        funding_results = []
        
        for i, account in enumerate(accounts_data, 1):
            print(f"\n📍 Processing account {i}/{len(accounts_data)}")
            print("-" * 50)
            
            success, tx_hash = self.fund_single_address(account, i)
            
            funding_results.append({
                'account': account,
                'success': success,
                'tx_hash': tx_hash
            })
            
            if success:
                successful_funding += 1
            else:
                failed_accounts.append(account['index'])
            
            # Progress update
            print(f"📊 Progress: {successful_funding}/{i} successful so far")
            
            # Small delay between transactions
            if i < len(accounts_data):  # Don't sleep after the last transaction
                logger.info("⏳ Waiting 0.1 seconds before next transaction...")
                time.sleep(0.1)
        
        print("\n" + "="*80)
        print("📋 FUNDING SUMMARY")
        print("="*80)
        print(f"✅ Successful: {successful_funding}/{len(accounts_data)} accounts")
        print(f"❌ Failed: {len(failed_accounts)} accounts")
        
        if failed_accounts:
            print(f"❌ Failed account indices: {failed_accounts}")
        
        print("="*80)
        
        logger.info(f"🎉 Funding completed: {successful_funding}/{len(accounts_data)} accounts successfully funded")
        return successful_funding, funding_results

    def run(self):
        """Main execution function"""
        try:
            print("🚀 EXORDE ACCOUNT FUNDER")
            print("="*60)
            
            # Initialize network
            self.initialize_network_config()
            
            # Create accounts folder
            self.create_accounts_folder()
            
            # Check if accounts already exist
            existing_accounts = self.check_existing_accounts()
            
            if existing_accounts:
                logger.info("📋 Using existing accounts. Skipping generation.")
                accounts_data = existing_accounts
            else:
                logger.info("🆕 No existing accounts found. Generating new accounts...")
                accounts_data = self.generate_sender_addresses()
                self.save_accounts_to_file(accounts_data)
            

            fund_choice = input("\n🤔 Do you want to proceed with funding? (y/n): ").lower().strip()
            if fund_choice == 'y':
                # STEP 2: Fund all addresses sequentially
                successful, results = self.fund_all_addresses_sequential(accounts_data)
                
                # STEP 3: Show final balances
                if successful > 0:
                    print(f"\n🔍 Checking final balances after funding...")
                    funded_after, total_after = self.check_account_balances(accounts_data, "FINAL ACCOUNT BALANCES")
                    
                    # Final summary
                    print("\n" + "="*80)
                    print("🎉 FUNDING PROCESS COMPLETED!")
                    print("="*80)
                    # print(f"📊 Before funding: {funded_before} accounts funded ({total_before:.6f} sFUEL)")
                    print(f"📊 After funding:  {funded_after} accounts funded ({total_after:.6f} sFUEL)")
                    print(f"✅ Successfully funded: {successful} accounts")
                    print(f"💰 Total sFUEL : {total_after:.6f} sFUEL")
                    print(f"📁 Accounts saved in: {self.accounts_folder}/")
                    print(f"📄 Master file: {self.accounts_file}")
                    print("="*80)
                else:
                    logger.error("❌ No accounts were successfully funded!")
            else:
                logger.info("🚫 Funding cancelled by user choice.")
                
        except Exception as e:
            logger.error(f"💥 Fatal error: {e}")
            raise

def main():
    funder = ExordeAccountFunder()
    funder.run()

if __name__ == "__main__":
    main()
