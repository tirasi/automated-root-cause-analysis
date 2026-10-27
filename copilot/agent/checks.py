"""Turn the KB's predictions into real tool calls.

The KB says, for each fault, "if this is the cause, tool X should show Y" (fault_prediction/3).
Each function here runs tool X on the live data and answers: confirmed, refuted or inconclusive.
Every observation is built only from numbers in the tool result, so a verifier can re-check it.

A check returns (verdict, observation, evidence_ids). Log checks weigh half as much as the others
because the KB already used those same log lines to rank the hypothesis (less independent)."""
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

Z_RISE = 4.0


def hhmm(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%H:%M")


@dataclass
class Ctx:
    tb: Any            # Toolbox
    kb: Any            # KnowledgeBase (used to turn log lines into tags)
    svc: str           # suspect service
    t0: int            # first alert time on the suspect
    t_end: int         # end of the incident
    det_ev: str        # evidence id of the detector output (holds t0)

    @property
    def win(self):
        # 30 min of look-ahead past the last alert: a gradual ramp needs a longer view to be told from a step
        return self.t0 - 600, self.t_end + 1800


# ---------- individual checks ----------
def deploy_before(max_gap):
    def check(c):
        r = c.tb.recent_deploys(c.t0 - max_gap, c.t0 + 60, services=[c.svc])
        if r["deploys"]:
            d = r["deploys"][-1]
            return ("confirmed", f"Deploy {d['version']} to {c.svc} at {hhmm(d['ts'])} before the first alert "
                    f"at {hhmm(c.t0)}: {d['diff_summary']}", [r["evidence_id"], c.det_ev])
        return ("refuted", f"No deploy to {c.svc} shortly before the first alert at {hhmm(c.t0)}",
                [r["evidence_id"], c.det_ev])
    return check


def config_changed(keywords=None, gap=2400):
    def check(c):
        r = c.tb.config_diff(c.t0 - gap, c.t0 + 60, service=c.svc)
        items = [x for x in r["changes"] if not keywords or any(k in x["key"] for k in keywords)]
        if items:
            x = items[-1]
            return ("confirmed", f"Config {x['key']} on {c.svc} changed from {x['old_value']} to {x['new_value']} "
                    f"at {hhmm(x['ts'])} by {x['changed_by']}, before the first alert at {hhmm(c.t0)}",
                    [r["evidence_id"], c.det_ev])
        return ("refuted", f"No matching config change on {c.svc} before the first alert at {hhmm(c.t0)}",
                [r["evidence_id"], c.det_ev])
    return check


def no_changes(c):
    d = c.tb.recent_deploys(c.t0 - 2400, c.t0 + 60, services=[c.svc])
    g = c.tb.config_diff(c.t0 - 2400, c.t0 + 60, service=c.svc)
    ids = [d["evidence_id"], g["evidence_id"], c.det_ev]
    if not d["deploys"] and not g["changes"]:
        return "confirmed", f"No deploy or config change on {c.svc} before the first alert at {hhmm(c.t0)}", ids
    return "refuted", f"{c.svc} had a deploy or config change before the first alert at {hhmm(c.t0)}", ids


def logs_have(expected_tags):
    def check(c):
        r = c.tb.query_logs(c.svc, *c.win, min_level="WARN")
        if not r["total_lines"]:
            return "inconclusive", f"No WARN or ERROR log lines on {c.svc} in the window", [r["evidence_id"]]
        msgs = [m for cl in r["clusters"] for m in cl["samples"][:1]]
        tags = set(c.kb.tag(msgs))
        top = r["clusters"][0]
        if tags & set(expected_tags):
            return ("confirmed", f"Log patterns on {c.svc} match the expected symptom "
                    f"({', '.join(sorted(tags & set(expected_tags)))}); {r['total_lines']} WARN or ERROR lines",
                    [r["evidence_id"]])
        return ("refuted", f"{r['total_lines']} WARN or ERROR lines on {c.svc}, but none match the expected "
                f"symptom; most common: {top['template'][:70]}", [r["evidence_id"]])
    return check


def metrics_rise(metrics):
    def check(c):
        rs = [c.tb.query_metrics(c.svc, m, *c.win) for m in metrics]
        ids = [r["evidence_id"] for r in rs]
        parts = ", ".join(f"{r['metric']} z={r['window_z_vs_baseline']}" for r in rs)
        if all((r["window_z_vs_baseline"] or 0) >= Z_RISE for r in rs):
            return "confirmed", f"On {c.svc}: {parts} (all well above baseline)", ids
        return "refuted", f"On {c.svc}: {parts} (not all of them rose above baseline)", ids
    return check


def memory_ramp(c):
    r = c.tb.query_metrics(c.svc, "mem_mb", *c.win)
    z = r["window_z_vs_baseline"] or 0
    if z >= Z_RISE and r["shape"] == "ramp":
        return "confirmed", f"mem_mb on {c.svc} grows gradually (z={z}, shape {r['shape']})", [r["evidence_id"]]
    return ("refuted", f"mem_mb on {c.svc} does not show steady growth (z={z}, shape {r['shape']})",
            [r["evidence_id"]])


def origin_here(c):
    r = c.tb.service_dependencies(c.svc, c.t0 + 300)
    me = r["self"]
    bad_up = [n for n, h in r["upstream_dependencies"].items() if h["status"] == "degraded"]
    if me["status"] != "degraded":
        return "refuted", f"{c.svc} itself looks healthy shortly after the first alert", [r["evidence_id"]]
    if bad_up:
        return ("refuted", f"{c.svc} is degraded but so is upstream {', '.join(bad_up)}, "
                f"so the origin may be deeper", [r["evidence_id"]])
    ups = ", ".join(r["upstream_dependencies"]) or "none"
    return ("confirmed", f"{c.svc} is degraded (worst z {me['worst_z']}) while its upstream dependencies "
            f"({ups}) are healthy, so the problem starts at {c.svc}", [r["evidence_id"]])


# (fault, tool) -> (check function, weight)
CHECKS = {
    ("bad_deploy", "recent_deploys"): (deploy_before(900), 1.0),
    ("bad_deploy", "query_logs"): (logs_have({"null_pointer"}), 0.5),
    ("slow_query", "query_logs"): (logs_have({"slow_query", "seq_scan"}), 0.5),
    ("slow_query", "query_metrics"): (metrics_rise(["latency_ms", "cpu_pct"]), 1.0),
    ("timeout_cascade", "service_dependencies"): (origin_here, 1.0),
    ("timeout_cascade", "config_diff"): (config_changed(keywords=("timeout", "retry")), 1.0),
    ("memory_leak", "query_metrics"): (memory_ramp, 1.0),
    ("memory_leak", "recent_deploys"): (deploy_before(2400), 1.0),
    ("config_change", "config_diff"): (config_changed(gap=600), 1.0),
    ("config_change", "query_logs"): (logs_have({"pool_exhausted", "db_wait_timeout"}), 0.5),
    ("schema_drift", "query_logs"): (logs_have({"schema_mismatch"}), 0.5),
    ("schema_drift", "recent_deploys"): (no_changes, 1.0),
    ("capacity_exhaustion", "query_metrics"): (metrics_rise(["cpu_pct"]), 1.0),
    ("capacity_exhaustion", "recent_deploys"): (no_changes, 1.0),
}


def run_checks(hypothesis, ctx):
    """Test every KB prediction of one hypothesis. Returns a list of check-result dicts."""
    out = []
    for pred in hypothesis["predictions"]:
        spec = CHECKS.get((hypothesis["fault"], pred["tool"]))
        if not spec:  # the KB predicts something we have no check for: say so, don't guess
            out.append({"fault": hypothesis["fault"], "tool": pred["tool"], "expect": pred["expect"],
                        "verdict": "inconclusive", "weight": 0.0, "observation": "no check implemented",
                        "cites": []})
            continue
        fn, weight = spec
        verdict, obs, ids = fn(ctx)
        out.append({"fault": hypothesis["fault"], "tool": pred["tool"], "expect": pred["expect"],
                    "verdict": verdict, "weight": weight, "observation": obs, "cites": ids})
    return out
