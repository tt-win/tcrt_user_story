"""Shared marker-sync utilities.

`automation_script_case_links` is the canonical table for automation ↔ manual
test case linkage. The `created_by` field carries a sentinel string that
identifies how a row was created. This module owns:

- The sentinel values (and their parsers)
- The `marker_note` JSON schema (`build_marker_note` / `parse_marker_note`)

Both `script_service` (orchestrator) and `linkage_service` (per-row write
interface) import from here. By keeping these utilities in a leaf module we
avoid a circular import between the two services.
"""
from __future__ import annotations

import json
from typing import Any


# Sentinel value stored in AutomationScriptCaseLink.created_by to mark records
# derived from in-code `@pytest.mark.tcrt` decorators.
MARKER_SYNC_CREATED_BY = "marker-sync"
AI_SUGGEST_PREFIX = "ai-suggest:"


def is_marker_sync_link(created_by: str | None) -> bool:
    return created_by == MARKER_SYNC_CREATED_BY


def is_ai_suggest_link(created_by: str | None) -> bool:
    return bool(created_by) and created_by.startswith(AI_SUGGEST_PREFIX)


def parse_ai_suggest_user_id(created_by: str | None) -> str | None:
    """Extract user id from `ai-suggest:<id>`; returns None if not the prefix."""
    if not created_by or not created_by.startswith(AI_SUGGEST_PREFIX):
        return None
    return created_by[len(AI_SUGGEST_PREFIX):] or None


def build_marker_note(*, test_name: str, line: int, marker_raw: str) -> str:
    """Serialize the JSON payload stored in AutomationScriptCaseLink.note.

    Schema is documented in `openspec/changes/add-automation-test-markers-and-test-view`
    and mirrored in `tools/skills/tcrt-automation-pomify/references/tcrt-format-rules.md` §5.1.2.
    """
    payload = {"test_name": test_name, "line": line, "marker_raw": marker_raw}
    return json.dumps(payload, ensure_ascii=False)


def parse_marker_note(note: str | None) -> dict[str, Any] | None:
    """Inverse of `build_marker_note`. Returns None on parse failure or empty input."""
    if not note:
        return None
    try:
        payload = json.loads(note)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None
