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
    "aios.tools.http_request",
    "aios.tools.code",
    "aios.tools.transform",
    "aios.tools.if_branch",
    "aios.tools.wait",
    "aios.tools.hubspot",
    "aios.tools.pipedrive",
    "aios.tools.rdstation",
    "aios.tools.transcribe",
    "aios.tools.dynamic",
    "aios.tools.crm",
    "aios.tools.lead_scoring",
    "aios.tools.sql_query",
    "aios.tools.python_sandbox",
    "aios.tools.rag_search",
    "aios.tools.etl_url",
    "aios.tools.calendar",
    "aios.tools.load_skills",
    "aios.tools.proactive_alerts",
    "aios.tools.team_collaboration",
    "aios.tools.voice_call",
    "aios.tools.whatsapp_template",
}

# Safety limits
_TOOL_TIMEOUT = 30.0  # seconds per tool call
_TOOL_MAX_RETRIES = 2
# Tools that change the world outside AIOS. Retrying these after an ambiguous
# failure duplicates the effect: the call may have succeeded and only the
# response was lost. `send_email` sent three emails, `crm_create_deal` created
# three deals. Everything else here is a read or a pure computation, so a retry
# is free and correct.
_TOOL_NON_IDEMPOTENT = {
    "send_email",
    "notify_human",
    "ask_team_manager",
    "crm_create_deal",
    "crm_delete_deal",
    "crm_merge_deals",
    "crm_set_follow_up",
    "whatsapp_template",
    "calendar_create_event",
    "voice_call",
}
_TOOL_MAX_OUTPUT = 100_000  # chars
_TOOL_MAX_INPUT_ARGS = 50_000  # chars
_TOOL_CALL_TRACKING = {}  # tool_name -> count for audit

# ponytail: in-memory tool audit. DB-backed when observability scales.


class ToolExecutionError(Exception):
    pass


class ToolEngine:
    def __init__(self, tool_names: list[str], org_id: str = "", agent_id: str = ""):
        self.tools: dict[str, Any] = {}
        self.org_id = org_id or ""
        # Caller identity for tools that answer "who is asking" (team_collaboration
        # resolves the caller's team from it). Empty on admin/dashboard paths,
        # where there is no agent — those callers pass org only.
        self.agent_id = agent_id or ""
        self.missing: list[str] = []
        for name in tool_names:
            # A tool name that no longer exists must not take the whole agent
            # down: ToolEngine is built in AgentRuntime.__init__, so raising
            # here meant one stale name made the agent unrunnable. Skip and
            # record it; the agent keeps the tools it can actually use.
            try:
                self.tools[name] = self._load(name)
            except Exception as e:
                self.missing.append(name)
                logger.warning("Tool '%s' unavailable: %s", name, e)

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
            raise ToolExecutionError(
                f"Tool args too large ({len(args_json)} chars, max {_TOOL_MAX_INPUT_ARGS})"
            )

        try:
            args = json.loads(args_json)
        except json.JSONDecodeError:
            raise ToolExecutionError("Invalid JSON args")

        # audit tracking
        _TOOL_CALL_TRACKING[name] = _TOOL_CALL_TRACKING.get(name, 0) + 1

        is_dynamic = entry.get("dynamic") if entry else False
        if is_dynamic:
            from aios.core.sandbox import run_isolated

            code = entry.get("instance_code") or ""
            runner = (
                f"{code}\n"
                f"import json, asyncio\n"
                f"args=json.loads({args_json!r})\n"
                f"result=asyncio.run(tool_instance.run(**args))\n"
                f"print(json.dumps(result) if isinstance(result, dict) else str(result))\n"
            )
            sb = await run_isolated(runner, timeout=_TOOL_TIMEOUT)
            if sb["ok"]:
                return sb["stdout"][:_TOOL_MAX_OUTPUT]
            raise ToolExecutionError(
                sb.get("stderr") or sb.get("error") or "sandbox failed"
            )
        last_err = None
        # Org context for tools that touch org-scoped rows (sql_query, read_file).
        # Without this every tool ran with a god-view session: an agent could
        # SELECT another org's rows and nothing recorded whose data it was.
        try:
            tool._org_id = self.org_id
            tool._agent_id = self.agent_id
        except Exception:
            pass
        # A retry is only safe for tools whose effect is idempotent. Retrying
        # `send_email` after a lost response sent the email three times.
        max_attempts = 1 if name in _TOOL_NON_IDEMPOTENT else _TOOL_MAX_RETRIES + 1
        for attempt in range(max_attempts):
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
            except TimeoutError:
                last_err = f"Tool '{name}' timed out after {_TOOL_TIMEOUT}s"
                if attempt < max_attempts - 1:
                    await asyncio.sleep(0.5)
                else:
                    raise ToolExecutionError(last_err)
            except Exception as e:
                logger.exception("Tool %s attempt %d failed", name, attempt + 1)
                last_err = str(e)
                # A permission denial is a verdict, not a hiccup. Retrying it
                # three times bought three identical tracebacks and the same
                # answer.
                deterministic = isinstance(e, (PermissionError, ToolExecutionError))
                if attempt < max_attempts - 1 and not deterministic:
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
    def register_runtime_tool(
        name: str, description: str, code: str, input_schema: dict = None
    ):
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
                TOOL_REGISTRY[t.name] = {
                    "code_reference": t.code_reference
                    or f"aios.tools.dynamic.{t.name}",
                    "description": t.description,
                    "input_schema": t.input_schema,
                }
