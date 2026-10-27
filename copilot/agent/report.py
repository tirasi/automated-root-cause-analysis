"""Plain-text rendering of a finished report."""


def render_text(report):
    r = report
    out = [f"INCIDENT {r['incident_id']}  [{r['status']}]", r["headline"], ""]
    rc = r["root_cause"]
    if rc.get("fault"):
        out.append(f"Root cause: {rc['fault']} on {rc['service']}  confidence {rc['confidence']:.2f} ({rc['confidence_label']})")
        out.append(f"Based on past cases: {', '.join(rc.get('precedents', []))}")
    else:
        out.append(f"Root cause: not determined. {rc['note']}")
    out += ["", "What the evidence shows:"]
    for f in r["findings"]:
        mark = {"supports": "+", "contradicts": "-"}.get(f.get("stance"), "*")
        out.append(f"  {mark} {f['claim']}  [{', '.join(f['cites'])}]")
    if r["caveats"]:
        out += ["", "Caveats from the critic:"] + [f"  ! {c}" for c in r["caveats"]]
    if r["recommended_actions"]:
        out += ["", f"Recommended fix ({r['recommended_actions'][0]['source']}, {r['recommended_actions'][0]['status']}):"]
        out += [f"  {i}. {a['step']}" for i, a in enumerate(r["recommended_actions"], 1)]
    if r["open_questions"]:
        out += ["", "Where to look next:"] + [f"  ? {q}" for q in r["open_questions"]]
    out += ["", "Timeline (first alerts):"] + [f"  {t['time']}  {t['event']}" for t in r["timeline"][:5]]
    v = r["verification"]
    out += ["", f"Verification: {'PASSED' if v['ok'] else 'FAILED'} - {v['claims_checked']} claims checked "
                f"against {v['evidence_cited']} evidence items"]
    return "\n".join(out)
