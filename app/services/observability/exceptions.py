"""Exceptions for observability events."""

from __future__ import annotations


class ObservabilityError(Exception):
    """Base exception for observability errors."""
    pass


class UnknownEventCodeError(ObservabilityError):
    """Raised when event_code is not in catalog."""
    def __init__(self, event_code: str):
        self.event_code = event_code
        super().__init__(f"Unknown event_code: {event_code}")


class EventDetailsValidationError(ObservabilityError):
    """Raised when event details fail schema validation."""
    def __init__(self, event_code: str, message: str):
        self.event_code = event_code
        super().__init__(f"Event {event_code} details validation failed: {message}")


class AuditWriteError(ObservabilityError):
    """Raised when audit DB write fails."""
    def __init__(self, event_code: str, message: str):
        self.event_code = event_code
        super().__init__(f"Audit write failed for {event_code}: {message}")