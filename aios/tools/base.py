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
        params = {}
        if self.input_model:
            params = self.input_model.model_json_schema()
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": params,
            },
        }
