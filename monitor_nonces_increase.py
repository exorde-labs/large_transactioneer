import requests
import time
import json
import os
from web3 import Web3, HTTPProvider
from web3.middleware import simple_cache_middleware
import logging
from datetime import datetime
from collections import defaultdict

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class ExordePoolMonitor:
    def __init__(self):
        # Configuration
        self.accounts_folder = "exorde_accounts"
        self.accounts_file = os.path.join(self.accounts_folder, "accounts.json")
        self.monitor_interval = 120  # 2 minutes between checks
        self.sample_every_nth = 10   # Monitor every 10th account
        
        # Network configuration
        self.w3 = None
        self.chain_id = None
        
        # Monitoring data
        self.monitored_accounts = []
        self.nonce_history = defaultdict(list)  # {address: [(timestamp, nonce), ...]}
        self.running = False

    def initialize_network(self):
        """Initialize network configuration"""
        try:
            logger.info("🔄 Initializing network connection...")
            net_configs = requests.get(
                "https://raw.githubusercontent.com/exorde-labs/TestnetProtocol/main/NetworkConfig.json",
                timeout=30
            ).json()
            
            # Extract configuration for testnet-A
            for network in net_configs['testnet']:
                if network['_networkId'] == 'testnet-A':
                    self.chain_id = network['_chainID']
                    rpc_url = network["_urlTxSkale"]
                    break
            
            # Initialize Web3 instance
            self.w3 = Web3(Web3.HTTPProvider(rpc_url))
            try:
                self.w3.middleware_onion.add(simple_cache_middleware)
            except Exception as e:
                logger.warning(f"⚠️  Middleware warning: {e}")
            
            logger.info(f"✅ Connected to network (Chain ID: {self.chain_id})")
            
        except Exception as e:
            logger.error(f"❌ Failed to initialize network: {e}")
            raise

    def load_monitored_accounts(self):
        """Load accounts and select every 10th for monitoring"""
        try:
            if not os.path.exists(self.accounts_file):
                raise FileNotFoundError(f"Accounts file not found: {self.accounts_file}")
            
            with open(self.accounts_file, 'r') as f:
                all_accounts = json.load(f)
            
            # Select every 10th account for monitoring
            self.monitored_accounts = []
            for i in range(0, len(all_accounts), self.sample_every_nth):
                account = all_accounts[i]
                self.monitored_accounts.append({
                    'index': account['index'],
                    'address': account['address'],
                    'position': i
                })
            
            logger.info(f"📋 Monitoring {len(self.monitored_accounts)} accounts (every {self.sample_every_nth}th from {len(all_accounts)} total)")
            
        except Exception as e:
            logger.error(f"❌ Failed to load accounts: {e}")
            raise

    def get_current_nonces(self):
        """Fetch current nonces for all monitored accounts"""
        current_time = datetime.now()
        nonces_data = {}
        
        for account in self.monitored_accounts:
            try:
                address = account['address']
                nonce = self.w3.eth.get_transaction_count(address)
                nonces_data[address] = nonce
                
                # Store in history
                self.nonce_history[address].append((current_time, nonce))
                
                # Keep only last 10 entries per account
                if len(self.nonce_history[address]) > 10:
                    self.nonce_history[address] = self.nonce_history[address][-10:]
                    
            except Exception as e:
                logger.error(f"❌ Failed to get nonce for {address}: {e}")
                nonces_data[address] = None
        
        return nonces_data, current_time

    def calculate_nonce_increases(self, current_nonces, current_time):
        """Calculate nonce increases since last check"""
        increases_data = []
        
        for account in self.monitored_accounts:
            address = account['address']
            current_nonce = current_nonces.get(address)
            
            if current_nonce is None:
                continue
            
            # Find previous nonce
            history = self.nonce_history[address]
            if len(history) >= 2:
                prev_time, prev_nonce = history[-2]
                increase = current_nonce - prev_nonce
                time_diff = (current_time - prev_time).total_seconds()
                rate = increase / (time_diff / 60) if time_diff > 0 else 0  # per minute
            else:
                prev_nonce = current_nonce
                increase = 0
                rate = 0
            
            increases_data.append({
                'account': account,
                'current_nonce': current_nonce,
                'prev_nonce': prev_nonce,
                'increase': increase,
                'rate_per_min': rate
            })
        
        return increases_data

    def display_monitoring_results(self, increases_data, current_time):
        """Display monitoring results in a nice format"""
        
        # Calculate summary statistics
        total_increases = sum(data['increase'] for data in increases_data)
        active_accounts = sum(1 for data in increases_data if data['increase'] > 0)
        avg_rate = sum(data['rate_per_min'] for data in increases_data) / len(increases_data) if increases_data else 0
        
        print("\n" + "="*80)
        print(f"📊 EXORDE TRANSACTION POOL MONITOR - {current_time.strftime('%H:%M:%S')}")
        print("="*80)
        print(f"📈 Summary Statistics:")
        print(f"   • Total nonce increases: {total_increases}")
        print(f"   • Active accounts: {active_accounts}/{len(increases_data)}")
        print(f"   • Average rate: {avg_rate:.2f} tx/min per monitored account")
        print(f"   • Estimated pool TPS: {(avg_rate * len(self.monitored_accounts) * self.sample_every_nth) / 60:.1f}")
        print("-" * 80)
        
        # Display individual account details
        print("📋 Account Activity Details:")
        print(f"{'Account':<10} {'Address':<12} {'Prev':<8} {'Current':<8} {'Increase':<8} {'Rate/min':<10} {'Status'}")
        print("-" * 80)
        
        for data in increases_data:
            account = data['account']
            status = "🟢 ACTIVE" if data['increase'] > 0 else "⚪ IDLE"
            
            print(f"{account['index']:<10} "
                  f"{account['address'][:12]:<12} "
                  f"{data['prev_nonce']:<8} "
                  f"{data['current_nonce']:<8} "
                  f"{data['increase']:<8} "
                  f"{data['rate_per_min']:<10.2f} "
                  f"{status}")
        
        print("="*80)
        
        # Pool utilization analysis
        utilization_pct = (active_accounts / len(increases_data)) * 100 if increases_data else 0
        
        print(f"🎯 Pool Utilization Analysis:")
        if utilization_pct >= 80:
            print(f"   ✅ EXCELLENT: {utilization_pct:.1f}% of monitored accounts active")
        elif utilization_pct >= 60:
            print(f"   ✅ GOOD: {utilization_pct:.1f}% of monitored accounts active")
        elif utilization_pct >= 40:
            print(f"   ⚠️  MODERATE: {utilization_pct:.1f}% of monitored accounts active")
        else:
            print(f"   ❌ LOW: {utilization_pct:.1f}% of monitored accounts active")
        
        if total_increases == 0:
            print(f"   ⚠️  No transaction activity detected in last {self.monitor_interval}s")
        
        print("="*80)

    def run_monitoring_cycle(self):
        """Run a single monitoring cycle"""
        try:
            logger.info("🔍 Starting monitoring cycle...")
            
            # Get current nonces
            current_nonces, current_time = self.get_current_nonces()
            
            # Calculate increases
            increases_data = self.calculate_nonce_increases(current_nonces, current_time)
            
            # Display results
            self.display_monitoring_results(increases_data, current_time)
            
            logger.info("✅ Monitoring cycle completed")
            
        except Exception as e:
            logger.error(f"❌ Error in monitoring cycle: {e}")

    def start_monitoring(self):
        """Start continuous monitoring loop"""
        logger.info("🚀 Starting continuous pool monitoring...")
        
        print("\n" + "="*80)
        print("🔍 EXORDE TRANSACTION POOL MONITOR STARTED")
        print("="*80)
        print(f"📊 Monitoring {len(self.monitored_accounts)} accounts (every {self.sample_every_nth}th)")
        print(f"⏱️  Check interval: {self.monitor_interval} seconds")
        print(f"🎯 Press Ctrl+C to stop monitoring")
        print("="*80)
        
        self.running = True
        
        try:
            while self.running:
                self.run_monitoring_cycle()
                
                # Wait for next cycle
                logger.info(f"⏳ Waiting {self.monitor_interval} seconds until next check...")
                time.sleep(self.monitor_interval)
                
        except KeyboardInterrupt:
            logger.info("🛑 Monitoring stopped by user")
            self.running = False
        except Exception as e:
            logger.error(f"💥 Fatal error in monitoring: {e}")
            self.running = False

    def run_single_check(self):
        """Run a single monitoring check and exit"""
        logger.info("🔍 Running single monitoring check...")
        self.run_monitoring_cycle()
        logger.info("✅ Single check completed")

    def run(self, continuous=True):
        """Main execution function"""
        try:
            print("🔍 EXORDE TRANSACTION POOL MONITOR")
            print("="*50)
            
            # Initialize
            self.initialize_network()
            self.load_monitored_accounts()
            
            if continuous:
                self.start_monitoring()
            else:
                self.run_single_check()
                
        except Exception as e:
            logger.error(f"💥 Fatal error: {e}")
            raise

def main():
    """Main function with options"""
    import sys
    
    monitor = ExordePoolMonitor()
    
    # Check command line arguments
    if len(sys.argv) > 1 and sys.argv[1] == "--single":
        # Run single check
        monitor.run(continuous=False)
    else:
        # Run continuous monitoring
        monitor.run(continuous=True)

if __name__ == "__main__":
    main()
