"""Log template extraction: collapse variable numbers so similar lines cluster."""
import re
from collections import defaultdict

_NUM = re.compile(r"\d+")
LEVEL_RANK = {"DEBUG": 0, "INFO": 1, "WARN": 2, "ERROR": 3}


def template_of(message):
    return _NUM.sub("<n>", message)


def cluster(rows):
    """rows: iterable of (ts, level, message). Returns clusters sorted by count desc."""
    groups = defaultdict(list)
    for ts, level, msg in rows:
        groups[(template_of(msg), level)].append((ts, msg))
    out = []
    for (tmpl, level), items in groups.items():
        items.sort()
        out.append({
            "template": tmpl, "level": level, "count": len(items),
            "first_seen": items[0][0], "last_seen": items[-1][0],
            "samples": [m for _, m in items[:2]],
        })
    out.sort(key=lambda c: (-c["count"], c["template"]))
    return out
