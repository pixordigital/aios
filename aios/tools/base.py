"""Base tool class all tools inherit from."""

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel


class BaseTool(ABC):
    name: str = ""
    description: str = ""
    input_model: type[BaseModel] | None = None
    output_model: type[BaseModel] | None = None

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
