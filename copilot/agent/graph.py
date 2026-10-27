"""Wires the nodes into the flowchart.

  START -> triage -> hypothesize -> gather_evidence -> score -> critic -+-> propose_fix -> approval_gate -+
                                                                        |                                 |
                                                                        +-> survey_unknown ---------------+-> postmortem -> verify -> END
The branch after `critic` is the unknown-fault path: when no known pattern fits, skip the fix and
approval, and report plain findings and open questions instead."""
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from .nodes import route_after_critic
from .state import InvestigationState

STEPS = ["triage", "hypothesize", "gather_evidence", "score", "critic"]


def build_graph(nodes, checkpointer=None):
    g = StateGraph(InvestigationState)
    for name in STEPS + ["propose_fix", "approval_gate", "survey_unknown", "postmortem", "verify"]:
        g.add_node(name, getattr(nodes, name))
    g.add_edge(START, STEPS[0])
    for a, b in zip(STEPS, STEPS[1:]):
        g.add_edge(a, b)
    g.add_conditional_edges("critic", route_after_critic,
                            {"propose_fix": "propose_fix", "survey_unknown": "survey_unknown"})
    g.add_edge("propose_fix", "approval_gate")
    g.add_edge("approval_gate", "postmortem")
    g.add_edge("survey_unknown", "postmortem")
    g.add_edge("postmortem", "verify")
    g.add_edge("verify", END)
    # the approval gate pauses the run, so the graph needs somewhere to keep its state meanwhile
    return g.compile(checkpointer=checkpointer or MemorySaver())
