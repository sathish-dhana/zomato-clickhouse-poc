from flask import Flask, jsonify, request, render_template, send_from_directory
from flask_cors import CORS
import clickhouse_driver
import datetime
import json
import os
import time
import threading
import queue
import logging
import argparse
import re

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__, static_folder='../frontend', template_folder='../frontend')
# Configure CORS to allow all origins during development
CORS(app, resources={r"/api/*": {"origins": "*"}}, supports_credentials=True)

# Global configuration
CONFIG = {
    'max_query_execution_time': 15,  # Maximum query execution time in seconds
    'default_limit': 100,           # Default limit for query results
    'max_limit': 100,              # Maximum limit for query results (set to 100 to enforce hard limit)
    'batch_size': 20000,            # Batching for inserts (similar to Zomato's approach)
    'query_timeout': 20,            # Query timeout in seconds
    'reconnect_delay': 3,           # Seconds to wait between reconnection attempts
    'pool_size': 5                  # Number of connections in the pool
}

# Create a connection pool for ClickHouse
# This helps with distributing the workload similar to Zomato's round-robin strategy
connection_pool = []
pool_lock = threading.RLock()  # Thread-safe lock for the connection pool

# Initialize the connection pool
for i in range(CONFIG['pool_size']):  # Creating more connections in the pool
    connection_pool.append({
        'client': clickhouse_driver.Client(
            host='localhost', 
            port=19000, 
            database='myntra_logs', 
            user='default', 
            password='password',  # Using the default password from docker
            connect_timeout=10,
            send_receive_timeout=20,
            sync_request_timeout=20,
            settings={
                'max_execution_time': CONFIG['max_query_execution_time'],
                'timeout_before_checking_execution_speed': 10,
                'max_threads': 2,  # Limit threads to avoid resource exhaustion
                'log_queries': 1   # Log all queries for debugging
            }
        ),
        'in_use': False,
        'last_used': 0,
        'id': i  # Add ID for better debugging
    })

# Get an available client from the pool
def get_client():
    with pool_lock:  # Use thread-safe lock to prevent race conditions
        # Find available clients
        available_clients = [c for c in connection_pool if not c['in_use']]
        
        if available_clients:
            client_info = min(available_clients, key=lambda x: x['last_used'])
            client_info['in_use'] = True
            logger.info(f"Using connection {client_info['id']} from pool")
        else:
            # If all clients are busy, create a new temporary connection
            logger.warning("All connections in use, creating temporary connection")
            temp_client = clickhouse_driver.Client(
                host='localhost', 
                port=19000, 
                database='myntra_logs', 
                user='default', 
                password='password',
                connect_timeout=10,
                send_receive_timeout=20,
                sync_request_timeout=20,
                settings={
                    'max_execution_time': CONFIG['max_query_execution_time'],
                    'timeout_before_checking_execution_speed': 10,
                    'max_threads': 2
                }
            )
            # Create a temporary client info object
            client_info = {
                'client': temp_client,
                'in_use': True,
                'last_used': 0,
                'id': 'temp',
                'is_temporary': True  # Mark as temporary
            }
            
    # Test the connection outside the lock
    try:
        # Simple ping to check connection
        client_info['client'].execute("SELECT 1")
    except Exception as e:
        logger.warning(f"Connection test failed: {str(e)}. Attempting to reconnect...")
        time.sleep(CONFIG['reconnect_delay'])
        
        try:
            # Create a new client
            new_client = clickhouse_driver.Client(
                host='localhost', 
                port=19000, 
                database='myntra_logs', 
                user='default', 
                password='password',
                connect_timeout=10,
                send_receive_timeout=20,
                sync_request_timeout=20,
                settings={
                    'max_execution_time': CONFIG['max_query_execution_time'],
                    'timeout_before_checking_execution_speed': 10,
                    'max_threads': 2
                }
            )
            # Test the new connection
            new_client.execute("SELECT 1")
            logger.info("Successfully reconnected to ClickHouse")
            client_info['client'] = new_client
        except Exception as reconnect_error:
            logger.error(f"Failed to reconnect: {str(reconnect_error)}")
    
    return client_info

# Release a client back to the pool
def release_client(client_info):
    with pool_lock:  # Use thread-safe lock
        # Check if this is a temporary client
        if client_info.get('is_temporary', False):
            # Close the temporary connection
            try:
                client_info['client'].disconnect()
            except Exception as e:
                logger.warning(f"Error closing temporary connection: {str(e)}")
            return
            
        # Reset the in_use flag for pooled connections
        client_info['in_use'] = False
        client_info['last_used'] = time.time()
        logger.info(f"Released connection {client_info['id']} back to pool")

# Batched insert queue (simulating Zomato's batching mechanism for inserts)
insert_queue = queue.Queue()
batch_lock = threading.Lock()
current_batch = []
batch_timer = None

def process_insert_batch():
    global current_batch, batch_timer
    
    with batch_lock:
        if not current_batch:
            return
        
        batch_to_process = current_batch
        current_batch = []
        batch_timer = None
    
    try:
        client_info = get_client()
        client = client_info['client']
        
        # Use the native format for faster insertion as mentioned in Zomato's blog
        client.execute(
            'INSERT INTO foo_service (ts, env, container_id, trace_id, msg, offset, _others) VALUES',
            batch_to_process
        )
        
        logger.info(f"Successfully inserted batch of {len(batch_to_process)} records")
    except Exception as e:
        logger.error(f"Error inserting batch: {str(e)}")
        # In a real implementation, we would add retry logic here
    finally:
        release_client(client_info)

def enqueue_insert(log_data):
    global current_batch, batch_timer
    
    with batch_lock:
        current_batch.append(log_data)
        
        # If we've reached batch size, process immediately
        if len(current_batch) >= CONFIG['batch_size']:
            if batch_timer:
                batch_timer.cancel()
                batch_timer = None
            threading.Thread(target=process_insert_batch).start()
        elif batch_timer is None:
            # Otherwise, start a timer to process the batch if it's not processed within 5 seconds
            # This is similar to Zomato's approach of a maximum lag of 5 seconds
            batch_timer = threading.Timer(5, lambda: threading.Thread(target=process_insert_batch).start())
            batch_timer.daemon = True
            batch_timer.start()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/demo')
def demo():
    return render_template('demo.html')

@app.route('/api/logs', methods=['GET'])
def get_logs():
    client_info = get_client()
    client = client_info['client']
    start_time = time.time()
    
    try:
        # Get query parameters with defaults
        env = request.args.get('env', '')
        start_date = request.args.get('start_date', (datetime.datetime.now() - datetime.timedelta(days=7)).strftime('%Y-%m-%d'))
        end_date = request.args.get('end_date', datetime.datetime.now().strftime('%Y-%m-%d'))
        search_term = request.args.get('search_term', '')
        
        # Apply limit (with bounds) - helps prevent excessive resource usage
        try:
            limit = int(request.args.get('limit', CONFIG['default_limit']))
            limit = min(limit, CONFIG['max_limit'])
        except ValueError:
            limit = CONFIG['default_limit']
        
        # High-frequency terms that might cause timeout
        high_frequency_terms = ['error', 'exception', 'fail', 'warning', 'unable', 'timeout', 'failed']
        
        # Check if it's a high-frequency term
        is_high_frequency = search_term and search_term.lower() in high_frequency_terms
        
        # Build the query with direct string substitution for all parameters
        # For high-frequency terms, we'll use a more optimized approach without SAMPLE
        query = f"""
        SELECT ts, env, container_id, trace_id, msg, offset, _others 
        FROM foo_service
        WHERE 1=1
        AND ts BETWEEN toDateTime('{start_date}') AND toDateTime('{end_date}')
        """
        
        # Environment filter is usually very selective due to being first in ORDER BY
        if env:
            query += f" AND env = '{env}'"
        
        # For high-frequency terms, add additional constraints to make query more selective
        if search_term:
            # Escape single quotes in the search term
            safe_search_term = search_term.replace("'", "''")
            
            if is_high_frequency:
                # For common terms like "error", we make the query more selective
                # by limiting the results and ensuring efficient ordering
                query += f" AND (msg LIKE '%{safe_search_term}%')"
                # Use a tighter limit for high-frequency terms to prevent timeouts
                actual_limit = limit
                # Use most recent logs only
                query += f" ORDER BY ts DESC LIMIT {actual_limit}"
                logger.info(f"Using optimized query for high-frequency term: {safe_search_term}")
            else:
                # For normal terms, use standard query
                query += f" AND (msg LIKE '%{safe_search_term}%')"
                query += f" ORDER BY ts DESC LIMIT {limit}"
        else:
            # No search term, use standard query
            query += f" ORDER BY ts DESC LIMIT {limit}"
        
        logger.info(f"Executing optimized query: {query}")
        
        # Execute with timeout adjusted based on query complexity
        timeout = CONFIG['query_timeout'] * 2 if is_high_frequency else CONFIG['query_timeout']
        
        # Execute the query with optimized settings - no SAMPLE clause
        results = client.execute(query, settings={
            'max_execution_time': timeout,
            'max_threads': 2,  # Limit threads as Zomato suggests for better resource usage
            'max_block_size': 10000,  # Use smaller blocks for network transfers
            'timeout_before_checking_execution_speed': 5,
            # Use ClickHouse's optimizations
            'enable_optimize_predicate_expression': 1,
            'optimize_skip_unused_shards': 1,
            'optimize_read_in_order': 1  # Optimize for ordered reads
        })
        
        # Format the results
        logs = []
        for row in results:
            ts, env, container_id, trace_id, msg, offset, others = row
            
            log_entry = {
                'timestamp': ts.strftime('%Y-%m-%d %H:%M:%S'),
                'env': env,
                'container_id': container_id,
                'trace_id': trace_id,
                'message': msg,
                'offset': offset
            }
            
            # Add other fields from the Map column
            for key, value in others.items():
                log_entry[key] = value
            
            logs.append(log_entry)
        
        # Apply limit on the client side for sampled queries
        logs = logs[:limit]
        
        query_time = time.time() - start_time
        logger.info(f"Query executed in {query_time:.3f} seconds, returned {len(logs)} results")
        
        return jsonify(logs)
    
    except Exception as e:
        logger.error(f"Error executing query: {str(e)}")
        return jsonify({"error": str(e)}), 500
    
    finally:
        release_client(client_info)

@app.route('/api/environments', methods=['GET'])
def get_environments():
    client_info = get_client()
    client = client_info['client']
    
    try:
        # Get unique environments - this query is simple and fast
        query = "SELECT DISTINCT env FROM foo_service"
        results = client.execute(query)
        
        environments = [row[0] for row in results]
        return jsonify(environments)
    
    except Exception as e:
        logger.error(f"Error getting environments: {str(e)}")
        return jsonify({"error": str(e)}), 500
        
    finally:
        release_client(client_info)

@app.route('/api/stats', methods=['GET'])
def get_stats():
    client_info = get_client()
    client = client_info['client']
    
    try:
        # Get query parameters with defaults
        start_date = request.args.get('start_date', (datetime.datetime.now() - datetime.timedelta(days=7)).strftime('%Y-%m-%d'))
        end_date = request.args.get('end_date', datetime.datetime.now().strftime('%Y-%m-%d'))
        
        # Similar to Zomato's approach, we're using efficient aggregations
        # Get log counts by environment
        env_query = f"""
        SELECT env, count() as count
        FROM foo_service
        WHERE ts BETWEEN toDateTime('{start_date}') AND toDateTime('{end_date}')
        GROUP BY env
        ORDER BY count DESC
        """
        
        env_results = client.execute(env_query)
        env_stats = [{'env': row[0], 'count': row[1]} for row in env_results]
        
        # Get log counts by day
        day_query = f"""
        SELECT toDate(ts) as day, count() as count
        FROM foo_service
        WHERE ts BETWEEN toDateTime('{start_date}') AND toDateTime('{end_date}')
        GROUP BY day
        ORDER BY day
        """
        
        day_results = client.execute(day_query)
        day_stats = [{'day': row[0].strftime('%Y-%m-%d'), 'count': row[1]} for row in day_results]
        
        return jsonify({
            'by_environment': env_stats,
            'by_day': day_stats
        })
    
    except Exception as e:
        logger.error(f"Error getting stats: {str(e)}")
        return jsonify({"error": str(e)}), 500
        
    finally:
        release_client(client_info)

# Example endpoint to add new logs (demonstrates the batching mechanism)
@app.route('/api/logs', methods=['POST'])
def add_log():
    try:
        log_data = request.json
        
        # Validate required fields
        required_fields = ['timestamp', 'env', 'container_id', 'trace_id', 'message']
        for field in required_fields:
            if field not in log_data:
                return jsonify({"error": f"Missing required field: {field}"}), 400
        
        # Convert timestamp to datetime object
        try:
            ts = datetime.datetime.fromisoformat(log_data['timestamp'].replace('Z', '+00:00'))
        except ValueError:
            ts = datetime.datetime.now()
        
        # Extract known fields
        env = log_data['env']
        container_id = log_data['container_id']
        trace_id = log_data['trace_id']
        msg = log_data['message']
        offset = log_data.get('offset', 0)
        
        # Put all other fields in the others map
        others = {}
        for key, value in log_data.items():
            if key not in required_fields + ['offset']:
                others[key] = str(value)
        
        # Enqueue the log for batched insertion
        log_entry = (ts, env, container_id, trace_id, msg, offset, others)
        enqueue_insert(log_entry)
        
        return jsonify({"success": True})
    
    except Exception as e:
        logger.error(f"Error adding log: {str(e)}")
        return jsonify({"error": str(e)}), 500

# Advanced query endpoint - similar to Zomato's need for customized queries
@app.route('/api/query', methods=['POST'])
def execute_query():
    client_info = get_client()
    client = client_info['client']
    start_time = time.time()
    
    try:
        req_data = request.json
        if not req_data or 'query' not in req_data:
            return jsonify({"error": "Missing query parameter"}), 400
        
        query = req_data['query']
        
        # Security check - prevent data modification
        lower_query = query.lower()
        if any(word in lower_query for word in ['insert', 'update', 'delete', 'drop', 'alter', 'create']):
            return jsonify({"error": "Only SELECT queries are allowed"}), 403
        
        # Detect if this is a high-frequency term query
        high_frequency_terms = ['error', 'exception', 'fail', 'warning', 'unable', 'timeout', 'failed']
        is_high_frequency_query = any(term in lower_query for term in high_frequency_terms)
        
        # For high-frequency terms, we'll use a stricter LIMIT instead of SAMPLE
        if is_high_frequency_query:
            # Add a stricter LIMIT for high-frequency terms
            if 'limit' not in lower_query:
                query += f" LIMIT {min(CONFIG['max_limit'] // 2, 1000)}"
            logger.info(f"Added stricter LIMIT for high-frequency query")
        else:
            # Ensure the query has a LIMIT to prevent excessive resource usage
            if 'limit' not in lower_query:
                query += f" LIMIT {CONFIG['max_limit']}"
        
        logger.info(f"Executing custom query: {query}")
        
        # Adjust timeout based on query complexity
        timeout = CONFIG['query_timeout'] * 2 if is_high_frequency_query else CONFIG['query_timeout']
        
        # Execute with optimized settings (similar to Zomato's approach)
        results = client.execute(query, settings={
            'max_execution_time': timeout,
            'max_threads': 2,  # Limit threads for better resource sharing
            'max_rows_to_read': 1000000,  # Add a safety limit on rows read
            'timeout_before_checking_execution_speed': 10,
            'enable_optimize_predicate_expression': 1,
            'optimize_skip_unused_shards': 1
        })
        
        # Get column names for the result set
        if results:
            # Extract column names from the result's metadata
            column_names = []
            if len(results[0]) > 0:
                # Try to get column names from metadata or generate generic names
                try:
                    column_descriptions = client.execute("DESCRIBE TABLE foo_service")
                    column_names = [desc[0] for desc in column_descriptions]
                    
                    # If we have more columns than names, add generic ones
                    while len(column_names) < len(results[0]):
                        column_names.append(f"column_{len(column_names)}")
                except Exception:
                    # If metadata retrieval fails, use generic column names
                    column_names = [f"column_{i}" for i in range(len(results[0]))]
            
            # Format the results with proper date handling
            formatted_results = []
            for row in results:
                row_dict = {}
                for i, value in enumerate(row):
                    if i < len(column_names):
                        # Handle datetime objects
                        if isinstance(value, datetime.datetime):
                            row_dict[column_names[i]] = value.strftime('%Y-%m-%d %H:%M:%S')
                        else:
                            row_dict[column_names[i]] = value
                    else:
                        row_dict[f"column_{i}"] = value
                formatted_results.append(row_dict)
            
            query_time = time.time() - start_time
            logger.info(f"Custom query executed in {query_time:.3f} seconds, returned {len(formatted_results)} results")
            
            return jsonify(formatted_results)
        else:
            return jsonify([])
    
    except Exception as e:
        logger.error(f"Error executing custom query: {str(e)}")
        return jsonify({"error": str(e)}), 500
        
    finally:
        release_client(client_info)

if __name__ == '__main__':
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='Start the Flask server')
    parser.add_argument('--port', type=int, default=8888, help='Port to run the server on')
    args = parser.parse_args()
    
    # Run on specified port
    app.run(debug=True, host='127.0.0.1', port=args.port) 