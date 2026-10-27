"""The shared notebook every node reads from and writes to.

A node returns ONLY the keys it changed. `trace` has a reducer (operator.add), so a node returns just
its new line(s) and LangGraph appends them."""
import operator
from typing import Annotated, Any, Dict, List, Optional, TypedDict


class InvestigationState(TypedDict, total=False):
    incident: Dict[str, Any]            # one incident dict from find_incidents()
    suspect: str                        # service that alerted first
    detection_ev: str                   # ev: id of the detector output (alerts, first-alert times)
    signature: Dict[str, Any]           # we have to keep this as it contains evidence ids
    hypotheses: List[Dict[str, Any]]    # ranked ideas from the Prolog KB
    checks: List[Dict[str, Any]]        # one result per KB prediction we tested with a tool
    evidence: List[Dict[str, Any]]      # every ev: item gathered so far
    scores: Dict[str, float]            # fault -> final score (KB match + evidence)
    ranking: List[Dict[str, Any]]       # same, with the parts of the score
    confidence: float                   # final score of the top hypothesis
    margin: float                       # gap between the top two
    confidence_label: str               # high / medium / low
    unknown: bool                       # True when nothing known fits well enough
    critique: str
    critic_flags: List[str]
    generic_findings: List[Dict[str, Any]]   # unknown path: plain facts about what happened
    open_questions: List[str]                # unknown path: where a human should look next
    nearest_known: List[Dict[str, Any]]      # unknown path: runbooks (kb: ids) that share keywords
    proposed_fix: Optional[Dict[str, Any]]
    approved: bool
    approver: str
    report: Dict[str, Any]
    verification: Dict[str, Any]
    trace: Annotated[List[str], operator.add]
