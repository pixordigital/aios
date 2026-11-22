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


def _require_keys(payload: dict[str, Any], schema_id: str, keys: tuple[str, ...]) -> None:
    missing = [k for k in keys if k not in payload]
    if missing:
        raise SchemaValidationError(
            f"payload for '{schema_id}' missing required keys: {missing}"
        )


def _require_str(payload: dict[str, Any], schema_id: str, key: str, allow_empty: bool = False) -> None:
    val = payload.get(key)
    if not isinstance(val, str):
        raise SchemaValidationError(f"'{key}' in '{schema_id}' must be a string")
    if not allow_empty and not val.strip():
        raise SchemaValidationError(f"'{key}' in '{schema_id}' must be non-empty")


def _opt_str(payload: dict[str, Any], schema_id: str, key: str) -> None:
    if key in payload and payload[key] is not None and not isinstance(payload[key], str):
        raise SchemaValidationError(f"'{key}' in '{schema_id}' must be a string when present")


def _opt_number(payload: dict[str, Any], schema_id: str, key: str) -> None:
    if key in payload and payload[key] is not None:
        if isinstance(payload[key], bool) or not isinstance(payload[key], (int, float)):
            raise SchemaValidationError(f"'{key}' in '{schema_id}' must be a number when present")


def _opt_dict(payload: dict[str, Any], schema_id: str, key: str) -> None:
    if key in payload and payload[key] is not None and not isinstance(payload[key], dict):
        raise SchemaValidationError(f"'{key}' in '{schema_id}' must be an object when present")


def _opt_list(payload: dict[str, Any], schema_id: str, key: str) -> None:
    if key in payload and payload[key] is not None and not isinstance(payload[key], list):
        raise SchemaValidationError(f"'{key}' in '{schema_id}' must be a list when present")


def _lead_research_input_v1(payload: Any) -> None:
    d = _require_dict(payload, "lead_research_input.v1")
    if d is None:
        return
    if not d:
        raise SchemaValidationError("payload for 'lead_research_input.v1' must not be empty")
    for k in ("query", "company", "domain", "target", "icp", "name"):
        _opt_str(d, "lead_research_input.v1", k, ) if False else None
    # type-check known keys when present
    for k in ("query", "company", "domain", "target", "icp", "name", "source"):
        _opt_str(d, "lead_research_input.v1", k)
    _opt_dict(d, "lead_research_input.v1", "lead")
    _opt_dict(d, "lead_research_input.v1", "criteria")
    _opt_list(d, "lead_research_input.v1", "companies")


def _company_research_output_v1(payload: Any) -> None:
    d = _require_dict(payload, "company_research_output.v1")
    if d is None:
        return
    if not d:
        raise SchemaValidationError("payload for 'company_research_output.v1' must not be empty")
    for k in ("company_name", "domain", "summary", "result", "status"):
        _opt_str(d, "company_research_output.v1", k)
    if "company" in d and d["company"] is not None and not isinstance(d["company"], (str, dict)):
        raise SchemaValidationError("'company' in 'company_research_output.v1' must be string/object when present")
    _opt_dict(d, "company_research_output.v1", "findings")
    _opt_list(d, "company_research_output.v1", "sources")
    _opt_list(d, "company_research_output.v1", "contacts")
    _opt_list(d, "company_research_output.v1", "leads")


def _lead_qualification_output_v1(payload: Any) -> None:
    d = _require_dict(payload, "lead_qualification_output.v1")
    if d is None:
        return
    if not d:
        raise SchemaValidationError("payload for 'lead_qualification_output.v1' must not be empty")
    if "qualified" in d and not isinstance(d["qualified"], bool):
        raise SchemaValidationError("'qualified' in 'lead_qualification_output.v1' must be bool when present")
    _opt_number(d, "lead_qualification_output.v1", "score")
    _opt_str(d, "lead_qualification_output.v1", "status")
    _opt_str(d, "lead_qualification_output.v1", "result")
    _opt_dict(d, "lead_qualification_output.v1", "qualification")
    _opt_str(d, "lead_qualification_output.v1", "reason")
    _opt_list(d, "lead_qualification_output.v1", "leads")


def _pet_enquiry_v1(payload: Any) -> None:
    d = _require_dict(payload, "pet.enquiry.v1")
    if d is None:
        return
    if not d:
        raise SchemaValidationError("payload for 'pet.enquiry.v1' must not be empty")
    for k in ("message", "text", "body", "enquiry", "phone", "from", "channel", "contact_id", "name"):
        _opt_str(d, "pet.enquiry.v1", k)
    _opt_dict(d, "pet.enquiry.v1", "contact")
    _opt_dict(d, "pet.enquiry.v1", "metadata")


def _pet_qualified_lead_v1(payload: Any) -> None:
    d = _require_dict(payload, "pet.qualified_lead.v1")
    if d is None:
        return
    if not d:
        raise SchemaValidationError("payload for 'pet.qualified_lead.v1' must not be empty")
    if "qualified" in d and not isinstance(d["qualified"], bool):
        raise SchemaValidationError("'qualified' in 'pet.qualified_lead.v1' must be bool when present")
    for k in ("status", "next_action", "result", "reason"):
        _opt_str(d, "pet.qualified_lead.v1", k)
    _opt_dict(d, "pet.qualified_lead.v1", "lead")
    _opt_dict(d, "pet.qualified_lead.v1", "handoff")
    _opt_dict(d, "pet.qualified_lead.v1", "contact")


def _pet_lead_context_v1(payload: Any) -> None:
    d = _require_dict(payload, "pet.lead_context.v1")
    if d is None:
        return
    if not d:
        raise SchemaValidationError("payload for 'pet.lead_context.v1' must not be empty")
    for k in ("deal_id", "lead_id", "phone", "status", "name"):
        _opt_str(d, "pet.lead_context.v1", k)
    _opt_dict(d, "pet.lead_context.v1", "lead")
    _opt_dict(d, "pet.lead_context.v1", "contact")
    _opt_dict(d, "pet.lead_context.v1", "conversation")
    _opt_list(d, "pet.lead_context.v1", "messages")


def _pet_follow_up_result_v1(payload: Any) -> None:
    d = _require_dict(payload, "pet.follow_up_result.v1")
    if d is None:
        return
    if not d:
        raise SchemaValidationError("payload for 'pet.follow_up_result.v1' must not be empty")
    if "sent" in d and not isinstance(d["sent"], bool):
        raise SchemaValidationError("'sent' in 'pet.follow_up_result.v1' must be bool when present")
    for k in ("status", "result", "next_action", "message", "reason"):
        _opt_str(d, "pet.follow_up_result.v1", k)


def _tool_call_v1(payload: Any) -> None:
    d = _require_dict(payload, "tool_call.v1")
    if d is None:
        return
    _require_keys(d, "tool_call.v1", ("tool",))
    _require_str(d, "tool_call.v1", "tool")
    _opt_dict(d, "tool_call.v1", "args")
    _opt_dict(d, "tool_call.v1", "input")
    _opt_str(d, "tool_call.v1", "call_id")
    _opt_str(d, "tool_call.v1", "status")


def _agent_run_v1(payload: Any) -> None:
    d = _require_dict(payload, "agent_run.v1")
    if d is None:
        return
    _require_keys(d, "agent_run.v1", ("agent_id",))
    _require_str(d, "agent_run.v1", "agent_id")
    _opt_str(d, "agent_run.v1", "run_id")
    _opt_str(d, "agent_run.v1", "status")
    _opt_dict(d, "agent_run.v1", "input")
    _opt_dict(d, "agent_run.v1", "output")
    _opt_dict(d, "agent_run.v1", "metadata")


def _memory_candidate_v1(payload: Any) -> None:
    d = _require_dict(payload, "memory_candidate.v1")
    if d is None:
        return
    _require_keys(d, "memory_candidate.v1", ("content",))
    _require_str(d, "memory_candidate.v1", "content")
    _opt_str(d, "memory_candidate.v1", "kind")
    _opt_str(d, "memory_candidate.v1", "source")
    _opt_dict(d, "memory_candidate.v1", "metadata")
    _opt_list(d, "memory_candidate.v1", "tags")


def _handoff_v1(payload: Any) -> None:
    d = _require_dict(payload, "handoff.v1")
    if d is None:
        return
    if not any(k in d for k in ("target", "to", "reason", "summary")):
        raise SchemaValidationError(
            "payload for 'handoff.v1' must include target/to/reason/summary"
        )
    for k in ("target", "to", "reason", "summary", "status"):
        _opt_str(d, "handoff.v1", k)
    _opt_dict(d, "handoff.v1", "context")
    _opt_dict(d, "handoff.v1", "payload")


def _trace_v1(payload: Any) -> None:
    d = _require_dict(payload, "trace.v1")
    if d is None:
        return
    if not any(k in d for k in ("event", "name", "span_id", "trace_id", "kind")):
        raise SchemaValidationError(
            "payload for 'trace.v1' must include event/name/span_id/trace_id/kind"
        )
    for k in ("event", "name", "span_id", "trace_id", "parent_id", "kind", "status"):
        _opt_str(d, "trace.v1", k)
    _opt_dict(d, "trace.v1", "attributes")
    _opt_dict(d, "trace.v1", "data")


_BUILTIN_SCHEMAS: dict[str, SchemaValidator] = {
    "lead_research_input.v1": _lead_research_input_v1,
    "company_research_output.v1": _company_research_output_v1,
    "lead_qualification_output.v1": _lead_qualification_output_v1,
    "pet.enquiry.v1": _pet_enquiry_v1,
    "pet.qualified_lead.v1": _pet_qualified_lead_v1,
    "pet.lead_context.v1": _pet_lead_context_v1,
    "pet.follow_up_result.v1": _pet_follow_up_result_v1,
    "tool_call.v1": _tool_call_v1,
    "agent_run.v1": _agent_run_v1,
    "memory_candidate.v1": _memory_candidate_v1,
    "handoff.v1": _handoff_v1,
    "trace.v1": _trace_v1,
}

# Built-in ids used by seeded manifests/vertical contracts. Explicit registry
# entries keep declared-schema enforcement fail-closed for unknown ids.
for _schema_id, _validator in _BUILTIN_SCHEMAS.items():
    _REGISTRY.setdefault(_schema_id, _validator)
