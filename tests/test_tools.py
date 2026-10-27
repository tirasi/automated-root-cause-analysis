from copilot.tools.toolbox import Toolbox


def test_evidence_ids_are_sequential_and_resolvable(make_scenario):
    info = make_scenario("bad_deploy")
    tb = Toolbox(info["db"])
    s, e = info["start_ts"], info["end_ts"]
    ids = [tb.query_logs("orders", s, e)["evidence_id"],
           tb.query_metrics("orders", "error_rate", s, e)["evidence_id"]]
    assert ids == ["ev:001", "ev:002"]
    assert all(i in tb.evidence for i in ids) and "ev:999" not in tb.evidence


def test_metrics_flag_change_point_at_fault_start(make_scenario):
    info = make_scenario("bad_deploy")
    r = Toolbox(info["db"]).query_metrics("orders", "error_rate", info["start_ts"], info["end_ts"])
    assert r["window_z_vs_baseline"] > 10
    assert r["change_point_ts"] == info["start_ts"]


def test_logs_surface_fault_template_first(make_scenario):
    info = make_scenario("slow_query")
    r = Toolbox(info["db"]).query_logs("db", info["start_ts"], info["end_ts"])
    assert any("slow query" in c["template"] or "sequential scan" in c["template"] for c in r["clusters"][:2])


def test_deploy_and_config_records_visible(make_scenario):
    bd = make_scenario("bad_deploy")
    d = Toolbox(bd["db"]).recent_deploys(bd["start_ts"] - 3600, bd["end_ts"], services=["orders"])
    assert d["deploys"][0]["version"] == "v2.14.0"
    cc = make_scenario("config_change")
    c = Toolbox(cc["db"]).config_diff(cc["start_ts"] - 3600, cc["end_ts"], service="orders")
    assert c["changes"][0]["key"] == "db.pool_size" and c["changes"][0]["new_value"] == "5"


def test_dependencies_separate_cause_from_cascade(make_scenario):
    info = make_scenario("slow_query")
    r = Toolbox(info["db"]).service_dependencies("orders", info["start_ts"] + 900)
    assert r["upstream_dependencies"]["db"]["status"] == "degraded"
    assert r["downstream_callers"]["api"]["status"] == "degraded"


def test_query_metrics_tells_a_ramp_from_a_step(make_scenario):
    leak = make_scenario("memory_leak")
    slow = make_scenario("slow_query")
    t0, t1 = leak["start_ts"] - 600, leak["end_ts"]
    assert Toolbox(leak["db"]).query_metrics("worker", "mem_mb", t0, t1)["shape"] == "ramp"
    assert Toolbox(slow["db"]).query_metrics("db", "latency_ms", t0, t1)["shape"] == "step"
    assert Toolbox(slow["db"]).query_metrics("api", "mem_mb", t0, t1)["shape"] == "flat"


def test_search_runbooks_returns_kb_ids_and_is_not_evidence(make_scenario):
    import pytest
    from copilot.kb import KBUnavailable, KnowledgeBase
    try:
        kb = KnowledgeBase()
    except KBUnavailable:
        pytest.skip("SWI-Prolog not installed")
    tb = Toolbox(make_scenario("slow_query")["db"], kb=kb)
    res = tb.search_runbooks("sequential scan on a slow sql query")
    assert res["matches"][0]["fault"] == "slow_query" and res["matches"][0]["kb_id"].startswith("kb:")
    assert "evidence_id" not in res and tb.evidence.all() == []   # knowledge is never evidence
    with pytest.raises(RuntimeError):
        Toolbox(make_scenario("slow_query")["db"]).search_runbooks("x")
