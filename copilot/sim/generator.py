"""Deterministic telemetry generator with a single injected fault."""
import random

from ..config import BASELINES, DEPENDENCIES, HISTORY_TICKS, METRICS, SERVICES, TICK_SECONDS
from ..store import init_db
from .faults import BACKGROUND_LOGS, FAULTS

BASE_TS = 1_760_000_000
FAULT_START_TICK = 120
CASCADE_METRICS = ("latency_ms", "error_rate")


def tick_ts(tick):
    return BASE_TS + tick * TICK_SECONDS


def callers_of(root):
    """Map each transitive caller of `root` to its hop distance."""
    hops, frontier, seen = {}, [root], {root}
    dist = 0
    while frontier:
        dist += 1
        nxt = []
        for svc in SERVICES:
            if svc in seen:
                continue
            if any(dep in frontier for dep in DEPENDENCIES[svc]):
                hops[svc] = dist
                seen.add(svc)
                nxt.append(svc)
        frontier = nxt
    return hops


def _effect(kind, magnitude, tick, start):
    if tick < start:
        return 0.0
    if kind == "step":
        return magnitude
    span = max(1, HISTORY_TICKS - start)
    return magnitude * (tick - start) / span


def _fmt(template, rng):
    return template.format(n=rng.randint(100, 9999))


def generate(fault_type, root=None, seed=0, db_path=None, scenario=None):
    spec = FAULTS[fault_type]
    root = root or spec["default_root"]
    rng = random.Random(f"{fault_type}:{root}:{seed}")
    scenario = scenario or f"{fault_type}-{root}-{seed}"
    start = FAULT_START_TICK
    hops = callers_of(root)

    metrics, logs = [], []
    for tick in range(HISTORY_TICKS):
        ts = tick_ts(tick)
        for svc in SERVICES:
            for metric in METRICS:
                mean, std = BASELINES[svc][metric]
                value = rng.gauss(mean, std)
                if svc == root and metric in spec["effects"]:
                    kind, mag = spec["effects"][metric]
                    value += _effect(kind, mag, tick, start)
                elif svc in hops and metric in CASCADE_METRICS and metric in spec["effects"]:
                    kind, mag = spec["effects"][metric]
                    h = hops[svc]
                    value += _effect(kind, mag * (0.5 ** h), tick, start + h)
                value = max(0.0, value)
                if metric == "error_rate":
                    value = min(100.0, value)
                metrics.append((ts, svc, metric, round(value, 3)))
            for _ in range(2):
                level, tmpl = rng.choice(BACKGROUND_LOGS)
                logs.append((ts + rng.randint(0, 59), svc, level, _fmt(tmpl, rng)))
        if tick % 37 == 5:  # benign distractor noise
            svc = rng.choice(SERVICES)
            logs.append((ts, svc, "WARN", "transient network blip, retry succeeded attempt=2"))
        if tick >= start:
            for _ in range(3):
                level, tmpl = rng.choice(spec["error_logs"])
                logs.append((ts + rng.randint(0, 59), root, level, _fmt(tmpl, rng)))
            for svc, h in hops.items():
                if tick >= start + h:
                    logs.append((ts + rng.randint(0, 59), svc, "ERROR",
                                 f"upstream {root} error status=503 duration_ms={rng.randint(500, 5000)}"))

    deploys = [(tick_ts(60), "api", "v3.2.1", "Bumped logging library; no behaviour change")]
    configs = [(tick_ts(75), "worker", "log.level", "INFO", "DEBUG", "bob@corp")]
    if spec["deploy"]:
        d = spec["deploy"]
        deploys.append((tick_ts(start + d["offset"]), root, d["version"], d["diff"]))
    if spec["config"]:
        c = spec["config"]
        configs.append((tick_ts(start + c["offset"]), root, c["key"], c["old"], c["new"], c["by"]))

    conn = init_db(db_path)
    conn.executemany("INSERT INTO metrics VALUES (?,?,?,?)", metrics)
    conn.executemany("INSERT INTO logs VALUES (?,?,?,?)", logs)
    conn.executemany("INSERT INTO deploys VALUES (?,?,?,?)", deploys)
    conn.executemany("INSERT INTO config_changes VALUES (?,?,?,?,?,?)", configs)
    conn.execute("INSERT INTO ground_truth VALUES (?,?,?,?,?)",
                 (scenario, fault_type, root, tick_ts(start), spec["description"]))
    conn.commit()
    conn.close()
    return {"scenario": scenario, "fault_type": fault_type, "root_service": root,
            "start_ts": tick_ts(start), "base_ts": BASE_TS, "end_ts": tick_ts(HISTORY_TICKS - 1)}
