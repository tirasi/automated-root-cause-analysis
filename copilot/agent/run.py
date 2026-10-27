"""One-call entry point: investigate(db_path) runs the whole graph and returns the final state.

`approver` decides the human-approval step:
  "auto"    approve automatically (tests, evaluation)
  "reject"  reject automatically
  callable  called with the question payload, must return {"approved": bool, "by": str}
`emit` (optional) receives one small dict per finished step; the API turns these into a live stream."""
import uuid

from langgraph.types import Command

from ..detect import find_incidents
from ..kb import KnowledgeBase
from ..tools.toolbox import Toolbox
from .graph import build_graph
from .llm import get_llm
from .nodes import Nodes


def _decide(approver, payload):
    if approver == "auto":
        return {"approved": True, "by": "auto-approver"}
    if approver == "reject":
        return {"approved": False, "by": "auto-reject"}
    return approver(payload)


def investigate(db_path, *, incident=None, kb=None, llm=None, approver="auto", emit=None, thread_id=None):
    kb = kb or KnowledgeBase()
    emit = emit or (lambda event: None)
    if incident is None:
        found = find_incidents(db_path)
        if not found:
            emit({"type": "done", "status": "no_incident"})
            return {"status": "no_incident"}
        incident = found[0]
    toolbox = Toolbox(db_path, kb=kb)
    graph = build_graph(Nodes(kb, toolbox, llm or get_llm()))
    config = {"configurable": {"thread_id": thread_id or uuid.uuid4().hex}}
    emit({"type": "start", "incident_id": incident["id"]})
    inp = {"incident": incident}
    try:
        while True:
            pending = None
            for chunk in graph.stream(inp, config, stream_mode="updates"):
                for node, update in chunk.items():
                    if node == "__interrupt__":
                        pending = update[0].value
                        emit({"type": "approval_required", "payload": pending})
                    else:
                        emit({"type": "step", "node": node, "trace": (update or {}).get("trace", [])})
            if pending is None:
                break
            decision = _decide(approver, pending)
            emit({"type": "decision", "decision": decision})
            inp = Command(resume=decision)
        final = dict(graph.get_state(config).values)
    finally:
        toolbox.conn.close()
    emit({"type": "done", "status": final["report"]["status"], "report": final["report"]})
    return final
