# Incident Copilot

Automated root-cause analysis for software and data pipelines. Something breaks; the system notices,
groups the symptoms into one incident, investigates with read-only tools, scores competing explanations,
asks a human before proposing a fix, and writes a postmortem in which **every claim cites evidence a
verifier has checked**. When nothing it knows fits, it says so instead of guessing.

```
simulator -> SQLite -> detector -> correlator -> LangGraph investigation -> verified report
                                                  triage -> hypothesize (Prolog KB) -> gather_evidence (tools)
                                                  -> score -> critic -+-> propose_fix -> approval_gate (human) -+
                                                                      +-> survey_unknown ---------------------+-> postmortem -> verify
```
Architecture page with diagram: see the published artifact linked from the project notes, or `docs`-style
summary below.

## What is where
| Path | What it does |
|---|---|
| `copilot/sim/` | Fake telemetry for 4 services with 7 injectable faults (`disk_full` is deliberately unknown to the KB) |
| `copilot/store.py` | SQLite: metrics, logs, deploys, config_changes, ground_truth (answer key, used only by demo/tests/eval) |
| `copilot/detect/` | No-LLM detection: robust z-score (median/MAD) on metrics, new-error-pattern on logs; correlation into incidents; suspect ranking that sees through cascades |
| `copilot/tools/` | Five read-only investigation tools (+ `search_runbooks`); every result stored as `ev:NNN` |
| `knowledge/*.pl`, `copilot/kb/` | Prolog knowledge base: 13 past incidents, 7 runbooks, matching rules. Supplies hypotheses and fixes (`kb:` ids), never evidence |
| `copilot/agent/` | The LangGraph investigation: `state.py`, `nodes.py`, `checks.py`, `graph.py`, `verify.py`, `learn.py`, `llm.py`, `run.py` |
| `copilot/api/` | FastAPI app with live Server-Sent Events and a human approval endpoint |
| `copilot/eval/` | Evaluation harness with baselines and held-out faults; results in `eval/results.md` |

## Quick start (uv)
```
brew install uv swi-prolog                   # once
uv sync --extra agent --extra api            # creates .venv with LangGraph + FastAPI + pytest
uv run python -m copilot.agent --fault slow_query            # simulate, investigate, print the report
uv run python -m copilot.agent --fault disk_full             # a fault the KB has never seen
uv run python -m copilot.agent --fault bad_deploy --approve ask   # answer the approval question yourself
uv run python demo.py                        # the earlier step-by-step demo (detect -> KB)
uv run python -m copilot.eval --seeds 5      # evaluation tables -> eval/results.md
uv run uvicorn copilot.api.app:app           # then open http://127.0.0.1:8000
uv run pytest -q
```
Commit `uv.lock`; do not commit `.venv` (it is platform-specific).

## How an investigation works
1. **triage** picks the suspect (first service to alert, seeing through cascades) and records the detector output as evidence.
2. **hypothesize** turns the incident into a symptom signature and asks the Prolog KB what it resembles.
3. **gather_evidence** runs the tool checks the KB predicts for the top three ideas (deploy before the alert? config change? memory ramp or step? is this service the origin of the degradation?).
4. **score** = 0.5 x KB match + 0.5 x evidence verdicts. Below 0.55 means "no known pattern fits".
5. **critic** lists concerns (contradicting evidence, missing symptoms, close calls). The LLM only words them.
6. Known fault: **propose_fix** (runbook) -> **approval_gate** (LangGraph `interrupt`, a human must say yes). Unknown fault: **survey_unknown** collects plain findings (what moved, strangest logs, recent changes, dependency health) and open questions instead.
7. **postmortem** drafts the report; **verify** re-checks every claim against the evidence store and removes or replaces anything unsupported.

### Reliability choices
- Detection, scoring and checks are plain code; the LLM (mock by default, Ollama optional) only writes wording, and a lying or dead LLM cannot change a fact (tests cover both).
- The verifier checks that each claim cites real evidence ids and that every time, version and number in it appears in that evidence.
- Nothing is applied without a human yes; no answer counts as no.
- Tools open the database read-only. The answer key is never read by investigation code (a test greps for it).
- Learning loop: `POST /investigations/{id}/label` (or `copilot.agent.learn`) lets a human name the real cause; the KB then recognises it next time (`knowledge/learned.pl`, git-ignored).

### Using a real model
```
RCA_LLM=ollama RCA_MODEL=llama3.1 uv run python -m copilot.agent --fault bad_deploy
```
If Ollama is down or answers nothing, the plain-text fallback is used and the report records it.

## Evaluation (simulated incidents; `eval/results.md`)
| | naive | kb-only | agent |
|---|---|---|---|
| Fault named correctly, KB has seen the fault (65 runs) | 100% | 100% | 100% |
| Fault named correctly, logs deleted (30 runs) | 33% | 33% | 83% (rest: abstained) |
| Held-out faults (35 runs): confidently wrong | 86% | 86% | 0% |
| Held-out faults: said "don't know" | 14% | 14% | 100% |

Read this honestly: the KB was written knowing the simulator's fault patterns, so the first row is a sanity
check. The last two rows (faults the KB has not seen) and the no-logs row are where the agent's evidence
checks and abstention matter. All data is simulated.

## Known limits
- Everything is simulated; real telemetry would need a real collector and tuned thresholds (all thresholds are engineering choices tuned on the simulator).
- Evidence checks exist for the 7 known fault types; a learned fault has no tool checks yet, so its report is marked "unconfirmed" and rests on similarity to past cases.
- The correlator merges alerts within 30 minutes of each other; two unrelated incidents that close would be merged.
- SQLite uses `journal_mode=TRUNCATE` because the default fails on some mounted/synced folders.
