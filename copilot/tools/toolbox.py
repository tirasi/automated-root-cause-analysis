"""The five typed investigation tools. Each returns a bounded summary plus an evidence id."""
import statistics

from ..config import DEPENDENCIES, DB_PATH, SERVICES
from ..detect.templates import LEVEL_RANK, cluster
from ..store import connect
from .evidence import EvidenceStore

BASELINE_WINDOW = 3600  # seconds of history used as the baseline before a window
CHANGE_Z = 3.0
CHANGE_RUN = 3


def _stats(values):
    if not values:
        return {"n": 0}
    return {"n": len(values), "mean": round(statistics.fmean(values), 2),
            "std": round(statistics.pstdev(values), 2),
            "min": round(min(values), 2), "max": round(max(values), 2)}


class Toolbox:
    def __init__(self, db_path=None, evidence=None):
        self.conn = connect(db_path or DB_PATH, readonly=True)
        self.evidence = evidence or EvidenceStore()

    def _done(self, tool, args, result):
        result["evidence_id"] = self.evidence.add(tool, args, result)
        return result

    def _series(self, service, metric, start, end):
        rows = self.conn.execute(
            "SELECT ts, value FROM metrics WHERE service=? AND metric=? AND ts>=? AND ts<=? ORDER BY ts",
            (service, metric, start, end)).fetchall()
        return [(r["ts"], r["value"]) for r in rows]

    def query_logs(self, service, start, end, min_level="WARN", pattern=None, top=6):
        args = dict(service=service, start=start, end=end, min_level=min_level, pattern=pattern)
        rows = self.conn.execute(
            "SELECT ts, level, message FROM logs WHERE service=? AND ts>=? AND ts<=? ORDER BY ts",
            (service, start, end)).fetchall()
        floor = LEVEL_RANK[min_level]
        picked = [(r["ts"], r["level"], r["message"]) for r in rows
                  if LEVEL_RANK[r["level"]] >= floor and (not pattern or pattern.lower() in r["message"].lower())]
        clusters = cluster(picked)
        return self._done("query_logs", args, {
            "service": service, "total_lines": len(picked),
            "clusters": clusters[:top], "clusters_omitted": max(0, len(clusters) - top)})

    def _metric_z(self, service, metric, start, end):
        window = self._series(service, metric, start, end)
        base = self._series(service, metric, start - BASELINE_WINDOW, start - 1)
        wvals = [v for _, v in window]
        bvals = [v for _, v in base]
        z = change_ts = None
        if len(bvals) > 1:
            # robust baseline (median/MAD) so a fault inside the lookback doesn't inflate it
            bmean = statistics.median(bvals)
            mad = statistics.median([abs(v - bmean) for v in bvals])
            bstd = max(1.4826 * mad, 1e-6)
            if wvals:
                z = round((statistics.fmean(wvals) - bmean) / bstd, 2)
            run = []
            for ts, v in window:
                if abs(v - bmean) / bstd >= CHANGE_Z:
                    run.append(ts)
                    if len(run) >= CHANGE_RUN:
                        change_ts = run[0]
                        break
                else:
                    run = []
        return z, change_ts, _stats(wvals), _stats(bvals)

    def query_metrics(self, service, metric, start, end):
        args = dict(service=service, metric=metric, start=start, end=end)
        z, change_ts, wstats, bstats = self._metric_z(service, metric, start, end)
        return self._done("query_metrics", args, {
            "service": service, "metric": metric, "window": wstats,
            "baseline": bstats, "window_z_vs_baseline": z, "change_point_ts": change_ts})

    def recent_deploys(self, start, end, services=None):
        args = dict(start=start, end=end, services=services)
        rows = self.conn.execute(
            "SELECT ts, service, version, diff_summary FROM deploys WHERE ts>=? AND ts<=? ORDER BY ts",
            (start, end)).fetchall()
        items = [dict(r) for r in rows if not services or r["service"] in services]
        return self._done("recent_deploys", args, {"deploys": items})

    def config_diff(self, start, end, service=None):
        args = dict(start=start, end=end, service=service)
        rows = self.conn.execute(
            "SELECT ts, service, key, old_value, new_value, changed_by FROM config_changes "
            "WHERE ts>=? AND ts<=? ORDER BY ts", (start, end)).fetchall()
        items = [dict(r) for r in rows if not service or r["service"] == service]
        return self._done("config_diff", args, {"changes": items})

    def _health(self, service, at_ts):
        worst = 0.0
        for metric in ("latency_ms", "error_rate"):
            z, _, _, _ = self._metric_z(service, metric, at_ts - 300, at_ts)
            if z is not None:
                worst = max(worst, abs(z))
        return {"status": "degraded" if worst >= 4 else "healthy", "worst_z": round(worst, 1)}

    def service_dependencies(self, service, at_ts):
        args = dict(service=service, at_ts=at_ts)
        upstream = {d: self._health(d, at_ts) for d in DEPENDENCIES[service]}
        downstream = {s: self._health(s, at_ts) for s in SERVICES if service in DEPENDENCIES[s]}
        return self._done("service_dependencies", args, {
            "service": service, "self": self._health(service, at_ts),
            "upstream_dependencies": upstream, "downstream_callers": downstream})
