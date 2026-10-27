"""Learning loop: a human labels a finished investigation, and the KB learns it.

Why this exists: an unknown fault gets "no known pattern". After an engineer finds the real cause,
`learn_from_resolution` writes it into knowledge/learned.pl (a past incident, optionally a runbook and
new log wording). The next time the same thing happens, the KB recognises it. Nothing is learned
without a human label, so a wrong guess can never teach the KB a wrong lesson."""
import re


def _slug(text):
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_") or "pattern"


def learn_from_resolution(kb, state, fault, root_service, resolution, steps=None, title=None, log_keywords=()):
    """state: the final state of an investigation. Returns the new kb: id."""
    sig = state["signature"]
    messages = " ".join(sig["messages"]).lower()
    new_tags = {_slug(kw): kw for kw in log_keywords if kw.lower() in messages}   # only wording really seen
    symptoms = list(sig["metrics"])
    symptoms += [f"log({t})" for t in sorted(set(kb.tag(sig["messages"])) | set(new_tags))]
    pid = "pm-" + state["incident"]["id"].removeprefix("inc-")
    summary = f"Learned from {state['incident']['id']}: {state['report']['findings'][0]['claim']}"
    return kb.learn(pid, fault, root_service, summary, resolution, symptoms,
                    runbook_steps=steps, title=title or fault.replace("_", " ").capitalize(), log_tags=new_tags)
