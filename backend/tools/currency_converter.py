from __future__ import annotations

from typing import Any

from backend.config import SUPPORTED_CURRENCY_RATES
from backend.errors import ToolValidationError
from backend.models import ToolResult
from backend.tools.base import BaseTool


class CurrencyConverterTool(BaseTool):
    name = "CurrencyConverterTool"

    def validate(self, params: dict[str, Any]) -> None:
        amount = params.get("amount")
        try:
            numeric_amount = float(amount)
        except (TypeError, ValueError) as error:
            raise ToolValidationError("INVALID_AMOUNT", "A numeric amount is required.") from error

        if numeric_amount <= 0:
            raise ToolValidationError("INVALID_AMOUNT", "Amount must be greater than zero.")

        source = str(params.get("from_currency", "")).upper()
        target = str(params.get("to_currency", "")).upper()
        if source not in SUPPORTED_CURRENCY_RATES or target not in SUPPORTED_CURRENCY_RATES:
            raise ToolValidationError(
                "CURRENCY_NOT_SUPPORTED",
                "Only USD, CAD, GBP, and AUD are supported.",
                {"supported_currencies": list(SUPPORTED_CURRENCY_RATES.keys())},
            )

    def execute(self, params: dict[str, Any], context: dict[str, Any]) -> ToolResult:
        self.validate(params)
        amount = float(params["amount"])
        source = str(params["from_currency"]).upper()
        target = str(params["to_currency"]).upper()

        if source == target:
            converted = round(amount, 2)
            summary = f"{converted:.2f} {target}"
            trace_message = "Source and target currencies matched; value returned unchanged."
        else:
            usd_value = amount / SUPPORTED_CURRENCY_RATES[source]
            converted = round(usd_value * SUPPORTED_CURRENCY_RATES[target], 2)
            summary = f"{amount:.2f} {source} = {converted:.2f} {target}"
            trace_message = f"Converted {source} to {target} using static mock rates."

        return ToolResult(
            summary=summary,
            data={
                "amount": amount,
                "from_currency": source,
                "to_currency": target,
                "converted_amount": converted,
                "rates": SUPPORTED_CURRENCY_RATES,
            },
            trace_message=trace_message,
        )
