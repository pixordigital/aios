"""Base tool class all tools inherit from."""

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel


class BaseTool(ABC):
    name: str = ""
    description: str = ""
    input_model: type[BaseModel] | None = None
    # Set by ToolEngine before run(). Tools that touch org-scoped rows must
    # read it and refuse cross-org access. Empty = unknown caller (defense in
    # depth still applies, but scoping cannot).
    _org_id: str = ""
    # Id of the agent whose run is executing the tool. Empty on admin/dashboard
    # paths, where no agent is running.
    _agent_id: str = ""

    @abstractmethod
    async def run(self, **kwargs) -> Any:
        ...

    def openai_schema(self) -> dict:
        """JSON-Schema function definition for the model.

        `input_model` is authoritative when set; otherwise fall back to the
        legacy `parameters` class attribute. Nine tools (sql_query,
        python_sandbox, calculator, crm_*, ...) defined a Pydantic input model
        and never assigned it, so they were advertised to the LLM as
        `"parameters": {}` — the model sends `{}` and every call dies on a
        missing positional argument.
        """
        params: dict = {}
        if self.input_model:
            schema = self.input_model.model_json_schema()
            # Pydantic hoists nested models into "$defs" and can leave
            # properties empty for a flat model. Flatten so the schema the
            # provider validates against matches the tool's real signature.
            props = dict(schema.get("properties") or {})
            if not props and "$defs" in schema:
                for sub in schema["$defs"].values():
                    props.update(sub.get("properties") or {})
            params = {
                "type": "object",
                "properties": props,
                "required": schema.get("required", []),
            }
        else:
            legacy = getattr(self, "parameters", None)
            if isinstance(legacy, dict) and legacy.get("properties"):
                params = legacy
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": params,
            },
        }
