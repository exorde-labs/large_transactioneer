transactions as you go from the rest of your application!** The example code showing pre-loading transactions is just one usage pattern, not a limitation.

## How the Queue System Works

The transaction sender is designed to work in **two modes simultaneously**:

### 1. **Pre-loaded Mode** (Your Example)
```python
# Add transactions before starting
example_transactions = [...]
sender.add_transactions_batch(example_transactions)
sender.run()  # Processes pre-loaded transactions
```

### 2. **Dynamic Mode** (Runtime Addition)
```python
# Start sender in background
import threading

def run_sender_background():
    sender = ExordeHighSpeedSender()
    sender.run()  # Runs indefinitely, waiting for transactions

# Start in background thread
sender_thread = threading.Thread(target=run_sender_background, daemon=True)
sender_thread.start()

# Now your application can add transactions anytime
while your_application_is_running:
    # Your application logic here
    if new_data_to_process:
        sender.add_transaction(
            file_hashs=["QmNewHash"],
            url_domains=["yourdomain.com"],
            item_counts=[42],
            extra="dynamic_data"
        )
```

## Key Design Features

### **Thread-Safe Queue Operations**
The sender uses `queue.Queue()` which is thread-safe, meaning:
- Your main application thread can add transactions
- The sender thread processes them independently
- No race conditions or data corruption

### **Continuous Processing Loop**
The `run_high_speed_loop()` method:
```python
while self.running:
    try:
        # Waits for transactions (with timeout)
        transaction_params = self.transaction_queue.get(timeout=self.queue_empty_timeout)
        # Process transaction
    except queue.Empty:
        # When queue is empty, just wait and continue
        continue
```

## Recommended Integration Pattern

Here's how to integrate it properly with your application:

```python
import threading
import time

class YourApplication:
    def __init__(self):
        self.sender = ExordeHighSpeedSender()
        self.sender_thread = None
        
    def start_transaction_sender(self):
        """Start the transaction sender in background"""
        def run_sender():
            self.sender.run()  # Runs indefinitely
            
        self.sender_thread = threading.Thread(target=run_sender, daemon=True)
        self.sender_thread.start()
        
        # Give it time to initialize
        time.sleep(2)
        print("✅ Transaction sender ready for dynamic transactions")
    
    def process_your_data(self):
        """Your main application logic"""
        while True:
            # Your data processing logic
            data = self.get_next_data_to_process()
            
            if data:
                # Add transaction dynamically
                self.sender.add_transaction(
                    file_hashs=[data['hash']],
                    url_domains=[data['domain']],
                    item_counts=[data['count']],
                    extra=data['extra']
                )
                
                print(f"📥 Added transaction, queue size: {self.sender.get_queue_size()}")
            
            time.sleep(0.1)  # Your processing interval
    
    def run(self):
        # Start transaction sender
        self.start_transaction_sender()
        
        # Run your main application
        self.process_your_data()

# Usage
app = YourApplication()
app.run()
```

## Queue Management Features

The sender provides several methods for dynamic interaction:

```python
# Add single transaction anytime
sender.add_transaction(file_hashs, url_domains, item_counts, extra)

# Add multiple transactions at once
sender.add_transactions_batch(transaction_list)

# Monitor queue status
queue_size = sender.get_queue_size()

# Stop processing gracefully
sender.stop()
```

## Performance Considerations

### **Queue Empty Behavior**
When no transactions are available:
- Sender waits `queue_empty_timeout` seconds (default: 1.0s)
- Logs "Queue empty, waiting..." message
- Continues checking for new transactions
- **Does not exit or stop**

### **Memory Management**
Consider setting a maximum queue size to prevent memory issues:
```python
# In __init__ method, replace:
self.transaction_queue = queue.Queue()
# With:
self.transaction_queue = queue.Queue(maxsize=10000)
```

## Your Example Fixed for Dynamic Use

```python
def main():
    sender = ExordeHighSpeedSender()
    
    # Start sender in background thread
    import threading
    
    def run_sender():
        sender.run()  # Runs indefinitely
    
    sender_thread = threading.Thread(target=run_sender, daemon=True)
    sender_thread.start()
    
    # Give it time to initialize
    time.sleep(2)
    
    # Now add transactions dynamically
    example_transactions = [
        {
            'file_hashs': ["QmUtQJK2YncnLcBL6W9d8xeJzSmThb2CU7mpbdiC4CpkcE"],
            'url_domains': [""],
            'item_counts': [40],
            'extra': ""
        },
        {
            'file_hashs': ["QmUtQJK2YncnLcBL6W9d8xeJzSmThb2CU7mpbdiC4CpkcE"],
            'url_domains': [""],
            'item_counts': [40],
            'extra': ""
        },
    ]
    
    # Add initial batch
    example_transactions = example_transactions * 1000
    sender.add_transactions_batch(example_transactions)
    
    # Continue adding more transactions as your app runs
    while True:
        # Your application can add more transactions here
        time.sleep(10)  # Example: add more every 10 seconds
        sender.add_transaction(
            file_hashs=["QmNewHash"],
            url_domains=[""],
            item_counts=[50],
            extra=""
        )
        print(f"Queue size: {sender.get_queue_size()}")
```

**The system is specifically designed for dynamic, continuous operation where your application can feed it transactions whenever needed!**
