from backend.errors import ToolValidationError
from backend.tools.calculator import CalculatorTool
from backend.tools.currency_converter import CurrencyConverterTool
from backend.tools.text_processor import TextProcessorTool
from backend.tools.transaction_categorizer import TransactionCategorizerTool
from backend.tools.weather_mock import WeatherMockTool


def test_text_processor_uppercase():
    result = TextProcessorTool().execute({"operation": "uppercase", "text": "hello world"}, {})
    assert result.summary == "HELLO WORLD"


def test_text_processor_missing_text():
    tool = TextProcessorTool()
    try:
        tool.execute({"operation": "uppercase", "text": ""}, {})
    except ToolValidationError as error:
        assert error.error_code == "TEXT_TARGET_REQUIRED"
    else:
        raise AssertionError("Expected ToolValidationError")


def test_calculator_precedence():
    result = CalculatorTool().execute({"expression": "(3 + 5) * 2"}, {})
    assert result.data["result"] == 16.0


def test_calculator_divide_by_zero():
    tool = CalculatorTool()
    try:
        tool.execute({"expression": "10 / 0"}, {})
    except ToolValidationError as error:
        assert error.error_code == "DIVIDE_BY_ZERO"
    else:
        raise AssertionError("Expected ToolValidationError")


def test_weather_city_is_case_insensitive():
    result = WeatherMockTool().execute({"city": "toronto"}, {})
    assert result.data["city"] == "Toronto"


def test_weather_rejects_unsupported_city():
    tool = WeatherMockTool()
    try:
        tool.execute({"city": "paris"}, {})
    except ToolValidationError as error:
        assert error.error_code == "CITY_NOT_SUPPORTED"
    else:
        raise AssertionError("Expected ToolValidationError")


def test_currency_converter_converts_between_supported_codes():
    result = CurrencyConverterTool().execute({"amount": 100, "from_currency": "CAD", "to_currency": "USD"}, {})
    assert result.data["converted_amount"] == 74.07


def test_currency_converter_rejects_negative_amount():
    tool = CurrencyConverterTool()
    try:
        tool.execute({"amount": -1, "from_currency": "USD", "to_currency": "CAD"}, {})
    except ToolValidationError as error:
        assert error.error_code == "INVALID_AMOUNT"
    else:
        raise AssertionError("Expected ToolValidationError")


def test_transaction_categorizer_matches_keywords():
    result = TransactionCategorizerTool().execute({"description": "Starbucks downtown"}, {})
    assert result.data["category"] == "dining"
    assert result.data["confidence"] == 0.9


def test_transaction_categorizer_falls_back_to_other():
    result = TransactionCategorizerTool().execute({"description": "Unknown merchant inc"}, {})
    assert result.data["category"] == "other"
    assert result.data["confidence"] == 0.5
