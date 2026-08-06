"""Tool registry — maps tool names to their implementations.

Each tool module self-registers on import.
"""

TOOL_REGISTRY: dict = {}
