from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from sqlalchemy import and_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.database_models import (
    AutomationProviderSlot,
    AutomationRun,
    AutomationRunStatus,
    AutomationRunTrigger,
    AutomationScript,
    SystemAutomationProvider,
)
from app.services.automation.provider_credential_service import decrypt_credentials
from app.services.automation.provider_registry import (
    ProviderNotConfiguredError,
    ProviderRegistryError,
    get_active_provider_record,
    instantiate_provider,
)
from app.services.automation.providers.base import CIProvider, ResultProvider, RunStatusSnapshot
from app.services.observability import (
    emit_ops_event,
    Outcome,
)


logger = logging.getLogger(__name__)


TERMINAL_STATUSES = {
    AutomationRunStatus.SUCCEEDED,
    AutomationRunStatus.FAILED,
    AutomationRunStatus.CANCELLED,
}

# Map provider RunStatusSnapshot.status → AutomationRunStatus enum
_STATUS_MAP: dict[str, AutomationRunStatus] = {
    "QUEUED": AutomationRunStatus.QUEUED,
    "RUNNING": AutomationRunStatus.RUNNING,
    "SUCCEEDED": AutomationRunStatus.SUCCEEDED,
    "FAILED": AutomationRunStatus.FAILED,
    "CANCELLED": AutomationRunStatus.CANCELLED,
    "UNKNOWN": AutomationRunStatus.UNKNOWN,
}


def _pending_run_order_clauses() -> tuple[Any, ...]:
    """Return portable NULL-first ordering for pending-run synchronization."""

    return (
        case((AutomationRun.last_synced_at.is_(None), 0), else_=1).asc(),
        AutomationRun.last_synced_at.asc(),
        AutomationRun.id.asc(),
    )


class AutomationRunServiceError(ValueError):
    """Base error from automation run service."""


class AutomationRunNotFoundError(AutomationRunServiceError):
    pass


class AutomationScriptNotFoundForRunError(AutomationRunServiceError):
    """Raised when a single-script lookup fails (legacy trigger helper).

    Retained for backward compat with `AutomationRunService._load_script`,
    which is still used by legacy callers (e.g. webhook service). No new
    callers should be added; see `move-automation-execution-to-test-run-set`.
    """

    pass


class AutomationRunAlreadyTerminalError(AutomationRunServiceError):
    pass


class AutomationRunExternalIdMissingError(AutomationRunServiceError):
    pass


class AutomationRunService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ------------------------------------------------------------------ list / get

    async def list_runs(
        self,
        *,
        team_id: int,
        status: AutomationRunStatus | None = None,
        branch: str | None = None,
        triggered_by: AutomationRunTrigger | None = None,
        script_id: int | None = None,
        group_id: int | None = None,
        test_run_set_id: int | None = None,
        triggered_by_webhook_id: int | None = None,
        environment: str | None = None,
        cursor: int | None = None,
        limit: int = 50,
    ) -> tuple[list[AutomationRun], int | None, int]:
        limit = max(1, min(limit, 200))
        conditions = [AutomationRun.team_id == team_id]
        if status is not None:
            conditions.append(AutomationRun.status == status)
        if branch:
            conditions.append(AutomationRun.branch == branch.strip())
        if environment:
            conditions.append(AutomationRun.environment == environment.strip())
        if triggered_by is not None:
            conditions.append(AutomationRun.triggered_by == triggered_by)
        if script_id is not None:
            conditions.append(AutomationRun.automation_script_id == script_id)
        if group_id is not None:
            conditions.append(AutomationRun.script_group_id == group_id)
        if test_run_set_id is not None:
            conditions.append(AutomationRun.test_run_set_id == test_run_set_id)
        if triggered_by_webhook_id is not None:
            conditions.append(AutomationRun.triggered_by_webhook_id == triggered_by_webhook_id)
        if cursor is not None:
            conditions.append(AutomationRun.id < cursor)

        stmt = (
            select(AutomationRun)
            .options(selectinload(AutomationRun.script_group))
            .where(and_(*conditions))
            .order_by(AutomationRun.id.desc())
            .limit(limit + 1)
        )
        count_stmt = select(func.count(AutomationRun.id)).where(and_(*conditions))
        rows = list((await self.session.execute(stmt)).scalars().all())
        total = int((await self.session.execute(count_stmt)).scalar_one())
        next_cursor = rows[-1].id if len(rows) > limit else None
        return rows[:limit], next_cursor, total

    async def get_run(self, *, team_id: int, run_id: int) -> AutomationRun:
        result = await self.session.execute(
            select(AutomationRun)
            .options(selectinload(AutomationRun.script_group))
            .where(
                AutomationRun.id == run_id,
                AutomationRun.team_id == team_id,
            )
        )
        run = result.scalar_one_or_none()
        if run is None:
            raise AutomationRunNotFoundError(f"Automation run {run_id} not found")
        return run

    # ------------------------------------------------------------------ trigger

    # NOTE: 觸發 automation run 的公開方法已於 `move-automation-execution-to-test-run-set` 移除。
    # Automation Hub 對外不暴露任何 trigger 端點；suite 觸發由 `TestRunSetService` 透過
    # webhook service（既有 `trigger_group_run` 內部 helper）呼叫。
    # 歷史 row（automation_script_id NOT NULL）仍可查詢；status sync / cancel / reconcile 維持不變。

    # ------------------------------------------------------------------ cancel / reconcile

    async def cancel_run(
        self,
        *,
        team_id: int,
        run_id: int,
        actor: str | None = None,
        ci_provider: CIProvider | None = None,
    ) -> AutomationRun:
        run = await self.get_run(team_id=team_id, run_id=run_id)
        if AutomationRunStatus(run.status) in TERMINAL_STATUSES:
            raise AutomationRunAlreadyTerminalError(
                f"Run {run_id} is already in terminal status {run.status}"
            )
        if not run.external_run_id:
            raise AutomationRunExternalIdMissingError(
                f"Run {run_id} has no external_run_id; cannot cancel on CI side"
            )
        provider = ci_provider or await self._provider_from_run_record(run)
        try:
            await provider.cancel_run(run.external_run_id)
        except Exception as exc:
            await emit_ops_event(
                event_code="tcrt.ops.automation.run.cancel",
                outcome=Outcome.FAILURE,
                details={"run_id": run_id, "external_run_id": run.external_run_id, "error": str(exc)},
            )
            logger.warning("Provider cancel failed for run %s: %s", run_id, exc, exc_info=True)
            raise AutomationRunServiceError(f"Provider failed to cancel run: {exc}") from exc

        await emit_ops_event(
            event_code="tcrt.ops.automation.run.cancel",
            outcome=Outcome.SUCCESS,
            details={"run_id": run_id, "external_run_id": run.external_run_id},
        )

        now = _utcnow()
        run.status = AutomationRunStatus.CANCELLED
        run.finished_at = run.finished_at or now
        if run.started_at:
            run.duration_ms = run.duration_ms or _duration_ms(run.started_at, now)
        run.last_synced_at = now
        run.updated_at = now
        if actor:
            run.error_summary = (run.error_summary or "") + f"\nCancelled by user {actor}"
        await self.session.flush()
        await self.session.refresh(run)
        return run

    async def reconcile_run(
        self,
        *,
        team_id: int,
        run_id: int,
        external_run_id: str | None = None,
        actor: str | None = None,
        ci_provider: CIProvider | None = None,
    ) -> AutomationRun:
        run = await self.get_run(team_id=team_id, run_id=run_id)
        # Manual association: user supplied the external id
        if external_run_id and external_run_id.strip() and not run.external_run_id:
            run.external_run_id = external_run_id.strip()
            run.updated_at = _utcnow()
            await self.session.flush()
        # Best-effort sync against provider; if no external_run_id, mark UNKNOWN
        if not run.external_run_id:
            run.status = AutomationRunStatus.UNKNOWN
            run.last_synced_at = _utcnow()
            run.updated_at = _utcnow()
            await self.session.flush()
            await self.session.refresh(run)
            return run
        return await self._apply_status_sync(run=run, ci_provider=ci_provider)

    # ------------------------------------------------------------------ sync

    async def sync_run(
        self,
        *,
        team_id: int,
        run_id: int,
        ci_provider: CIProvider | None = None,
    ) -> AutomationRun:
        run = await self.get_run(team_id=team_id, run_id=run_id)
        if not run.external_run_id:
            raise AutomationRunExternalIdMissingError(
                f"Run {run_id} has no external_run_id; nothing to sync"
            )
        return await self._apply_status_sync(run=run, ci_provider=ci_provider)

    async def sync_pending_runs(
        self,
        *,
        team_id: int | None = None,
        limit: int = 50,
    ) -> list[AutomationRun]:
        conditions = [
            AutomationRun.status.in_([AutomationRunStatus.QUEUED, AutomationRunStatus.RUNNING]),
            AutomationRun.external_run_id.isnot(None),
        ]
        if team_id is not None:
            conditions.append(AutomationRun.team_id == team_id)
        stmt = (
            select(AutomationRun)
            .where(and_(*conditions))
            .order_by(*_pending_run_order_clauses())
            .limit(max(1, min(limit, 200)))
        )
        rows = list((await self.session.execute(stmt)).scalars().all())

        synced: list[AutomationRun] = []
        for run in rows:
            try:
                updated = await self._apply_status_sync(run=run, ci_provider=None)
                await emit_ops_event(
                    event_code="tcrt.ops.automation.run.sync",
                    outcome=Outcome.SUCCESS,
                    details={"run_id": run.id, "external_run_id": run.external_run_id},
                )
                synced.append(updated)
            except httpx.HTTPError as exc:
                # CI connectivity/HTTP errors (timeouts, unreachable host, 4xx/5xx)
                # are operational, not bugs — log concisely without a stack trace
                # so a flaky or relocated CI doesn't flood the log every tick.
                await emit_ops_event(
                    event_code="tcrt.ops.automation.run.sync",
                    outcome=Outcome.FAILURE,
                    details={"run_id": run.id, "external_run_id": run.external_run_id, "error": str(exc)},
                )
                logger.warning("Sync failed for run %s: %s", run.id, exc)
            except Exception as exc:  # noqa: BLE001
                await emit_ops_event(
                    event_code="tcrt.ops.automation.run.sync",
                    outcome=Outcome.FAILURE,
                    details={"run_id": run.id, "external_run_id": run.external_run_id, "error": str(exc)},
                )
                logger.warning("Sync failed for run %s: %s", run.id, exc, exc_info=True)
        return synced

    async def backfill_pending_reports(
        self,
        *,
        team_id: int | None = None,
        limit: int = 50,
        max_age_minutes: int = 30,
    ) -> list[AutomationRun]:
        """Retry ``report_url`` backfill for recently-terminal runs lacking one.

        The terminal-transition sync pulls Jenkins build artifacts the moment
        the build flips to a result, but Jenkins frequently hasn't finished
        archiving ``allure-results`` at that instant — so the pull 404s and the
        run, now terminal, leaves the QUEUED/RUNNING set ``sync_pending_runs``
        watches and is never revisited. The race is worst for fast single-script
        runs that complete between two sync ticks. This sweep gives the pull a
        few more chances until the artifacts land.

        Bounded by ``finished_at`` recency so we stop hammering the CI for runs
        that genuinely never produced results (e.g. infra failures before the
        test stage). CANCELLED runs are skipped — they have no artifacts.
        """
        cutoff = _utcnow() - timedelta(minutes=max_age_minutes)
        conditions = [
            AutomationRun.status.in_(
                [AutomationRunStatus.SUCCEEDED, AutomationRunStatus.FAILED]
            ),
            AutomationRun.report_url.is_(None),
            AutomationRun.external_run_id.isnot(None),
            AutomationRun.finished_at.isnot(None),
            AutomationRun.finished_at >= cutoff,
        ]
        if team_id is not None:
            conditions.append(AutomationRun.team_id == team_id)
        stmt = (
            select(AutomationRun)
            .where(and_(*conditions))
            .order_by(AutomationRun.finished_at.asc(), AutomationRun.id.asc())
            .limit(max(1, min(limit, 200)))
        )
        rows = list((await self.session.execute(stmt)).scalars().all())

        filled: list[AutomationRun] = []
        for run in rows:
            try:
                provider = await self._provider_from_run_record(run)
                await self._maybe_fill_report_url(run=run, ci_provider=provider)
                if run.report_url:
                    filled.append(run)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Report backfill failed for run %s: %s", run.id, exc, exc_info=True
                )
        return filled

    # ------------------------------------------------------------------ helpers

    async def _apply_status_sync(
        self,
        *,
        run: AutomationRun,
        ci_provider: CIProvider | None,
    ) -> AutomationRun:
        provider = ci_provider or await self._provider_from_run_record(run)
        snapshot = await provider.get_run_status(run.external_run_id)
        outcome = Outcome.SUCCESS if snapshot.status in ("SUCCEEDED", "FAILED", "CANCELLED") else Outcome.FAILURE
        await emit_ops_event(
            event_code="tcrt.ops.automation.run.sync",
            outcome=outcome,
            details={"run_id": run.id, "external_run_id": run.external_run_id, "status": snapshot.status},
        )
        merged = self._merge_status_snapshot(run=run, snapshot=snapshot)
        # Pass the live CI provider into the backfill helper so it can pull
        # build artifacts from Jenkins (cross-network firewalls usually
        # prevent the reverse — Jenkins pushing to TCRT — but TCRT always
        # has working auth to Jenkins for status polling).
        await self._maybe_fill_report_url(run=merged, ci_provider=provider)
        return merged

    async def _maybe_fill_report_url(
        self, *, run: AutomationRun, ci_provider: CIProvider | None = None
    ) -> None:
        """Backfill report_url; see ``maybe_fill_report_url`` docstring."""
        await maybe_fill_report_url(
            session=self.session, run=run, ci_provider=ci_provider
        )

    def _merge_status_snapshot(
        self,
        *,
        run: AutomationRun,
        snapshot: RunStatusSnapshot,
    ) -> AutomationRun:
        new_status = _STATUS_MAP.get(snapshot.status.upper(), AutomationRunStatus.UNKNOWN)
        now = _utcnow()
        run.status = new_status
        # Persist `external_run_id` upgrades — Jenkins starts a run as
        # `queue:NNNN` and switches to a build URL once an executor picks it
        # up. Queue items get garbage-collected ~5min after dispatch, so if
        # we don't write the upgraded ref back, the next sync hits 404.
        if snapshot.external_run_id and snapshot.external_run_id != run.external_run_id:
            run.external_run_id = snapshot.external_run_id
            if snapshot.external_run_url:
                run.external_run_url = snapshot.external_run_url
        elif snapshot.external_run_url and not run.external_run_url:
            run.external_run_url = snapshot.external_run_url
        snapshot_started = _parse_iso_datetime(snapshot.started_at)
        snapshot_finished = _parse_iso_datetime(snapshot.finished_at)
        if snapshot_started and not run.started_at:
            run.started_at = snapshot_started
        if snapshot_finished and not run.finished_at:
            run.finished_at = snapshot_finished
        if snapshot.duration_ms is not None and run.duration_ms is None:
            run.duration_ms = snapshot.duration_ms
        if new_status in TERMINAL_STATUSES:
            if run.started_at and not run.finished_at:
                run.finished_at = now
            if run.started_at and run.finished_at and run.duration_ms is None:
                run.duration_ms = _duration_ms(run.started_at, run.finished_at)
        if snapshot.error_summary and not run.error_summary:
            run.error_summary = snapshot.error_summary
        run.last_synced_at = now
        run.updated_at = now
        return run

    async def _load_script(self, *, team_id: int, script_id: int) -> AutomationScript:  # noqa: D401 — kept for backward compat
        """Load an AutomationScript by id+team; raises if missing.

        Retained for legacy callers (e.g. webhook service) that still resolve
        a single script. Not used by any public trigger path — the single
        script trigger has been removed; see `move-automation-execution-to-test-run-set`.
        """
        result = await self.session.execute(
            select(AutomationScript).where(
                AutomationScript.id == script_id,
                AutomationScript.team_id == team_id,
            )
        )
        script = result.scalar_one_or_none()
        if script is None:
            raise AutomationScriptNotFoundForRunError(
                f"Automation script {script_id} not found for team {team_id}"
            )
        return script

    async def _resolve_ci_provider(
        self,
        team_id: int,
        ci_provider: CIProvider | None,
    ) -> tuple[SystemAutomationProvider, CIProvider, dict[str, Any]]:
        """Resolve the team's active CI provider; pass-through if pre-injected.

        Kept on the service for `cancel_run` / `sync_run` / `reconcile_run`
        (which need to look up the provider from a stored `AutomationRun`).
        """
        provider_record = await get_active_provider_record(
            team_id, AutomationProviderSlot.CI, self.session
        )
        provider_config = _load_json_object(provider_record.config_json)
        if ci_provider is not None:
            return provider_record, ci_provider, provider_config
        provider = instantiate_provider(
            provider_record.provider_type,
            provider_config,
            decrypt_credentials(provider_record.credentials_encrypted),
        )
        return provider_record, provider, provider_config

    async def _provider_from_run_record(self, run: AutomationRun) -> CIProvider:
        # automation_runs.provider_id now FK to system_automation_providers
        # (CI providers are org-scoped). Look up by id in the system table.
        result = await self.session.execute(
            select(SystemAutomationProvider).where(SystemAutomationProvider.id == run.provider_id)
        )
        provider_record = result.scalar_one_or_none()
        if provider_record is None:
            raise ProviderRegistryError(
                f"Provider {run.provider_id} no longer exists; cannot sync run {run.id}"
            )
        provider_config = _load_json_object(provider_record.config_json)
        return instantiate_provider(
            provider_record.provider_type,
            provider_config,
            decrypt_credentials(provider_record.credentials_encrypted),
        )


async def load_result_provider(
    *,
    session: AsyncSession,
    team_id: int,
) -> ResultProvider | None:
    """Return the active Result provider for team_id, or None if not configured."""
    try:
        provider_record = await get_active_provider_record(
            team_id, AutomationProviderSlot.RESULT, session
        )
    except ProviderNotConfiguredError:
        return None
    provider_config = _load_json_object(provider_record.config_json)
    try:
        return instantiate_provider(
            provider_record.provider_type,
            provider_config,
            decrypt_credentials(provider_record.credentials_encrypted),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Failed to instantiate Result provider for team %s: %s", team_id, exc
        )
        return None


async def maybe_fill_report_url(
    *,
    session: AsyncSession,
    run: AutomationRun,
    ci_provider: CIProvider | None = None,
) -> None:
    """Populate ``run.report_url`` when the run reaches a terminal state.

    Two strategies, tried in order:

    1. **CI artifact pull → Allure proxy.** When the CI provider exposes
       ``download_build_artifacts_zip`` (currently Jenkins), TCRT pulls the
       build's archived ``allure-results`` and forwards them to the local
       Allure server. This is the only viable path when Jenkins can't reach
       TCRT (air-gapped / one-way-firewall topology); pull works because
       TCRT already has Jenkins credentials for status polling.

    2. **Legacy Result provider URL template.** Falls back to the team's
       ``result:allure`` provider's ``run_url_template`` (opt-in only — see
       ``allure_result.py``). Mostly a no-op now that the proxy is the
       canonical path.

    All exceptions are swallowed + logged so a flaky Allure server doesn't
    fail the sync loop. Idempotent: a subsequent call no-ops once
    ``report_url`` is set.
    """
    if run.report_url:
        return
    if AutomationRunStatus(run.status) not in TERMINAL_STATUSES:
        return
    if not run.external_run_id:
        return

    # Strategy 1 — TCRT pulls artifacts from the CI (Jenkins) and forwards.
    if ci_provider is not None and hasattr(ci_provider, "download_build_artifacts_zip"):
        try:
            archive_bytes = await ci_provider.download_build_artifacts_zip(run.external_run_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "CI artifact download failed for run %s: %s", run.id, exc
            )
            archive_bytes = None
        if archive_bytes:
            from app.services.automation.allure_proxy import (
                AllureProxyError,
                AllureProxyNotConfiguredError,
                upload_run_results,
            )

            try:
                await upload_run_results(
                    session=session, run=run, archive_bytes=archive_bytes
                )
                run.updated_at = _utcnow()
                return
            except AllureProxyNotConfiguredError:
                # operator hasn't set base_url — fall through to strategy 2
                pass
            except AllureProxyError as exc:
                logger.warning(
                    "Allure proxy upload failed for run %s: %s", run.id, exc
                )
                # fall through

    # Strategy 2 — legacy result-provider URL template (opt-in via config).
    result_provider = await load_result_provider(session=session, team_id=run.team_id)
    if result_provider is None:
        return
    try:
        url = await result_provider.get_run_report_url(run.external_run_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Result provider report URL lookup failed for run %s: %s", run.id, exc
        )
        return
    if url:
        run.report_url = url
        run.updated_at = _utcnow()


def automation_run_to_dict(run: AutomationRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "team_id": run.team_id,
        "automation_script_id": run.automation_script_id,
        "script_group_id": run.script_group_id,
        "script_group_name": run.script_group.name if getattr(run, "script_group", None) else None,
        "test_run_set_id": run.test_run_set_id,
        "provider_id": run.provider_id,
        "external_run_id": run.external_run_id,
        "external_run_url": run.external_run_url,
        "status": run.status,
        "triggered_by": run.triggered_by,
        "triggered_by_user_id": run.triggered_by_user_id,
        "triggered_by_webhook_id": run.triggered_by_webhook_id,
        "tcrt_correlation_id": run.tcrt_correlation_id,
        "ci_correlation_id": run.ci_correlation_id,
        "workflow_id": run.workflow_id,
        "branch": run.branch,
        "inputs": _load_json_object(run.inputs_json),
        "runner_label": run.runner_label,
        "environment": run.environment,
        "report_url": run.report_url,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "duration_ms": run.duration_ms,
        "error_summary": run.error_summary,
        "last_synced_at": run.last_synced_at,
        "created_at": run.created_at,
        "updated_at": run.updated_at,
    }


def _default_runner_label(provider_type: str, provider_config: dict[str, Any]) -> str:
    fallback = "any" if provider_type == "ci:jenkins" else "ubuntu-latest"
    return str(provider_config.get("default_runner_label") or fallback)


async def _resolve_tcrt_webhook_url_for_team(
    *, session: AsyncSession, team_id: int
) -> str:
    """Idempotently ensure the team's auto-managed inbound webhook + build URL.

    Mirrors ``AutomationScriptGroupService._resolve_tcrt_webhook_url`` so the
    single-script trigger path bakes the same value into Jenkins job XML as
    the suite path. Returns "" when ``app.public_base_url`` is unset.
    """
    from app.services.automation.webhook_service import (
        AutomationWebhookService,
        build_inbound_webhook_url,
    )

    service = AutomationWebhookService(session)
    webhook = await service.ensure_default_inbound_webhook(team_id=team_id)
    return build_inbound_webhook_url(webhook)


async def _build_git_context_for_script(
    *,
    session: AsyncSession,
    script: AutomationScript,
    override_branch: str | None = None,
) -> dict[str, Any] | None:
    """Build the Jenkins checkout context from a script's storage provider.

    Returns a dict with `url`, `branch`, optional `token`. Returns None if
    the storage provider can't be resolved or isn't a supported git host
    (e.g. local_git provider — those would need a different checkout path).

    NOTE: Single-script trigger has been removed (see
    `move-automation-execution-to-test-run-set`). This helper is retained
    solely because `AutomationScriptGroupService` still imports it
    via a late import (line 537) for group-level git context derivation.
    """

    from app.models.database_models import TeamAutomationProvider

    result = await session.execute(
        select(TeamAutomationProvider).where(TeamAutomationProvider.id == script.provider_id)
    )
    storage = result.scalar_one_or_none()
    if storage is None:
        return None
    config = _load_json_object(storage.config_json)
    provider_type = storage.provider_type or ""

    if provider_type == "storage:github":
        from app.services.automation.providers.github_storage import GitHubStorageConfig

        try:
            gh_config = GitHubStorageConfig.model_validate(config)
        except Exception:  # noqa: BLE001
            return None
        # A provider may hold several repos — pick the one this script came from.
        repo_entry = gh_config.repo_for((script.ref_repo or "").strip())
        # Default to GitHub.com; api_base_url is set for GHE — derive web URL
        # by stripping the `/api/v3` suffix if present.
        api_base = gh_config.api_base_url.rstrip("/")
        if api_base == "https://api.github.com":
            web_host = "https://github.com"
        else:
            web_host = api_base[: -len("/api/v3")] if api_base.endswith("/api/v3") else api_base
        url = f"{web_host}/{repo_entry.owner}/{repo_entry.repo}.git"
        creds = decrypt_credentials(storage.credentials_encrypted)
        token = creds.get("pat") if isinstance(creds, dict) else None
        branch = (override_branch or "").strip() or gh_config.branch_for(repo_entry)
        ctx: dict[str, Any] = {"url": url, "branch": branch}
        if token:
            ctx["token"] = token
        return ctx

    # Non-GitHub storage (e.g. local_git) — Jenkins host should have the
    # working dir pre-mounted; skip git_context so the legacy template path
    # (no Checkout stage) doesn't try to clone.
    return None


def _load_json_object(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _duration_ms(start: datetime, end: datetime) -> int | None:
    if not start or not end:
        return None
    delta = end - start
    return int(delta.total_seconds() * 1000)


def _parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    candidate = value.strip()
    if not candidate:
        return None
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed
