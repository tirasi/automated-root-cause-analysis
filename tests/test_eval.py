import pytest

from copilot.eval.run import run_eval, to_markdown
from copilot.kb import KBUnavailable, find_swipl

try:
    find_swipl()
except KBUnavailable:
    pytest.skip("SWI-Prolog not installed", allow_module_level=True)


def test_eval_smoke_agent_beats_baselines_where_it_should():
    s = run_eval(seeds=1)
    assert s["normal"]["agent"]["fault_accuracy"] == 1.0 and s["normal"]["agent"]["root_accuracy"] == 1.0
    assert s["no_logs"]["agent"]["fault_accuracy"] > s["no_logs"]["kb-only"]["fault_accuracy"]
    assert s["held_out"]["agent"]["wrong_confident"] == 0.0
    assert s["held_out"]["kb-only"]["wrong_confident"] > 0.5
    assert s["agent_extra"]["reports_verified"] == 1.0
    assert "Held-out" in to_markdown(s)
