"""Group alerts into incidents (one per cascade) using time proximity and the dependency graph."""
from ..config import DEPENDENCIES, SERVICES

WINDOW = 1800  # seconds: an alert joins an incident if it lands within this of the latest alert (weak victims alert late)
TOLERANCE = 180  # seconds: alerts this close to the very first one count as "at the same time"


def _depth(service, memo=None):
    """Depth of a service in the call graph; leaf dependencies (db) have depth 0."""
    memo = memo if memo is not None else {}
    if service not in memo:
        deps = DEPENDENCIES[service]
        memo[service] = 0 if not deps else 1 + max(_depth(d, memo) for d in deps)
    return memo[service]


def _upstream(service):
    """Every service `service` depends on, directly or through others."""
    out, stack = set(), list(DEPENDENCIES[service])
    while stack:
        d = stack.pop()
        if d not in out:
            out.add(d)
            stack.extend(DEPENDENCIES[d])
    return out


def rank_suspects(first):
    """first: service -> time of its first alert. Earliest alert wins, but alerts within TOLERANCE of
    the first one are treated as simultaneous (a victim's log line can beat the root's metric alert by
    a few seconds). Among those, a service that depends on another early-alerting service may be its
    victim, so only services nobody early depends on are root candidates."""
    order = sorted(first, key=lambda s: (first[s], _depth(s)))
    early = [s for s in order if first[s] - first[order[0]] <= TOLERANCE]
    roots = [s for s in early if not (_upstream(s) & set(early))] or early[:1]
    return roots + [s for s in order if s not in roots]


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
    order = sorted(first, key=lambda s: (first[s], _depth(s)))   # the order services were hit
    suspects = rank_suspects(first)                              # best root-cause candidates first
    max_score = max(a["score"] for a in g["alerts"])
    return {"id": f"inc-{g['start_ts']}", "start_ts": g["start_ts"], "end_ts": g["end_ts"],
            "services": order, "first_alert_ts": first, "suspects": suspects,
            "severity": "high" if len(first) >= 3 or max_score >= 50 else "medium",
            "alerts": g["alerts"]}
