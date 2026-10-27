# Evaluation results

65 normal, 30 no-log and 35 held-out runs on simulated incidents.

## Normal: the KB has seen this kind of fault
| | naive | kb-only | agent |
|---|---|---|---|
| root_accuracy | 100% | 100% | 100% |
| fault_accuracy | 100% | 100% | 100% |
| abstained | 0% | 0% | 0% |
| wrong_answer | 0% | 0% | 0% |

The KB was written knowing the simulator's fault patterns, so fault accuracy here is a sanity check, not a generalisation result.

## No logs: every WARN and ERROR line deleted (broken logging pipeline)
| | naive | kb-only | agent |
|---|---|---|---|
| root_accuracy | 100% | 100% | 100% |
| fault_accuracy | 33% | 33% | 83% |
| abstained | 0% | 0% | 17% |
| wrong_answer | 67% | 67% | 0% |

Only metrics plus deploy and config history remain. Guessing from symptoms alone cannot tell similar faults apart; checking deploys and config can.

## Held-out: the KB has NOT seen this kind of fault
| | naive | kb-only | agent |
|---|---|---|---|
| root_accuracy | 100% | 100% | 100% |
| abstained | 14% | 14% | 100% |
| wrong_confident | 86% | 86% | 0% |

Never taught = disk_full; left out of KB = a known fault whose past incidents were removed. A method that always answers is wrong every time here; the agent should say it does not know.

## Per fault: how often the right fault was named (normal runs)
| | naive | kb-only | agent |
|---|---|---|---|
| bad_deploy | 100% | 100% | 100% |
| config_change | 100% | 100% | 100% |
| memory_leak | 100% | 100% | 100% |
| schema_drift | 100% | 100% | 100% |
| slow_query | 100% | 100% | 100% |
| timeout_cascade | 100% | 100% | 100% |

## Agent extras
- Reports that passed the citation verifier: 100%
- Average evidence items per investigation: 10.0; claims checked per report: 10.8
- Average confidence: 0.99 on normal runs, 0.3 on held-out runs
