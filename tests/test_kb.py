import shutil

import pytest

from copilot.detect import find_incidents
from copilot.kb import KB_DIR, KBUnavailable, KnowledgeBase, find_swipl, metric_symbol
from copilot.kb.signature import hypotheses_for
from copilot.sim.faults import KNOWN_FAULTS
from copilot.tools.toolbox import Toolbox

try:
    find_swipl()
except KBUnavailable:
    pytest.skip("SWI-Prolog not installed", allow_module_level=True)

ERR_LAT = [metric_symbol("error_rate"), metric_symbol("latency_ms")]


@pytest.fixture(scope="module")
def kb():
    return KnowledgeBase()


def test_log_messages_map_to_tags(kb):
    tags = kb.tag(["NullPointerException in X", "slow query took 9ms", "all good"])
    assert tags == ["null_pointer", "slow_query"]


def test_matching_precedent_ranks_first_and_explains_itself(kb):
    top = kb.hypotheses("orders", ERR_LAT, ["NullPointerException in OrderHandler at line 4"])[0]
    assert top["fault"] == "bad_deploy" and top["score"] == 1.0
    assert top["precedents"][0] in ("kb:pm-001", "kb:pm-002")
    assert "log(null_pointer)" in top["matched"] and top["missing"] == []
    assert top["runbook"] == "kb:rb-bad-deploy" and top["predictions"]


def test_trap_precedent_is_offered_but_ranked_lower(kb):
    ranked = kb.hypotheses("orders", ERR_LAT, ["NullPointerException in OrderHandler at line 4"], top_k=6)
    faults = [h["fault"] for h in ranked]
    assert "capacity_exhaustion" in faults and faults.index("capacity_exhaustion") > 0


def test_fault_must_be_possible_for_the_service(kb):
    sym = [metric_symbol("latency_ms")]
    msgs = ["slow query took 99ms"]
    assert "slow_query" in [h["fault"] for h in kb.hypotheses("db", sym, msgs, top_k=6)]
    assert "slow_query" not in [h["fault"] for h in kb.hypotheses("orders", sym, msgs, top_k=6)]
    schema = [h["fault"] for h in kb.hypotheses("api", [metric_symbol("error_rate")], ["KeyError: 'x'"], top_k=6)]
    assert "schema_drift" not in schema


def test_held_out_precedents_are_not_used():
    held_out = KnowledgeBase(exclude=["pm-003", "pm-004"])
    ranked = held_out.hypotheses("db", [metric_symbol("latency_ms")], ["slow query took 99ms"], top_k=6)
    assert "slow_query" not in [h["fault"] for h in ranked]


def test_runbook_incident_and_search(kb):
    assert len(kb.runbook("config_change")["steps"]) == 4
    assert kb.incident("kb:pm-013")["fault"] == "capacity_exhaustion"
    assert kb.search_runbooks("connection pool size config change")[0]["fault"] == "config_change"
    assert kb.runbook("no_such_fault") is None


def test_learn_writes_new_precedent_back(tmp_path):
    copy = tmp_path / "knowledge"
    shutil.copytree(KB_DIR, copy, ignore=shutil.ignore_patterns("learned.pl"))
    kb = KnowledgeBase(kb_dir=copy)
    kb.learn("kb:pm-100", "memory_leak", "db", "Test precedent.", "Restarted.",
             [metric_symbol("mem_mb"), "log(oom)"])
    assert kb.incident("kb:pm-100")["root_service"] == "db"
    top = kb.hypotheses("orders", [metric_symbol("mem_mb")], ["OutOfMemoryError: heap"])[0]
    assert top["fault"] == "memory_leak" and top["precedents"][0] == "kb:pm-100"
    # the learned precedent is for a datastore, where a memory leak is not a possible fault here
    assert kb.hypotheses("db", [metric_symbol("mem_mb")], ["OutOfMemoryError: heap"]) == []


@pytest.mark.parametrize("fault", KNOWN_FAULTS)
def test_end_to_end_signature_ranks_true_fault_first(make_scenario, kb, fault):
    info = make_scenario(fault)
    inc = find_incidents(info["db"])[0]
    sig, ranked = hypotheses_for(kb, inc, toolbox=Toolbox(info["db"]))
    assert sig["service"] == info["root_service"] and sig["evidence_ids"]
    assert ranked[0]["fault"] == fault
