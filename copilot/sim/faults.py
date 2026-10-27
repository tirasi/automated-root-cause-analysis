"""Fault catalogue. Each fault says how metrics shift on the root service,
which log lines appear, and which deploy/config record (if any) precedes it.

effects: metric -> (kind, magnitude)
  kind "step": add `magnitude` x baseline std * 10 ... simplified: add absolute amount
  kind "ramp": grows linearly from 0 to `magnitude` over the fault window
"""

FAULTS = {
    "bad_deploy": {
        "description": "A new release introduced a null-handling bug in the request handler.",
        "default_root": "orders",
        "effects": {"error_rate": ("step", 18.0), "latency_ms": ("step", 60.0)},
        "error_logs": [
            ("ERROR", "NullPointerException in OrderHandler.process order_id={n} at line {n}"),
            ("ERROR", "Unhandled exception processing request id={n}: NoneType has no attribute 'items'"),
        ],
        "deploy": {"offset": -2, "version": "v2.14.0", "diff": "Refactored OrderHandler.process; removed null guard on cart items"},
        "config": None,
    },
    "slow_query": {
        "description": "A missing index made a hot query scan the full table.",
        "default_root": "db",
        "effects": {"latency_ms": ("step", 220.0), "cpu_pct": ("step", 35.0)},
        "error_logs": [
            ("WARN", "slow query took {n}ms table=orders sql=SELECT * FROM orders WHERE customer_ref=?"),
            ("WARN", "sequential scan on orders rows={n} no usable index"),
        ],
        "deploy": None,
        "config": None,
    },
    "timeout_cascade": {
        "description": "The worker's downstream dependency stalled, causing timeouts to pile up.",
        "default_root": "worker",
        "effects": {"latency_ms": ("step", 900.0), "error_rate": ("step", 12.0)},
        "error_logs": [
            ("ERROR", "upstream timeout after {n}ms calling db.write retry={n}"),
            ("ERROR", "request queue depth {n} exceeds threshold; shedding load"),
        ],
        "deploy": None,
        "config": {"offset": -3, "key": "db.write_timeout_ms", "old": "5000", "new": "30000", "by": "svc-autotune"},
    },
    "memory_leak": {
        "description": "A cache without eviction grows until the process is killed.",
        "default_root": "worker",
        "effects": {"mem_mb": ("ramp", 1400.0), "cpu_pct": ("ramp", 25.0)},
        "error_logs": [
            ("WARN", "GC pause {n}ms heap_used_mb={n}"),
            ("ERROR", "OutOfMemoryError: Java heap space, restarting worker pid={n}"),
        ],
        "deploy": {"offset": -30, "version": "v1.8.3", "diff": "Added in-memory result cache (no TTL or max size)"},
        "config": None,
    },
    "config_change": {
        "description": "A config change cut the connection pool size, exhausting connections.",
        "default_root": "orders",
        "effects": {"latency_ms": ("step", 350.0), "error_rate": ("step", 9.0)},
        "error_logs": [
            ("ERROR", "connection pool exhausted: waited {n}ms for a free connection (max=5)"),
            ("WARN", "request timed out waiting for db connection id={n}"),
        ],
        "deploy": None,
        "config": {"offset": -1, "key": "db.pool_size", "old": "50", "new": "5", "by": "alice@corp"},
    },
    "schema_drift": {
        "description": "An upstream data feed changed its payload schema; the worker cannot parse it.",
        "default_root": "worker",
        "effects": {"error_rate": ("step", 25.0)},
        "error_logs": [
            ("ERROR", "KeyError: 'customer_id' missing from feed payload batch={n}"),
            ("ERROR", "schema validation failed: unexpected field 'cust_id' in record {n}"),
        ],
        "deploy": None,
        "config": None,
    },
    # Deliberately NOT in the knowledge base: used to test how the system behaves on an unknown fault.
    "disk_full": {
        "description": "The database volume filled up, so writes started failing.",
        "default_root": "db",
        "effects": {"error_rate": ("step", 15.0), "latency_ms": ("step", 120.0)},
        "error_logs": [
            ("ERROR", "No space left on device: write failed file=wal_{n}.log"),
            ("ERROR", "checkpoint failed: disk quota exceeded volume=/data{n}"),
        ],
        "deploy": None,
        "config": None,
    },
}

BACKGROUND_LOGS = [
    ("INFO", "request completed status=200 duration_ms={n}"),
    ("INFO", "health check ok"),
    ("INFO", "cache hit key=session:{n}"),
    ("DEBUG", "connection reused conn_id={n}"),
]

# Faults the knowledge base has never been taught (used to test unknown-fault behaviour).
HELD_OUT = {"disk_full"}
KNOWN_FAULTS = sorted(set(FAULTS) - HELD_OUT)
