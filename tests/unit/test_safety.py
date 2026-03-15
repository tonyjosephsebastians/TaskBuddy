import pytest

from backend.errors import AppError
from backend.safety.guard import SafetyGuard


def test_safety_guard_rejects_more_than_two_hundred_fifty_characters():
    guard = SafetyGuard()
    over_limit_text = "a" * 251

    with pytest.raises(AppError) as error:
        guard.validate(over_limit_text)

    assert error.value.error_code == "INPUT_TOO_LONG"
    assert error.value.details == {"max_characters": 250}


def test_safety_guard_accepts_exactly_two_hundred_fifty_characters():
    guard = SafetyGuard()
    valid_text = "a" * 250

    assert guard.validate(valid_text) == valid_text
