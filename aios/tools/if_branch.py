from pydantic import BaseModel, Field
from aios.tools.base import BaseTool
from aios.tools.registry import TOOL_REGISTRY
import ast

class IfInput(BaseModel):
    condition: str = Field(description="Expressão python com `input` dict, ex: input['age']>18")
    input: dict = Field(default_factory=dict)

class IfTool(BaseTool):
    name = "if_branch"
    description = "Avalia condição sobre input, retorna {branch: true|false}"
    input_model = IfInput

    async def run(self, condition: str, input: dict | None = None) -> dict:
        input = input or {}
        if not condition:
            return {"branch": True, "input": input}
        try:
            tree = ast.parse(condition, mode="eval")
            for n in ast.walk(tree):
                if isinstance(n, (ast.Import, ast.ImportFrom)):
                    return {"error": "import blocked", "branch": False}
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in ("__import__","eval","exec","open","compile"):
                    return {"error": "call blocked", "branch": False}
            res = eval(compile(tree, "<if>", "eval"), {"__builtins__": {}}, {"input": input, "json": input})
            return {"branch": bool(res), "input": input}
        except Exception as e:
            return {"error": str(e), "branch": False, "input": input}

TOOL_REGISTRY["if_branch"] = {"code_reference": "aios.tools.if_branch.IfTool"}
