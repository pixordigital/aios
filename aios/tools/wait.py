import asyncio
from pydantic import BaseModel, Field
from aios.tools.base import BaseTool
from aios.tools.registry import TOOL_REGISTRY

class WaitInput(BaseModel):
    seconds: float = Field(default=1, ge=0, le=300)
    input: dict = Field(default_factory=dict)

class WaitTool(BaseTool):
    name = "wait"
    description = "Pausa execução por N segundos (max 300)"
    input_model = WaitInput

    async def run(self, seconds: float = 1, input: dict | None = None) -> dict:
        await asyncio.sleep(min(float(seconds), 300))
        return {"ok": True, "waited": seconds, "input": input or {}}

TOOL_REGISTRY["wait"] = {"code_reference": "aios.tools.wait.WaitTool"}
