"""Evaluation harness: how often is the system right, and does it know when it does not know?

Three methods are run on the SAME simulated incidents:
  naive      blame the service with the loudest alert, then take the knowledge base's top guess
  kb-only    our detector's first suspect, then the knowledge base's top guess (no evidence checks, never abstains)
  agent      the full investigation (tool checks, scoring, critic, unknown-fault path, verifier)

Two situations:
  normal     the KB has seen this kind of fault before (6 faults, several services and seeds)
  held-out   the KB has NOT seen this kind of fault: either a fault class it was never taught (disk_full)
             or a known fault whose past incidents are removed from the KB (leave-one-fault-out)
A third situation, "no logs", deletes every WARN/ERROR log line (a broken logging pipeline), so only metrics
and deploy/config history remain. This is where checking evidence should beat guessing from symptoms.
The honest result is the held-out one: a method that always answers is confidently wrong there.

The simulator's answer key (ground_truth) is only read here, to score results. The investigation code
never reads it (tests/test_agent.py checks that)."""
import re
import sqlite3
import tempfile
from collections import defaultdict
from pathlib import Path

from ..agent.run import investigate
from ..detect import find_incidents
from ..kb import KB_DIR, KnowledgeBase
from ..kb.signature import hypotheses_for
from ..sim.generator import generate
from ..tools.toolbox import Toolbox

# (fault, root service): the default root plus a few other services where the fault can happen
SCENARIOS = [
    ("bad_deploy", "orders"), ("bad_deploy", "api"), ("bad_deploy", "worker"),
    ("slow_query", "db"),
    ("timeout_cascade", "worker"), ("timeout_cascade", "orders"),
    ("memory_leak", "worker"), ("memory_leak", "orders"), ("memory_leak", "api"),
    ("config_change", "orders"), ("config_change", "api"), ("config_change", "db"),
    ("schema_drift", "worker"),
]
DEFAULT_ROOTS = {"bad_deploy": "orders", "slow_query": "db", "timeout_cascade": "worker",
                 "memory_leak": "worker", "config_change": "orders", "schema_drift": "worker"}
UNSEEN_FAULT = ("disk_full", "db")   # a fault class the KB was never taught
METHODS = ["naive", "kb-only", "agent"]


def precedent_ids(fault):
    text = (Path(KB_DIR) / "incidents.pl").read_text()
    return re.findall(r"past_incident\('([^']+)',\s*" + fault + r"\s*,", text)


def _kb_guess(kb, inc, service, toolbox):
    _, ranked = hypotheses_for(kb, inc, service=service, toolbox=toolbox)
    return ranked[0]["fault"] if ranked else None


def _run_one(fault, root, seed, kb, tmp, drop_logs=False):
    db = str(Path(tmp) / f"{fault}-{root}-{seed}{'-nologs' if drop_logs else ''}.db")
    generate(fault, root, seed, db_path=db)
    if drop_logs:
        conn = sqlite3.connect(db)
        conn.execute("DELETE FROM logs WHERE level IN ('WARN','ERROR')")
        conn.commit()
        conn.close()
    incs = find_incidents(db)
    out = {"fault": fault, "root": root, "seed": seed, "incidents": len(incs)}
    if not incs:
        out.update({m: {"root": None, "fault": None} for m in METHODS})
        return out
    inc = incs[0]
    tb = Toolbox(db)
    loud = max(inc["alerts"], key=lambda a: a["score"])["service"]
    out["naive"] = {"root": loud, "fault": _kb_guess(kb, inc, loud, None)}
    out["kb-only"] = {"root": inc["suspects"][0], "fault": _kb_guess(kb, inc, None, tb)}
    tb.conn.close()
    final = investigate(db, incident=inc, kb=kb)
    rc = final["report"]["root_cause"]
    out["agent"] = {"root": rc["service"], "fault": rc["fault"], "confidence": final["confidence"],
                    "verified": final["report"]["status"] == "verified",
                    "evidence_items": len(final["evidence"]), "claims": final["verification"]["claims_checked"]}
    return out


def run_eval(seeds=3, progress=None):
    results = {"normal": [], "held_out": [], "no_logs": []}
    with tempfile.TemporaryDirectory() as tmp:
        kb = KnowledgeBase()
        for fault, root in SCENARIOS:
            for seed in range(seeds):
                results["normal"].append(_run_one(fault, root, seed, kb, tmp))
                progress and progress(f"normal {fault}@{root} seed {seed}")
        # degraded: logging pipeline is broken, only metrics and deploy/config history remain
        for fault, root in [s_ for s_ in SCENARIOS if s_[0] in DEFAULT_ROOTS and DEFAULT_ROOTS[s_[0]] == s_[1]]:
            for seed in range(seeds):
                results["no_logs"].append(_run_one(fault, root, seed, kb, tmp, drop_logs=True))
                progress and progress(f"no-logs {fault}@{root} seed {seed}")
        # held-out 1: a fault class the KB has never been taught
        for seed in range(seeds):
            r = _run_one(*UNSEEN_FAULT, seed, kb, tmp)
            r["kind"] = "never taught"
            results["held_out"].append(r)
            progress and progress(f"held-out {UNSEEN_FAULT[0]} seed {seed}")
        # held-out 2: leave one known fault out of the KB's memory
        for fault in sorted({f for f, _ in SCENARIOS}):
            root = next(r for f, r in SCENARIOS if f == fault)
            kb_minus = KnowledgeBase(exclude=precedent_ids(fault))
            for seed in range(seeds):
                r = _run_one(fault, root, seed, kb_minus, tmp)
                r["kind"] = "left out of KB"
                results["held_out"].append(r)
                progress and progress(f"held-out {fault} (left out) seed {seed}")
    return summarize(results)


def _rate(n, d):
    return round(n / d, 3) if d else None


def summarize(results):
    s = {"runs": {k: len(v) for k, v in results.items()}, "normal": {}, "held_out": {}, "per_fault": {}, "raw": results}
    normal, held, nolog = results["normal"], results["held_out"], results["no_logs"]
    s["no_logs"] = {}
    for m in METHODS:
        s["no_logs"][m] = {
            "root_accuracy": _rate(sum(r[m]["root"] == r["root"] for r in nolog), len(nolog)),
            "fault_accuracy": _rate(sum(r[m]["fault"] == r["fault"] for r in nolog), len(nolog)),
            "abstained": _rate(sum(r[m]["fault"] is None for r in nolog), len(nolog)),
            "wrong_answer": _rate(sum(r[m]["fault"] not in (None, r["fault"]) for r in nolog), len(nolog)),
        }
    for m in METHODS:
        s["normal"][m] = {
            "root_accuracy": _rate(sum(r[m]["root"] == r["root"] for r in normal), len(normal)),
            "fault_accuracy": _rate(sum(r[m]["fault"] == r["fault"] for r in normal), len(normal)),
            "abstained": _rate(sum(r[m]["fault"] is None for r in normal), len(normal)),
            "wrong_answer": _rate(sum(r[m]["fault"] not in (None, r["fault"]) for r in normal), len(normal)),
        }
        s["held_out"][m] = {
            "root_accuracy": _rate(sum(r[m]["root"] == r["root"] for r in held), len(held)),
            "abstained": _rate(sum(r[m]["fault"] is None for r in held), len(held)),
            "wrong_confident": _rate(sum(r[m]["fault"] is not None for r in held), len(held)),
        }
    ag = [r["agent"] for r in normal + held + nolog if "verified" in r["agent"]]
    s["agent_extra"] = {
        "reports_verified": _rate(sum(a["verified"] for a in ag), len(ag)),
        "avg_evidence_items": round(sum(a["evidence_items"] for a in ag) / len(ag), 1) if ag else None,
        "avg_claims_checked": round(sum(a["claims"] for a in ag) / len(ag), 1) if ag else None,
        "avg_confidence_normal": round(sum(r["agent"]["confidence"] for r in normal if "confidence" in r["agent"]) / len(normal), 2),
        "avg_confidence_held_out": round(sum(r["agent"]["confidence"] for r in held if "confidence" in r["agent"]) / len(held), 2),
    }
    by = defaultdict(list)
    for r in normal:
        by[r["fault"]].append(r)
    for f, rs in sorted(by.items()):
        s["per_fault"][f] = {m: _rate(sum(r[m]["fault"] == f for r in rs), len(rs)) for m in METHODS}
    return s


def pct(x):
    return "n/a" if x is None else f"{round(100 * x)}%"


def to_markdown(s):
    n, h = s["normal"], s["held_out"]
    rows = lambda d, keys: "\n".join(f"| {k} | " + " | ".join(pct(d[m][k]) for m in METHODS) + " |" for k in keys)
    head = "| | naive | kb-only | agent |\n|---|---|---|---|"
    x = s["agent_extra"]
    out = [
        "# Evaluation results", "",
        f"{s['runs']['normal']} normal, {s['runs']['no_logs']} no-log and {s['runs']['held_out']} held-out runs on simulated incidents.", "",
        "## Normal: the KB has seen this kind of fault", head,
        rows(n, ["root_accuracy", "fault_accuracy", "abstained", "wrong_answer"]), "",
        "The KB was written knowing the simulator's fault patterns, so fault accuracy here is a sanity check, "
        "not a generalisation result.", "",
        "## No logs: every WARN and ERROR line deleted (broken logging pipeline)", head,
        rows(s["no_logs"], ["root_accuracy", "fault_accuracy", "abstained", "wrong_answer"]), "",
        "Only metrics plus deploy and config history remain. Guessing from symptoms alone cannot tell similar faults apart; "
        "checking deploys and config can.", "",
        "## Held-out: the KB has NOT seen this kind of fault", head,
        rows(h, ["root_accuracy", "abstained", "wrong_confident"]), "",
        "Never taught = disk_full; left out of KB = a known fault whose past incidents were removed. "
        "A method that always answers is wrong every time here; the agent should say it does not know.", "",
        "## Per fault: how often the right fault was named (normal runs)", head,
        "\n".join(f"| {f} | " + " | ".join(pct(v[m]) for m in METHODS) + " |" for f, v in s["per_fault"].items()), "",
        "## Agent extras",
        f"- Reports that passed the citation verifier: {pct(x['reports_verified'])}",
        f"- Average evidence items per investigation: {x['avg_evidence_items']}; claims checked per report: {x['avg_claims_checked']}",
        f"- Average confidence: {x['avg_confidence_normal']} on normal runs, {x['avg_confidence_held_out']} on held-out runs",
    ]
    return "\n".join(out) + "\n"
