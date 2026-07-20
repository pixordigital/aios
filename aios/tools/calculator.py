"""Calculator tool — safe eval for math expressions with DoS protection."""

import ast
import operator

from pydantic import BaseModel, Field

from aios.tools.base import BaseTool
from aios.tools.registry import TOOL_REGISTRY

_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
}

_MAX_RECURSION = 20  # prevent DoS via deeply nested expressions


def _safe_eval(expr: str) -> float:
    """Evaluate mathematical expression safely — no exec/eval, depth-limited."""

    def _eval(node: ast.AST, depth: int = 0) -> float:
        if depth > _MAX_RECURSION:
            raise ValueError("Expression too complex (nesting limit)")
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, ast.BinOp):
            op = _OPERATORS.get(type(node.op))
            if not op:
                raise ValueError(f"Unsupported operator: {type(node.op).__name__}")
            return op(_eval(node.left, depth + 1), _eval(node.right, depth + 1))
        if isinstance(node, ast.UnaryOp):
            op = _OPERATORS.get(type(node.op))
            if not op:
                raise ValueError(f"Unsupported unary operator: {type(node.op).__name__}")
            return op(_eval(node.operand, depth + 1))
        raise ValueError(f"Unsupported expression: {type(node).__name__}")

    tree = ast.parse(expr.strip(), mode="eval")
    return _eval(tree.body)


class CalculatorInput(BaseModel):
    expression: str = Field(
        description="Mathematical expression e.g. 2 + 3 * 4",
        max_length=200,
    )


class CalculatorTool(BaseTool):
    name = "calculator"
    description = "Evaluate mathematical expressions (addition, subtraction, multiplication, division, powers)"
    input_model = CalculatorInput

    async def run(self, expression: str) -> dict:
        try:
            result = _safe_eval(expression)
            return {"result": result}
        except Exception as e:
            return {"error": str(e)}


TOOL_REGISTRY["calculator"] = {
    "code_reference": "aios.tools.calculator.CalculatorTool",
}
