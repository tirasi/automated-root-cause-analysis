% Incident Copilot knowledge base: reasoning rules.
% Facts live in incidents.pl, runbooks.pl and (runtime) learned.pl.
% Retrieval is symbolic: a live incident signature is matched against past incidents by shared
% symptoms; every result says which symptoms matched and which did not.

:- multifile past_incident/5, incident_symptom/2.
:- dynamic past_incident/5, incident_symptom/2.
:- dynamic excluded/1.

% ---------- service model ----------
service_kind(api, gateway).
service_kind(orders, app).
service_kind(worker, app).
service_kind(worker, consumer).
service_kind(db, datastore).

% fault_applies(Fault, ServiceKind): constrains which services a fault can originate in
fault_applies(bad_deploy, gateway).
fault_applies(bad_deploy, app).
fault_applies(slow_query, datastore).
fault_applies(timeout_cascade, gateway).
fault_applies(timeout_cascade, app).
fault_applies(memory_leak, gateway).
fault_applies(memory_leak, app).
fault_applies(config_change, gateway).
fault_applies(config_change, app).
fault_applies(config_change, datastore).
fault_applies(schema_drift, consumer).
fault_applies(capacity_exhaustion, gateway).
fault_applies(capacity_exhaustion, app).

applicable(_, any) :- !.
applicable(Fault, Service) :- service_kind(Service, Kind), fault_applies(Fault, Kind), !.

% ---------- log message -> symptom tag ----------
log_tag(null_pointer, "nullpointerexception").
log_tag(null_pointer, "nonetype has no attribute").
log_tag(slow_query, "slow query").
log_tag(seq_scan, "sequential scan").
log_tag(upstream_timeout, "upstream timeout").
log_tag(queue_backlog, "queue depth").
log_tag(gc_pressure, "gc pause").
log_tag(oom, "outofmemoryerror").
log_tag(pool_exhausted, "connection pool exhausted").
log_tag(db_wait_timeout, "waiting for db connection").
log_tag(schema_mismatch, "keyerror").
log_tag(schema_mismatch, "schema validation").

message_tag(Msg, Tag) :-
    string_lower(Msg, Lower),
    log_tag(Tag, Pattern),
    sub_string(Lower, _, _, _, Pattern).

tags_of(Msgs, Tags) :-
    findall(T, (member(M, Msgs), message_tag(M, T)), Ts),
    sort(Ts, Tags).

% ---------- scoring ----------
sym_weight(metric(_, _), 1).
sym_weight(log(_), 2).     % log patterns are more specific than metric shifts

weight_sum([], 0).
weight_sum([S|T], W) :- sym_weight(S, W0), weight_sum(T, W1), W is W0 + W1.

incident_symptoms(Id, Syms) :- findall(S, incident_symptom(Id, S), Syms).

% match_incident(+Live, +PastId, -Score, -Matched, -Missing)
% Score = weight(matched) / (weight(past symptoms) + 0.5 * weight(live symptoms the past case lacked))
match_incident(Live, Id, Score, Matched, Missing) :-
    incident_symptoms(Id, Past),
    intersection(Past, Live, Matched),
    subtract(Past, Live, Missing),
    subtract(Live, Past, Extra),
    weight_sum(Matched, WM), weight_sum(Past, WP), weight_sum(Extra, WE),
    Denom is WP + 0.5 * WE,
    ( Denom =:= 0 -> Score = 0.0 ; Score is WM / Denom ).

fault(F) :- runbook(F, _, _).

% hypothesis(+Service, +Live, ?Fault, -Score, -Ids, -Matched, -Missing)
% Best-matching precedent sets the score; each further supporting precedent adds 0.05 (max 2).
hypothesis(Service, Live, Fault, Score, Ids, Matched, Missing) :-
    fault(Fault),
    applicable(Fault, Service),
    findall(S-Id-M-Mi,
            ( past_incident(Id, Fault, _, _, _), \+ excluded(Id),
              match_incident(Live, Id, S, M, Mi), S > 0 ),
            Rows),
    Rows \== [],
    sort(0, @>=, Rows, [Best-_-Matched-Missing|Rest]),
    sort(0, @>=, Rows, Sorted),
    findall(I, member(_-I-_-_, Sorted), Ids),
    length(Rest, NR),
    Score is min(1.0, Best + min(NR, 2) * 0.05).
