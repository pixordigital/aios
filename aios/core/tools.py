"""Tool execution engine. Allow-list based — no arbitrary imports."""

import asyncio
import importlib
import json
import logging
from typing import Any

from aios.tools.registry import TOOL_REGISTRY

logger = logging.getLogger(__name__)

# Built-in tool modules that are safe to import
_ALLOWED_MODULES = {
    "aios.tools.calculator",
    "aios.tools.web_search",
    "aios.tools.send_email",
    "aios.tools.read_file",
    "aios.tools.current_datetime",
    "aios.tools.http_get",
    "aios.tools.dynamic",
}

# Safety limits
_TOOL_TIMEOUT = 30.0  # seconds per tool call
_TOOL_MAX_RETRIES = 2
_TOOL_MAX_OUTPUT = 100_000  # chars
_TOOL_MAX_INPUT_ARGS = 50_000  # chars
_TOOL_CALL_TRACKING = {}  # tool_name -> count for audit

# ponytail: in-memory tool audit. DB-backed when observability scales.


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

        # double-check tool is in registry allow-list
        entry = TOOL_REGISTRY.get(name)
        if not entry:
            raise ToolExecutionError(f"Tool '{name}' not in registry")
        mod_path = entry["code_reference"]
        module_name = mod_path.rsplit(".", 1)[0]
        if module_name not in _ALLOWED_MODULES:
            raise ToolExecutionError(f"Tool '{name}' module not allowed")

        # input size limit
        if len(args_json) > _TOOL_MAX_INPUT_ARGS:
            raise ToolExecutionError(f"Tool args too large ({len(args_json)} chars, max {_TOOL_MAX_INPUT_ARGS})")

        try:
            args = json.loads(args_json)
        except json.JSONDecodeError:
            raise ToolExecutionError(f"Invalid JSON args")

        # audit tracking
        _TOOL_CALL_TRACKING[name] = _TOOL_CALL_TRACKING.get(name, 0) + 1

        # retry loop with timeout
        last_err = None
        for attempt in range(_TOOL_MAX_RETRIES + 1):
            try:
                result = await asyncio.wait_for(
                    tool.run(**args),
                    timeout=_TOOL_TIMEOUT,
                )
                output = json.dumps(result) if isinstance(result, dict) else str(result)
                # output size limit
                if len(output) > _TOOL_MAX_OUTPUT:
                    output = output[:_TOOL_MAX_OUTPUT] + "\n... [truncated]"
                return output
            except asyncio.TimeoutError:
                last_err = f"Tool '{name}' timed out after {_TOOL_TIMEOUT}s"
                if attempt < _TOOL_MAX_RETRIES:
                    await asyncio.sleep(0.5)
                else:
                    raise ToolExecutionError(last_err)
            except Exception as e:
                logger.exception("Tool %s attempt %d failed", name, attempt + 1)
                last_err = str(e)
                if attempt < _TOOL_MAX_RETRIES:
                    await asyncio.sleep(0.5)
                else:
                    raise ToolExecutionError(f"Tool '{name}' failed: {last_err}")

        raise ToolExecutionError(f"Tool '{name}' failed: {last_err}")

    @staticmethod
    def audit_summary() -> dict:
        return dict(_TOOL_CALL_TRACKING)

    def _load(self, name: str) -> Any:
        entry = TOOL_REGISTRY.get(name)
        if not entry:
            raise ValueError(f"Tool '{name}' not registered")
        if entry.get("dynamic") and entry.get("instance"):
            return entry["instance"]
        mod_path = entry["code_reference"]
        module_name = mod_path.rsplit(".", 1)[0]
        if module_name not in _ALLOWED_MODULES:
            raise ValueError(f"Tool module '{module_name}' not in allow-list")
        mod = importlib.import_module(module_name)
        cls_name = mod_path.rsplit(".", 1)[1]
        cls = getattr(mod, cls_name)
        return cls()

    @staticmethod
    def register_runtime_tool(name: str, description: str, code: str, input_schema: dict = None):
        from aios.tools.dynamic import register_dynamic_tool
        return register_dynamic_tool(name, description, code, input_schema)

    @staticmethod
    def load_db_tools(db_tools: list):
        for t in db_tools:
            if t.name in TOOL_REGISTRY:
                continue
            if t.code_reference and t.code_reference.startswith("code:"):
                code = t.code_reference[5:]
                from aios.tools.dynamic import register_dynamic_tool
                register_dynamic_tool(t.name, t.description, code, t.input_schema)
            else:
                TOOL_REGISTRY[t.name] = {"code_reference": t.code_reference or f"aios.tools.dynamic.{t.name}", "description": t.description, "input_schema": t.input_schema}
