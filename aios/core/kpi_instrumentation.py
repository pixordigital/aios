"""KPI instrumentation contract: no synthetic/fabricated readings, no unknown-as-number.

Missing source -> not_instrumented. Known source + numeric value -> recorded reading.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from math import isfinite
from typing import Any

NOT_INSTRUMENTED = "not_instrumented"


@dataclass(frozen=True)
class KPIReading:
    name: str
    value: float | int | None
    unit: str
    source: str
    observed_at: str
    instrumented: bool
    confidence: float
    status: str = "ok"
    reason: str | None = None


# Registry of known KPI sources. Values hold source metadata; presence means instrumented.
KPI_SOURCE_REGISTRY: dict[str, dict[str, Any]] = {}


def register_source(source: str, *, description: str = "", owner: str = "") -> dict[str, Any]:
    """Register a known KPI source. Idempotent for same name."""
    key = str(source or "").strip()
    if not key:
        raise ValueError("source required")
    entry = {"source": key, "description": description, "owner": owner}
    KPI_SOURCE_REGISTRY[key] = entry
    return entry


def get_source(source: str) -> dict[str, Any] | None:
    return KPI_SOURCE_REGISTRY.get(str(source or "").strip())


def clear_sources() -> None:
    """Test/helper reset."""
    KPI_SOURCE_REGISTRY.clear()


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(float(value))


def record_reading(
    *,
    name: str,
    value: Any,
    unit: str,
    source: str,
    observed_at: str | None = None,
    confidence: float = 1.0,
    synthetic: bool = False,
    fabricated: bool = False,
) -> KPIReading:
    """Record a KPI reading from a known source.

    - missing/unknown source -> returns not_instrumented reading
    - synthetic/fabricated -> rejected
    - unknown-as-number / non-numeric value -> rejected
    """
    src = str(source or "").strip()
    kpi_name = str(name or "").strip()
    ts = observed_at or datetime.now(timezone.utc).isoformat()
    conf = float(confidence)

    if synthetic or fabricated:
        raise ValueError("synthetic/fabricated KPI reading rejected")

    if not src or get_source(src) is None:
        return KPIReading(
            name=kpi_name,
            value=None,
            unit=str(unit or ""),
            source=src,
            observed_at=ts,
            instrumented=False,
            confidence=0.0,
            status=NOT_INSTRUMENTED,
            reason="source_missing" if not src else "source_not_instrumented",
        )

    if not _is_number(value):
        raise ValueError("unknown-as-number: KPI value must be a finite numeric reading")

    if not kpi_name:
        raise ValueError("name required")
    if not (0.0 <= conf <= 1.0):
        raise ValueError("confidence must be between 0 and 1")

    return KPIReading(
        name=kpi_name,
        value=float(value),
        unit=str(unit or ""),
        source=src,
        observed_at=ts,
        instrumented=True,
        confidence=conf,
        status="ok",
    )
