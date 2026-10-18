"""SQLite telemetry store: metrics, logs, deploys, config changes, ground truth."""
import sqlite3
from pathlib import Path

from .config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS metrics (
    ts INTEGER NOT NULL, service TEXT NOT NULL, metric TEXT NOT NULL, value REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_metrics ON metrics (service, metric, ts);
CREATE TABLE IF NOT EXISTS logs (
    ts INTEGER NOT NULL, service TEXT NOT NULL, level TEXT NOT NULL, message TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_logs ON logs (service, ts);
CREATE TABLE IF NOT EXISTS deploys (
    ts INTEGER NOT NULL, service TEXT NOT NULL, version TEXT NOT NULL, diff_summary TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS config_changes (
    ts INTEGER NOT NULL, service TEXT NOT NULL, key TEXT NOT NULL,
    old_value TEXT, new_value TEXT, changed_by TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ground_truth (
    scenario TEXT PRIMARY KEY, fault_type TEXT NOT NULL, root_service TEXT NOT NULL,
    start_ts INTEGER NOT NULL, description TEXT NOT NULL
);
"""

TABLES = ["metrics", "logs", "deploys", "config_changes", "ground_truth"]


def connect(path=None, readonly=False):
    path = Path(path or DB_PATH)
    if readonly:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    if not readonly:
        # DELETE journal mode fails on some mounted/synced folders; TRUNCATE is portable.
        conn.execute("PRAGMA journal_mode=TRUNCATE")
    return conn


def init_db(path=None):
    """Create a fresh database (drops existing data)."""
    path = Path(path or DB_PATH)
    if path.exists():
        path.unlink()
    conn = connect(path)
    conn.executescript(SCHEMA)
    conn.commit()
    return conn
