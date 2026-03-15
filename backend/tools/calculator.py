from __future__ import annotations

import ast
import operator
from typing import Any

from backend.errors import ToolValidationError
from backend.models import ToolResult
from backend.tools.base import BaseTool


ALLOWED_BINARY_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
}
ALLOWED_UNARY_OPERATORS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


class CalculatorTool(BaseTool):
    name = "CalculatorTool"

    def validate(self, params: dict[str, Any]) -> None:
        expression = str(params.get("expression", "")).strip()
        if not expression:
            raise ToolValidationError("INVALID_EXPRESSION", "A calculator expression is required.")
        invalid = set(expression) - set("0123456789.+-*/() ")
        if invalid:
            raise ToolValidationError("INVALID_EXPRESSION", "Only basic arithmetic is supported.", {"invalid": sorted(invalid)})
        if "^" in expression:
            raise ToolValidationError("INVALID_EXPRESSION", "Exponentiation is not supported.")

    def execute(self, params: dict[str, Any], context: dict[str, Any]) -> ToolResult:
        self.validate(params)
        expression = str(params["expression"]).strip()
        try:
            parsed = ast.parse(expression, mode="eval")
            result = self._evaluate(parsed.body)
        except ZeroDivisionError as error:
            raise ToolValidationError("DIVIDE_BY_ZERO", "Cannot divide by zero.") from error
        except ToolValidationError:
            raise
        except Exception as error:
            raise ToolValidationError("INVALID_EXPRESSION", "Malformed calculator expression.") from error

        return ToolResult(
            summary=str(result),
            data={"expression": expression, "result": result},
            trace_message=f"Calculated expression {expression}.",
        )

    def _evaluate(self, node: ast.AST) -> float:
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, ast.BinOp) and type(node.op) in ALLOWED_BINARY_OPERATORS:
            left = self._evaluate(node.left)
            right = self._evaluate(node.right)
            return float(ALLOWED_BINARY_OPERATORS[type(node.op)](left, right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in ALLOWED_UNARY_OPERATORS:
            return float(ALLOWED_UNARY_OPERATORS[type(node.op)](self._evaluate(node.operand)))
        raise ToolValidationError("INVALID_EXPRESSION", "Unsupported calculator syntax.")
