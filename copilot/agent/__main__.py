"""python -m copilot.agent --fault slow_query            investigate a freshly simulated incident
   python -m copilot.agent --db data/telemetry.db        investigate an existing database
   --approve yes|no|ask   how to answer the approval question (ask = prompt in the terminal)
   --json                 print the full report as JSON"""
import argparse
import json

from ..sim.faults import FAULTS
from ..sim.generator import generate
from .report import render_text
from .run import investigate


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--fault", choices=sorted(FAULTS))
    p.add_argument("--root")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--db", default="data/demo.db")
    p.add_argument("--approve", choices=["yes", "no", "ask"], default="yes")
    p.add_argument("--json", action="store_true")
    a = p.parse_args()
    if a.fault:
        generate(a.fault, a.root, a.seed, db_path=a.db)

    def ask(payload):
        print(f"\nAPPROVAL NEEDED: apply runbook {payload['runbook']} for {payload['fault']} on {payload['service']}?")
        for i, s in enumerate(payload["steps"], 1):
            print(f"  {i}. {s}")
        ok = input("approve? [y/N] ").strip().lower().startswith("y")
        return {"approved": ok, "by": "terminal-user"}

    approver = {"yes": "auto", "no": "reject", "ask": ask}[a.approve]
    final = investigate(a.db, approver=approver, emit=lambda e: e["type"] == "step" and [print(f"  > {t}") for t in e["trace"]])
    if final.get("status") == "no_incident":
        return print("No incident found.")
    print()
    print(json.dumps(final["report"], indent=2) if a.json else render_text(final["report"]))


if __name__ == "__main__":
    main()
