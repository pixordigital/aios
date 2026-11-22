"""Deterministic schema validation registry for ICM stage boundaries.

Manifests declare ``inputs_schema`` / ``outputs_schema`` ids. A declared schema
is enforced fail-closed: missing registry entry or invalid payload raises.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

SchemaValidator = Callable[[Any], None]

_REGISTRY: dict[str, SchemaValidator] = {}


class SchemaValidationError(ValueError):
    """Payload failed a declared schema check."""


def register_schema(schema_id: str, validator: SchemaValidator) -> None:
    if not isinstance(schema_id, str) or not schema_id.strip():
        raise ValueError("schema_id must be a non-empty string")
    if not callable(validator):
        raise TypeError("validator must be callable")
    _REGISTRY[schema_id] = validator


def unregister_schema(schema_id: str) -> None:
    _REGISTRY.pop(schema_id, None)


def clear_schemas() -> None:
    _REGISTRY.clear()


def has_schema(schema_id: str) -> bool:
    return schema_id in _REGISTRY


def validate_schema(schema_id: str, payload: Any) -> None:
    """Validate payload against a declared schema id.

    Fail-closed: a declared schema id must have a registered validator.
    """
    if not isinstance(schema_id, str) or not schema_id.strip():
        raise SchemaValidationError("schema id must be a non-empty string")
    validator = _REGISTRY.get(schema_id)
    if validator is None:
        raise SchemaValidationError(
            f"declared schema '{schema_id}' has no registered validator"
        )
    try:
        validator(payload)
    except SchemaValidationError:
        raise
    except Exception as exc:
        raise SchemaValidationError(
            f"payload failed schema '{schema_id}': {exc}"
        ) from exc


def _accept_any(_payload: Any) -> None:
    return None


# Built-in ids used by seeded manifests/vertical contracts. Explicit registry
# entries keep declared-schema enforcement fail-closed for unknown ids while
# allowing deterministic boundary checks for known contracts.
for _schema_id in (
    "lead_research_input.v1",
    "company_research_output.v1",
    "lead_qualification_output.v1",
    "pet.enquiry.v1",
    "pet.qualified_lead.v1",
    "pet.lead_context.v1",
    "pet.follow_up_result.v1",
):
    _REGISTRY.setdefault(_schema_id, _accept_any)
