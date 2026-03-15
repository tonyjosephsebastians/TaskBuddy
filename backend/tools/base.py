from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from backend.models import ToolResult


class BaseTool(ABC):
    name: str

    @abstractmethod
    def validate(self, params: dict[str, Any]) -> None:
        raise NotImplementedError

    @abstractmethod
    def execute(self, params: dict[str, Any], context: dict[str, Any]) -> ToolResult:
        raise NotImplementedError
