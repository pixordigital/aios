"""No-synthetic KPI instrumentation contract."""

import pytest

from aios.core.kpi_instrumentation import (
    KPIReading,
    NOT_INSTRUMENTED,
    clear_sources,
    record_reading,
    register_source,
)


@pytest.fixture(autouse=True)
def _clean_registry():
    clear_sources()
    yield
    clear_sources()


def test_missing_source_returns_not_instrumented():
    reading = record_reading(
        name="mrr",
        value=1200.0,
        unit="usd",
        source="billing_db",
    )
    assert isinstance(reading, KPIReading)
    assert reading.instrumented is False
    assert reading.status == NOT_INSTRUMENTED
    assert reading.value is None
    assert reading.source == "billing_db"


def test_numeric_reading_from_known_source_ok():
    register_source("billing_db", description="Billing DB", owner="finance")
    reading = record_reading(
        name="mrr",
        value=1200.5,
        unit="usd",
        source="billing_db",
        observed_at="2026-11-25T12:00:00+00:00",
        confidence=0.95,
    )
    assert reading.instrumented is True
    assert reading.status == "ok"
    assert reading.name == "mrr"
    assert reading.value == 1200.5
    assert reading.unit == "usd"
    assert reading.source == "billing_db"
    assert reading.observed_at == "2026-11-25T12:00:00+00:00"
    assert reading.confidence == 0.95


def test_synthetic_or_fabricated_flag_rejected():
    register_source("billing_db")
    with pytest.raises(ValueError, match="synthetic/fabricated"):
        record_reading(
            name="mrr",
            value=100.0,
            unit="usd",
            source="billing_db",
            synthetic=True,
        )
    with pytest.raises(ValueError, match="synthetic/fabricated"):
        record_reading(
            name="mrr",
            value=100.0,
            unit="usd",
            source="billing_db",
            fabricated=True,
        )


def test_unknown_as_number_rejected():
    register_source("billing_db")
    with pytest.raises(ValueError, match="unknown-as-number"):
        record_reading(name="mrr", value=None, unit="usd", source="billing_db")
    with pytest.raises(ValueError, match="unknown-as-number"):
        record_reading(name="mrr", value="unknown", unit="usd", source="billing_db")
    with pytest.raises(ValueError, match="unknown-as-number"):
        record_reading(name="mrr", value=float("nan"), unit="usd", source="billing_db")
