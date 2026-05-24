# Chaos Simulation Engine for Local GraphRAG SRE Agent
import os
import sqlite3
import random
import uuid
import time
import json
import argparse
from datetime import datetime, timedelta

DB_PATH = "telemetry.db"
SCHEMA_PATH = "schema.sql"
STATE_PATH = "chaos_state.json"

SERVICES = ["Gateway", "Auth", "Checkout", "Inventory", "Payment", "Database"]

# Normal execution baselines (mean latency, std dev)
BASELINES = {
    "Auth": (15, 3),
    "Checkout": (35, 5),
    "Inventory": (45, 8),
    "Payment": (120, 15),
    "Database": (8, 2)
}

def init_db(force=False):
    """Initializes the SQLite database with the schema."""
    if force and os.path.exists(DB_PATH):
        os.remove(DB_PATH)
        print("Existing database removed.")

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    if os.path.exists(SCHEMA_PATH):
        with open(SCHEMA_PATH, "r") as f:
            schema = f.read()
            cursor.executescript(schema)
        print("Database schema initialized successfully.")
    else:
        print(f"Error: {SCHEMA_PATH} not found!")

    conn.commit()
    conn.close()

    # Initialize chaos state
    set_chaos_state("none")

def get_chaos_state():
    """Reads the current active failure mode."""
    if not os.path.exists(STATE_PATH):
        return "none"
    try:
        with open(STATE_PATH, "r") as f:
            data = json.load(f)
            return data.get("mode", "none")
    except Exception:
        return "none"

def set_chaos_state(mode):
    """Sets a new active failure mode."""
    with open(STATE_PATH, "w") as f:
        json.dump({"mode": mode, "updated_at": str(datetime.now())}, f)
    print(f"Chaos state updated to: {mode}")

def write_trace(cursor, trace_id, span_id, parent_id, service, endpoint, duration, status, timestamp):
    cursor.execute(
        """
        INSERT INTO traces (trace_id, span_id, parent_span_id, service, endpoint, duration_ms, status_code, timestamp)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (trace_id, span_id, parent_id, service, endpoint, int(duration), int(status), timestamp.strftime('%Y-%m-%d %H:%M:%f'))
    )

def write_log(cursor, service, level, message, trace_id, timestamp):
    cursor.execute(
        """
        INSERT INTO logs (service, level, message, trace_id, timestamp)
        VALUES (?, ?, ?, ?, ?)
        """,
        (service, level, message, trace_id, timestamp.strftime('%Y-%m-%d %H:%M:%f'))
    )

def write_metric(cursor, service, name, value, timestamp):
    cursor.execute(
        """
        INSERT INTO metrics (service, metric_name, value, timestamp)
        VALUES (?, ?, ?, ?)
        """,
        (service, name, float(value), timestamp.strftime('%Y-%m-%d %H:%M:%f'))
    )

def simulate_request(conn, timestamp=None):
    """Simulates a single complete transaction path with logs, metrics, and traces."""
    if timestamp is None:
        timestamp = datetime.now()

    cursor = conn.cursor()
    trace_id = str(uuid.uuid4())
    failure_mode = get_chaos_state()

    # 1. Gateway Span (Parent Span)
    gateway_span = str(uuid.uuid4())
    gw_start = timestamp
    
    # 2. Auth Span
    auth_span = str(uuid.uuid4())
    auth_latency = random.normalvariate(*BASELINES["Auth"])
    auth_status = 200
    
    # Inject Failure Mode: auth_leak (creates latency & token failures)
    if failure_mode == "auth_leak":
        auth_latency = random.uniform(800, 1500) # Auth slowdown
        if random.random() < 0.15:
            auth_status = 401 # Unauthorized leaks

    auth_timestamp = gw_start + timedelta(milliseconds=2)
    write_trace(cursor, trace_id, auth_span, gateway_span, "Auth", "/v1/auth/verify", auth_latency, auth_status, auth_timestamp)
    write_log(cursor, "Auth", "INFO", "Verifying JWT auth header", trace_id, auth_timestamp)
    
    if auth_status == 401:
        write_log(cursor, "Auth", "ERROR", "Token signature validation failed - unauthorized access attempt", trace_id, auth_timestamp + timedelta(milliseconds=auth_latency))
        # Gateway fails early
        write_trace(cursor, trace_id, gateway_span, None, "Gateway", "/checkout", auth_latency + 5, 401, gw_start)
        write_log(cursor, "Gateway", "WARNING", "Request terminated at Gateway due to Auth validation failure", trace_id, gw_start + timedelta(milliseconds=auth_latency))
        return

    write_log(cursor, "Auth", "INFO", "Auth verified successfully", trace_id, auth_timestamp + timedelta(milliseconds=auth_latency))

    # 3. Checkout Span
    checkout_span = str(uuid.uuid4())
    chk_start = auth_timestamp + timedelta(milliseconds=auth_latency + 1)
    
    # 4. Inventory Span
    inv_span = str(uuid.uuid4())
    inv_latency = random.normalvariate(*BASELINES["Inventory"])
    inv_status = 200
    write_trace(cursor, trace_id, inv_span, checkout_span, "Inventory", "/v1/inventory/deduct", inv_latency, inv_status, chk_start + timedelta(milliseconds=2))
    write_log(cursor, "Inventory", "INFO", "Deducting stock for item SKU-8842", trace_id, chk_start + timedelta(milliseconds=2))
    write_log(cursor, "Inventory", "INFO", "Stock successfully deducted", trace_id, chk_start + timedelta(milliseconds=inv_latency))

    # 5. Payment Span
    pay_span = str(uuid.uuid4())
    pay_start = chk_start + timedelta(milliseconds=inv_latency + 3)
    pay_latency = random.normalvariate(*BASELINES["Payment"])
    pay_status = 200

    # Inject Failure Mode: payment_gateway_down
    if failure_mode == "payment_gateway_down":
        pay_latency = random.uniform(2000, 3000) # Gateway timeout
        if random.random() < 0.8:
            pay_status = 504 # Gateway timeout

    # 6. Database Span
    db_span = str(uuid.uuid4())
    db_latency = random.normalvariate(*BASELINES["Database"])
    db_status = 200

    # Inject Failure Mode: database_slowdown
    if failure_mode == "database_slowdown":
        db_latency = random.uniform(4000, 6000) # SQL lock wait / missing index
        if random.random() < 0.2:
            db_status = 500 # Internal DB timeout / error

    db_start = pay_start + timedelta(milliseconds=10)
    write_trace(cursor, trace_id, db_span, pay_span, "Database", "INSERT INTO transactions VALUES (?, ?)", db_latency, db_status, db_start)
    write_log(cursor, "Database", "INFO", "Beginning SQL transaction block", trace_id, db_start)
    
    if db_status == 500:
        write_log(cursor, "Database", "CRITICAL", "PGSQL Lock Wait Timeout exceeded - lock detected on transaction table", trace_id, db_start + timedelta(milliseconds=100))
    elif failure_mode == "database_slowdown":
        write_log(cursor, "Database", "WARNING", "Slow query detected: table scan took longer than threshold", trace_id, db_start + timedelta(milliseconds=db_latency))
    else:
        write_log(cursor, "Database", "INFO", "SQL transaction committed", trace_id, db_start + timedelta(milliseconds=db_latency))

    # Payment wraps up
    actual_pay_latency = pay_latency + db_latency
    write_trace(cursor, trace_id, pay_span, checkout_span, "Payment", "/v1/charges/create", actual_pay_latency, pay_status if db_status == 200 else 500, pay_start)
    write_log(cursor, "Payment", "INFO", "Processing credit card capture via external gateway", trace_id, pay_start)
    
    if pay_status == 504:
        write_log(cursor, "Payment", "ERROR", "Failed to connect to external processor: Gateway Timeout", trace_id, pay_start + timedelta(milliseconds=1500))
    elif db_status == 500:
        write_log(cursor, "Payment", "ERROR", "Internal transaction failure due to database rollback", trace_id, pay_start + timedelta(milliseconds=db_latency))

    # Checkout wraps up
    checkout_status = 200
    if pay_status != 200 or db_status != 200:
        checkout_status = 500

    checkout_latency = 5 + inv_latency + actual_pay_latency
    write_trace(cursor, trace_id, checkout_span, gateway_span, "Checkout", "/v1/checkout/process", checkout_latency, checkout_status, chk_start)
    write_log(cursor, "Checkout", "INFO", "Processing order summary details", trace_id, chk_start)
    
    if checkout_status == 500:
        write_log(cursor, "Checkout", "CRITICAL", "Checkout workflow failed - throwing HTTP 500 Internal Server Error", trace_id, chk_start + timedelta(milliseconds=checkout_latency))

    # 1. Gateway Parent Span Finalizes
    write_trace(cursor, trace_id, gateway_span, None, "Gateway", "/checkout", checkout_latency + 10, checkout_status, gw_start)
    
    # Write system metrics
    write_metric(cursor, "Gateway", "http.latency", checkout_latency + 10, gw_start)
    write_metric(cursor, "Database", "db.connection_count", random.randint(18, 25) if failure_mode != "database_slowdown" else random.randint(95, 120), gw_start)
    write_metric(cursor, "Checkout", "cpu.utilization", random.uniform(5.0, 15.0), gw_start)

def run_continuous(interval=1.0):
    """Runs a continuous loop inserting telemetry."""
    print("Starting continuous telemetry simulation... Press Ctrl+C to stop.")
    conn = sqlite3.connect(DB_PATH)
    try:
        while True:
            simulate_request(conn)
            conn.commit()
            time.sleep(interval + random.uniform(-0.1, 0.2))
    except KeyboardInterrupt:
        print("\nTelemetry simulation stopped.")
    finally:
        conn.close()

def generate_bulk(duration_minutes=20, rate_per_second=2):
    """Generates bulk historical logs, traces, and metrics over a historical range."""
    print(f"Generating {duration_minutes} minutes of telemetry in bulk...")
    init_db(force=True)
    conn = sqlite3.connect(DB_PATH)
    
    total_seconds = duration_minutes * 60
    end_time = datetime.now()
    start_time = end_time - timedelta(minutes=duration_minutes)

    # Let's say failure starts 5 minutes before the end of the timeline
    failure_start = end_time - timedelta(minutes=6)
    
    current_time = start_time
    request_count = 0

    while current_time < end_time:
        # Determine active mode based on current timestamp
        if current_time >= failure_start:
            # We seed a specific failure mode in the DB history
            # Choose database_slowdown as our default mock outage
            os.environ["CHRONOS_SIMULATED_FAIL"] = "database_slowdown"
            # Set the actual config state
            with open(STATE_PATH, "w") as f:
                json.dump({"mode": "database_slowdown", "updated_at": str(current_time)}, f)
        else:
            with open(STATE_PATH, "w") as f:
                json.dump({"mode": "none", "updated_at": str(current_time)}, f)

        # Simulate standard requests per second
        requests_this_sec = random.randint(1, rate_per_second + 1)
        for _ in range(requests_this_sec):
            # Add small millisecond offsets within the second
            offset = random.randint(0, 999)
            req_time = current_time + timedelta(milliseconds=offset)
            simulate_request(conn, timestamp=req_time)
            request_count += 1

        current_time += timedelta(seconds=1)
        if request_count % 100 == 0:
            conn.commit()

    conn.commit()
    conn.close()
    
    # Reset state to none at the end
    set_chaos_state("none")
    print(f"Bulk generation complete. Seeded {request_count} transactions.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Telemetry Chaos Simulator")
    parser.add_argument("command", choices=["init", "run", "inject", "bulk", "status"], help="Command to run")
    parser.add_argument("--mode", choices=["none", "database_slowdown", "payment_gateway_down", "auth_leak"], default="none", help="Failure mode to inject")
    parser.add_argument("--minutes", type=int, default=20, help="Minutes of historical data to generate in bulk")
    
    args = parser.parse_args()

    if args.command == "init":
        init_db(force=True)
    elif args.command == "run":
        if not os.path.exists(DB_PATH):
            init_db()
        run_continuous()
    elif args.command == "inject":
        set_chaos_state(args.mode)
    elif args.command == "bulk":
        generate_bulk(duration_minutes=args.minutes)
    elif args.command == "status":
        print(f"Active Failure Mode: {get_chaos_state()}")
        if os.path.exists(DB_PATH):
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("SELECT count(*) FROM traces")
            tc = c.fetchone()[0]
            c.execute("SELECT count(*) FROM logs")
            lc = c.fetchone()[0]
            print(f"Total Traces in DB: {tc}")
            print(f"Total Logs in DB: {lc}")
            conn.close()
        else:
            print("Database not initialized.")
