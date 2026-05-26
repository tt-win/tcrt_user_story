from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

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


class AutomationRunServiceError(ValueError):
    """Base error from automation run service."""


class AutomationRunNotFoundError(AutomationRunServiceError):
    pass


class AutomationScriptNotFoundForRunError(AutomationRunServiceError):
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
        cursor: int | None = None,
        limit: int = 50,
    ) -> tuple[list[AutomationRun], int | None, int]:
        limit = max(1, min(limit, 200))
        conditions = [AutomationRun.team_id == team_id]
        if status is not None:
            conditions.append(AutomationRun.status == status)
        if branch:
            conditions.append(AutomationRun.branch == branch.strip())
        if triggered_by is not None:
            conditions.append(AutomationRun.triggered_by == triggered_by)
        if script_id is not None:
            conditions.append(AutomationRun.automation_script_id == script_id)
        if group_id is not None:
            conditions.append(AutomationRun.script_group_id == group_id)
        if cursor is not None:
            conditions.append(AutomationRun.id < cursor)

        stmt = (
            select(AutomationRun)
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
            select(AutomationRun).where(
                AutomationRun.id == run_id,
                AutomationRun.team_id == team_id,
            )
        )
        run = result.scalar_one_or_none()
        if run is None:
            raise AutomationRunNotFoundError(f"Automation run {run_id} not found")
        return run

    # ------------------------------------------------------------------ trigger

    async def trigger_script(
        self,
        *,
        team_id: int,
        script_id: int,
        actor: str | None = None,
        workflow_id: str | None = None,
        branch: str | None = None,
        runner_label: str | None = None,
        inputs: dict[str, Any] | None = None,
        ci_provider: CIProvider | None = None,
    ) -> AutomationRun:
        script = await self._load_script(team_id=team_id, script_id=script_id)
        provider_record, provider, provider_config = await self._resolve_ci_provider(team_id, ci_provider)

        resolved_branch = (branch or "").strip() or script.ref_branch or str(provider_config.get("default_branch") or "main")
        resolved_runner_label = (runner_label or script.preferred_runner_label or "").strip() or _default_runner_label(
            provider_record.provider_type, provider_config
        )
        # Load the script's STORAGE provider (per-team) to build the git
        # checkout context. Jenkins workspace doesn't have the repo by default;
        # the pipeline clones it during the Checkout stage using these values.
        git_context = await _build_git_context_for_script(
            session=self.session, script=script, override_branch=resolved_branch
        )
        tcrt_webhook_url = await _resolve_tcrt_webhook_url_for_team(
            session=self.session, team_id=team_id
        )
        resolved_workflow = await _resolve_script_workflow(
            provider=provider,
            script=script,
            workflow_id=workflow_id,
            default_runner_label=resolved_runner_label,
            git_context=git_context,
            tcrt_webhook_url=tcrt_webhook_url,
        )
        tcrt_correlation_id = str(uuid.uuid4())
        run_inputs = {
            **(inputs or {}),
            "tcrt_run_id": tcrt_correlation_id,
            "runner_label": resolved_runner_label,
            "test_paths": json.dumps([script.ref_path], ensure_ascii=False),
        }
        # Pass git checkout info as build parameters too — `JenkinsCIProvider
        # .trigger_run` maps these to GIT_URL / GIT_BRANCH / GIT_TOKEN params
        # on the Jenkins job (token is PasswordParameter → masked in console).
        if git_context:
            if git_context.get("url"):
                run_inputs["git_url"] = git_context["url"]
            if git_context.get("branch"):
                run_inputs["git_branch"] = git_context["branch"]
            if git_context.get("token"):
                run_inputs["git_token"] = git_context["token"]

        external_run = await provider.trigger_run(resolved_workflow, resolved_branch, run_inputs)
        now = _utcnow()
        run = AutomationRun(
            team_id=team_id,
            automation_script_id=script.id,
            script_group_id=None,
            provider_id=provider_record.id,
            external_run_id=external_run.external_run_id,
            external_run_url=external_run.external_run_url,
            status=AutomationRunStatus.QUEUED,
            triggered_by=AutomationRunTrigger.USER,
            triggered_by_user_id=actor,
            tcrt_correlation_id=tcrt_correlation_id,
            workflow_id=resolved_workflow,
            branch=resolved_branch,
            inputs_json=json.dumps(run_inputs, ensure_ascii=False),
            runner_label=resolved_runner_label,
            started_at=now,
            created_at=now,
            updated_at=now,
        )
        self.session.add(run)
        await self.session.flush()
        await self.session.refresh(run)
        return run

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
            logger.warning("Provider cancel failed for run %s: %s", run_id, exc, exc_info=True)
            raise AutomationRunServiceError(f"Provider failed to cancel run: {exc}") from exc

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
            .order_by(AutomationRun.last_synced_at.asc().nullsfirst(), AutomationRun.id.asc())
            .limit(max(1, min(limit, 200)))
        )
        rows = list((await self.session.execute(stmt)).scalars().all())

        synced: list[AutomationRun] = []
        for run in rows:
            try:
                updated = await self._apply_status_sync(run=run, ci_provider=None)
                synced.append(updated)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Sync failed for run %s: %s", run.id, exc, exc_info=True)
        return synced

    # ------------------------------------------------------------------ helpers

    async def _apply_status_sync(
        self,
        *,
        run: AutomationRun,
        ci_provider: CIProvider | None,
    ) -> AutomationRun:
        provider = ci_provider or await self._provider_from_run_record(run)
        snapshot = await provider.get_run_status(run.external_run_id)
        merged = self._merge_status_snapshot(run=run, snapshot=snapshot)
        await self._maybe_fill_report_url(run=merged)
        return merged

    async def _maybe_fill_report_url(self, *, run: AutomationRun) -> None:
        """Backfill report_url from team's Result provider when run is terminal."""
        await maybe_fill_report_url(session=self.session, run=run)

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

    async def _load_script(self, *, team_id: int, script_id: int) -> AutomationScript:
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


async def maybe_fill_report_url(*, session: AsyncSession, run: AutomationRun) -> None:
    """Backfill run.report_url from the team's Result provider when run is terminal.

    No-op when the run already has a report_url, isn't terminal, has no external_run_id,
    or no Result provider is configured. Errors from the provider are swallowed (logged).
    """
    if run.report_url:
        return
    if AutomationRunStatus(run.status) not in TERMINAL_STATUSES:
        return
    if not run.external_run_id:
        return
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


async def _resolve_script_workflow(
    provider: CIProvider,
    script: AutomationScript,
    workflow_id: str | None,
    default_runner_label: str,
    git_context: dict[str, Any] | None = None,
    tcrt_webhook_url: str | None = None,
) -> str:
    requested = (workflow_id or "").strip()
    if requested:
        return requested

    job_id = f"script-{script.id}"
    job_name = _single_script_job_name(script)
    test_paths = [script.ref_path]
    # `git_context` flows into the job XML's GIT_URL / GIT_BRANCH defaultValue
    # so Jenkins-UI-direct triggers (without TCRT) still get a checkout.
    # `tcrt_webhook_url` is baked into the TCRT_WEBHOOK_URL PasswordParameter
    # default so the Jenkins post-stage callback works without per-agent env.
    # `JenkinsCIProvider.update_suite_job` accepts these kwargs; other providers
    # (GH Actions) get passed-through and ignore the kwargs they don't know.
    try:
        return await provider.update_suite_job(
            job_id, job_name, test_paths, default_runner_label,
            git_context=git_context, tcrt_webhook_url=tcrt_webhook_url,
        )
    except TypeError:
        # Provider implementation doesn't accept the kwargs yet — fall back
        # to legacy signature.
        try:
            return await provider.update_suite_job(job_id, job_name, test_paths, default_runner_label)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 404:
                raise AutomationRunServiceError(
                    f"Provider failed to update single-script CI job: {exc}"
                ) from exc
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code != 404:
            raise AutomationRunServiceError(
                f"Provider failed to update single-script CI job: {exc}"
            ) from exc

    try:
        return await provider.create_suite_job(
            job_id, job_name, test_paths, default_runner_label,
            git_context=git_context, tcrt_webhook_url=tcrt_webhook_url,
        )
    except TypeError:
        try:
            return await provider.create_suite_job(job_id, job_name, test_paths, default_runner_label)
        except httpx.HTTPStatusError as exc:
            raise AutomationRunServiceError(
                f"Provider failed to create single-script CI job: {exc}"
            ) from exc
    except httpx.HTTPStatusError as exc:
        raise AutomationRunServiceError(
            f"Provider failed to create single-script CI job: {exc}"
        ) from exc


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
        owner = str(config.get("owner") or "").strip()
        repo = str(config.get("repo") or "").strip()
        if not owner or not repo:
            return None
        # Default to GitHub.com; api_base_url is set for GHE — derive web URL
        # by stripping the `/api/v3` suffix if present.
        api_base = str(config.get("api_base_url") or "https://api.github.com").rstrip("/")
        if api_base == "https://api.github.com":
            web_host = "https://github.com"
        else:
            web_host = api_base[: -len("/api/v3")] if api_base.endswith("/api/v3") else api_base
        url = f"{web_host}/{owner}/{repo}.git"
        creds = decrypt_credentials(storage.credentials_encrypted)
        token = creds.get("pat") if isinstance(creds, dict) else None
        branch = (override_branch or "").strip() or str(config.get("default_branch") or "main")
        ctx: dict[str, Any] = {"url": url, "branch": branch}
        if token:
            ctx["token"] = token
        return ctx

    # Non-GitHub storage (e.g. local_git) — Jenkins host should have the
    # working dir pre-mounted; skip git_context so the legacy template path
    # (no Checkout stage) doesn't try to clone.
    return None


def _single_script_job_name(script: AutomationScript) -> str:
    name = (script.name or script.ref_path.rsplit("/", 1)[-1] or f"script-{script.id}").strip()
    return f"Script {name}"


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
