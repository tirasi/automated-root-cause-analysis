import copy
import pathlib
import shutil

import pytest

from copilot.agent.learn import learn_from_resolution
from copilot.agent.llm import LLMError, MockLLM
from copilot.agent.run import investigate
from copilot.agent.verify import unsupported_tokens, verify_report
from copilot.detect import find_incidents
from copilot.kb import KB_DIR, KBUnavailable, KnowledgeBase, find_swipl
from copilot.sim.faults import KNOWN_FAULTS
from copilot.sim.generator import generate
from copilot.tools.evidence import EvidenceStore

try:
    find_swipl()
except KBUnavailable:
    pytest.skip("SWI-Prolog not installed", allow_module_level=True)


@pytest.fixture(scope="module")
def kb():
    return KnowledgeBase()


@pytest.mark.parametrize("fault", KNOWN_FAULTS)
def test_known_fault_is_diagnosed_verified_and_approved(make_scenario, kb, fault):
    info = make_scenario(fault)
    final = investigate(info["db"], kb=kb)
    rc = final["report"]["root_cause"]
    assert rc["fault"] == fault and rc["service"] == info["root_service"]
    assert final["report"]["status"] == "verified" and final["verification"]["ok"]
    assert final["confidence"] >= 0.55 and not final["unknown"]
    assert final["approved"] and final["report"]["recommended_actions"][0]["status"] == "approved"
    assert any(f["stance"] == "supports" for f in final["report"]["findings"])


def test_steps_run_in_order(make_scenario, kb):
    final = investigate(make_scenario("bad_deploy")["db"], kb=kb)
    names = [line.split(":")[0] for line in final["trace"]]
    assert names == ["triage", "hypothesize", "gather_evidence", "score", "critic", "propose_fix",
                     "approval_gate", "postmortem", "verify"]


def test_unknown_fault_says_so_and_does_not_guess(make_scenario, kb):
    final = investigate(make_scenario("disk_full")["db"], kb=kb)
    r = final["report"]
    assert final["unknown"] and r["root_cause"]["fault"] is None
    assert r["status"] == "verified"
    assert r["recommended_actions"] == [] and "approval_gate" not in " ".join(final["trace"])
    assert r["open_questions"] and any("No space left" in f["claim"] for f in r["findings"])
    assert r["root_cause"]["service"] == "db"   # first failing service is still reported


def test_rejected_fix_is_recorded(make_scenario, kb):
    final = investigate(make_scenario("slow_query")["db"], kb=kb, approver="reject")
    assert not final["approved"]
    assert final["report"]["recommended_actions"][0]["status"] == "rejected by reviewer"


def test_custom_approver_receives_the_question(make_scenario, kb):
    seen = {}

    def approver(payload):
        seen.update(payload)
        return {"approved": True, "by": "ritu"}
    final = investigate(make_scenario("schema_drift")["db"], kb=kb, approver=approver)
    assert seen["fault"] == "schema_drift" and seen["steps"] and final["approver"] == "ritu"


def test_events_are_emitted_for_streaming(make_scenario, kb):
    events = []
    investigate(make_scenario("memory_leak")["db"], kb=kb, emit=events.append)
    kinds = [e["type"] for e in events]
    assert kinds[0] == "start" and kinds[-1] == "done" and "approval_required" in kinds
    assert [e["node"] for e in events if e["type"] == "step"][:2] == ["triage", "hypothesize"]


def test_no_incident_is_reported_not_crashed(tmp_path, kb):
    from copilot.store import init_db
    db = tmp_path / "empty.db"
    init_db(db).close()
    assert investigate(str(db), kb=kb)["status"] == "no_incident"


# ---------- the LLM may only change wording, never facts ----------
class LyingLLM:
    name = "liar"

    def complete(self, prompt):
        return "The root cause is clearly a meteor strike [ev:999] with 77777 errors at 03:33."


class DeadLLM:
    name = "dead"

    def complete(self, prompt):
        raise LLMError("server down")


def test_hallucinating_llm_is_caught_and_replaced(make_scenario, kb):
    final = investigate(make_scenario("config_change")["db"], kb=kb, llm=LyingLLM())
    r = final["report"]
    assert r["status"] == "verified" and r["meta"]["summary_replaced"]
    assert "meteor" not in r["summary"] and "ev:999" not in r["summary"]


def test_dead_llm_falls_back_to_plain_text(make_scenario, kb):
    final = investigate(make_scenario("config_change")["db"], kb=kb, llm=DeadLLM())
    assert final["report"]["status"] == "verified" and final["report"]["meta"]["llm_fell_back"]


# ---------- verifier on its own ----------
@pytest.fixture
def good(make_scenario, kb):
    final = investigate(make_scenario("bad_deploy")["db"], kb=kb)
    return final["report"], final


def _store_from(final):
    store = EvidenceStore()
    for e in final["evidence"]:
        store._items[e["id"]] = e
    return store


def test_verifier_accepts_a_good_report(good):
    report, final = good
    assert verify_report(report, _store_from(final))["ok"]


def test_verifier_rejects_fake_citation(good):
    report, final = good
    bad = copy.deepcopy(report)
    bad["findings"][1]["cites"] = ["ev:777"]
    out = verify_report(bad, _store_from(final))
    assert not out["ok"] and out["problems"][0]["issue"] == "unknown_citation"


def test_verifier_rejects_uncited_claim(good):
    report, final = good
    bad = copy.deepcopy(report)
    bad["findings"][1]["cites"] = []
    assert verify_report(bad, _store_from(final))["problems"][0]["issue"] == "uncited"


def test_verifier_rejects_number_not_in_evidence(good):
    report, final = good
    bad = copy.deepcopy(report)
    bad["findings"][-1]["claim"] = bad["findings"][-1]["claim"] + " with 9876.5 errors"
    out = verify_report(bad, _store_from(final))
    assert any(p["issue"] == "unsupported_value" for p in out["problems"])


def test_verifier_rejects_root_cause_without_support(good):
    report, final = good
    bad = copy.deepcopy(report)
    for f in bad["findings"]:
        f["stance"] = "context"
    assert any(p["issue"] == "no_supporting_evidence" for p in verify_report(bad, _store_from(final))["problems"])


def test_token_check_handles_times_versions_and_numbers():
    items = [{"id": "ev:001", "tool": "t", "args": {}, "result": {"ts": 1760007200, "v": "v2.14.0", "z": 9.13}}]
    assert unsupported_tokens("deploy v2.14.0 at 10:53 z=9.13", items) == []
    assert unsupported_tokens("deploy v9.9.9 at 11:53 z=77", items) == ["11:53", "v9.9.9", "77"]


# ---------- learning loop ----------
def test_a_labelled_unknown_fault_is_recognised_next_time(tmp_path):
    copy_dir = tmp_path / "knowledge"
    shutil.copytree(KB_DIR, copy_dir, ignore=shutil.ignore_patterns("learned.pl"))
    kb = KnowledgeBase(kb_dir=copy_dir)
    db = str(tmp_path / "a.db")
    generate("disk_full", seed=0, db_path=db)
    first = investigate(db, kb=kb)
    assert first["unknown"]
    new_id = learn_from_resolution(
        kb, first, "disk_full", "db", "Freed disk space and added a disk-usage alert.",
        steps=["Check free space on the database volume.", "Remove old logs or expand the volume.",
               "Add a disk usage alert."], log_keywords=["no space left on device"])
    assert new_id.startswith("kb:pm-")
    db2 = str(tmp_path / "b.db")
    generate("disk_full", seed=1, db_path=db2)
    second = investigate(db2, kb=kb)
    rc = second["report"]["root_cause"]
    assert rc["fault"] == "disk_full" and second["report"]["status"] == "verified"
    assert rc["unconfirmed"] and any("past incidents" in c for c in second["report"]["caveats"])
    assert second["proposed_fix"]["steps"][0].startswith("Check free space")


# ---------- the investigation never sees the answer key ----------
def test_investigation_code_never_reads_ground_truth():
    root = pathlib.Path(__file__).resolve().parent.parent / "copilot"
    for pkg in ("agent", "kb", "tools", "detect"):
        for path in (root / pkg).rglob("*.py"):
            assert "ground_truth" not in path.read_text(), path
