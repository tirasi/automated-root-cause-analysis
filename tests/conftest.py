import pytest

from copilot.sim.generator import generate


@pytest.fixture
def make_scenario(tmp_path):
    def _make(fault, root=None, seed=0):
        db = tmp_path / f"{fault}.db"
        info = generate(fault, root, seed, db_path=db)
        info["db"] = str(db)
        return info
    return _make
