import ast
import asyncio
import json
import logging
from aios.tools.base import BaseTool
from aios.tools.registry import TOOL_REGISTRY

logger = logging.getLogger(__name__)

_BLOCKED_NODES = (ast.Import, ast.ImportFrom, ast.While, ast.For, ast.AsyncFor, ast.With, ast.AsyncWith)
_BLOCKED_NAMES = {"__import__", "eval", "exec", "open", "compile", "input", "globals", "locals", "vars", "__builtins__", "os", "sys", "subprocess", "socket", "requests"}
_MAX_CODE_LEN = 5000
_EXEC_TIMEOUT = 5.0

def _validate_ast(code: str):
    if len(code) > _MAX_CODE_LEN:
        raise ValueError(f"code too long ({len(code)} > {_MAX_CODE_LEN})")
    tree = ast.parse(code)
    for node in ast.walk(tree):
        if isinstance(node, _BLOCKED_NODES):
            raise ValueError(f"blocked statement: {type(node).__name__}")
        if isinstance(node, ast.Name) and node.id in _BLOCKED_NAMES:
            raise ValueError(f"blocked name: {node.id}")
        if isinstance(node, ast.Attribute) and node.attr.startswith("_"):
            raise ValueError(f"blocked attribute: {node.attr}")
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in _BLOCKED_NAMES:
                raise ValueError(f"blocked call: {func.id}")

class DynamicTool(BaseTool):
    def __init__(self, name: str, description: str, code: str, input_schema: dict = None):
        _validate_ast(code)
        self.name = name
        self.description = description
        self._code = code
        self._schema = input_schema or {"type": "object", "properties": {}, "additionalProperties": True}

    def openai_schema(self):
        return {"type": "function", "function": {"name": self.name, "description": self.description, "parameters": self._schema}}

    async def run(self, **kwargs):
        safe_globals = {"__builtins__": {"len": len, "str": str, "int": int, "float": float, "round": round, "min": min, "max": max, "sum": sum, "sorted": sorted, "json": json, "dict": dict, "list": list, "set": set, "tuple": tuple, "abs": abs, "any": any, "all": all, "enumerate": enumerate, "zip": zip}}
        safe_locals = dict(kwargs)
        safe_locals["_input"] = kwargs
        def _sync_exec():
            exec(self._code, safe_globals, safe_locals)
            if "result" in safe_locals:
                return safe_locals["result"]
            if "_output" in safe_locals:
                return safe_locals["_output"]
            return {k: v for k, v in safe_locals.items() if not k.startswith("_")}
        try:
            res = await asyncio.wait_for(asyncio.to_thread(_sync_exec), timeout=_EXEC_TIMEOUT)
            if isinstance(res, dict) and len(json.dumps(res)) > 100000:
                return {"error": "output too large"}
            return res
        except asyncio.TimeoutError:
            return {"error": f"tool timeout after {_EXEC_TIMEOUT}s"}
        except Exception as e:
            logger.warning("Dynamic tool %s failed: %s", self.name, e)
            return {"error": str(e)}


def register_dynamic_tool(name: str, description: str, code: str, input_schema: dict = None):
    tool = DynamicTool(name, description, code, input_schema)
    TOOL_REGISTRY[name] = {"code_reference": f"aios.tools.dynamic.{name}", "description": description, "input_schema": input_schema or {}, "dynamic": True, "instance": tool}
    return tool


def get_dynamic_tool(name: str):
    entry = TOOL_REGISTRY.get(name)
    if entry and entry.get("dynamic"):
        return entry.get("instance")
    return None
