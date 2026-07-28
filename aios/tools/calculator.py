import logging

logger = logging.getLogger(__name__)

import hashlib
import re
from aios.tools.base import BaseTool
from aios.tools.registry import TOOL_REGISTRY


class CalculatorInput:
    expression: str


def _safe_eval(expr: str) -> float:
    """Evaluate safe math expression — no import, no exec."""
    clean = re.sub(r"[^0-9+\-*/.()%\s]", "", expr)
    if not clean.strip():
        raise ValueError("Empty expression")
    allowed = {"abs": abs, "round": round, "min": min, "max": max, "pow": pow}
    return eval(clean, {"__builtins__": {}}, allowed)  # noqa: S307


class CalculatorTool(BaseTool):
    name = "calculator"
    description = "Evaluate mathematical expressions (addition, subtraction, multiplication, division, powers)"
    parameters = {
        "type": "object",
        "properties": {
            "expression": {
                "type": "string",
                "description": "Mathematical expression to evaluate (e.g. 2 + 2, (3 * 4) / 2)"
            }
        }
    }

    async def run(self, expression: str) -> dict:
        try:
            result = _safe_eval(expression)
            return {"result": result}
        except Exception as e:
            logger.exception("Calculator tool error for expression: %s", expression)
            return {"error": str(e)}


TOOL_REGISTRY["calculator"] = {
    "code_reference": "aios.tools.calculator.CalculatorTool",
}
