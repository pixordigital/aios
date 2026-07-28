"""Agent contracts — typed I/O schemas for agent composition.

Each agent declares what it expects (input_schema) and what it produces
(output_schema). Orchestrator validates and transforms between agents.
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentContract:
    """Schema contract for an agent's input and output."""
    input_schema: dict = field(default_factory=lambda: {
        "type": "object",
        "properties": {
            "message": {"type": "string", "description": "User message to process"},
        },
        "required": ["message"],
    })
    output_schema: dict = field(default_factory=lambda: {
        "type": "object",
        "properties": {
            "response": {"type": "string", "description": "Agent response"},
        },
        "required": ["response"],
    })


def validate_against_schema(data: dict, schema: dict) -> list[str]:
    """Basic JSON Schema validation. Returns list of errors (empty = valid)."""
    errors = []
    required = schema.get("required", [])
    props = schema.get("properties", {})

    for field_name in required:
        if field_name not in data:
            errors.append(f"Missing required field: '{field_name}'")

    for key, value in data.items():
        prop = props.get(key)
        if not prop:
            continue
        expected_type = prop.get("type")
        if expected_type == "string" and not isinstance(value, str):
            errors.append(f"Field '{key}' should be string, got {type(value).__name__}")
        elif expected_type == "integer" and not isinstance(value, int):
            errors.append(f"Field '{key}' should be integer, got {type(value).__name__}")
        elif expected_type == "number" and not isinstance(value, (int, float)):
            errors.append(f"Field '{key}' should be number, got {type(value).__name__}")
        elif expected_type == "boolean" and not isinstance(value, bool):
            errors.append(f"Field '{key}' should be boolean, got {type(value).__name__}")
        elif expected_type == "array" and not isinstance(value, list):
            errors.append(f"Field '{key}' should be array, got {type(value).__name__}")
        elif expected_type == "object" and not isinstance(value, dict):
            errors.append(f"Field '{key}' should be object, got {type(value).__name__}")

    return errors


def contract_from_agent(agent: Any) -> AgentContract:
    """Extract contract from an agent model, falling back to defaults."""
    mc = getattr(agent, "memory_config", {}) or {}
    return AgentContract(
        input_schema=mc.get("input_schema", AgentContract().input_schema),
        output_schema=mc.get("output_schema", AgentContract().output_schema),
    )
