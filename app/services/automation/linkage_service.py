from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database_models import (
    AutomationRun,
    AutomationScript,
    AutomationScriptCaseLink,
    AutomationScriptLinkType,
    TestCaseLocal,
)


class AutomationLinkageServiceError(ValueError):
    """Base error raised by automation linkage service."""


class AutomationLinkNotFoundError(AutomationLinkageServiceError):
    pass


class AutomationLinkAlreadyExistsError(AutomationLinkageServiceError):
    pass


class PrimaryAutomationLinkConflictError(AutomationLinkageServiceError):
    pass


class AutomationLinkageService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_link(
        self,
        *,
        team_id: int,
        script_id: int,
        test_case_id: int,
        link_type: AutomationScriptLinkType,
        note: str | None = None,
        actor: str | None = None,
    ) -> AutomationScriptCaseLink:
        script = await self._get_script(team_id, script_id)
        await self._ensure_test_case(team_id, test_case_id)
        await self._ensure_link_does_not_exist(script_id, test_case_id)
        if link_type == AutomationScriptLinkType.PRIMARY:
            await self._ensure_primary_available(team_id, test_case_id)

        link = AutomationScriptCaseLink(
            team_id=team_id,
            automation_script_id=script.id,
            test_case_id=test_case_id,
            link_type=link_type,
            note=note,
            created_by=actor,
            created_at=_utcnow(),
        )
        self.session.add(link)
        await self.session.flush()
        await self._refresh_script_link_count(script.id)
        await self.session.refresh(link)
        return link

    async def update_link(
        self,
        *,
        team_id: int,
        script_id: int,
        link_id: int,
        link_type: AutomationScriptLinkType | None = None,
        note: str | None = None,
    ) -> AutomationScriptCaseLink:
        link = await self._get_link(team_id, script_id, link_id)
        if link_type == AutomationScriptLinkType.PRIMARY and link.link_type != AutomationScriptLinkType.PRIMARY:
            await self._ensure_primary_available(team_id, link.test_case_id, exclude_link_id=link.id)
        if link_type is not None:
            link.link_type = link_type
        if note is not None:
            link.note = note
        await self.session.flush()
        await self.session.refresh(link)
        return link

    async def delete_link(self, *, team_id: int, script_id: int, link_id: int) -> None:
        link = await self._get_link(team_id, script_id, link_id)
        await self.session.delete(link)
        await self.session.flush()
        await self._refresh_script_link_count(script_id)

    async def list_links_for_script(
        self, *, team_id: int, script_id: int
    ) -> list[AutomationScriptCaseLink]:
        """List link rows for a single script (used by Test view link badges)."""
        await self._get_script(team_id, script_id)
        result = await self.session.execute(
            select(AutomationScriptCaseLink)
            .where(
                AutomationScriptCaseLink.team_id == team_id,
                AutomationScriptCaseLink.automation_script_id == script_id,
            )
            .order_by(AutomationScriptCaseLink.id)
        )
        return list(result.scalars().all())

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
            last_run = await self._latest_run(team_id=team_id, script_id=script.id)
            summaries.append(
                {
                    "script_id": script.id,
                    "name": script.name,
                    "script_format": script.script_format.value
                    if hasattr(script.script_format, "value")
                    else str(script.script_format),
                    "link_type": link.link_type,
                    "created_by": link.created_by,
                    "last_run_status": last_run.status.value if last_run and last_run.status else None,
                    "last_run_at": last_run.started_at if last_run else None,
                    "last_run_url": last_run.external_run_url if last_run else None,
                    "report_url": last_run.report_url if last_run else None,
                }
            )
        return summaries

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

    async def _get_link(self, team_id: int, script_id: int, link_id: int) -> AutomationScriptCaseLink:
        result = await self.session.execute(
            select(AutomationScriptCaseLink).where(
                AutomationScriptCaseLink.id == link_id,
                AutomationScriptCaseLink.team_id == team_id,
                AutomationScriptCaseLink.automation_script_id == script_id,
            )
        )
        link = result.scalar_one_or_none()
        if link is None:
            raise AutomationLinkNotFoundError(f"Automation script link {link_id} not found")
        return link

    async def _ensure_link_does_not_exist(self, script_id: int, test_case_id: int) -> None:
        result = await self.session.execute(
            select(AutomationScriptCaseLink.id).where(
                AutomationScriptCaseLink.automation_script_id == script_id,
                AutomationScriptCaseLink.test_case_id == test_case_id,
            )
        )
        if result.scalar_one_or_none() is not None:
            raise AutomationLinkAlreadyExistsError("Automation script already linked to this test case")

    async def _ensure_primary_available(
        self,
        team_id: int,
        test_case_id: int,
        exclude_link_id: int | None = None,
    ) -> None:
        conditions = [
            AutomationScriptCaseLink.team_id == team_id,
            AutomationScriptCaseLink.test_case_id == test_case_id,
            AutomationScriptCaseLink.link_type == AutomationScriptLinkType.PRIMARY,
        ]
        if exclude_link_id is not None:
            conditions.append(AutomationScriptCaseLink.id != exclude_link_id)
        result = await self.session.execute(select(AutomationScriptCaseLink.id).where(and_(*conditions)).limit(1))
        if result.scalar_one_or_none() is not None:
            raise PrimaryAutomationLinkConflictError("該 case 已有 PRIMARY link")

    async def _refresh_script_link_count(self, script_id: int) -> None:
        result = await self.session.execute(
            select(AutomationScript).where(AutomationScript.id == script_id)
        )
        script = result.scalar_one_or_none()
        if script is None:
            return
        count_result = await self.session.execute(
            select(AutomationScriptCaseLink.id).where(AutomationScriptCaseLink.automation_script_id == script_id)
        )
        script.linked_test_case_count = len(count_result.scalars().all())

    async def _latest_run(self, *, team_id: int, script_id: int) -> AutomationRun | None:
        result = await self.session.execute(
            select(AutomationRun)
            .where(AutomationRun.team_id == team_id, AutomationRun.automation_script_id == script_id)
            .order_by(AutomationRun.started_at.desc().nullslast(), AutomationRun.id.desc())
            .limit(1)
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


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)
