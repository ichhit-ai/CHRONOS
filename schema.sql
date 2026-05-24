-- SQLite Telemetry Schema for Local GraphRAG SRE Agent

CREATE TABLE IF NOT EXISTS traces (
    trace_id TEXT,
    span_id TEXT PRIMARY KEY,
    parent_span_id TEXT,
    service TEXT,
    endpoint TEXT,
    duration_ms INTEGER,
    status_code INTEGER,
    timestamp DATETIME DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now'))
);

CREATE TABLE IF NOT EXISTS logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')),
    service TEXT,
    level TEXT,
    message TEXT,
    trace_id TEXT
);

CREATE TABLE IF NOT EXISTS metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')),
    service TEXT,
    metric_name TEXT,
    value REAL
);

-- Indexing for high-performance JIT querying
CREATE INDEX IF NOT EXISTS idx_traces_timestamp ON traces(timestamp);
CREATE INDEX IF NOT EXISTS idx_traces_trace_id ON traces(trace_id);
CREATE INDEX IF NOT EXISTS idx_logs_timestamp ON logs(timestamp);
CREATE INDEX IF NOT EXISTS idx_metrics_timestamp ON metrics(timestamp);

-- Codebase Structural Ontology Graph Tables
CREATE TABLE IF NOT EXISTS codebase_nodes (
    id TEXT PRIMARY KEY,
    label TEXT,
    type TEXT,
    source_file TEXT,
    code_block TEXT
);

CREATE TABLE IF NOT EXISTS codebase_edges (
    source TEXT,
    target TEXT,
    relationship TEXT,
    PRIMARY KEY (source, target, relationship)
);
