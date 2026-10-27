"""Python interface to the Prolog knowledge base (knowledge/*.pl) via the swipl CLI.

Retrieval is symbolic: each result says which symptoms matched and which did not. The KB supplies
hypotheses and remedies (ids `kb:...`); it never supplies evidence about the current incident."""
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from ..config import ROOT

KB_DIR = ROOT / "knowledge"
FILES = ["rules.pl", "incidents.pl", "runbooks.pl", "learned.pl", "main.pl"]
_ATOM = re.compile(r"^[a-z][a-z0-9_]*$")


class KBUnavailable(RuntimeError):
    pass


def find_swipl():
    for cand in (os.environ.get("RCA_SWIPL"), shutil.which("swipl"), str(Path.home() / "swipl/bin/swipl")):
        if cand and Path(cand).exists():
            return cand
    raise KBUnavailable("SWI-Prolog not found: install it (https://www.swi-prolog.org) or set RCA_SWIPL")


def pl_str(text):
    return json.dumps(str(text))  # JSON string escapes are valid Prolog string escapes


def pl_atom(name):
    if not _ATOM.match(name):
        raise ValueError(f"not a plain atom: {name!r}")
    return name


def _quoted(name):
    return "'" + str(name).replace("\\", "\\\\").replace("'", "\\'") + "'"


def metric_symbol(metric, direction="up"):
    return f"metric({pl_atom(metric)},{pl_atom(direction)})"


class KnowledgeBase:
    def __init__(self, exclude=(), swipl=None, kb_dir=None):
        self.swipl = swipl or find_swipl()
        self.dir = Path(kb_dir or KB_DIR)
        self.exclude = list(exclude)
        self._cache = {}  # runbook/predictions are static facts: look each up once per instance

    def _query(self, goal):
        files = [self.dir / f for f in FILES if (self.dir / f).exists()]
        load = "consult([" + ",".join(_quoted(f) for f in files) + "])"
        proc = subprocess.run([self.swipl, "-q", "-f", "none", "-g", load, "-g", "main", "-t", "halt"],
                              input=goal + ".\n", capture_output=True, text=True, timeout=30)
        rows = [line.split("\t") for line in proc.stdout.splitlines() if line.strip()]
        for row in rows:
            if row[0] == "ERR":
                raise RuntimeError(f"KB query failed: {row[1:]} | {proc.stderr[:300]}")
        return rows

    def tag(self, messages):
        rows = self._query(f"tag([{','.join(pl_str(m) for m in messages)}])")
        return [t for t in rows[0][1].split(";") if t] if rows else []

    def hypotheses(self, service, metrics, messages, top_k=4):
        """metrics: ["metric(error_rate,up)", ...]; messages: raw log lines. Ranked, explainable."""
        excl = ",".join(_quoted(e) for e in self.exclude)
        goal = (f"hypotheses({pl_atom(service)},[{','.join(metrics)}],"
                f"[{','.join(pl_str(m) for m in messages)}],[{excl}],{int(top_k)})")
        out = []
        for _, fault, score, ids, matched, missing in (r for r in self._query(goal) if r[0] == "HYP"):
            rb = self.runbook(fault)
            out.append({"fault": fault, "score": float(score),
                        "precedents": [f"kb:{i}" for i in ids.split(",") if i],
                        "matched": [s for s in matched.split(";") if s],
                        "missing": [s for s in missing.split(";") if s],
                        "runbook": rb["kb_id"] if rb else None,
                        "predictions": self.predictions(fault)})
        return out

    def incident(self, kb_id):
        pid = kb_id.removeprefix("kb:")
        for r in self._query(f"incident({_quoted(pid)})"):
            if r[0] == "PM":
                return {"kb_id": f"kb:{r[1]}", "fault": r[2], "root_service": r[3],
                        "summary": r[4], "resolution": r[5]}
        return None

    def runbook(self, fault):
        key = ("runbook", fault)
        if key not in self._cache:
            self._cache[key] = self._runbook(fault)
        return self._cache[key]

    def _runbook(self, fault):
        rows = self._query(f"runbook({pl_atom(fault)})")
        head = next((r for r in rows if r[0] == "RB"), None)
        if not head:
            return None
        return {"kb_id": f"kb:{head[1]}", "fault": head[2], "title": head[3],
                "steps": [r[2] for r in rows if r[0] == "STEP"]}

    def predictions(self, fault):
        key = ("pred", fault)
        if key not in self._cache:
            self._cache[key] = [{"tool": r[1], "expect": r[2]}
                                for r in self._query(f"predictions({pl_atom(fault)})") if r[0] == "PRED"]
        return self._cache[key]

    def search_runbooks(self, text, top_k=3):
        rows = [r for r in self._query(f"search({pl_str(text)})") if r[0] == "RB"]
        return [{"kb_id": f"kb:{r[1]}", "fault": r[2], "score": int(r[3]), "title": r[4]} for r in rows[:top_k]]

    def learn(self, kb_id, fault, root_service, summary, resolution, symptoms, runbook_steps=None, title=None, log_tags=None):
        """Write a finished incident back as new precedent facts (postmortem node). `symptoms` use
        the same service-agnostic form as incidents.pl, e.g. ["metric(error_rate,up)", "log(oom)"]."""
        pid = kb_id.removeprefix("kb:")
        path = self.dir / "learned.pl"
        header = "" if path.exists() else (
            ":- multifile past_incident/5, incident_symptom/2, runbook/3, runbook_step/3, log_tag/2.\n"
            ":- dynamic past_incident/5, incident_symptom/2.\n")
        lines = [f"past_incident({_quoted(pid)}, {pl_atom(fault)}, {pl_atom(root_service)}, "
                 f"{pl_str(summary)}, {pl_str(resolution)})."]
        lines += [f"incident_symptom({_quoted(pid)}, {s})." for s in symptoms]
        for tag, pattern in (log_tags or {}).items():   # new log wording -> symptom tag (lower-case match)
            lines.append(f"log_tag({pl_atom(tag)}, {pl_str(pattern.lower())}).")
        if runbook_steps and not self.runbook(fault):  # a fault the KB has no runbook for yet
            rid = "rb-learned-" + fault.replace("_", "-")
            lines.append(f"runbook({pl_atom(fault)}, {_quoted(rid)}, {pl_str(title or fault)}).")
            lines += [f"runbook_step({_quoted(rid)}, {n}, {pl_str(t)})." for n, t in enumerate(runbook_steps, 1)]
        with open(path, "a") as fh:
            fh.write(header + "\n".join(lines) + "\n")
        self._cache.clear()
        return f"kb:{pid}"
