"""Tool execution engine. Allow-list based — no arbitrary imports."""

import importlib
import json
from typing import Any

from aios.tools.registry import TOOL_REGISTRY

# Built-in tool modules that are safe to import
_ALLOWED_MODULES = {
    "aios.tools.calculator",
    "aios.tools.web_search",
    "aios.tools.send_email",
}


class ToolExecutionError(Exception):
    pass


class ToolEngine:
    def __init__(self, tool_names: list[str]):
        self.tools: dict[str, Any] = {}
        for name in tool_names:
            self.tools[name] = self._load(name)

    def schemas(self) -> list[dict]:
        return [tool.openai_schema() for tool in self.tools.values()]

    async def execute(self, name: str, args_json: str) -> str:
        tool = self.tools.get(name)
        if not tool:
            raise ToolExecutionError(f"Unknown tool: {name}")

        try:
            args = json.loads(args_json)
        except json.JSONDecodeError:
            raise ToolExecutionError(f"Invalid JSON args")

        try:
            result = await tool.run(**args)
            return json.dumps(result) if isinstance(result, dict) else str(result)
        except Exception as e:
            raise ToolExecutionError(f"Tool '{name}' failed: {e}")

    def _load(self, name: str) -> Any:
        entry = TOOL_REGISTRY.get(name)
        if not entry:
            raise ValueError(f"Tool '{name}' not registered")
        mod_path = entry["code_reference"]
        # Security: only allow known built-in modules
        module_name = mod_path.rsplit(".", 1)[0]
        if module_name not in _ALLOWED_MODULES:
            raise ValueError(f"Tool module '{module_name}' not in allow-list")
        mod = importlib.import_module(module_name)
        cls_name = mod_path.rsplit(".", 1)[1]
        cls = getattr(mod, cls_name)
        return cls()
