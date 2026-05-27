"""Background async tickers for Automation Hub.

Two long-running coroutines started at app startup:
- run_sync_loop: every SYNC_INTERVAL_SECONDS, polls CI providers for QUEUED/RUNNING
  runs across ALL teams. Backs §5.3 (60-second sync) using a lightweight asyncio
  task instead of refactoring the daily-only TaskScheduler.
- script_discovery_loop: every DISCOVERY_INTERVAL_SECONDS, walks teams that have
  a Storage provider configured and re-runs auto-discovery. Backs §4.3 (hourly
  background scan).

Both loops are best-effort: per-team errors are logged but never propagate, so
one bad team can't kill the ticker. They are gracefully stopped on shutdown via
the cancellation event.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from sqlalchemy import distinct, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db_access.main import get_main_access_boundary
from app.models.database_models import AutomationProviderSlot, TeamAutomationProvider
from app.services.automation.run_service import AutomationRunService
from app.services.automation.script_service import AutomationScriptService


logger = logging.getLogger(__name__)


SYNC_INTERVAL_SECONDS = 60
DISCOVERY_INTERVAL_SECONDS = 60 * 60  # 1 hour


class AutomationBackgroundManager:
    """Owns the asyncio background tasks for run sync + script discovery."""

    def __init__(self) -> None:
        self._tasks: list[asyncio.Task] = []
        self._stop_event: Optional[asyncio.Event] = None

    async def start(self) -> None:
        if self._tasks:
            return
        self._stop_event = asyncio.Event()
        self._tasks = [
            asyncio.create_task(self._run_sync_loop(), name="automation-run-sync"),
            asyncio.create_task(self._script_discovery_loop(), name="automation-script-discovery"),
        ]
        logger.info("Automation Hub background ticker started")

    async def stop(self) -> None:
        if not self._tasks:
            return
        if self._stop_event:
            self._stop_event.set()
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        self._tasks = []
        logger.info("Automation Hub background ticker stopped")

    async def _run_sync_loop(self) -> None:
        """Poll CI providers for in-flight runs across all teams every 60s."""
        assert self._stop_event is not None
        try:
            while not self._stop_event.is_set():
                try:
                    await self._sync_pending_for_all_teams()
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Automation run sync loop iteration failed: %s", exc)
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=SYNC_INTERVAL_SECONDS)
                except asyncio.TimeoutError:
                    pass
        except asyncio.CancelledError:
            return

    async def _script_discovery_loop(self) -> None:
        """Periodically walk teams with a Storage provider and rediscover scripts."""
        assert self._stop_event is not None
        # Wait a short delay so the app finishes boot before the first scan
        try:
            await asyncio.wait_for(self._stop_event.wait(), timeout=30)
            return
        except asyncio.TimeoutError:
            pass

        try:
            while not self._stop_event.is_set():
                try:
                    await self._discover_for_all_teams()
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Automation script discovery iteration failed: %s", exc)
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(), timeout=DISCOVERY_INTERVAL_SECONDS
                    )
                except asyncio.TimeoutError:
                    pass
        except asyncio.CancelledError:
            return

    # ------------------------------------------------------------------ workers

    async def _sync_pending_for_all_teams(self) -> None:
        boundary = get_main_access_boundary()

        async def _do(session: AsyncSession) -> None:
            service = AutomationRunService(session)
            await service.sync_pending_runs(team_id=None, limit=200)
            # Retry report_url pull for runs that went terminal before Jenkins
            # finished archiving allure-results (the terminal sync gets only one
            # shot; these runs are no longer in the QUEUED/RUNNING set above).
            await service.backfill_pending_reports(team_id=None, limit=200)

        try:
            await boundary.run_write(_do)
        except Exception as exc:  # noqa: BLE001
            logger.warning("sync_pending_runs (global) failed: %s", exc)

    async def _discover_for_all_teams(self) -> None:
        boundary = get_main_access_boundary()

        async def _list_teams(session: AsyncSession) -> list[int]:
            result = await session.execute(
                select(distinct(TeamAutomationProvider.team_id)).where(
                    TeamAutomationProvider.provider_slot == AutomationProviderSlot.STORAGE,
                    TeamAutomationProvider.is_active.is_(True),
                )
            )
            return [int(row[0]) for row in result.all() if row[0] is not None]

        try:
            team_ids = await boundary.run_read(_list_teams)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to enumerate teams for script discovery: %s", exc)
            return

        for team_id in team_ids:
            try:
                await self._discover_for_team(team_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Auto-discovery failed for team %s: %s", team_id, exc)

    async def _discover_for_team(self, team_id: int) -> None:
        boundary = get_main_access_boundary()

        async def _do(session: AsyncSession) -> None:
            service = AutomationScriptService(session)
            await service.sync_scripts(team_id=team_id, provider_id=None, branch=None, actor="scheduler")

        await boundary.run_write(_do)


# Module-level singleton, mirrors task_scheduler pattern.
automation_background_manager = AutomationBackgroundManager()
