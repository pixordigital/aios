"""Deterministic schema validation registry for ICM stage boundaries.

Manifests declare ``inputs_schema`` / ``outputs_schema`` ids. A declared schema
is enforced fail-closed: missing registry entry or invalid payload raises.
"""
from __future__ import annotations

import json
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


def _as_dict(payload: Any, schema_id: str) -> dict[str, Any] | None:
    """Normalize payload to dict for shape validation.

    Returns None for absent legacy payloads (None/"") to preserve compat with
    existing call sites that pass empty/absent input. Dict payloads and JSON
    object strings are validated; other non-empty strings pass as legacy opaque
    outputs.
    """
    if payload is None or payload == "":
        return None
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, str):
        try:
            parsed = json.loads(payload)
        except Exception:
            return "__legacy_string__"  # type: ignore[return-value]
        if isinstance(parsed, dict):
            return parsed
        return "__legacy_string__"  # type: ignore[return-value]
    raise SchemaValidationError(f"payload for '{schema_id}' must be an object/dict")


def _require_dict(payload: Any, schema_id: str) -> dict[str, Any] | None:
    d = _as_dict(payload, schema_id)
    if d == "__legacy_string__":  # type: ignore[comparison-overlap]
        return None
    return d


# Shapes: "str" | "number" | "bool" | "object" | "list";
# ("list", shape) = list of shape; ("oneof", shape, ...) = union;
# {key: shape} = object with typed fields (absent/null fields ignored).
_SPECS: dict[str, dict[str, Any]] = {
    "lead_research_input.v1": {
        "nonempty": True,
        "fields": {
            "query": "str",
            "company": "str",
            "domain": "str",
            "target": "str",
            "icp": "str",
            "name": "str",
            "source": "str",
            "lead": {"name": "str", "domain": "str"},
            "criteria": "object",
            "companies": ("list", "object"),
        },
    },
    "company_research_output.v1": {
        "nonempty": True,
        "fields": {
            "company_name": "str",
            "domain": "str",
            "summary": "str",
            "result": "str",
            "status": "str",
            "company": ("oneof", "str", "object"),
            "findings": "object",
            "sources": "list",
            "contacts": "list",
            "leads": "list",
        },
    },
    "lead_qualification_output.v1": {
        "nonempty": True,
        "fields": {
            "qualified": "bool",
            "score": "number",
            "status": "str",
            "result": "number",
            "qualification": "object",
            "reason": "str",
            "leads": "list",
        },
    },
    "pet.enquiry.v1": {
        "nonempty": True,
        "fields": {
            "message": "str",
            "text": "str",
            "body": "str",
            "enquiry": "str",
            "phone": "str",
            "from": "str",
            "channel": "str",
            "contact_id": "str",
            "name": "str",
            "contact": "object",
            "metadata": "object",
        },
    },
    "pet.qualified_lead.v1": {
        "nonempty": True,
        "fields": {
            "qualified": "bool",
            "status": "str",
            "next_action": "str",
            "result": "str",
            "reason": "str",
            "lead": "object",
            "handoff": "object",
            "contact": "object",
        },
    },
    "pet.lead_context.v1": {
        "nonempty": True,
        "fields": {
            "deal_id": "str",
            "lead_id": "str",
            "phone": "str",
            "status": "str",
            "name": "str",
            "lead": "object",
            "contact": "object",
            "conversation": "object",
            "messages": "list",
        },
    },
    "pet.follow_up_result.v1": {
        "nonempty": True,
        "fields": {
            "sent": "bool",
            "status": "str",
            "result": "str",
            "next_action": "str",
            "message": "str",
            "reason": "str",
        },
    },
    "cdus.enquiry.v1": {
        "nonempty": True,
        "fields": {
            "message": "str",
            "text": "str",
            "body": "str",
            "enquiry": "str",
            "phone": "str",
            "from": "str",
            "channel": "str",
            "contact_id": "str",
            "name": "str",
            "contact": "object",
            "metadata": "object",
        },
    },
    "cdus.qualified_lead.v1": {
        "nonempty": True,
        "fields": {
            "qualified": "bool",
            "status": "str",
            "next_action": "str",
            "result": "str",
            "reason": "str",
            "lead": "object",
            "handoff": "object",
            "contact": "object",
        },
    },
    "cdus.lead_context.v1": {
        "nonempty": True,
        "fields": {
            "deal_id": "str",
            "lead_id": "str",
            "phone": "str",
            "status": "str",
            "name": "str",
            "lead": "object",
            "contact": "object",
            "conversation": "object",
            "messages": "list",
        },
    },
    "cdus.follow_up_result.v1": {
        "nonempty": True,
        "fields": {
            "sent": "bool",
            "status": "str",
            "result": "str",
            "next_action": "str",
            "message": "str",
            "reason": "str",
        },
    },
    "tool_call.v1": {
        "required": {"tool": "str"},
        "fields": {
            "args": "object",
            "input": "object",
            "call_id": "str",
            "status": "str",
        },
    },
    "agent_run.v1": {
        "required": {"agent_id": "str"},
        "fields": {
            "run_id": "str",
            "status": "str",
            "input": "object",
            "output": "object",
            "metadata": "object",
        },
    },
    "memory_candidate.v1": {
        "required": {"content": "str"},
        "fields": {
            "kind": "str",
            "source": "str",
            "metadata": "object",
            "tags": ("list", "str"),
        },
    },
    "handoff.v1": {
        "required_any": ("target", "to", "reason", "summary"),
        "fields": {
            "target": "str",
            "to": "str",
            "reason": "str",
            "summary": "str",
            "status": "str",
            "context": "object",
            "payload": "object",
        },
    },
    "trace.v1": {
        "required_any": ("event", "name", "span_id", "trace_id", "kind"),
        "fields": {
            "event": "str",
            "name": "str",
            "span_id": "str",
            "trace_id": "str",
            "parent_id": "str",
            "kind": "str",
            "status": "str",
            "attributes": "object",
            "data": "object",
        },
    },
}


def _check_shape(value: Any, shape: Any, schema_id: str, path: str) -> None:
    if isinstance(shape, tuple) and shape and shape[0] == "list":
        if not isinstance(value, list):
            raise SchemaValidationError(f"'{path}' in '{schema_id}' must be a list")
        for index, item in enumerate(value):
            _check_shape(item, shape[1], schema_id, f"{path}[{index}]")
        return
    if isinstance(shape, tuple) and shape and shape[0] == "oneof":
        for option in shape[1:]:
            try:
                _check_shape(value, option, schema_id, path)
            except SchemaValidationError:
                continue
            return
        raise SchemaValidationError(f"'{path}' in '{schema_id}' has an invalid type")
    if isinstance(shape, dict):
        if not isinstance(value, dict):
            raise SchemaValidationError(f"'{path}' in '{schema_id}' must be an object")
        for key, sub_shape in shape.items():
            if key in value and value[key] is not None:
                _check_shape(value[key], sub_shape, schema_id, f"{path}.{key}")
        return
    if shape == "str":
        ok = isinstance(value, str)
    elif shape == "number":
        ok = not isinstance(value, bool) and isinstance(value, (int, float))
    elif shape == "bool":
        ok = isinstance(value, bool)
    elif shape == "object":
        ok = isinstance(value, dict)
    elif shape == "list":
        ok = isinstance(value, list)
    else:
        raise SchemaValidationError(f"invalid shape spec for '{schema_id}'")
    if not ok:
        raise SchemaValidationError(f"'{path}' in '{schema_id}' must be {shape}")


def _validate_spec(payload: Any, schema_id: str, spec: dict[str, Any]) -> None:
    d = _require_dict(payload, schema_id)
    if d is None:
        return
    if spec.get("nonempty") and not d:
        raise SchemaValidationError(f"payload for '{schema_id}' must not be empty")
    required = spec.get("required", {})
    missing = [key for key in required if key not in d]
    if missing:
        raise SchemaValidationError(
            f"payload for '{schema_id}' missing required keys: {missing}"
        )
    for key, shape in required.items():
        _check_shape(d[key], shape, schema_id, key)
        if shape == "str" and not d[key].strip():
            raise SchemaValidationError(f"'{key}' in '{schema_id}' must be non-empty")
    required_any = spec.get("required_any", ())
    if required_any and not any(key in d for key in required_any):
        raise SchemaValidationError(
            f"payload for '{schema_id}' must include {'/'.join(required_any)}"
        )
    for key, shape in spec.get("fields", {}).items():
        if key in d and d[key] is not None:
            _check_shape(d[key], shape, schema_id, key)


_BUILTIN_SCHEMAS: dict[str, SchemaValidator] = {
    schema_id: (
        lambda payload, schema_id=schema_id, spec=spec: _validate_spec(
            payload, schema_id, spec
        )
    )
    for schema_id, spec in _SPECS.items()
}

# Built-in ids used by seeded manifests/vertical contracts. Explicit registry
# entries keep declared-schema enforcement fail-closed for unknown ids.
for _schema_id, _validator in _BUILTIN_SCHEMAS.items():
    _REGISTRY.setdefault(_schema_id, _validator)
