"""Enumerations for observability events."""

from __future__ import annotations

from enum import Enum


class Impact(str, Enum):
    """Action impact/sensitivity level."""
    ROUTINE = "routine"
    NOTABLE = "notable"
    SENSITIVE = "sensitive"
    PRIVILEGED = "privileged"


class Outcome(str, Enum):
    """Operation outcome."""
    SUCCESS = "success"
    DENIED = "denied"
    FAILURE = "failure"
    PARTIAL = "partial"


class OpLevel(str, Enum):
    """System log level (stdlib logging levels)."""
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"