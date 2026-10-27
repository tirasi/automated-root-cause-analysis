"""The eight steps of an investigation (plus the unknown-fault path and the verifier).

Each method takes the shared state and returns only the keys it changed.
Shared objects (KB, toolbox, LLM) live on the class, not in the state, because state is plain data."""
from langgraph.types import interrupt

from ..config import METRICS
from ..kb.signature import hypotheses_for
from .checks import Ctx, hhmm, run_checks
from .llm import LLMError
from .verify import verify_report

TOP_CHECKED = 3         # how many KB hypotheses get tested with tools
UNKNOWN_BELOW = 0.55    # final score under this = "no known pattern fits"; tuned on the simulator
CLOSE_CALL = 0.10       # top-2 closer than this = flag it
W_KB, W_EVIDENCE = 0.5, 0.5
VERDICT_VALUE = {"confirmed": 1.0, "inconclusive": 0.0, "refuted": -1.0}


def evidence_score(checks):
    """-1..+1 weighted average of the check verdicts, mapped to 0..1 (0.5 = no information)."""
    den = sum(c["weight"] for c in checks)
    if den == 0:
        return 0.5
    return (sum(c["weight"] * VERDICT_VALUE[c["verdict"]] for c in checks) / den + 1) / 2


def route_after_critic(state):
    return "survey_unknown" if state.get("unknown") else "propose_fix"


class Nodes:
    def __init__(self, kb, toolbox, llm):
        self.kb = kb
        self.toolbox = toolbox
        self.llm = llm

    # ---------- helpers ----------
    @property
    def ev(self):
        return self.toolbox.evidence

    def _say(self, prompt, fallback):
        """Ask the LLM for wording. If it fails or says nothing, use the plain-text fallback."""
        try:
            text = self.llm.complete(prompt)
        except LLMError:
            return fallback, True
        return (text, False) if text else (fallback, True)

    def _ctx(self, state):
        inc, svc = state["incident"], state["suspect"]
        return Ctx(self.toolbox, self.kb, svc, inc["first_alert_ts"][svc], inc["end_ts"], state["detection_ev"])

    # ---------- 1. triage ----------
    def triage(self, state):
        inc = state["incident"]
        suspect = inc["suspects"][0]
        alerts = [{"service": a["service"], "signal": a["signal"], "ts": a["ts"], "score": a["score"],
                   "direction": a.get("direction"), "detail": a["detail"]} for a in inc["alerts"]]
        eid = self.ev.add("find_incidents", {"incident_id": inc["id"]}, {
            "incident_id": inc["id"], "start_ts": inc["start_ts"], "end_ts": inc["end_ts"],
            "services": inc["services"], "suspects": inc["suspects"],
            "first_alert_ts": inc["first_alert_ts"], "severity": inc["severity"], "alerts": alerts})
        return {"suspect": suspect, "detection_ev": eid, "evidence": self.ev.all(),
                "trace": [f"triage: {inc['id']} severity {inc['severity']}, services hit in order "
                          f"{' -> '.join(inc['services'])}; suspect {suspect} [{eid}]"]}

    # ---------- 2. hypothesize ----------
    def hypothesize(self, state):
        sig, ranked = hypotheses_for(self.kb, state["incident"], state["suspect"], toolbox=self.toolbox)
        top = ", ".join(f"{h['fault']} ({h['score']:.2f})" for h in ranked[:3]) or "nothing matched"
        return {"signature": sig, "hypotheses": ranked, "evidence": self.ev.all(),
                "trace": [f"hypothesize: KB suggests {top}"]}

    # ---------- 3. gather_evidence ----------
    def gather_evidence(self, state):
        ctx = self._ctx(state)
        checks = []
        for h in state["hypotheses"][:TOP_CHECKED]:
            checks += run_checks(h, ctx)
        counts = {v: sum(c["verdict"] == v for c in checks) for v in VERDICT_VALUE}
        return {"checks": checks, "evidence": self.ev.all(),
                "trace": [f"gather_evidence: ran {len(checks)} checks on the top {TOP_CHECKED} ideas: "
                          f"{counts['confirmed']} confirmed, {counts['refuted']} refuted, "
                          f"{counts['inconclusive']} inconclusive"]}

    # ---------- 4. score ----------
    def score(self, state):
        ranking = []
        for h in state["hypotheses"]:
            own = [c for c in state["checks"] if c["fault"] == h["fault"]]
            # untested ideas can't win, unless the KB has no test for them at all (e.g. a learned fault)
            ev = evidence_score(own) if own else (0.0 if h["predictions"] else 0.5)
            ranking.append({"fault": h["fault"], "kb_score": round(h["score"], 3),
                            "evidence_score": round(ev, 3), "checked": bool(own),
                            "final": round(W_KB * h["score"] + W_EVIDENCE * ev, 3)})
        ranking.sort(key=lambda r: -r["final"])
        top = ranking[0]["final"] if ranking else 0.0
        margin = round(top - ranking[1]["final"], 3) if len(ranking) > 1 else top
        unknown = not ranking or top < UNKNOWN_BELOW
        refuted_top = any(c["verdict"] == "refuted" and c["weight"] >= 1 for c in state["checks"]
                          if ranking and c["fault"] == ranking[0]["fault"])
        label = ("low" if unknown or top < 0.7 else
                 "high" if margin >= CLOSE_CALL and not refuted_top and top >= 0.8 else "medium")
        verdict = "no known pattern fits" if unknown else f"{ranking[0]['fault']} ({label} confidence)"
        return {"ranking": ranking, "scores": {r["fault"]: r["final"] for r in ranking},
                "confidence": top, "margin": margin, "unknown": unknown, "confidence_label": label,
                "trace": [f"score: best {top:.2f}, margin {margin:.2f} -> {verdict}"]}

    # ---------- 5. critic ----------
    def critic(self, state):
        flags = []
        rank = state["ranking"]
        if state["unknown"]:
            flags.append(f"No known pattern fits well: the best score is {state['confidence']:.2f}, below "
                         f"{UNKNOWN_BELOW}. Treat any suggested cause as a guess.")
        elif rank:
            top = rank[0]["fault"]
            for c in state["checks"]:
                if c["fault"] == top and c["verdict"] == "refuted" and c["weight"] >= 1:
                    flags.append(f"Evidence argues against {top}: {c['observation']}")
            hyp = next(h for h in state["hypotheses"] if h["fault"] == top)
            if hyp["missing"]:
                flags.append(f"Past {top} incidents also showed {', '.join(hyp['missing'])}, "
                             f"which was not seen here.")
            if len(rank) > 1 and state["margin"] < CLOSE_CALL:
                flags.append(f"Close call between {top} ({rank[0]['final']:.2f}) and "
                             f"{rank[1]['fault']} ({rank[1]['final']:.2f}).")
        fallback = " ".join(flags) or "No objections: the evidence agrees with the leading hypothesis."
        prompt = ("You are a sceptical reviewer of a root-cause analysis. Rewrite the points below as a short "
                  "critique. Add nothing that is not in the facts.\nFACTS:\n" + "\n".join(f"- {f}" for f in flags or [fallback]))
        text, fell_back = self._say(prompt, fallback)
        return {"critique": text, "critic_flags": flags,
                "trace": [f"critic: {len(flags)} concern(s) raised" + (" (LLM unavailable, plain text used)" if fell_back else "")]}

    # ---------- 6a. propose_fix (known fault) ----------
    def propose_fix(self, state):
        fault = state["ranking"][0]["fault"]
        rb = self.kb.runbook(fault)
        fix = {"fault": fault, "kb_id": rb["kb_id"], "title": rb["title"], "steps": rb["steps"]}
        return {"proposed_fix": fix, "trace": [f"propose_fix: runbook {rb['kb_id']} ({len(rb['steps'])} steps)"]}

    # ---------- 7. approval_gate (human in the loop) ----------
    def approval_gate(self, state):
        fix = state["proposed_fix"]
        decision = interrupt({"question": "Approve this remediation?", "fault": fix["fault"],
                              "service": state["suspect"], "confidence": state["confidence"],
                              "runbook": fix["kb_id"], "steps": fix["steps"]})
        ok = bool(decision.get("approved"))
        by = decision.get("by", "unknown")
        return {"approved": ok, "approver": by,
                "trace": [f"approval_gate: {'approved' if ok else 'rejected'} by {by}"]}

    # ---------- 6b. survey_unknown (no known fault fits) ----------
    def survey_unknown(self, state):
        ctx, tb = self._ctx(state), self.toolbox
        svc, t0 = ctx.svc, ctx.t0
        findings = [{"claim": f"First alert on {svc} at {hhmm(t0)}; services affected, in order: "
                              f"{', '.join(state['incident']['services'])}", "cites": [ctx.det_ev]}]
        questions = []
        for m in METRICS:
            r = tb.query_metrics(svc, m, *ctx.win)
            z = r["window_z_vs_baseline"]
            if z is not None and abs(z) >= 4:
                findings.append({"claim": f"{m} on {svc} moved (z={z}, shape {r['shape']})",
                                 "cites": [r["evidence_id"]]})
        logs = tb.query_logs(svc, *ctx.win, min_level="WARN", top=3)
        for cl in logs["clusters"]:
            findings.append({"claim": f"{cl['count']} {cl['level']} lines on {svc}: {cl['template'][:80]}",
                             "cites": [logs["evidence_id"]]})
            questions.append(f"Find out what produces this message on {svc}: {cl['template'][:80]}")
        d = tb.recent_deploys(t0 - 3600, t0 + 60)
        g = tb.config_diff(t0 - 3600, t0 + 60)
        for x in d["deploys"]:
            findings.append({"claim": f"Deploy {x['version']} to {x['service']} at {hhmm(x['ts'])}: {x['diff_summary']}",
                             "cites": [d["evidence_id"]]})
        for x in g["changes"]:
            findings.append({"claim": f"Config {x['key']} on {x['service']} changed from {x['old_value']} to "
                                      f"{x['new_value']} at {hhmm(x['ts'])}", "cites": [g["evidence_id"]]})
        if not d["deploys"] and not g["changes"]:
            findings.append({"claim": "No deploy or config change happened in the hour before the first alert",
                             "cites": [d["evidence_id"], g["evidence_id"]]})
            questions.append(f"No change preceded the incident, so check resources and external limits on {svc} "
                             f"(disk, memory, quotas, traffic) rather than a release.")
        else:
            questions.append("Check whether the deploy or config change listed above explains the symptoms.")
        dep = tb.service_dependencies(svc, t0 + 300)
        bad_up = [n for n, h in dep["upstream_dependencies"].items() if h["status"] == "degraded"]
        findings.append({"claim": f"{svc} is {dep['self']['status']} (worst z {dep['self']['worst_z']}); degraded "
                                  f"upstream: {', '.join(bad_up) or 'none'}", "cites": [dep["evidence_id"]]})
        near = tb.search_runbooks(" ".join(cl["template"] for cl in logs["clusters"]))["matches"]
        if near:
            questions.append("Closest known runbooks to read (keyword overlap only): " +
                             ", ".join(f"{m['kb_id']} {m['title']}" for m in near))
        return {"generic_findings": findings, "open_questions": questions, "nearest_known": near,
                "evidence": self.ev.all(),
                "trace": [f"survey_unknown: no known pattern; collected {len(findings)} plain findings and "
                          f"{len(questions)} open question(s)"]}

    # ---------- 8. postmortem ----------
    def postmortem(self, state):
        inc, svc, unknown = state["incident"], state["suspect"], state.get("unknown", False)
        det, t0 = state["detection_ev"], state["incident"]["first_alert_ts"][state["suspect"]]
        sig = state["signature"]
        findings = [{"claim": f"First alert on {svc} at {hhmm(t0)}; services affected, in order: "
                              f"{', '.join(inc['services'])}", "cites": [det], "stance": "context"}]
        if unknown:
            findings = [dict(f, stance="context") for f in state["generic_findings"]]
            root = {"fault": None, "service": svc, "confidence": state["confidence"], "confidence_label": "low",
                    "note": "No known pattern fits. The first failing service is shown, not a diagnosed cause."}
            kb_refs = [m["kb_id"] for m in state.get("nearest_known", [])]
            actions = []
        else:
            top = state["ranking"][0]["fault"]
            hyp = next(h for h in state["hypotheses"] if h["fault"] == top)
            findings.append({"claim": f"Symptoms on {svc}: {', '.join(sig['metrics']) or 'no metric symptoms'}",
                             "cites": [det] + sig["evidence_ids"], "stance": "context"})
            for c in state["checks"]:
                if c["fault"] == top and c["verdict"] != "inconclusive":
                    findings.append({"claim": c["observation"], "cites": c["cites"],
                                     "stance": "supports" if c["verdict"] == "confirmed" else "contradicts"})
            fix = state["proposed_fix"]
            status = "approved" if state.get("approved") else "rejected by reviewer"
            actions = [{"step": s, "source": fix["kb_id"], "status": status} for s in fix["steps"]]
            root = {"fault": top, "service": svc, "confidence": state["confidence"],
                    "confidence_label": state["confidence_label"], "precedents": hyp["precedents"],
                    "runbook": fix["kb_id"]}
            kb_refs = list(dict.fromkeys(hyp["precedents"] + [fix["kb_id"]]))
            if not any(f["stance"] == "supports" for f in findings):
                root["unconfirmed"] = True   # nothing independent confirmed it: similarity to past cases only
        timeline = [{"time": hhmm(a["ts"]), "event": f"{a['service']}: {a['detail']}", "cites": [det]}
                    for a in sorted(inc["alerts"], key=lambda a: a["ts"])[:8]]
        headline = (f"No known pattern fits; {svc} failed first." if unknown else
                    f"Likely cause: {root['fault']} on {svc} ({root['confidence_label']} confidence).")
        facts = "\n".join(f"- {f['claim']} [{', '.join(f['cites'])}]" for f in findings)
        prompt = ("Write a short, plain postmortem summary of this incident for an engineer. Use ONLY the facts "
                  "below, keep the evidence ids in square brackets exactly as given, and do not add numbers.\n"
                  f"HEADLINE: {headline}\nFACTS:\n{facts}")
        narrative, fell_back = self._say(prompt, facts)
        caveats = list(state.get("critic_flags", []))
        if root.get("unconfirmed"):
            caveats.append("No tool check independently confirmed this cause; it rests on similarity to past incidents.")
        report = {"incident_id": inc["id"], "headline": headline, "status": "unverified",
                  "root_cause": root, "summary": narrative, "findings": findings, "timeline": timeline,
                  "recommended_actions": actions, "caveats": caveats,
                  "open_questions": state.get("open_questions", []), "kb_refs": kb_refs,
                  "evidence_index": [{"id": e["id"], "tool": e["tool"], "args": e["args"]} for e in self.ev.all()],
                  "meta": {"llm": getattr(self.llm, "name", "?"), "llm_fell_back": fell_back}}
        return {"report": report, "trace": [f"postmortem: report drafted ({len(findings)} findings)"]}

    # ---------- 9. verify ----------
    def verify(self, state):
        report = state["report"]
        first = verify_report(report, self.ev)
        removed = []
        if not first["ok"]:
            bad = {p["index"] for p in first["problems"] if p["where"] == "findings"}
            if bad:
                removed = [f for i, f in enumerate(report["findings"]) if i in bad]
                report["findings"] = [f for i, f in enumerate(report["findings"]) if i not in bad]
            if any(p["where"] == "summary" for p in first["problems"]):
                report["summary"] = "\n".join(f"- {f['claim']} [{', '.join(f['cites'])}]" for f in report["findings"])
                report["meta"]["summary_replaced"] = True
        second = verify_report(report, self.ev) if not first["ok"] else first
        report["status"] = "verified" if second["ok"] else "needs_review"
        report["rejected_claims"] = removed
        report["verification"] = second
        return {"report": report, "verification": second,
                "trace": [f"verify: {report['status']} ({second['claims_checked']} claims checked, "
                          f"{len(first['problems'])} problem(s) found" + (", removed" if removed else "") + ")"]}
