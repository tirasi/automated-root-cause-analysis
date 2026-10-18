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
