# Incident Copilot

Automated root-cause analysis for software and data pipelines: detect an anomaly, group alerts into one
incident, investigate with typed tools, and report a ranked root cause with cited evidence.

## Status
- [x] Fault-injectable simulator (6 faults: bad_deploy, slow_query, timeout_cascade, memory_leak, config_change, schema_drift)
- [x] SQLite telemetry store (metrics, logs, deploys, config changes, ground truth)
- [x] Investigation tools with evidence IDs (`query_logs`, `query_metrics`, `recent_deploys`, `config_diff`, `service_dependencies`)
- [x] Detector (robust rolling z-score + new-error-template) and incident correlation
- [x] Prolog knowledge base (`knowledge/*.pl`): 13 precedents, 7 runbooks, symptom-matching rules, service-applicability rules, write-back (`KnowledgeBase.learn`)
- [ ] `search_runbooks` exposed as an investigation tool (the KB method exists: `KnowledgeBase.search_runbooks`)
- [ ] LangGraph investigation (triage, hypothesize, gather_evidence, score, critic, propose_fix, approval_gate, postmortem)
- [ ] Citation verifier, FastAPI + SSE, eval harness with baseline

## Quick start (uv)
```
brew install uv swi-prolog          # once (Linux: install uv from astral.sh, apt install swi-prolog)
uv sync                             # creates .venv and installs pytest
uv run python demo.py               # break -> detect -> clues -> knowledge base -> fix steps
uv run python demo.py --fault bad_deploy
uv run pytest -q
uv run python -m copilot.sim --fault slow_query --db data/telemetry.db
```
Later steps: `uv sync --extra agent` (LangGraph) and `uv sync --extra api` (FastAPI).
Commit `uv.lock`; do not commit `.venv` (it is platform-specific).

## Knowledge base (Prolog, symbolic RAG)
Retrieval matches a live incident's symptoms (metric shifts + log-pattern tags) against past incidents.
Every hypothesis lists the precedents (`kb:pm-NNN`), matched symptoms and missing symptoms, plus the
runbook (`kb:rb-...`) and the tool calls that would confirm it. Rules also constrain which services a fault
can originate in (e.g. `slow_query` only on a datastore). The KB supplies hypotheses and remedies, never evidence.

Requires SWI-Prolog 9+ on PATH (or set `RCA_SWIPL`): `brew install swi-prolog` / `apt install swi-prolog` /
https://www.swi-prolog.org. Tests skip the KB module if it is missing.

## Notes
- SQLite uses `journal_mode=TRUNCATE` because the default DELETE mode fails on some mounted/synced folders.
- The KB precedents were authored with knowledge of the simulator's fault signatures, so a 6/6 top-1 on the simulator is a sanity check, not a result to quote. Honest evaluation needs held-out fault types/services (`KnowledgeBase(exclude=[...])`) and the agent's evidence checks.
- Ground truth lives in the `ground_truth` table for the eval harness; investigation code must never read it.
