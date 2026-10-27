% Runbooks, testable predictions and search keywords per fault. Runbook ids are cited as kb:<id>.
% Predictions tell the investigation which tool can confirm or refute a hypothesis.
:- multifile runbook/3, runbook_step/3.
:- discontiguous runbook/3, runbook_step/3.

runbook(bad_deploy, 'rb-bad-deploy', "Bad deploy").
runbook_step('rb-bad-deploy', 1, "Confirm a deploy to the affected service landed shortly before the first alert.").
runbook_step('rb-bad-deploy', 2, "Compare the error signature with the release diff to find the changed code path.").
runbook_step('rb-bad-deploy', 3, "Roll back to the previous version and watch the error rate return to baseline.").
runbook_step('rb-bad-deploy', 4, "Open a fix-forward ticket with a regression test before redeploying.").

runbook(slow_query, 'rb-slow-query', "Slow database query").
runbook_step('rb-slow-query', 1, "Find the slow statement in the database log and its table.").
runbook_step('rb-slow-query', 2, "Check the query plan for a sequential scan and the table for a missing or dropped index.").
runbook_step('rb-slow-query', 3, "Create the index or cancel the offending sessions.").
runbook_step('rb-slow-query', 4, "Confirm latency on the database and its callers returns to baseline.").

runbook(timeout_cascade, 'rb-timeout-cascade', "Timeout cascade").
runbook_step('rb-timeout-cascade', 1, "Identify the stalled dependency from the dependency graph; it is the deepest degraded service.").
runbook_step('rb-timeout-cascade', 2, "Check for a recently raised timeout or retry setting that lets calls hang.").
runbook_step('rb-timeout-cascade', 3, "Restore the dependency or shed load; revert the timeout to its safe value.").
runbook_step('rb-timeout-cascade', 4, "Add a circuit breaker and cap retries.").

runbook(memory_leak, 'rb-memory-leak', "Memory leak").
runbook_step('rb-memory-leak', 1, "Confirm memory rises steadily with no matching traffic increase.").
runbook_step('rb-memory-leak', 2, "Find the release that introduced the growth (new cache, unbounded collection).").
runbook_step('rb-memory-leak', 3, "Restart the service to recover and roll back the release.").
runbook_step('rb-memory-leak', 4, "Add a size limit or TTL to the growing structure.").

runbook(config_change, 'rb-config-change', "Bad configuration change").
runbook_step('rb-config-change', 1, "List configuration changes to the affected service shortly before the first alert.").
runbook_step('rb-config-change', 2, "Match the changed key to the log symptom, for example pool size and connection wait errors.").
runbook_step('rb-config-change', 3, "Revert the key to its previous value and confirm recovery.").
runbook_step('rb-config-change', 4, "Add review or a guard on the key.").

runbook(schema_drift, 'rb-schema-drift', "Schema drift in a data feed").
runbook_step('rb-schema-drift', 1, "Compare a failing record with the expected schema to find the renamed, added or missing field.").
runbook_step('rb-schema-drift', 2, "Confirm no deploy or config change on the consumer explains the failures.").
runbook_step('rb-schema-drift', 3, "Add a field alias or relax validation; replay the failed batches.").
runbook_step('rb-schema-drift', 4, "Agree a schema-change notice process with the feed owner.").

runbook(capacity_exhaustion, 'rb-capacity', "Capacity exhaustion").
runbook_step('rb-capacity', 1, "Check whether traffic rose and CPU is saturated, with no deploy or config change.").
runbook_step('rb-capacity', 2, "Scale the service out.").
runbook_step('rb-capacity', 3, "Add autoscaling and a load alert.").

% fault_prediction(Fault, Tool, Expectation): what the tool should show if the hypothesis is true
fault_prediction(bad_deploy, recent_deploys, "A deploy to the suspect service lands just before the first alert.").
fault_prediction(bad_deploy, query_logs, "Exception messages that point to the changed code path.").
fault_prediction(slow_query, query_logs, "Slow-query or sequential-scan messages on the database.").
fault_prediction(slow_query, query_metrics, "Database latency and CPU rise first; callers follow.").
fault_prediction(timeout_cascade, service_dependencies, "The deepest degraded dependency is the origin; callers are degraded after it.").
fault_prediction(timeout_cascade, config_diff, "A timeout or retry setting was raised recently.").
fault_prediction(memory_leak, query_metrics, "Memory rises steadily rather than jumping.").
fault_prediction(memory_leak, recent_deploys, "A release shortly before the growth began.").
fault_prediction(config_change, config_diff, "A configuration key on the suspect service changed just before the first alert.").
fault_prediction(config_change, query_logs, "Messages naming the changed resource, for example connection pool exhaustion.").
fault_prediction(schema_drift, query_logs, "Parse or validation errors naming a missing or unexpected field.").
fault_prediction(schema_drift, recent_deploys, "No deploy or config change on the consumer explains the errors.").
fault_prediction(capacity_exhaustion, query_metrics, "CPU is saturated and rises with load.").
fault_prediction(capacity_exhaustion, recent_deploys, "No deploy or config change precedes the incident.").

fault_keyword(bad_deploy, deploy). fault_keyword(bad_deploy, release). fault_keyword(bad_deploy, rollback).
fault_keyword(bad_deploy, exception). fault_keyword(bad_deploy, null). fault_keyword(bad_deploy, version).
fault_keyword(slow_query, query). fault_keyword(slow_query, index). fault_keyword(slow_query, scan).
fault_keyword(slow_query, slow). fault_keyword(slow_query, database). fault_keyword(slow_query, sql).
fault_keyword(timeout_cascade, timeout). fault_keyword(timeout_cascade, retry). fault_keyword(timeout_cascade, upstream).
fault_keyword(timeout_cascade, queue). fault_keyword(timeout_cascade, cascade). fault_keyword(timeout_cascade, hang).
fault_keyword(memory_leak, memory). fault_keyword(memory_leak, heap). fault_keyword(memory_leak, gc).
fault_keyword(memory_leak, oom). fault_keyword(memory_leak, leak). fault_keyword(memory_leak, cache).
fault_keyword(config_change, config). fault_keyword(config_change, pool). fault_keyword(config_change, setting).
fault_keyword(config_change, connection). fault_keyword(config_change, change). fault_keyword(config_change, key).
fault_keyword(schema_drift, schema). fault_keyword(schema_drift, field). fault_keyword(schema_drift, feed).
fault_keyword(schema_drift, parse). fault_keyword(schema_drift, validation). fault_keyword(schema_drift, payload).
fault_keyword(capacity_exhaustion, traffic). fault_keyword(capacity_exhaustion, load). fault_keyword(capacity_exhaustion, scale).
fault_keyword(capacity_exhaustion, capacity). fault_keyword(capacity_exhaustion, cpu). fault_keyword(capacity_exhaustion, saturated).
