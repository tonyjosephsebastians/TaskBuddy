from __future__ import annotations

from typing import Any

from backend.config import TRANSACTION_KEYWORDS
from backend.errors import ToolValidationError
from backend.models import ToolResult
from backend.tools.base import BaseTool


class TransactionCategorizerTool(BaseTool):
    name = "TransactionCategorizerTool"

    def validate(self, params: dict[str, Any]) -> None:
        description = str(params.get("description", "")).strip()
        if not description:
            raise ToolValidationError("TRANSACTION_DESCRIPTION_REQUIRED", "A transaction description is required.")

    def execute(self, params: dict[str, Any], context: dict[str, Any]) -> ToolResult:
        self.validate(params)
        description = str(params["description"]).strip()
        lowered = description.lower()

        category = "other"
        matched_keyword: str | None = None
        confidence = 0.5
        for candidate, keywords in TRANSACTION_KEYWORDS.items():
            for keyword in keywords:
                if keyword in lowered:
                    category = candidate
                    matched_keyword = keyword
                    confidence = 0.9
                    break
            if matched_keyword:
                break

        return ToolResult(
            summary=f"Category: {category}",
            data={
                "description": description,
                "category": category,
                "matched_keyword": matched_keyword,
                "confidence": confidence,
                "amount": params.get("amount"),
            },
            trace_message=f"Classified transaction as {category}.",
        )
