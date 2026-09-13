import pytest
from aios.core.whatsapp.anti_ban.health_monitor import compute
from aios.core.whatsapp.migration_advisor import evaluate
from aios.core.whatsapp.voice.quality_monitor import mos_from_metrics

def test_health_green():
    h = compute("inst1", True, 0, 0, 0)
    assert h["level"]=="green" and h["risk"]<40

def test_migration_warn():
    r = evaluate(1500, 75, 6)
    assert r.urgency in ("medium","critical") and r.reasons

def test_mos():
    assert mos_from_metrics(10, 0, 20) > 4.0
    assert mos_from_metrics(100, 10, 300) < 3.5
