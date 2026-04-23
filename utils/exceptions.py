from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


VALIDATION_SEVERITIES = {"WARNING", "ERROR"}


@dataclass(slots=True)
class ValidationIssue:
    code: str
    message: str
    field_name: str | None = None
    severity: str = "ERROR"
    recoverable: bool = True
    user_feedback: str | None = None
    context: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        resolved_severity = str(self.severity or "ERROR").strip().upper()
        if resolved_severity not in VALIDATION_SEVERITIES:
            raise ValueError("severity must be WARNING or ERROR")
        self.severity = resolved_severity
        if self.user_feedback is None:
            self.user_feedback = self.message

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "field_name": self.field_name,
            "severity": self.severity,
            "recoverable": self.recoverable,
            "user_feedback": self.user_feedback,
            "context": dict(self.context),
        }


class GamblingAppException(Exception):
    def __init__(self, message: str, code: str = "APP_ERROR", recoverable: bool = False, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.recoverable = recoverable
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "recoverable": self.recoverable,
            "details": dict(self.details),
        }


class ValidationException(GamblingAppException):
    def __init__(self, message: str, code: str = "VALIDATION_ERROR", recoverable: bool = True, details: dict[str, Any] | None = None):
        super().__init__(message=message, code=code, recoverable=recoverable, details=details)


class RecoverableValidationException(ValidationException):
    def __init__(self, message: str, code: str = "RECOVERABLE_VALIDATION_ERROR", details: dict[str, Any] | None = None):
        super().__init__(message=message, code=code, recoverable=True, details=details)


class NonRecoverableValidationException(ValidationException):
    def __init__(self, message: str, code: str = "NON_RECOVERABLE_VALIDATION_ERROR", details: dict[str, Any] | None = None):
        super().__init__(message=message, code=code, recoverable=False, details=details)
