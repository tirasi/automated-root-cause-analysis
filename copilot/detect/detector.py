"""Statistical detection (no LLM): robust rolling z-scores on metrics plus new-error-template
detection on logs. Produces alerts; correlate.py groups them into incidents."""
import statistics
from collections import defaultdict

from ..config import METRICS, SERVICES, TICK_SECONDS
from ..store import connect
from .templates import LEVEL_RANK, template_of

LOOKBACK = 90      # samples in the rolling baseline
GAP = 10           # most recent samples skipped, so an ongoing fault can't pollute its baseline
MIN_BASE = 30
Z_THRESHOLD = 4.0
RUN_LENGTH = 3     # consecutive anomalous samples required
NEW_TEMPLATE_MIN = 5


def _robust_z(history, value):
    med = statistics.median(history)
    mad = statistics.median([abs(v - med) for v in history])
    return (value - med) / max(1.4826 * mad, 1e-6)


def metric_alerts(conn, start_ts=None, end_ts=None):
    alerts = []
    for svc in SERVICES:
        for metric in METRICS:
            rows = conn.execute(
                "SELECT ts, value FROM metrics WHERE service=? AND metric=? ORDER BY ts", (svc, metric)).fetchall()
            ts_list = [r["ts"] for r in rows]
            vals = [r["value"] for r in rows]
            run, peak, in_episode, calm = [], 0.0, False, 0
            for i in range(MIN_BASE + GAP, len(vals)):
                hist = vals[max(0, i - LOOKBACK - GAP): i - GAP]
                z = _robust_z(hist, vals[i])
                if abs(z) >= Z_THRESHOLD:
                    run.append((ts_list[i], z))
                    calm = 0
                    if len(run) >= RUN_LENGTH and not in_episode:
                        in_episode = True
                        first_ts = run[0][0]
                        if (start_ts is None or first_ts >= start_ts) and (end_ts is None or first_ts <= end_ts):
                            peak = max(abs(x) for _, x in run)
                            alerts.append({"ts": first_ts, "service": svc, "kind": "metric",
                                           "signal": metric, "score": round(peak, 1),
                                           "direction": "up" if run[0][1] > 0 else "down",
                                           "detail": f"{metric} z={z:+.1f} vs rolling baseline"})
                else:
                    run = []
                    calm += 1
                    if calm >= 5:
                        in_episode = False
    return alerts


def log_alerts(conn, start_ts=None, end_ts=None):
    alerts = []
    for svc in SERVICES:
        rows = conn.execute("SELECT ts, level, message FROM logs WHERE service=? ORDER BY ts", (svc,)).fetchall()
        seen_before, counts, first = set(), defaultdict(int), {}
        # logs before the cutoff define "known" templates; default = first hour treated as healthy
        cutoff = start_ts if start_ts is not None else (rows[0]["ts"] + 3600 if rows else 0)
        for r in rows:
            if LEVEL_RANK[r["level"]] < LEVEL_RANK["ERROR"]:
                continue
            t = template_of(r["message"])
            if r["ts"] < cutoff:
                seen_before.add(t)
                continue
            if end_ts is not None and r["ts"] > end_ts:
                continue
            counts[t] += 1
            first.setdefault(t, r["ts"])
        for t, n in counts.items():
            if t not in seen_before and n >= NEW_TEMPLATE_MIN:
                alerts.append({"ts": first[t], "service": svc, "kind": "log", "signal": "new_error_template",
                               "score": float(n), "detail": f"new ERROR pattern x{n}: {t[:80]}"})
    return alerts


def detect(db_path=None, start_ts=None, end_ts=None):
    conn = connect(db_path, readonly=True)
    try:
        alerts = metric_alerts(conn, start_ts, end_ts) + log_alerts(conn, start_ts, end_ts)
    finally:
        conn.close()
    alerts.sort(key=lambda a: (a["ts"], a["service"], a["signal"]))
    return alerts
