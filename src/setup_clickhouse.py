import clickhouse_driver
import random
import datetime
import uuid
import json

# Create a connection to ClickHouse
client = clickhouse_driver.Client(host='localhost', port=19000, user='default', password='password')

# Create database
client.execute('CREATE DATABASE IF NOT EXISTS myntra_logs')
client.execute('USE myntra_logs')

# Create table similar to what's described in the Zomato blog
# Modified to work with the current ClickHouse version
client.execute('''
CREATE TABLE IF NOT EXISTS foo_service (
    ts          DateTime,
    env         LowCardinality(String),
    container_id LowCardinality(String),
    trace_id    String,
    msg         String,
    offset      UInt64 CODEC(DoubleDelta, ZSTD),
    _others     Map(LowCardinality(String), String),
    INDEX foo_service_msg_index msg TYPE tokenbf_v1(212062, 3, 0) GRANULARITY 1
) ENGINE = MergeTree
PARTITION BY toYYYYMMDD(ts)
ORDER BY (env, trace_id, ts)
''')

# Generate sample data
environments = ['production', 'staging', 'development']
container_ids = ['container_' + str(i) for i in range(1, 6)]
message_templates = [
    "HTTP request completed with status code {status_code}",
    "Database query executed in {query_time} ms",
    "User {user_id} logged in successfully",
    "Payment of {amount} processed for order {order_id}",
    "Could not make HTTP request to {url}",
    "Error processing user request: {error_message}",
    "Cache hit for key {cache_key}",
    "New order created with ID {order_id}"
]

# Helper function to generate random log entries
def generate_log_entry():
    env = random.choice(environments)
    container_id = random.choice(container_ids)
    trace_id = str(uuid.uuid4())
    
    # Generate a random timestamp within the last 7 days
    now = datetime.datetime.now()
    days_ago = random.randint(0, 7)
    hours_ago = random.randint(0, 23)
    minutes_ago = random.randint(0, 59)
    seconds_ago = random.randint(0, 59)
    ts = now - datetime.timedelta(days=days_ago, hours=hours_ago, minutes=minutes_ago, seconds=seconds_ago)
    
    # Generate message
    template = random.choice(message_templates)
    
    # Generate _others map data
    others = {}
    
    if "status_code" in template:
        status_code = random.choice([200, 201, 400, 404, 500])
        msg = template.format(status_code=status_code)
        others["status_code"] = str(status_code)
    
    elif "query_time" in template:
        query_time = random.randint(1, 1000)
        msg = template.format(query_time=query_time)
        others["query_time"] = str(query_time)
        others["db_name"] = random.choice(["users", "orders", "payments", "products"])
    
    elif "user_id" in template:
        user_id = random.randint(1000, 9999)
        msg = template.format(user_id=user_id)
        others["user_id"] = str(user_id)
        others["ip_address"] = f"192.168.{random.randint(1, 255)}.{random.randint(1, 255)}"
    
    elif "amount" in template:
        amount = round(random.uniform(10, 1000), 2)
        order_id = random.randint(10000, 99999)
        msg = template.format(amount=amount, order_id=order_id)
        others["amount"] = str(amount)
        others["order_id"] = str(order_id)
        others["payment_method"] = random.choice(["credit_card", "debit_card", "upi", "wallet"])
    
    elif "url" in template:
        url = f"https://api.example.com/v1/{random.choice(['users', 'orders', 'products'])}/{random.randint(1, 1000)}"
        msg = template.format(url=url)
        others["url"] = url
        others["user_id"] = str(random.randint(1000, 9999))
    
    elif "error_message" in template:
        error_messages = ["Timeout exceeded", "Invalid input", "Database connection failed", "Permission denied"]
        error_message = random.choice(error_messages)
        msg = template.format(error_message=error_message)
        others["error_message"] = error_message
        others["error_code"] = str(random.randint(1000, 9999))
    
    elif "cache_key" in template:
        cache_key = f"user:{random.randint(1000, 9999)}:prefs"
        msg = template.format(cache_key=cache_key)
        others["cache_key"] = cache_key
        others["ttl"] = str(random.randint(60, 3600))
    
    elif "order_id" in template and "amount" not in template:
        order_id = random.randint(10000, 99999)
        msg = template.format(order_id=order_id)
        others["order_id"] = str(order_id)
        others["user_id"] = str(random.randint(1000, 9999))
        others["items_count"] = str(random.randint(1, 10))
    
    # Add some common fields
    others["service"] = "foo_service"
    others["version"] = f"v1.{random.randint(0, 9)}.{random.randint(0, 99)}"
    
    return (ts, env, container_id, trace_id, msg, random.randint(1, 1000000), others)

# Insert 1000 sample log entries
sample_data = [generate_log_entry() for _ in range(1000)]
client.execute(
    'INSERT INTO foo_service (ts, env, container_id, trace_id, msg, offset, _others) VALUES',
    sample_data
)

print(f"Successfully inserted {len(sample_data)} sample log entries into ClickHouse.")
print("You can now query the data using the web UI or direct queries.") 