"""Citation verifier: checks a finished report against the evidence it cites. No LLM involved.

For every claim it checks that
  1. it cites at least one evidence id, and every cited id really exists in the EvidenceStore;
  2. every time (HH:MM), version (v1.2.3) and number in the claim appears in the cited evidence;
  3. the free-text summary only cites ids that exist and invents no numbers;
  4. a named root cause has at least one supporting finding (or is openly marked unconfirmed), and every recommended action points
     at a knowledge-base id the report lists.
A report that fails is repaired by the verify node (bad claims removed) and re-checked."""
import re
from datetime import datetime, timezone

CITE = re.compile(r"\bev:\d{3,}\b")
KBREF = re.compile(r"\bkb:[a-z0-9-]+\b", re.I)
TIME = re.compile(r"\b(?:[01]\d|2[0-3]):[0-5]\d\b")
VERSION = re.compile(r"\bv\d+(?:\.\d+)+\b")
NUMBER = re.compile(r"(?<![\w.:/<>-])[-+]?\d+(?:\.\d+)?(?![\w:/<>])")


def _leaves(obj, nums, strs):
    if isinstance(obj, bool) or obj is None:
        return
    if isinstance(obj, (int, float)):
        nums.append(float(obj))
    elif isinstance(obj, str):
        strs.append(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            _leaves(v, nums, strs)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _leaves(v, nums, strs)


def _hhmm(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%H:%M")


def unsupported_tokens(text, items):
    """Tokens in `text` (times, versions, numbers) that no evidence item in `items` contains."""
    nums, strs = [], []
    for it in items:
        _leaves(it["result"], nums, strs)
        _leaves(it["args"], nums, strs)
    clock = {_hhmm(n) for n in nums if n > 1e9}
    text = CITE.sub(" ", text)
    bad = []
    for t in TIME.findall(text):
        if t not in clock and not any(t in s for s in strs):
            bad.append(t)
    text = TIME.sub(" ", text)
    for v in VERSION.findall(text):
        if not any(v in s for s in strs):
            bad.append(v)
    text = VERSION.sub(" ", text)
    for tok in NUMBER.findall(text):
        x = float(tok)
        near = any(abs(x - n) <= max(0.011, 0.005 * abs(n)) for n in nums)
        if not near and not any(tok.lstrip("+") in s for s in strs):
            bad.append(tok)
    return bad


def _items(ids, store):
    return [store.get(i) for i in ids if i in store]


def verify_report(report, store):
    problems, checked = [], 0

    def check_claim(where, idx, claim, cites):
        nonlocal checked
        checked += 1
        if not cites:
            problems.append({"where": where, "index": idx, "issue": "uncited", "detail": claim[:90]})
            return
        missing = [c for c in cites if c not in store]
        if missing:
            problems.append({"where": where, "index": idx, "issue": "unknown_citation",
                             "detail": f"{', '.join(missing)} not in evidence store"})
            return
        bad = unsupported_tokens(claim, _items(cites, store))
        if bad:
            problems.append({"where": where, "index": idx, "issue": "unsupported_value",
                             "detail": f"{', '.join(bad)} not found in {', '.join(cites)}"})

    for i, f in enumerate(report.get("findings", [])):
        check_claim("findings", i, f["claim"], f.get("cites", []))
    for i, t in enumerate(report.get("timeline", [])):
        check_claim("timeline", i, t["event"], t.get("cites", []))

    # the free-text summary: only real ids, no new numbers
    all_cited = {c for f in report.get("findings", []) + report.get("timeline", []) for c in f.get("cites", [])}
    summary = report.get("summary", "")
    for eid in CITE.findall(summary):
        if eid not in store:
            problems.append({"where": "summary", "index": 0, "issue": "unknown_citation", "detail": eid})
    bad = unsupported_tokens(summary, _items(sorted(all_cited), store))
    if bad:
        problems.append({"where": "summary", "index": 0, "issue": "unsupported_value", "detail": ", ".join(bad)})
    for ref in KBREF.findall(summary):
        if ref not in report.get("kb_refs", []):
            problems.append({"where": "summary", "index": 0, "issue": "unknown_kb_ref", "detail": ref})

    root = report.get("root_cause", {})
    if root.get("fault") and not root.get("unconfirmed") and not any(f.get("stance") == "supports" for f in report.get("findings", [])):
        problems.append({"where": "root_cause", "index": 0, "issue": "no_supporting_evidence",
                         "detail": f"{root['fault']} is named but no finding supports it"})
    for i, a in enumerate(report.get("recommended_actions", [])):
        if a["source"] not in report.get("kb_refs", []):
            problems.append({"where": "recommended_actions", "index": i, "issue": "unknown_kb_ref",
                             "detail": a["source"]})
    return {"ok": not problems, "problems": problems, "claims_checked": checked,
            "evidence_cited": len(all_cited)}
