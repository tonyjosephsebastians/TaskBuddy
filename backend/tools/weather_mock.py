from __future__ import annotations

from typing import Any

from backend.config import SUPPORTED_WEATHER_CITIES
from backend.errors import ToolValidationError
from backend.models import ToolResult
from backend.tools.base import BaseTool


class WeatherMockTool(BaseTool):
    name = "WeatherMockTool"

    def validate(self, params: dict[str, Any]) -> None:
        city_key = str(params.get("city", "")).strip().lower()
        if city_key not in SUPPORTED_WEATHER_CITIES:
            raise ToolValidationError(
                "CITY_NOT_SUPPORTED",
                "Unsupported weather city.",
                {"supported_cities": [value["city"] for value in SUPPORTED_WEATHER_CITIES.values()]},
            )

    def execute(self, params: dict[str, Any], context: dict[str, Any]) -> ToolResult:
        self.validate(params)
        city_key = str(params["city"]).strip().lower()
        payload = SUPPORTED_WEATHER_CITIES[city_key]
        summary = (
            f"{payload['city']}: {payload['condition']}, "
            f"{payload['temperature_c']}C, humidity {payload['humidity_pct']}%."
        )
        return ToolResult(summary=summary, data=payload, trace_message=f"Returned mock weather for {payload['city']}.")
