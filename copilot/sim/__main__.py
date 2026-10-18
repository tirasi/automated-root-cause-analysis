"""CLI: python -m copilot.sim --fault slow_query [--root db] [--seed 0] [--db data/telemetry.db]"""
import argparse
import json

from .faults import FAULTS
from .generator import generate


def main():
    p = argparse.ArgumentParser(description="Generate telemetry with one injected fault")
    p.add_argument("--fault", choices=sorted(FAULTS), required=True)
    p.add_argument("--root", help="root-cause service (defaults per fault)")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--db", help="output sqlite path (default data/telemetry.db)")
    a = p.parse_args()
    print(json.dumps(generate(a.fault, a.root, a.seed, a.db), indent=2))


if __name__ == "__main__":
    main()
