from __future__ import annotations

import re

from backend.config import MAX_CHARACTERS
from backend.errors import AppError


CARD_LIKE_PATTERN = re.compile(r"\b(\d{4})\d{4,11}(\d{4})\b")
CONTROL_CHAR_PATTERN = re.compile(r"[\x00-\x08\x0B-\x1F\x7F]")
WHITESPACE_PATTERN = re.compile(r"\s+")


def mask_sensitive_numbers(text: str) -> str:
    return CARD_LIKE_PATTERN.sub(lambda match: f"{match.group(1)}{'*' * 6}{match.group(2)}", text)


def mask_sensitive_payload(value):
    if isinstance(value, str):
        return mask_sensitive_numbers(value)
    if isinstance(value, list):
        return [mask_sensitive_payload(item) for item in value]
    if isinstance(value, dict):
        return {key: mask_sensitive_payload(item) for key, item in value.items()}
    return value


class SafetyGuard:
    def normalize(self, task_text: str) -> str:
        stripped = CONTROL_CHAR_PATTERN.sub(" ", task_text)
        stripped = WHITESPACE_PATTERN.sub(" ", stripped).strip()
        return stripped

    def validate(self, task_text: str) -> str:
        normalized = self.normalize(task_text)
        if not normalized:
            raise AppError("EMPTY_INPUT", "Task input cannot be empty.", 422)
        if len(normalized) > MAX_CHARACTERS:
            raise AppError(
                "INPUT_TOO_LONG",
                f"Task input must be {MAX_CHARACTERS} characters or fewer.",
                422,
                {"max_characters": MAX_CHARACTERS},
            )

        return normalized
