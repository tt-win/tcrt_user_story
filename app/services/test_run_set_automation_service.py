"""Test Run Set 觸發 automation suites 的 service。

`Automation Hub` 對外不再提供 run trigger 端點；觸發由 Test Run Set
detail 頁的「Run as Automation」CTA 統一入口。

`TestRunSetAutomationService.trigger_automation_suites(team_id, set_id)`
載入 Test Run Set 的 `automation_suite_ids` 列表，逐一呼叫
`AutomationScriptGroupService.trigger_group_run(...)` 並把
`test_run_set_id` 寫入 `automation_runs` 對應欄位（讓 run 可追溯回觸發的 set）。

See `openspec/changes/move-automation-execution-to-test-run-set/`.
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database_models import (
    AutomationProviderSlot,
    AutomationScriptGroup,
    TestRunSet as TestRunSetDB,
)
from app.services.automation.script_group_service import AutomationScriptGroupService
from app.services.automation.run_service import AutomationRunService


logger = logging.getLogger(__name__)


class TestRunSetAutomationError(ValueError):
    """Base error from Test Run Set automation trigger."""


class TestRunSetNotFoundError(TestRunSetAutomationError):
    pass


class TestRunSetEmptySuitesError(TestRunSetAutomationError):
    """Raised when Test Run Set has no automation suites to trigger."""


class TestRunSetSuiteCrossTeamError(TestRunSetAutomationError):
    """Raised when a suite id in `automation_suite_ids_json` belongs to a different team."""


class TestRunSetSuiteNotFoundError(TestRunSetAutomationError):
    """Raised when a suite id in `automation_suite_ids_json` no longer exists."""


class TestRunSetSuiteNotInSetError(TestRunSetAutomationError):
    """Raised when a requested suite is not associated with the Test Run Set."""


def _deserialize_suite_ids(raw: str | None) -> list[int]:
    """Inverse of `TestRunSetBase.automation_suite_ids` JSON serialization."""
    if not raw:
        return []
    import json

    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return []
    if not isinstance(parsed, list):
        return []
    return [int(x) for x in parsed if isinstance(x, int) and x > 0]


class TestRunSetAutomationService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def trigger_automation_suites(
        self,
        *,
        team_id: int,
        set_id: int,
        suite_id: int | None = None,
        actor: str | None = None,
    ) -> dict[str, list[int]]:
        """Trigger automation suites associated with the given Test Run Set.

        Returns:
            ``{"triggered_suite_ids": [int, ...], "run_ids": [int, ...]}``

        Raises:
            TestRunSetNotFoundError — set not found or wrong team
            TestRunSetEmptySuitesError — no suites in `automation_suite_ids_json`
            TestRunSetSuiteNotInSetError — requested suite is not associated with the set
            TestRunSetSuiteCrossTeamError — a suite id belongs to a different team
            TestRunSetSuiteNotFoundError — a suite id no longer exists in DB
        """
        set_db = await self._load_set_or_404(team_id=team_id, set_id=set_id)
        associated_suite_ids = _deserialize_suite_ids(set_db.automation_suite_ids_json)
        if not associated_suite_ids:
            raise TestRunSetEmptySuitesError(
                f"Test Run Set {set_id} has no automation suites to trigger."
            )
        if suite_id is not None:
            if suite_id not in associated_suite_ids:
                raise TestRunSetSuiteNotInSetError(
                    f"Automation suite {suite_id} is not associated with Test Run Set {set_id}."
                )
            suite_ids = [suite_id]
        else:
            suite_ids = associated_suite_ids

        # Validate every suite before triggering any — fail fast on cross-team or
        # missing ids so the user gets a clear error rather than a partial
        # "triggered some suites, others 404" report.
        for sid in suite_ids:
            suite_db = await self._load_suite_or_raise(
                team_id=team_id, suite_id=sid
            )
            if suite_db.team_id != team_id:
                raise TestRunSetSuiteCrossTeamError(
                    f"Automation suite {sid} does not belong to team {team_id}."
                )

        # Trigger each suite via the existing group-trigger helper, which
        # handles CI job self-heal + automation_runs write.
        group_service = AutomationScriptGroupService(self.session)
        triggered_suite_ids: list[int] = []
        run_ids: list[int] = []
        for sid in suite_ids:
            run = await group_service.trigger_group_run(
                team_id=team_id,
                group_id=sid,
                actor=actor,
                test_run_set_id=set_id,
            )
            await self.session.flush()
            triggered_suite_ids.append(sid)
            run_ids.append(int(run.id))

        logger.info(
            "Test Run Set %s triggered %d automation suite runs for team %s (actor=%s)",
            set_id,
            len(run_ids),
            team_id,
            actor,
        )
        return {"triggered_suite_ids": triggered_suite_ids, "run_ids": run_ids}

    async def _load_set_or_404(
        self, *, team_id: int, set_id: int
    ) -> TestRunSetDB:
        result = await self.session.execute(
            select(TestRunSetDB).where(
                TestRunSetDB.id == set_id, TestRunSetDB.team_id == team_id
            )
        )
        set_db = result.scalar_one_or_none()
        if set_db is None:
            raise TestRunSetNotFoundError(
                f"Test Run Set {set_id} not found for team {team_id}"
            )
        return set_db

    async def _load_suite_or_raise(
        self, *, team_id: int, suite_id: int
    ) -> AutomationScriptGroup:
        result = await self.session.execute(
            select(AutomationScriptGroup).where(
                AutomationScriptGroup.id == suite_id
            )
        )
        suite_db = result.scalar_one_or_none()
        if suite_db is None:
            raise TestRunSetSuiteNotFoundError(
                f"Automation suite {suite_id} no longer exists."
            )
        if suite_db.team_id != team_id:
            raise TestRunSetSuiteCrossTeamError(
                f"Automation suite {suite_id} does not belong to team {team_id}."
            )
        return suite_db
