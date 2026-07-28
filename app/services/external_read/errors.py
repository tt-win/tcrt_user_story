"""Domain exceptions for the shared external read surface.

These exceptions carry the canonical Chinese messages so that router-level
error mapping (Decision 3) can preserve the exact strings previously produced
by inline ``HTTPException`` raises in ``app/api/mcp.py``.
"""

from __future__ import annotations

from typing import Iterable


class ExternalReadError(Exception):
    """Base class for external read domain errors."""


class TeamNotFoundError(ExternalReadError):
    """Raised when a referenced team_id does not exist."""

    def __init__(self, team_id: int) -> None:
        self.team_id = team_id
        super().__init__(f"找不到團隊 ID {team_id}")


class TestCaseSetNotFoundError(ExternalReadError):
    """Raised when ``strict_set`` is requested for an unknown set_id."""

    def __init__(self, team_id: int, set_id: int) -> None:
        self.team_id = team_id
        self.set_id = set_id
        super().__init__(f"找不到團隊 {team_id} 的 Test Case Set {set_id}")


class TestCaseNotFoundError(ExternalReadError):
    """Raised when a test case detail lookup yields no row."""

    def __init__(self, team_id: int, case_id: int) -> None:
        self.team_id = team_id
        self.case_id = case_id
        super().__init__(f"找不到團隊 {team_id} 的 Test Case {case_id}")


class MissingLookupFilterError(ExternalReadError):
    """Raised when a cross-team lookup provides no filter at all."""

    def __init__(self) -> None:
        super().__init__("至少需要提供 q、test_case_number、ticket 其中之一")


class UnknownRunTypeError(ExternalReadError):
    """Raised when ``run_type`` contains unsupported values."""

    def __init__(self, unknown_values: Iterable[str]) -> None:
        self.unknown_values: list[str] = sorted(unknown_values)
        super().__init__(f"run_type 不支援的值: {', '.join(self.unknown_values)}")
