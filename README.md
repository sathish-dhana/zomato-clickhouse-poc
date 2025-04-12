# Myntra LogStore ClickHouse POC

This is a Proof of Concept (POC) implementation based on the Zomato blog about building a cost-effective logging platform using ClickHouse for petabyte scale.

## Overview

This POC demonstrates:
- Setting up ClickHouse with a schema similar to what Zomato used
- Generating and inserting sample log data
- Building a simple web UI to visualize and query logs
- Pagination and filtering capabilities
- Advanced querying interface
- Optimized search techniques for high-frequency terms

## Requirements

- Docker
- Python 3.8+
- pip

## Setup Instructions

### 1. Start ClickHouse Server

Run ClickHouse in a Docker container:

```bash
docker run -d --name clickhouse-server \
  -p 18123:8123 -p 19000:9000 \
  clickhouse/clickhouse-server
```

### 2. Install Python Dependencies

```bash
pip install -r requirements.txt
```

### 3. Set Up Database and Insert Sample Data

```bash
python src/setup_clickhouse.py
```

This will:
- Create a database named `myntra_logs`
- Create a table with the schema similar to Zomato's implementation
- Insert 1000 sample log entries across development, staging, and production environments

## Running the Application

### Starting the Application

1. Start the backend server:
```bash
python src/app.py --port 5000
```

2. Start the frontend server:
```bash
cd frontend && python -m http.server 8080
```

3. Access the application in your browser:
   - Main Log Viewer: http://localhost:8080/demo.html
   - Advanced Query Interface: http://localhost:8080/query.html

### Stopping the Application

1. Stop the backend server by pressing `Ctrl+C` in the terminal where it's running, or use:
```bash
pkill -f "python3 src/app.py"
```

2. Stop the frontend server by pressing `Ctrl+C` in its terminal, or use:
```bash
pkill -f "python -m http.server 8080"
```

3. Stop the ClickHouse server when you're done:
```bash
docker stop clickhouse-server
```

## Default Data

The application comes pre-loaded with sample log data that includes:
- Logs across three environments: `development`, `staging`, and `production`
- Various message types including errors, warnings, and information
- Timestamps spanning the last 7 days
- Container IDs, trace IDs, and additional metadata
- User IDs and other custom fields in the `_others` map column

When you first load the application, you'll see logs from all environments for the past 7 days (limited to 100 results).

## Features

- **Log Viewing**: View logs in a paginated table format (10, 20, 50, or 100 logs per page)
- **Filtering**: Filter logs by environment, date range, and search term
- **Statistics**: View log distribution by environment and day with interactive charts
- **Log Details**: View detailed information about each log entry in a modal
- **Advanced Query**: Execute custom SQL queries against the ClickHouse database

## High-Performance Search Optimizations

Similar to Zomato's petabyte-scale implementation, this POC includes several optimizations for high-volume log searches:

### 1. Sampling for High-Frequency Terms

When searching for common terms like "error", "exception", or "warning" that might appear in many logs, the application automatically applies sampling to reduce query time:

```sql
SELECT ... FROM foo_service 
WHERE ... AND msg LIKE '%error%'
SAMPLE 0.3  -- Sample 30% of the data
ORDER BY ts DESC LIMIT 100
```

This approach significantly reduces the data scanned while providing representative results, making queries complete in seconds instead of timing out.

### 2. Leveraging ClickHouse's Tokenized Bloom Filters

The schema design includes a bloom filter index on the message field:

```sql
INDEX foo_service_msg_index tokenbf_v1(212062,3,0) GRANULARITY 1
```

This allows the database to quickly filter out blocks that don't contain the search term before reading them, making text search much faster.

### 3. Optimized Query Construction

Queries are constructed to:
- Apply date filters first (leverage partitioning)
- Apply environment filters next (first column in ORDER BY)
- Apply text search last, with special handling for high-frequency terms
- Use early limiting to prevent excessive resource usage

### 4. Resource Management

Additional ClickHouse settings are applied:
- Thread limits to prevent query overload
- Row read limits for safety
- Timeout controls that adjust based on query complexity
- Query optimization flags to help ClickHouse make better execution plans

These optimizations allow searches to complete in under 1 second for most queries, and under 10 seconds even for high-frequency terms that might appear in millions of logs.

## End-to-End Workflow Guide

1. **Loading the Application**:
   - Open http://localhost:8080/demo.html
   - You'll see logs from all environments with default pagination (10 logs per page)
   - The sidebar shows statistics and a chart of logs by day

2. **Filtering Logs**:
   - Select a date range using the date picker
   - Choose an environment from the dropdown (development, staging, production)
   - Enter search terms to find specific log messages
   - Click "Apply Filters" to update the results

3. **Viewing Log Details**:
   - Click "View Details" on any log entry to see complete information
   - The modal shows the trace ID, message, and all fields in JSON format

4. **Using Pagination**:
   - Navigate between pages using the pagination controls
   - Change how many logs per page to display using the dropdown

5. **Advanced Querying**:
   - Click "Advanced Query" in the header
   - Write custom SQL queries in the editor
   - Use example queries from the sidebar as references
   - Execute queries and view results in the table format

## Schema Design

The schema is based on the one described in the Zomato blog:

```sql
CREATE TABLE IF NOT EXISTS foo_service (
    ts          DateTime,
    env         LowCardinality(String),
    container_id LowCardinality(String),
    trace_id    String,
    msg         String,
    offset      UInt64 CODEC(DoubleDelta, ZSTD),
    _others     Map(LowCardinality(String), String),
    INDEX foo_service_msg_index tokenbf_v1(212062, 3, 0) GRANULARITY 1
) ENGINE = MergeTree
PARTITION BY toYYYYMMDD(ts)
ORDER BY (env, trace_id, ts)
```

## Troubleshooting

- **Port Already in Use**: If you encounter "Address already in use" errors:
  - Change the backend port: `python src/app.py --port 5050`
  - Change the frontend port: `python -m http.server 8081`
  - Update `API_BASE_URL` in frontend/script.js to match your backend port

- **ClickHouse Connection Issues**:
  - Ensure Docker is running and the ClickHouse container is active
  - Verify connection parameters in `src/app.py`

- **No Data Showing**:
  - Check if `setup_clickhouse.py` was run successfully
  - Check browser console for API errors

- **Slow Queries or Timeouts**:
  - For high-frequency search terms like "error", the application uses sampling
  - Try making your search more specific (e.g., "connection error" instead of just "error")
  - Consider adding environment filters to reduce data volume

## Directory Structure

- `src/setup_clickhouse.py`: Script to set up the database schema and insert sample data
- `src/app.py`: Flask application serving the API
- `frontend/`: Frontend files (HTML, CSS, JavaScript)
  - `demo.html`: Main log viewer interface
  - `query.html`: Advanced query interface
  - `script.js`: Main JavaScript for the frontend
- `requirements.txt`: Python dependencies

## References

This POC is based on the Zomato blog article: [Building a cost-effective logging platform using Clickhouse for petabyte scale](https://blog.zomato.com/building-a-cost-effective-logging-platform-using-clickhouse-for-petabyte-scale) 