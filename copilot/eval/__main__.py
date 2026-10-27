"""python -m copilot.eval [--seeds 3] [--out eval]   -> prints the tables, saves eval/results.md and .json"""
import argparse
import json
from pathlib import Path

from .run import run_eval, to_markdown


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--seeds", type=int, default=3)
    p.add_argument("--out", default="eval")
    a = p.parse_args()
    s = run_eval(a.seeds, progress=lambda m: print("  ..", m, flush=True))
    md = to_markdown(s)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "results.md").write_text(md)
    (out / "results.json").write_text(json.dumps(s, indent=2))
    print("\n" + md)


if __name__ == "__main__":
    main()
