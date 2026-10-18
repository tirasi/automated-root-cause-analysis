"""Central config: paths and simulation constants."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "telemetry.db"

SERVICES = ["api", "orders", "worker", "db"]

# service -> services it calls (upstream dependencies)
DEPENDENCIES = {
    "api": ["orders"],
    "orders": ["db", "worker"],
    "worker": ["db"],
    "db": [],
}

METRICS = ["latency_ms", "error_rate", "cpu_pct", "mem_mb"]

# Healthy baselines per service: metric -> (mean, std)
BASELINES = {
    "api":    {"latency_ms": (120, 8),  "error_rate": (0.5, 0.2), "cpu_pct": (35, 4), "mem_mb": (512, 10)},
    "orders": {"latency_ms": (80, 6),   "error_rate": (0.4, 0.2), "cpu_pct": (40, 4), "mem_mb": (640, 12)},
    "worker": {"latency_ms": (200, 15), "error_rate": (0.3, 0.1), "cpu_pct": (55, 5), "mem_mb": (768, 14)},
    "db":     {"latency_ms": (15, 2),   "error_rate": (0.1, 0.05), "cpu_pct": (45, 4), "mem_mb": (2048, 20)},
}

TICK_SECONDS = 60          # one metric sample per service per minute
HISTORY_TICKS = 180        # 3 hours of data per run
