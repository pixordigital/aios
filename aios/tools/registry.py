"""Global tool registry. Map tool name → code reference."""

TOOL_REGISTRY: dict[str, dict] = {}

# ponytail: built-in tools registered on import. Custom tools loaded from DB.
