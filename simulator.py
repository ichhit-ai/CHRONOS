# Chaos Simulation Engine for Local GraphRAG SRE Agent
import os
import sqlite3
import random
import uuid
import time
import json
import argparse
from datetime import datetime, timedelta

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter
from opentelemetry.trace import Status, StatusCode
from opentelemetry.sdk.resources import Resource

DB_PATH = "telemetry.db"
SCHEMA_PATH = "schema.sql"
STATE_PATH = "chaos_state.json"

# --- Custom OpenTelemetry Exporter ---
class ChronosSQLiteExporter(SpanExporter):
    def __init__(self, db_path):
        self.db_path = db_path

    def export(self, spans):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("BEGIN TRANSACTION")
        try:
            for span in spans:
                trace_id = format(span.context.trace_id, '032x')
                span_id = format(span.context.span_id, '016x')
                parent_id = format(span.parent.span_id, '016x') if span.parent else None
                
                service = span.attributes.get("service", span.resource.attributes.get("service.name", "Unknown"))
                endpoint = span.attributes.get("endpoint", span.name)
                
                duration_ms = (span.end_time - span.start_time) / 1e6
                
                status_code = 500 if span.status.status_code == StatusCode.ERROR else 200
                if "http.status_code" in span.attributes:
                    status_code = span.attributes["http.status_code"]
                    
                timestamp = datetime.fromtimestamp(span.start_time / 1e9)
                
                cursor.execute(
                    """
                    INSERT INTO traces (trace_id, span_id, parent_span_id, service, endpoint, duration_ms, status_code, timestamp)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (trace_id, span_id, parent_id, service, endpoint, int(duration_ms), int(status_code), timestamp.strftime('%Y-%m-%d %H:%M:%f'))
                )
                
                # Export Events as Logs
                for event in span.events:
                    level = event.attributes.get("level", "INFO")
                    evt_time = datetime.fromtimestamp(event.timestamp / 1e9)
                    cursor.execute(
                        """
                        INSERT INTO logs (service, level, message, trace_id, timestamp)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (service, level, event.name, trace_id, evt_time.strftime('%Y-%m-%d %H:%M:%f'))
                    )
            conn.commit()
        except Exception as e:
            conn.rollback()
            print(f"Failed to export spans: {e}")
        finally:
            conn.close()
            
        from opentelemetry.sdk.trace.export import SpanExportResult
        return SpanExportResult.SUCCESS

    def shutdown(self):
        pass

# Initialize OpenTelemetry
resource = Resource(attributes={"service.name": "simulator"})
provider = TracerProvider(resource=resource)
exporter = ChronosSQLiteExporter(DB_PATH)
# Use BatchSpanProcessor for huge performance gains
provider.add_span_processor(BatchSpanProcessor(exporter, max_export_batch_size=512))
trace.set_tracer_provider(provider)
tracer = trace.get_tracer(__name__)

# --- Database & State Init ---
def init_db(force=False):
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
    set_chaos_state("none")

def get_chaos_state():
    if not os.path.exists(STATE_PATH):
        return "none"
    try:
        with open(STATE_PATH, "r") as f:
            data = json.load(f)
            return data.get("mode", "none")
    except Exception:
        return "none"

def set_chaos_state(mode):
    with open(STATE_PATH, "w") as f:
        json.dump({"mode": mode, "updated_at": str(datetime.now())}, f)
    print(f"Chaos state updated to: {mode}")

def write_metric(service, name, value, timestamp):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO metrics (service, metric_name, value, timestamp)
        VALUES (?, ?, ?, ?)
        """,
        (service, name, float(value), timestamp.strftime('%Y-%m-%d %H:%M:%f'))
    )
    conn.commit()
    conn.close()

# --- Dynamic Graph Loading ---
def load_graph_topology():
    if not os.path.exists(DB_PATH):
        return None, None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT id, label, type FROM codebase_nodes WHERE type IN ('Microservice', 'Operation')")
        nodes = {row[0]: {"label": row[1], "type": row[2]} for row in cursor.fetchall()}
        
        cursor.execute("SELECT source, target FROM codebase_edges")
        edges = {}
        for src, tgt in cursor.fetchall():
            edges.setdefault(src, []).append(tgt)
        conn.close()
        return nodes, edges
    except Exception:
        return None, None

_CACHED_NODES = None
_CACHED_EDGES = None

def invalidate_cache():
    """Clears the in-memory topology cache so the next simulate_request() reloads from DB."""
    global _CACHED_NODES, _CACHED_EDGES
    _CACHED_NODES = None
    _CACHED_EDGES = None
    print("Simulator topology cache invalidated. Will reload from DB on next request.")

# --- Simulation Logic ---
def simulate_request(timestamp=None):
    """Simulates a complete transaction using dynamic codebase AST topologies."""
    global _CACHED_NODES, _CACHED_EDGES
    if timestamp is None:
        timestamp = datetime.now()

    if _CACHED_NODES is None:
        _CACHED_NODES, _CACHED_EDGES = load_graph_topology()

    failure_mode = get_chaos_state()
    
    # Check if we have a valid custom codebase graph to simulate on
    if _CACHED_NODES and len(_CACHED_NODES) > 0:
        # Generate Dynamic Trace Walk based on AST Codebase
        entry_node_id = random.choice(list(_CACHED_NODES.keys()))
        path = [entry_node_id]
        current = entry_node_id
        # Walk up to 4 layers deep to simulate a real call stack
        for _ in range(random.randint(1, 4)):
            if _CACHED_EDGES and current in _CACHED_EDGES and _CACHED_EDGES[current]:
                next_node = random.choice(_CACHED_EDGES[current])
                if next_node in _CACHED_NODES:
                    path.append(next_node)
                    current = next_node
                else:
                    break
            else:
                break
                
        def run_span(node_idx, current_time_ns):
            node_id = path[node_idx]
            node_label = _CACHED_NODES[node_id]["label"]
            
            latency = random.uniform(5, 25)
            status = 200
            is_failing = False
            
            if failure_mode != "none":
                # Bug #4 fix: Inject failure at leaf with 65% probability, or any node with 20%
                is_leaf = node_idx == len(path) - 1
                if (is_leaf and random.random() < 0.65) or (not is_leaf and random.random() < 0.20):
                    latency = random.uniform(800, 3000)
                    status = 500
                    is_failing = True

            start_ns = current_time_ns
            with tracer.start_as_current_span(node_label, start_time=start_ns, end_on_exit=False) as span:
                span.set_attribute("service", node_label)
                span.set_attribute("endpoint", f"/{node_label.replace('.', '/')}")
                span.set_attribute("http.status_code", status)
                
                if is_failing:
                    span.add_event(f"CRITICAL: Application threw unhandled exception during {node_label} due to {failure_mode}", timestamp=start_ns, attributes={"level": "ERROR"})
                    span.set_status(Status(StatusCode.ERROR))
                else:
                    span.add_event(f"Executing {node_label} successfully", timestamp=start_ns, attributes={"level": "INFO"})
                
                child_end_ns = start_ns + int(latency * 1e6)
                if node_idx < len(path) - 1:
                    child_end_ns = run_span(node_idx + 1, child_end_ns)
                    
                end_ns = child_end_ns + int(random.uniform(1, 5) * 1e6)
                
                if is_failing and node_idx < len(path) - 1:
                    # Propagate error up the stack
                    span.add_event(f"Failed waiting on downstream call inside {node_label}", timestamp=end_ns, attributes={"level": "WARNING"})
                    span.set_status(Status(StatusCode.ERROR))
                    span.set_attribute("http.status_code", 500)
                    
                span.end(end_time=end_ns)
                return end_ns

        gw_start_ns = int(timestamp.timestamp() * 1e9)
        run_span(0, gw_start_ns)
        
    else:
        # Fallback Hardcoded Simulation (If DB is empty or unindexed)
        # We will just generate a tiny Gateway trace to prove it's alive
        gw_start_ns = int(timestamp.timestamp() * 1e9)
        with tracer.start_as_current_span("Gateway", start_time=gw_start_ns, end_on_exit=False) as gw_span:
            gw_span.set_attribute("service", "Gateway")
            gw_span.set_attribute("endpoint", "/")
            gw_span.add_event("Processing request", timestamp=gw_start_ns, attributes={"level": "INFO"})
            gw_end_ns = gw_start_ns + int(15 * 1e6)
            gw_span.end(end_time=gw_end_ns)

def run_continuous(interval=1.0):
    print("Starting continuous telemetry simulation... Press Ctrl+C to stop.")
    try:
        while True:
            simulate_request()
            time.sleep(interval + random.uniform(-0.1, 0.2))
    except KeyboardInterrupt:
        print("\nTelemetry simulation stopped.")

def generate_bulk(duration_minutes=20, rate_per_second=2):
    print(f"Generating {duration_minutes} minutes of dynamic codebase telemetry in bulk using OpenTelemetry...")
    
    # DO NOT init_db(force=True) here anymore, because it wipes the AST graph!!!
    # Instead, we just delete the traces/logs from telemetry.db so the graph persists!
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM traces")
    cursor.execute("DELETE FROM logs")
    cursor.execute("DELETE FROM metrics")
    conn.commit()
    conn.close()
    
    total_seconds = duration_minutes * 60
    end_time = datetime.now()
    start_time = end_time - timedelta(minutes=duration_minutes)

    failure_start = end_time - timedelta(minutes=6)
    
    current_time = start_time
    request_count = 0

    # Ensure nodes are loaded
    global _CACHED_NODES, _CACHED_EDGES
    _CACHED_NODES, _CACHED_EDGES = load_graph_topology()

    while current_time < end_time:
        if current_time >= failure_start:
            mode = get_chaos_state()
            if mode == "none":
                # if someone passed via generate_bulk implicitly without setting state
                mode = "database_slowdown"
            with open(STATE_PATH, "w") as f:
                json.dump({"mode": mode, "updated_at": str(current_time)}, f)
        else:
            with open(STATE_PATH, "w") as f:
                json.dump({"mode": "none", "updated_at": str(current_time)}, f)

        requests_this_sec = random.randint(1, rate_per_second + 1)
        for _ in range(requests_this_sec):
            offset = random.randint(0, 999)
            req_time = current_time + timedelta(milliseconds=offset)
            simulate_request(timestamp=req_time)
            request_count += 1

        current_time += timedelta(seconds=1)

    # Force flush before exiting
    provider.force_flush()
    set_chaos_state("none")
    print(f"Bulk generation complete. Seeded {request_count} dynamic transactions via OpenTelemetry.")

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
        set_chaos_state(args.mode)
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
