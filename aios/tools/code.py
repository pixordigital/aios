import json
import logging
from pydantic import BaseModel, Field
from aios.tools.base import BaseTool
from aios.tools.registry import TOOL_REGISTRY

logger = logging.getLogger(__name__)

class CodeInput(BaseModel):
    code: str = Field(description="Python code. Input доступно em `input_data` (dict). Use `output = ...` ou print().")
    input_data: dict = Field(default_factory=dict)
    timeout: int = Field(default=10, ge=1, le=60)

class CodeTool(BaseTool):
    name = "code"
    description = "Executa Python com input_data, retorna output. Para transformar dados entre nodes."
    input_model = CodeInput

    async def run(self, code: str, input_data: dict | None = None, timeout: int = 10) -> dict:
        if len(code) > 15000:
            return {"error": "code too large"}
        input_data = input_data or {}
        wrapped = (
            "import json, sys\n"
            f"input_data = json.loads({json.dumps(json.dumps(input_data))!r})\n"
            "if isinstance(input_data, str):\n"
            "    import json as _j; input_data=_j.loads(input_data)\n"
            f"{code}\n"
            "if 'output' in dir():\n"
            "    _o=output\n"
            "else:\n"
            "    _o=None\n"
            "if _o is not None:\n"
            "    print(json.dumps(_o) if isinstance(_o,(dict,list)) else str(_o))\n"
        )
        try:
            from aios.core.sandbox import run_isolated
            res = await run_isolated(wrapped, timeout=timeout, max_memory_mb=256)
            out = res.get("stdout","").strip()[:20000]
            err = res.get("stderr","").strip()[:5000]
            if res.get("ok"):
                try:
                    parsed = json.loads(out) if out else None
                    return {"ok": True, "output": parsed if parsed is not None else out, "stderr": err}
                except Exception:
                    return {"ok": True, "output": out, "stderr": err}
            return {"ok": False, "error": err or res.get("error",""), "output": out}
        except Exception as e:
            return {"error": str(e)}

TOOL_REGISTRY["code"] = {"code_reference": "aios.tools.code.CodeTool"}
