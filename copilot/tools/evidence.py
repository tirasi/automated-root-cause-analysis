"""Evidence registry. Every tool result is stored under an `ev:NNN` id so later
claims can cite it and a verifier can check the citation exists."""
import json
class EvidenceStore:
    def __init__(self):
        self._items = {}

    def add(self, tool, args, result):
        eid = f"ev:{len(self._items) + 1:03d}"
        self._items[eid] = {"id": eid, "tool": tool, "args": args, "result": result}
        return eid

    def get(self, eid):
        return self._items.get(eid)

    def __contains__(self, eid):
        return eid in self._items

    def all(self):
        return list(self._items.values())

    def dumps(self):
        return json.dumps(self.all(), indent=2, default=str)
