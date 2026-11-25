"""supply_level_monitor: risk level from weekly-supply-check.json."""
import tempfile

from aios.core import supply_level_monitor


def test_missing_file_no_risk():
    r = supply_level_monitor.supply_check("/nope/missing.json")
    assert r["missing"] is True and r["risk"] is False


def test_level_0_1_no_risk_level_2_risk():
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
        fh.write('{"supply_level": 0}')
        p0 = fh.name
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
        fh.write('{"supply_level": 2}')
        p2 = fh.name
    assert supply_level_monitor.supply_check(p0)["risk"] is False
    assert supply_level_monitor.supply_check(p2)["risk"] is True
