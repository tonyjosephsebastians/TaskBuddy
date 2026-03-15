from __future__ import annotations


class AppError(Exception):
    def __init__(self, error_code: str, message: str, status_code: int = 400, details: dict | None = None):
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.status_code = status_code
        self.details = details or {}


class ToolValidationError(AppError):
    def __init__(self, error_code: str, message: str, details: dict | None = None):
        super().__init__(error_code=error_code, message=message, status_code=422, details=details)


class RetryableToolError(AppError):
    def __init__(self, error_code: str, message: str, details: dict | None = None):
        super().__init__(error_code=error_code, message=message, status_code=503, details=details)
