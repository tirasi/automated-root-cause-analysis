import pytest

from copilot.detect import find_incidents
from copilot.detect.templates import cluster, template_of
from copilot.sim.faults import FAULTS


@pytest.mark.parametrize("fault", sorted(FAULTS))
def test_one_incident_with_true_root_ranked_first(make_scenario, fault):
    info = make_scenario(fault)
    incidents = find_incidents(info["db"])
    assert len(incidents) == 1
    inc = incidents[0]
    assert inc["suspects"][0] == info["root_service"]
    assert 0 <= inc["start_ts"] - info["start_ts"] <= 120


def test_no_false_alarms_before_fault(make_scenario):
    info = make_scenario("slow_query")
    assert find_incidents(info["db"], end_ts=info["start_ts"] - 600) == []


def test_template_normalization_and_clustering():
    assert template_of("took 4521ms id=7") == "took <n>ms id=<n>"
    clusters = cluster([(1, "WARN", "x 1"), (5, "WARN", "x 2"), (3, "ERROR", "y 9")])
    assert clusters[0]["count"] == 2 and clusters[0]["first_seen"] == 1 and clusters[0]["last_seen"] == 5


@pytest.mark.parametrize("seed", range(6))
@pytest.mark.parametrize("fault", sorted(FAULTS))
def test_root_found_across_seeds(make_scenario, fault, seed):
    """A victim's log alert can land seconds before the root's metric alert; the root must still win."""
    info = make_scenario(fault, seed=seed)
    incidents = find_incidents(info["db"])
    assert len(incidents) == 1
    assert incidents[0]["suspects"][0] == info["root_service"]
