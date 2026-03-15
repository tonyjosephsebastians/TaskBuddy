from __future__ import annotations

from typing import Any

from backend.errors import ToolValidationError
from backend.models import ToolResult
from backend.tools.base import BaseTool


class TextProcessorTool(BaseTool):
    name = "TextProcessorTool"
    supported_operations = {"uppercase", "lowercase", "titlecase", "word_count", "char_count"}

    def validate(self, params: dict[str, Any]) -> None:
        operation = params.get("operation")
        text = params.get("text")
        if operation not in self.supported_operations:
            raise ToolValidationError("TEXT_OPERATION_UNSUPPORTED", "Unsupported text operation.", {"operation": operation})
        if not text or not str(text).strip():
            raise ToolValidationError("TEXT_TARGET_REQUIRED", "A target text value is required.")

    def execute(self, params: dict[str, Any], context: dict[str, Any]) -> ToolResult:
        self.validate(params)
        operation = params["operation"]
        text = str(params["text"])

        if operation == "uppercase":
            value: str | int = text.upper()
        elif operation == "lowercase":
            value = text.lower()
        elif operation == "titlecase":
            value = text.title()
        elif operation == "word_count":
            value = len(text.split())
        else:
            value = len(text)

        return ToolResult(
            summary=str(value),
            data={"operation": operation, "input": text, "result": value},
            trace_message=f"Applied {operation} to the text input.",
        )
