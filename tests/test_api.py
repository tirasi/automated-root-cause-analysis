import json
import shutil
import time

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient

from copilot.api.app import create_app
from copilot.kb import KB_DIR, KBUnavailable, KnowledgeBase, find_swipl

try:
    find_swipl()
except KBUnavailable:
    pytest.skip("SWI-Prolog not installed", allow_module_level=True)


@pytest.fixture
def client(tmp_path):
    # the API can teach the KB, so tests use a private copy: the real knowledge/ folder must stay untouched
    kb_dir = tmp_path / "knowledge"
    shutil.copytree(KB_DIR, kb_dir, ignore=shutil.ignore_patterns("learned.pl"))
    return TestClient(create_app(kb=KnowledgeBase(kb_dir=kb_dir), data_dir=tmp_path))


def sse_events(client, job_id):
    out, name = [], None
    with client.stream("GET", f"/investigations/{job_id}/events") as resp:
        assert resp.headers["content-type"].startswith("text/event-stream")
        for line in resp.iter_lines():
            if line.startswith("event:"):
                name = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                out.append((name, json.loads(line.split(":", 1)[1])))
    return out


def wait_for(client, job_id, status, tries=100):
    for _ in range(tries):
        body = client.get(f"/investigations/{job_id}").json()
        if body["status"] == status:
            return body
        time.sleep(0.1)
    raise AssertionError(f"never reached {status}: {body['status']}")


def test_health_and_faults(client):
    assert client.get("/health").json()["ok"]
    assert "disk_full" in client.get("/faults").json()["faults"]


def test_auto_approved_run_streams_every_step_then_done(client):
    job = client.post("/investigations", json={"fault": "slow_query", "auto_approve": True}).json()["id"]
    events = sse_events(client, job)
    kinds = [k for k, _ in events]
    assert kinds[0] == "start" and kinds[-1] == "done"
    steps = [d["node"] for k, d in events if k == "step"]
    assert steps[:3] == ["triage", "hypothesize", "gather_evidence"] and steps[-1] == "verify"
    body = client.get(f"/investigations/{job}").json()
    assert body["status"] == "done" and body["report"]["root_cause"]["fault"] == "slow_query"


def test_run_waits_for_a_human_and_applies_the_answer(client):
    job = client.post("/investigations", json={"fault": "bad_deploy"}).json()["id"]
    waiting = wait_for(client, job, "awaiting_approval")
    assert waiting["pending_approval"]["fault"] == "bad_deploy" and waiting["report"] is None
    assert client.post(f"/investigations/{job}/approval", json={"approved": False, "by": "ritu"}).status_code == 200
    done = wait_for(client, job, "done")
    assert done["report"]["recommended_actions"][0]["status"] == "rejected by reviewer"
    # answering again is refused
    assert client.post(f"/investigations/{job}/approval", json={"approved": True}).status_code == 409


def test_unknown_fault_needs_no_approval_and_can_be_labelled(client):
    job = client.post("/investigations", json={"fault": "disk_full"}).json()["id"]
    done = wait_for(client, job, "done")
    assert done["report"]["root_cause"]["fault"] is None
    label = {"fault": "disk_full", "root_service": "db", "resolution": "Expanded the volume.",
             "steps": ["Check free space.", "Expand the volume."], "log_keywords": ["no space left on device"]}
    assert client.post(f"/investigations/{job}/label", json=label).json()["learned"].startswith("kb:pm-")


def test_bad_requests_are_rejected(client):
    assert client.post("/investigations", json={}).status_code == 400
    assert client.post("/investigations", json={"fault": "nope"}).status_code == 400
    assert client.post("/investigations", json={"db_path": "/etc/passwd"}).status_code == 400
    assert client.get("/investigations/missing").status_code == 404
