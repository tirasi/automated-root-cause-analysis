"""Build a service-agnostic symptom signature for an incident's suspect service.

Metrics come from detector alerts; log symptoms come from `query_logs` evidence when a toolbox is
given (so the signature is traceable to an ev: id), else from log-alert templates."""
from . import metric_symbol


def build_signature(incident, service=None, toolbox=None):
    service = service or incident["suspects"][0]
    alerts = [a for a in incident["alerts"] if a["service"] == service]
    metrics = sorted({metric_symbol(a["signal"], a["direction"]) for a in alerts
                      if a["kind"] == "metric" and a.get("direction")})
    messages, evidence = [], []
    if toolbox is not None:
        start = incident["first_alert_ts"][service] - 120
        res = toolbox.query_logs(service, start, incident["end_ts"] + 600, min_level="WARN")
        evidence.append(res["evidence_id"])
        for c in res["clusters"]:
            messages.extend(c["samples"][:1])
    else:
        messages = [a["detail"] for a in alerts if a["kind"] == "log"]
    return {"service": service, "metrics": metrics, "messages": messages, "evidence_ids": evidence}


def hypotheses_for(kb, incident, service=None, toolbox=None, top_k=4):
    sig = build_signature(incident, service, toolbox)
    ranked = kb.hypotheses(sig["service"], sig["metrics"], sig["messages"], top_k)
    return sig, ranked
