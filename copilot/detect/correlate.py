"""Group alerts into incidents (one per cascade) using time proximity and the dependency graph."""
from ..config import DEPENDENCIES, SERVICES

WINDOW = 600  # seconds: an alert joins an incident if it lands within this of the incident's latest alert


def _depth(service, memo=None):
    """Depth of a service in the call graph; leaf dependencies (db) have depth 0."""
    memo = memo if memo is not None else {}
    if service not in memo:
        deps = DEPENDENCIES[service]
        memo[service] = 0 if not deps else 1 + max(_depth(d, memo) for d in deps)
    return memo[service]


def _connected(a, b):
    """True if two services are linked through the (undirected) dependency graph."""
    adj = {s: set(DEPENDENCIES[s]) for s in SERVICES}
    for s, deps in DEPENDENCIES.items():
        for d in deps:
            adj[d].add(s)
    seen, stack = {a}, [a]
    while stack:
        cur = stack.pop()
        if cur == b:
            return True
        for nxt in adj[cur] - seen:
            seen.add(nxt)
            stack.append(nxt)
    return False


def correlate(alerts, window=WINDOW):
    groups = []
    for alert in sorted(alerts, key=lambda a: a["ts"]):
        for g in groups:
            if alert["ts"] - g["end_ts"] <= window and any(_connected(alert["service"], s) for s in g["services"]):
                g["alerts"].append(alert)
                g["end_ts"] = max(g["end_ts"], alert["ts"])
                g["services"].add(alert["service"])
                break
        else:
            groups.append({"alerts": [alert], "start_ts": alert["ts"], "end_ts": alert["ts"],
                           "services": {alert["service"]}})
    return [_finalize(g) for g in groups]


def _finalize(g):
    first = {}
    for a in g["alerts"]:
        first.setdefault(a["service"], a["ts"])
    # heuristic suspects: earliest alert first; ties go to the deeper dependency (closer to the leaf)
    suspects = sorted(first, key=lambda s: (first[s], _depth(s)))
    max_score = max(a["score"] for a in g["alerts"])
    return {"id": f"inc-{g['start_ts']}", "start_ts": g["start_ts"], "end_ts": g["end_ts"],
            "services": suspects, "first_alert_ts": first, "suspects": suspects,
            "severity": "high" if len(first) >= 3 or max_score >= 50 else "medium",
            "alerts": g["alerts"]}
