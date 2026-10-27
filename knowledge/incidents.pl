% Past incidents (synthetic postmortems). Symptoms are service-agnostic so precedents transfer
% across services. Ids are cited in reports as kb:<id>.
:- multifile past_incident/5, incident_symptom/2.
:- dynamic past_incident/5, incident_symptom/2.

% past_incident(id, fault, services, error, fix)- this is the relation

past_incident('pm-001', bad_deploy, api,
  "Release v1.9 removed a null guard; checkout requests started failing within minutes of the deploy.",
  "Rolled back to v1.8; added a regression test.").
incident_symptom('pm-001', metric(error_rate, up)).
incident_symptom('pm-001', metric(latency_ms, up)).
incident_symptom('pm-001', log(null_pointer)).

past_incident('pm-002', bad_deploy, worker,
  "A refactor of the batch handler dereferenced a missing field; most jobs raised exceptions after rollout.",
  "Reverted the release; patched the handler.").
incident_symptom('pm-002', metric(error_rate, up)).
incident_symptom('pm-002', log(null_pointer)).

past_incident('pm-003', slow_query, db,
  "A new report query ran a sequential scan on a large table; latency and CPU rose on the database.",
  "Added the missing index; killed the long-running sessions.").
incident_symptom('pm-003', metric(latency_ms, up)).
incident_symptom('pm-003', metric(cpu_pct, up)).
incident_symptom('pm-003', log(slow_query)).
incident_symptom('pm-003', log(seq_scan)).

past_incident('pm-004', slow_query, db,
  "A dropped index after a migration made a hot lookup slow; callers saw rising latency.",
  "Recreated the index.").
incident_symptom('pm-004', metric(latency_ms, up)).
incident_symptom('pm-004', log(slow_query)).

past_incident('pm-005', timeout_cascade, orders,
  "A stalled dependency made calls hang until the long timeout; threads piled up and errors followed.",
  "Restored the dependency; reset the timeout to its safe value.").
incident_symptom('pm-005', metric(latency_ms, up)).
incident_symptom('pm-005', metric(error_rate, up)).
incident_symptom('pm-005', log(upstream_timeout)).

past_incident('pm-006', timeout_cascade, api,
  "Retries against a slow service amplified load; the request queue backed up and load shedding began.",
  "Capped retries; added a circuit breaker.").
incident_symptom('pm-006', metric(latency_ms, up)).
incident_symptom('pm-006', metric(error_rate, up)).
incident_symptom('pm-006', log(upstream_timeout)).
incident_symptom('pm-006', log(queue_backlog)).

past_incident('pm-007', memory_leak, orders,
  "An unbounded in-memory cache grew steadily until the process was killed by the OOM handler.",
  "Restarted the service; added a size limit and TTL to the cache.").
incident_symptom('pm-007', metric(mem_mb, up)).
incident_symptom('pm-007', metric(cpu_pct, up)).
incident_symptom('pm-007', log(gc_pressure)).
incident_symptom('pm-007', log(oom)).

past_incident('pm-008', memory_leak, api,
  "Session objects were never released; heap usage rose for hours and GC pauses grew.",
  "Fixed the session cleanup; restarted pods.").
incident_symptom('pm-008', metric(mem_mb, up)).
incident_symptom('pm-008', log(gc_pressure)).

past_incident('pm-009', config_change, worker,
  "An automated tuning job cut the database pool size; workers waited for connections and jobs failed.",
  "Reverted the pool size; locked the key against auto-tuning.").
incident_symptom('pm-009', metric(latency_ms, up)).
incident_symptom('pm-009', metric(error_rate, up)).
incident_symptom('pm-009', log(pool_exhausted)).
incident_symptom('pm-009', log(db_wait_timeout)).

past_incident('pm-010', config_change, api,
  "A manual edit lowered the connection pool maximum; requests queued for a free connection.",
  "Reverted the change; added review for config edits.").
incident_symptom('pm-010', metric(latency_ms, up)).
incident_symptom('pm-010', log(pool_exhausted)).

past_incident('pm-011', schema_drift, orders,
  "A partner feed renamed a field without notice; parsing failed for every record.",
  "Added a field alias; agreed a schema-change notice with the partner.").
incident_symptom('pm-011', metric(error_rate, up)).
incident_symptom('pm-011', log(schema_mismatch)).

past_incident('pm-012', schema_drift, worker,
  "The upstream export added a new required field; strict validation rejected whole batches.",
  "Relaxed validation for unknown fields; versioned the schema.").
incident_symptom('pm-012', metric(error_rate, up)).
incident_symptom('pm-012', log(schema_mismatch)).

% TRAP precedent: looks like a deploy or config problem (latency and errors both up) but the cause
% was plain load. Evidence for a recent change must be found before anyone trusts this one.
past_incident('pm-013', capacity_exhaustion, orders,
  "A marketing campaign tripled traffic; CPU saturated and both latency and errors rose with no change shipped.",
  "Scaled out the service; added autoscaling.").
incident_symptom('pm-013', metric(latency_ms, up)).
incident_symptom('pm-013', metric(error_rate, up)).
incident_symptom('pm-013', metric(cpu_pct, up)).
