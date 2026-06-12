"""Linkage service for `automation_script_case_links`.

> **Marker sync is the only write path** for `automation_script_case_links`
> (see `openspec/changes/remove-manual-automation-link-ui-and-write-api/`).
> The historical `create_link` / `update_link` / `delete_link` write methods
> have been removed. The three public write methods below
> (`upsert_marker_link`, `delete_marker_link`, `refresh_script_link_count`)
> are called by `AutomationScriptService.sync_markers_for_team` after a
> successful marker parse. Manual write APIs are gone; the Automation
> Hub "Manage links" modals are gone.

`linked_test_case_count` is maintained exclusively by marker sync — there
is no longer any other writer to that column.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database_models import (
    AutomationRun,
    AutomationScript,
    AutomationScriptCaseLink,
    AutomationScriptLinkType,
    TestCaseLocal,
)
from app.services.automation.marker_sync import (
    MARKER_SYNC_CREATED_BY,
    build_marker_note,
    is_marker_sync_link,
    parse_marker_note,
)

logger = logging.getLogger(__name__)


class AutomationLinkageServiceError(ValueError):
    """Base error raised by automation linkage service."""


class AutomationLinkNotFoundError(AutomationLinkageServiceError):
    pass


class AutomationLinkageService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ------------------------------------------------------------------ reads


    async def list_links_for_script_detailed(
        self, *, team_id: int, script_id: int
    ) -> list[dict[str, Any]]:
        """List a script's links enriched with the linked case number + title.

        Powers the Automation Hub Test view "linked cases" list.
        """
        await self._get_script(team_id, script_id)
        result = await self.session.execute(
            select(AutomationScriptCaseLink, TestCaseLocal.test_case_number, TestCaseLocal.title)
            .join(TestCaseLocal, TestCaseLocal.id == AutomationScriptCaseLink.test_case_id)
            .where(
                AutomationScriptCaseLink.team_id == team_id,
                AutomationScriptCaseLink.automation_script_id == script_id,
            )
            .order_by(AutomationScriptCaseLink.id)
        )
        return [
            {**link_to_dict(link), "test_case_number": number, "title": title}
            for link, number, title in result.all()
        ]

    async def list_linked_automation(self, *, team_id: int, test_case_id: int) -> list[dict[str, Any]]:
        await self._ensure_test_case(team_id, test_case_id)
        result = await self.session.execute(
            select(AutomationScriptCaseLink, AutomationScript)
            .join(AutomationScript, AutomationScript.id == AutomationScriptCaseLink.automation_script_id)
            .where(
                AutomationScriptCaseLink.team_id == team_id,
                AutomationScriptCaseLink.test_case_id == test_case_id,
            )
            .order_by(AutomationScriptCaseLink.id)
        )
        rows = result.all()
        summaries: list[dict[str, Any]] = []
        for link, script in rows:
            # Run history is owned by Test Run Set after the run-orchestration
            # redesign (move-automation-execution-to-test-run-set). Scripts no
            # longer carry a direct `last_run_*`; callers should query the
            # Test Run Set runs endpoint for execution status.
            summaries.append(
                {
                    "script_id": script.id,
                    "name": script.name,
                    "script_format": script.script_format.value
                    if hasattr(script.script_format, "value")
                    else str(script.script_format),
                    "link_type": link.link_type,
                    "created_by": link.created_by,
                }
            )
        return summaries

    # ----------------------------------------------------- marker-sync writes

    async def upsert_marker_link(
        self,
        *,
        team_id: int,
        script: AutomationScript,
        test_case_id: int,
        link_type: AutomationScriptLinkType,
        marker_meta: dict[str, Any],
    ) -> tuple[AutomationScriptCaseLink, str]:
        """Upsert a link driven by an in-code `@pytest.mark.tcrt(...)` marker.

        `marker_meta` is the JSON payload produced by `build_marker_note`
        (keys: `test_name`, `line`, `marker_raw`).

        Returns `(link, action)` where `action` is one of:
          - `"created"` — new link row inserted
          - `"updated"` — existing `marker-sync` link drifted; refreshed
          - `"unchanged"` — existing `marker-sync` link already in sync
          - `"skipped_conflict"` — pre-existing non-marker link blocks
            the upsert; caller should record a `link_type_conflict` warning
        """
        note = build_marker_note(
            test_name=marker_meta["test_name"],
            line=marker_meta["line"],
            marker_raw=marker_meta["marker_raw"],
        )
        existing = await self._find_link(script_id=script.id, test_case_id=test_case_id)
        if existing is None:
            new_link = AutomationScriptCaseLink(
                team_id=team_id,
                automation_script_id=script.id,
                test_case_id=test_case_id,
                link_type=link_type,
                note=note,
                created_by=MARKER_SYNC_CREATED_BY,
                created_at=_utcnow(),
            )
            self.session.add(new_link)
            return new_link, "created"

        if not is_marker_sync_link(existing.created_by):
            # Manual / AI-confirmed link blocks the marker upsert.
            return existing, "skipped_conflict"

        changed = False
        if existing.link_type != link_type:
            existing.link_type = link_type
            changed = True
        if existing.note != note:
            existing.note = note
            changed = True
        return existing, "updated" if changed else "unchanged"

    async def delete_marker_link(
        self,
        *,
        team_id: int,
        script_id: int,
        test_case_id: int,
    ) -> bool:
        """Delete a single `marker-sync` link by `(script_id, test_case_id)`.

        Returns `True` if a row was deleted, `False` if no matching marker-sync
        link existed (caller may have already cleaned it up). Non-marker links
        are never deleted by this method.
        """
        existing = await self._find_link(script_id=script_id, test_case_id=test_case_id)
        if existing is None or not is_marker_sync_link(existing.created_by):
            return False
        await self.session.delete(existing)
        return True

    async def list_marker_link_case_ids(self, *, script_id: int) -> list[int]:
        """Return all `test_case_id` values for marker-sync links on a script.

        Used by the marker sync cleanup pass to identify orphan links.
        """
        result = await self.session.execute(
            select(AutomationScriptCaseLink.test_case_id).where(
                AutomationScriptCaseLink.automation_script_id == script_id,
                AutomationScriptCaseLink.created_by == MARKER_SYNC_CREATED_BY,
            )
        )
        return [row[0] for row in result.all()]

    async def refresh_script_link_count(self, script_id: int) -> int:
        """Recompute `AutomationScript.linked_test_case_count` for one script.

        Called by marker sync after upsert/delete; the only writer to that
        column now that manual link writes are gone.
        """
        from sqlalchemy import func as sa_func, update as sa_update

        count_result = await self.session.execute(
            select(sa_func.count(AutomationScriptCaseLink.id)).where(
                AutomationScriptCaseLink.automation_script_id == script_id
            )
        )
        count = int(count_result.scalar_one())
        await self.session.execute(
            sa_update(AutomationScript)
            .where(AutomationScript.id == script_id)
            .values(linked_test_case_count=count)
        )
        return count

    # ------------------------------------------------------------------ helpers

    async def _get_script(self, team_id: int, script_id: int) -> AutomationScript:
        result = await self.session.execute(
            select(AutomationScript).where(AutomationScript.id == script_id, AutomationScript.team_id == team_id)
        )
        script = result.scalar_one_or_none()
        if script is None:
            raise AutomationLinkNotFoundError(f"Automation script {script_id} not found")
        return script

    async def _ensure_test_case(self, team_id: int, test_case_id: int) -> TestCaseLocal:
        result = await self.session.execute(
            select(TestCaseLocal).where(TestCaseLocal.id == test_case_id, TestCaseLocal.team_id == team_id)
        )
        test_case = result.scalar_one_or_none()
        if test_case is None:
            raise AutomationLinkNotFoundError(f"Test case {test_case_id} not found")
        return test_case

    async def _find_link(
        self, *, script_id: int, test_case_id: int
    ) -> AutomationScriptCaseLink | None:
        result = await self.session.execute(
            select(AutomationScriptCaseLink).where(
                AutomationScriptCaseLink.automation_script_id == script_id,
                AutomationScriptCaseLink.test_case_id == test_case_id,
            )
        )
        return result.scalar_one_or_none()


def link_to_dict(link: AutomationScriptCaseLink) -> dict[str, Any]:
    return {
        "id": link.id,
        "team_id": link.team_id,
        "automation_script_id": link.automation_script_id,
        "test_case_id": link.test_case_id,
        "link_type": link.link_type,
        "note": link.note,
        "created_by": link.created_by,
        "created_at": link.created_at,
    }


def marker_link_payload(link: AutomationScriptCaseLink) -> dict[str, Any] | None:
    """Convenience: return the parsed `marker_note` JSON for a marker-sync link.

    Returns `None` for non-marker links (no JSON to extract) or if the note
    cannot be parsed.
    """
    if not is_marker_sync_link(link.created_by):
        return None
    return parse_marker_note(link.note)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)
