from __future__ import annotations

import re

from backend.config import MAX_PLAN_STEPS, SUPPORTED_WEATHER_CITIES
from backend.errors import AppError
from backend.models import ParsedTask, ToolStep


CURRENCY_PATTERN = re.compile(r"(?P<amount>\d+(?:\.\d+)?)\s*(?P<currency>USD|CAD|GBP|AUD)\b", re.IGNORECASE)
TARGET_CURRENCY_PATTERN = re.compile(r"\bto\s+(USD|CAD|GBP|AUD)\b", re.IGNORECASE)
QUOTED_TEXT_PATTERN = re.compile(r'"([^"]+)"|\'([^\']+)\'')
MULTI_TASK_SPLIT_PATTERN = re.compile(r"\s+(?:and|then)\s+", re.IGNORECASE)
TEXT_CONVERT_PATTERN = re.compile(
    r"(?i)^(?:convert|change|make|turn)\s+(.+?)\s+to\s+(uppercase|upper case|upper|lowercase|lower case|lower|titlecase|title case|title)\b"
)
WORD_COUNT_PATTERN = re.compile(r"(?i)^(?:count words in|word count for|word count of|how many words in)\s+(.+)$")
CHAR_COUNT_PATTERN = re.compile(
    r"(?i)^(?:count characters in|character count for|character count of|char count for|char count of|how many characters in)\s+(.+)$"
)
SUBTRACT_FROM_PATTERN = re.compile(r"(?i)^subtract\s+(.+?)\s+from\s+(.+)$")
DIFFERENCE_PATTERN = re.compile(r"(?i)^(?:difference between)\s+(.+?)\s+and\s+(.+)$")
ADD_PREFIX_PATTERN = re.compile(r"(?i)^(?:add|sum|sum of|total of)\s+")
MULTIPLY_PREFIX_PATTERN = re.compile(r"(?i)^(?:multiply|product of)\s+")
DIVIDE_PREFIX_PATTERN = re.compile(r"(?i)^(?:divide|quotient of)\s+")
CALCULATOR_PREFIX_PATTERN = re.compile(r"(?i)^(?:calculate|what is|solve|compute)\s+")
CALCULATOR_CHARSET = set("0123456789.+-*/() ")
CALCULATOR_OPERATOR_WORDS = (
    "plus",
    "minus",
    "times",
    "multiplied by",
    "divided by",
    "over",
)
WEATHER_KEYWORDS = ("weather", "forecast", "temperature", "condition", "humidity")
TRANSACTION_KEYWORDS = ("categorize", "category", "transaction", "merchant", "classify", "classification", "spend")
MULTI_SUBTASK_ERROR = "Multi-tool execution supports up to 2 subtasks per request."


class TaskInterpreter:
    def interpret(self, original_text: str, sanitized_text: str) -> ParsedTask:
        parsed = ParsedTask(original_text=original_text, sanitized_text=sanitized_text)
        lowered = sanitized_text.lower()
        output_transform = self._extract_output_transform(lowered)

        subtasks = self._split_subtasks(sanitized_text)
        if len(subtasks) > 2:
            raise AppError("TASK_TOO_COMPLEX", MULTI_SUBTASK_ERROR, 422, {"max_subtasks": 2})

        if len(subtasks) == 2:
            result_transform = self._extract_output_transform(subtasks[1].lower())
            if result_transform:
                parsed.steps.append(self._build_primary_step(subtasks[0]))
                parsed.steps.append(
                    ToolStep(
                        tool_name="TextProcessorTool",
                        params={"operation": result_transform, "text_from_context_key": "previous_summary"},
                    )
                )
                return self._finalize(parsed)

        if len(subtasks) == 2 and self._is_transaction_currency_pipeline(subtasks, sanitized_text):
            transaction_step = self._build_transaction_step(subtasks[0])
            currency_step = self._build_currency_step(sanitized_text)
            if transaction_step and currency_step:
                parsed.steps.extend([transaction_step, currency_step])
                parsed.output_transform = output_transform
                return self._finalize(parsed)

        if len(subtasks) == 2:
            parsed.steps = [self._build_primary_step(subtask) for subtask in subtasks]
            parsed.metadata["combine_results"] = True
            parsed.metadata["subtasks"] = subtasks
            return self._finalize(parsed)

        direct_text_step = self._build_text_step(sanitized_text, direct_only=True)
        if direct_text_step:
            parsed.steps.append(direct_text_step)
            return self._finalize(parsed)

        parsed.steps.append(self._build_primary_step(sanitized_text))
        parsed.output_transform = output_transform
        if parsed.output_transform and parsed.steps[-1].tool_name != "TextProcessorTool":
            parsed.steps.append(
                ToolStep(
                    tool_name="TextProcessorTool",
                    params={"operation": parsed.output_transform, "text_from_context_key": "previous_summary"},
                )
            )
        return self._finalize(parsed)

    def _finalize(self, parsed: ParsedTask) -> ParsedTask:
        if len(parsed.steps) > MAX_PLAN_STEPS:
            raise AppError("TASK_TOO_COMPLEX", MULTI_SUBTASK_ERROR, 422, {"max_subtasks": 2})
        return parsed

    def _split_subtasks(self, text: str) -> list[str]:
        parts = [part.strip(" ,?:") for part in MULTI_TASK_SPLIT_PATTERN.split(text) if part.strip(" ,?:")]
        if len(parts) <= 1:
            return [text]
        if len(parts) > 2:
            return parts
        if self._is_transaction_currency_pipeline(parts, text):
            return parts
        if self._extract_output_transform(parts[1].lower()):
            return parts
        if all(self._looks_like_supported_subtask(part) for part in parts):
            return parts
        return [text]

    def _looks_like_supported_subtask(self, text: str) -> bool:
        return any(
            step is not None
            for step in (
                self._build_text_step(text, direct_only=False),
                self._build_weather_step(text),
                self._build_calculator_step(text),
                self._build_currency_step(text),
                self._build_transaction_step(text),
            )
        )

    def _is_transaction_currency_pipeline(self, subtasks: list[str], full_text: str) -> bool:
        first_task, second_task = subtasks
        first_lowered = first_task.lower()
        second_lowered = second_task.lower()
        return (
            any(keyword in first_lowered for keyword in TRANSACTION_KEYWORDS)
            and any(keyword in second_lowered for keyword in ("convert", "exchange", "currency", "usd", "cad", "gbp", "aud"))
            and CURRENCY_PATTERN.search(full_text) is not None
            and TARGET_CURRENCY_PATTERN.search(full_text) is not None
        )

    def _build_primary_step(self, text: str) -> ToolStep:
        direct_text_step = self._build_text_step(text, direct_only=False)
        if direct_text_step:
            return direct_text_step

        for builder in (
            self._build_weather_step,
            self._build_calculator_step,
            self._build_currency_step,
            self._build_transaction_step,
        ):
            step = builder(text)
            if step:
                return step

        raise AppError("UNSUPPORTED_TASK", "TaskBuddy could not match your task to a supported tool.", 422)

    def _extract_output_transform(self, lowered: str) -> str | None:
        if "uppercase the result" in lowered or "upper case the result" in lowered:
            return "uppercase"
        if "lowercase the result" in lowered or "lower case the result" in lowered:
            return "lowercase"
        if "titlecase the result" in lowered or "title case the result" in lowered:
            return "titlecase"
        return None

    def _build_text_step(self, text: str, direct_only: bool) -> ToolStep | None:
        lowered = text.lower()
        operation_map = {
            "uppercase": ["uppercase", "upper case", "upper"],
            "lowercase": ["lowercase", "lower case", "lower"],
            "titlecase": ["titlecase", "title case", "title"],
            "word_count": ["word count", "count words", "how many words"],
            "char_count": ["character count", "char count", "count characters", "how many characters"],
        }
        for operation, phrases in operation_map.items():
            if any(phrase in lowered for phrase in phrases):
                if direct_only and "result" in lowered:
                    return None
                return ToolStep("TextProcessorTool", {"operation": operation, "text": self._extract_text_target(text)})
        return None

    def _extract_text_target(self, text: str) -> str:
        quoted = QUOTED_TEXT_PATTERN.findall(text)
        for group in quoted:
            candidate = group[0] or group[1]
            if candidate.strip():
                return candidate.strip()

        convert_match = TEXT_CONVERT_PATTERN.match(text.strip())
        if convert_match:
            return self._clean_text_target(convert_match.group(1))

        word_count_match = WORD_COUNT_PATTERN.match(text.strip())
        if word_count_match:
            return self._clean_text_target(word_count_match.group(1))

        char_count_match = CHAR_COUNT_PATTERN.match(text.strip())
        if char_count_match:
            return self._clean_text_target(char_count_match.group(1))

        if ":" in text:
            return self._clean_text_target(text.split(":", 1)[1])

        cleaned = re.sub(
            r"(?i)\b(convert|change|make|turn|uppercase|upper case|upper|lowercase|lower case|lower|titlecase|title case|title|word count|count words|how many words|character count|char count|count characters|how many characters|of|for|to)\b",
            " ",
            text,
        )
        return self._clean_text_target(cleaned) or text.strip()

    def _clean_text_target(self, value: str) -> str:
        return value.strip().strip('"\'').strip()

    def _build_weather_step(self, text: str) -> ToolStep | None:
        lowered = text.lower()
        if not any(keyword in lowered for keyword in WEATHER_KEYWORDS):
            return None
        for city in SUPPORTED_WEATHER_CITIES:
            if city in lowered:
                return ToolStep("WeatherMockTool", {"city": city})
        return ToolStep("WeatherMockTool", {"city": lowered})

    def _build_calculator_step(self, text: str) -> ToolStep | None:
        expression = self._normalize_calculator_expression(text)
        lowered = text.lower()
        has_calculator_intent = (
            any(keyword in lowered for keyword in ("calculate", "what is", "solve", "compute", "add", "sum", "subtract", "difference", "multiply", "product", "divide", "quotient"))
            or any(keyword in lowered for keyword in CALCULATOR_OPERATOR_WORDS)
            or bool(set(text.strip()) <= CALCULATOR_CHARSET and any(operator in text for operator in ("+", "-", "*", "/")))
        )
        if not has_calculator_intent or not expression:
            return None
        if set(expression) - CALCULATOR_CHARSET:
            return None
        if any(operator in expression for operator in ("+", "-", "*", "/")):
            return ToolStep("CalculatorTool", {"expression": expression})
        return None

    def _normalize_calculator_expression(self, text: str) -> str:
        expression = text.strip().strip("?:")
        subtract_match = SUBTRACT_FROM_PATTERN.match(expression)
        if subtract_match:
            return f"{subtract_match.group(2).strip()} - {subtract_match.group(1).strip()}"

        difference_match = DIFFERENCE_PATTERN.match(expression)
        if difference_match:
            return f"{difference_match.group(1).strip()} - {difference_match.group(2).strip()}"

        if ADD_PREFIX_PATTERN.match(expression):
            expression = ADD_PREFIX_PATTERN.sub("", expression, count=1)
            expression = re.sub(r"(?i)\s+and\s+", " + ", expression)
        elif MULTIPLY_PREFIX_PATTERN.match(expression):
            expression = MULTIPLY_PREFIX_PATTERN.sub("", expression, count=1)
            expression = re.sub(r"(?i)\s+(?:and|by)\s+", " * ", expression)
        elif DIVIDE_PREFIX_PATTERN.match(expression):
            expression = DIVIDE_PREFIX_PATTERN.sub("", expression, count=1)
            expression = re.sub(r"(?i)\s+by\s+", " / ", expression)
        else:
            expression = CALCULATOR_PREFIX_PATTERN.sub("", expression, count=1)

        replacements = (
            (r"(?i)\bmultiplied by\b", " * "),
            (r"(?i)\bdivided by\b", " / "),
            (r"(?i)\bplus\b", " + "),
            (r"(?i)\bminus\b", " - "),
            (r"(?i)\btimes\b", " * "),
            (r"(?i)\bover\b", " / "),
        )
        for pattern, replacement in replacements:
            expression = re.sub(pattern, replacement, expression)
        return " ".join(expression.split())

    def _build_currency_step(self, text: str) -> ToolStep | None:
        lowered = text.lower()
        if not any(keyword in lowered for keyword in ("convert", "exchange", "currency", "rate")) and not CURRENCY_PATTERN.search(text):
            return None

        amount_match = CURRENCY_PATTERN.search(text)
        target_match = TARGET_CURRENCY_PATTERN.search(text)
        if not amount_match:
            return None

        source = amount_match.group("currency").upper()
        target = target_match.group(1).upper() if target_match else source
        return ToolStep(
            "CurrencyConverterTool",
            {"amount": amount_match.group("amount"), "from_currency": source, "to_currency": target},
        )

    def _build_transaction_step(self, text: str) -> ToolStep | None:
        lowered = text.lower()
        if not any(keyword in lowered for keyword in TRANSACTION_KEYWORDS):
            return None
        description = re.sub(r"(?i)\b(categorize|category|transaction|merchant|classify|classification|spend|spending)\b", "", text).strip(" :,-")
        amount_match = CURRENCY_PATTERN.search(text)
        amount = float(amount_match.group("amount")) if amount_match else None
        return ToolStep("TransactionCategorizerTool", {"description": description, "amount": amount})
