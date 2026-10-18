"""End-to-end demo of what is built so far:
   break something -> detect it -> collect clues -> ask the knowledge base -> show the fix steps.
   Usage: python demo.py [--fault slow_query] [--root db]"""
import argparse
from datetime import datetime, timezone

from copilot.detect import find_incidents
from copilot.kb import KnowledgeBase
from copilot.kb.signature import hypotheses_for
from copilot.sim.faults import FAULTS
from copilot.sim.generator import generate
from copilot.store import connect
from copilot.tools.toolbox import Toolbox

DB = "data/demo.db"


def clock(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%H:%M")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--fault", choices=sorted(FAULTS), default="slow_query")
    p.add_argument("--root", help="service to break (default depends on the fault)")
    a = p.parse_args()

    print(f"1. BREAK  injecting '{a.fault}' into fake telemetry ...")
    generate(a.fault, a.root, db_path=DB)

    print("2. DETECT  scanning the numbers for anything unusual ...")
    incidents = find_incidents(DB)
    if not incidents:
        return print("   nothing found")
    inc = incidents[0]
    print(f"   one incident at {clock(inc['start_ts'])}, severity {inc['severity']}, "
          f"services hit in order: {' -> '.join(inc['services'])}")

    print("3. CLUES  looking closer at the first service that went wrong ...")
    tools = Toolbox(DB)
    suspect = inc["suspects"][0]
    sig, ranked = hypotheses_for(KnowledgeBase(), inc, toolbox=tools)
    print(f"   suspect: {suspect}")
    print(f"   numbers that jumped: {', '.join(sig['metrics'])}")
    for m in sig["messages"][:3]:
        print(f"   log line: {m[:90]}")

    print("4. IDEAS  asking the knowledge base what this looks like ...")
    for h in ranked[:3]:
        print(f"   {h['fault']:20s} match {h['score']:.2f}  similar past cases: {', '.join(h['precedents'])}")
    best = ranked[0]
    print(f"\n5. FIX  top idea is '{best['fault']}'. Runbook {best['runbook']}:")
    for i, step in enumerate(KnowledgeBase().runbook(best["fault"])["steps"], 1):
        print(f"   {i}. {step}")
    print("   To confirm it, check:")
    for pr in best["predictions"]:
        print(f"   - {pr['tool']}: {pr['expect']}")

    truth = connect(DB, readonly=True).execute("SELECT fault_type, root_service FROM ground_truth").fetchone()
    print(f"\nANSWER KEY (for the demo only): {truth['fault_type']} in {truth['root_service']}")


if __name__ == "__main__":
    main()
