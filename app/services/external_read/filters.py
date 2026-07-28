"""Filter normalization helpers for the shared external read surface.

Moved verbatim from ``app/api/mcp.py`` (Phase 2). ``parse_run_types`` raises
:class:`~app.services.external_read.errors.UnknownRunTypeError` instead of an
``HTTPException``.
"""

from __future__ import annotations

from typing import Any, Iterable, Optional

from app.models.lark_types import Priority, TestResultStatus
from app.models.test_run_set import TestRunSetStatus
from app.services.external_read.errors import UnknownRunTypeError
from app.services.external_read.payloads import to_text


def normalize_priority_filter(raw: Optional[str]) -> Optional[Any]:
    if not raw:
        return None
    normalized = raw.strip().lower()
    if not normalized:
        return None
    for enum_item in Priority:
        if normalized in {enum_item.name.lower(), enum_item.value.lower()}:
            return enum_item
    return raw.strip()


def normalize_result_filter(raw: Optional[str]) -> Optional[Any]:
    if not raw:
        return None
    normalized = raw.strip().lower()
    if not normalized:
        return None
    for enum_item in TestResultStatus:
        if normalized in {enum_item.name.lower(), enum_item.value.lower()}:
            return enum_item
    return raw.strip()


def parse_status_filters(raw: Optional[str]) -> set[str]:
    if not raw:
        return set()
    return {item.strip().lower() for item in raw.split(",") if item.strip()}


def parse_run_types(raw: Optional[str]) -> set[str]:
    if not raw:
        return {"set", "unassigned", "adhoc"}
    values = {item.strip().lower() for item in raw.split(",") if item.strip()}
    if "all" in values:
        return {"set", "unassigned", "adhoc"}
    allowed = {"set", "unassigned", "adhoc"}
    unknown = values - allowed
    if unknown:
        raise UnknownRunTypeError(unknown)
    if not values:
        return {"set", "unassigned", "adhoc"}
    return values


def status_match(value: Any, filters: set[str]) -> bool:
    if not filters:
        return True
    return to_text(value).lower() in filters


def apply_archive_and_status(
    items: Iterable[Any],
    status_filters: set[str],
    *,
    include_archived: bool,
) -> list[Any]:
    result_items: list[Any] = []
    for item in items:
        item_status = to_text(getattr(item, "status", ""))
        if not include_archived and item_status.lower() == TestRunSetStatus.ARCHIVED.value:
            continue
        if not status_match(item_status, status_filters):
            continue
        result_items.append(item)
    return result_items
