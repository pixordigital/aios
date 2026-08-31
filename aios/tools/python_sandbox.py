import logging
from pydantic import BaseModel, Field

from aios.tools.base import BaseTool
from aios.tools.registry import TOOL_REGISTRY

logger = logging.getLogger(__name__)


class PythonSandboxInput(BaseModel):
    code: str = Field(
        description="Python code with pandas/matplotlib, print() output returned. 10s, 128M"
    )


class PythonSandboxTool(BaseTool):
    name = "python_sandbox"
    description = "Executa Python isolado (pandas, matplotlib, numpy). Use print() para resultado."

    async def run(self, code: str) -> dict:
        if len(code) > 8000:
            return {"error": "code too large"}
        blocked = ["os.system", "subprocess", "socket", "open(", "__import__('os"]
        if any(b in code for b in blocked):
            return {"error": "blocked import"}
        try:
            from aios.core.sandbox import run_isolated

            res = await run_isolated(code, timeout=10, max_memory_mb=256)
            return {
                "ok": res["ok"],
                "stdout": res["stdout"][:8000],
                "stderr": res["stderr"][:2000],
                "code": res.get("code"),
            }
        except Exception as e:
            return {"error": str(e)}


TOOL_REGISTRY["python_sandbox"] = {
    "code_reference": "aios.tools.python_sandbox.PythonSandboxTool"
}
