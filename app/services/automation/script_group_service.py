from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database_models import (
    AutomationEnvironment,
    AutomationProviderSlot,
    AutomationRun,
    AutomationRunStatus,
    AutomationRunTrigger,
    AutomationScript,
    AutomationScriptGroup,
    AutomationScriptGroupJobType,
    SystemAutomationProvider,
    Team,
)
from app.services.automation.provider_credential_service import decrypt_credentials
from app.services.automation.provider_registry import get_active_provider_record, instantiate_provider
from app.services.automation.providers.base import CIProvider
from app.services.automation.webhook_service import (
    AutomationWebhookService,
    build_inbound_webhook_url,
)


class AutomationScriptGroupServiceError(ValueError):
    """Base error raised by automation script group service."""


class AutomationScriptGroupNotFoundError(AutomationScriptGroupServiceError):
    pass


class AutomationScriptGroupNameConflictError(AutomationScriptGroupServiceError):
    pass


class AutomationScriptGroupScriptNotFoundError(AutomationScriptGroupServiceError):
    pass


class AutomationScriptGroupCIJobMissingError(AutomationScriptGroupServiceError):
    pass


class AutomationScriptGroupCIApiError(AutomationScriptGroupServiceError):
    """Raised when the upstream CI (Jenkins / GH Actions) rejects a request."""


class AutomationEnvironmentRequiredError(AutomationScriptGroupServiceError):
    """Suite scripts declare required variables but no environment could be resolved."""

    def __init__(self, message: str, available: list[str] | None = None) -> None:
        super().__init__(message)
        self.available = available or []


class AutomationEnvironmentIncompleteError(AutomationScriptGroupServiceError):
    """Resolved environment is missing required variable values for some scripts."""

    def __init__(self, message: str, missing: dict[str, list[str]] | None = None) -> None:
        super().__init__(message)
        self.missing = missing or {}


logger = logging.getLogger(__name__)


def _wrap_ci_http_error(exc: httpx.HTTPStatusError, action: str) -> AutomationScriptGroupCIApiError:
    """Turn a raw httpx.HTTPStatusError into a domain error with a helpful hint.

    Common upstream symptoms:
    - 401 → credentials wrong / expired
    - 403 → user lacks permission (e.g. Job > Create on Jenkins) or CSRF crumb missing
    - 404 → wrong base_url / job_name_template producing an invalid path
    - 5xx → CI server itself is unhealthy
    """
    status_code = exc.response.status_code if exc.response is not None else 0
    url = str(exc.request.url) if exc.request is not None else "<unknown>"
    body_excerpt = ""
    try:
        body_excerpt = (exc.response.text or "")[:200] if exc.response is not None else ""
    except Exception:  # noqa: BLE001
        body_excerpt = ""
    hint = {
        401: "credentials rejected — verify the CI provider username + API token in 同步組織架構 → Org Automation Infra",
        403: (
            "CI server refused the request — usually the API-token user lacks Job/Create permission, "
            "or Jenkins CSRF protection rejected the request. Check the Jenkins user's role and the "
            "`csrf_protection_enabled` config."
        ),
        404: "URL not found — verify base_url, default_job_name and view_name_template config",
    }.get(status_code, f"CI server returned HTTP {status_code}")
    message = f"Failed to {action}: {hint}. URL: {url}"
    if body_excerpt:
        message += f". Body: {body_excerpt}"
    logger.warning("CI API error while %s: %s", action, message)
    return AutomationScriptGroupCIApiError(message)


class AutomationScriptGroupService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        # Populated by update_group: user-facing warnings from the last update
        # (e.g. a rename that discarded the suite's old Allure report).
        self.last_warnings: list[str] = []

    async def list_groups(
        self,
        *,
        team_id: int,
        q: str | None = None,
        cursor: int | None = None,
        limit: int = 50,
    ) -> tuple[list[AutomationScriptGroup], int | None, int]:
        limit = max(1, min(limit, 200))
        conditions = [AutomationScriptGroup.team_id == team_id]
        if cursor is not None:
            conditions.append(AutomationScriptGroup.id > cursor)
        if q:
            query = f"%{q.strip()}%"
            conditions.append(or_(AutomationScriptGroup.name.ilike(query), AutomationScriptGroup.description.ilike(query)))

        stmt = select(AutomationScriptGroup).where(and_(*conditions)).order_by(AutomationScriptGroup.id).limit(limit + 1)
        count_stmt = select(func.count(AutomationScriptGroup.id)).where(and_(*conditions))
        rows = list((await self.session.execute(stmt)).scalars().all())
        total = int((await self.session.execute(count_stmt)).scalar_one())
        next_cursor = rows[-1].id if len(rows) > limit else None
        return rows[:limit], next_cursor, total

    async def _get_team_name(self, team_id: int) -> str | None:
        """Look up the team name for Allure project-id-template expansion.

        Returns None when the team has been deleted out from under us; callers
        treat None as "fall back to default placeholder" so suite-job creation
        keeps working even on dangling references.
        """
        result = await self.session.execute(select(Team.name).where(Team.id == team_id))
        return result.scalar_one_or_none()

    async def _resolve_tcrt_webhook_url(self, team_id: int) -> str:
        """Get-or-create the team's auto-managed inbound webhook and build its URL.

        Used to bake a TCRT_WEBHOOK_URL default into the generated Jenkins job
        XML so the Jenkins agent doesn't need any agent-level configuration.
        Returns an empty string when ``app.public_base_url`` is unset — the
        Jinja template then renders an empty <defaultValue>, which the shell
        gracefully skips (the existing ``if [ -n "$TCRT_WEBHOOK_URL" ]`` guard).
        """
        webhook_service = AutomationWebhookService(self.session)
        webhook = await webhook_service.ensure_default_inbound_webhook(team_id=team_id)
        return build_inbound_webhook_url(webhook)

    async def get_group(self, *, team_id: int, group_id: int) -> AutomationScriptGroup:
        result = await self.session.execute(
            select(AutomationScriptGroup).where(
                AutomationScriptGroup.id == group_id,
                AutomationScriptGroup.team_id == team_id,
            )
        )
        group = result.scalar_one_or_none()
        if group is None:
            raise AutomationScriptGroupNotFoundError(f"Automation script group {group_id} not found")
        return group

    async def create_group(
        self,
        *,
        team_id: int,
        name: str,
        description: str | None,
        script_ids: list[int],
        actor: str | None = None,
        ci_provider: CIProvider | None = None,
    ) -> AutomationScriptGroup:
        await self._ensure_unique_name(team_id=team_id, name=name)
        scripts = await self.validate_script_paths(team_id=team_id, script_ids=script_ids)
        script_paths = [script.ref_path for script in scripts]
        provider_record, provider, provider_config = await self._resolve_ci_provider(team_id, ci_provider)

        now = _utcnow()
        group = AutomationScriptGroup(
            team_id=team_id,
            name=name,
            description=description,
            script_paths_json=json.dumps(script_paths, ensure_ascii=False),
            ref_repo=scripts[0].ref_repo or "",
            ci_job_type=_job_type_for_provider(provider_record.provider_type),
            created_by=actor,
            updated_by=actor,
            created_at=now,
            updated_at=now,
        )
        self.session.add(group)
        await self.session.flush()

        git_context = await _build_git_context_for_group(self.session, scripts)
        team_name = await self._get_team_name(team_id)
        tcrt_webhook_url = await self._resolve_tcrt_webhook_url(team_id)
        try:
            group.ci_job_name = await provider.create_suite_job(
                str(group.id),
                group.name,
                script_paths,
                _default_runner_label(provider_config, group.ci_job_type),
                git_context=git_context,
                team_id=team_id,
                team_name=team_name,
                tcrt_webhook_url=tcrt_webhook_url,
            )
        except httpx.HTTPStatusError as exc:
            raise _wrap_ci_http_error(exc, action="create suite job on CI") from exc
        group.updated_at = _utcnow()
        await self.session.flush()
        return group

    async def update_group(
        self,
        *,
        team_id: int,
        group_id: int,
        actor: str | None = None,
        name: str | None = None,
        description: str | None = None,
        description_provided: bool = False,
        script_ids: list[int] | None = None,
        ci_provider: CIProvider | None = None,
    ) -> AutomationScriptGroup:
        group = await self.get_group(team_id=team_id, group_id=group_id)
        next_name = name or group.name
        if name is not None and name != group.name:
            await self._ensure_unique_name(team_id=team_id, name=name, exclude_group_id=group.id)

        script_paths = _load_script_paths(group.script_paths_json)
        if script_ids is not None:
            scripts = await self.validate_script_paths(team_id=team_id, script_ids=script_ids)
            script_paths = [script.ref_path for script in scripts]

        should_sync_ci = name is not None or script_ids is not None
        if should_sync_ci:
            _, provider, provider_config = await self._resolve_ci_provider(team_id, ci_provider)
            scripts_for_git = scripts if script_ids is not None else await self.load_group_scripts(group=group)
            git_context = await _build_git_context_for_group(self.session, scripts_for_git)
            team_name = await self._get_team_name(team_id)
            tcrt_webhook_url = await self._resolve_tcrt_webhook_url(team_id)
            try:
                group.ci_job_name = await provider.update_suite_job(
                    str(group.id),
                    next_name,
                    script_paths,
                    _default_runner_label(provider_config, group.ci_job_type),
                    git_context=git_context,
                    team_id=team_id,
                    team_name=team_name,
                    tcrt_webhook_url=tcrt_webhook_url,
                    existing_job_name=group.ci_job_name,
                )
            except httpx.HTTPStatusError as exc:
                raise _wrap_ci_http_error(exc, action="update suite job on CI") from exc

            # Keep the suite's webhook job (if one exists) in sync too: same
            # config refresh, and a rename must relocate it (doRename) so it is
            # not orphaned. Suites that never got a webhook job (lazy) skip this.
            if group.ci_job_name_webhook:
                try:
                    group.ci_job_name_webhook = await provider.update_suite_job(
                        str(group.id),
                        next_name,
                        script_paths,
                        _default_runner_label(provider_config, group.ci_job_type),
                        git_context=git_context,
                        team_id=team_id,
                        team_name=team_name,
                        tcrt_webhook_url=tcrt_webhook_url,
                        existing_job_name=group.ci_job_name_webhook,
                        job_suffix="_hook",
                    )
                except httpx.HTTPStatusError as exc:
                    raise _wrap_ci_http_error(exc, action="update webhook suite job on CI") from exc

        # A rename changes the Allure project_id (it embeds the name slug) and
        # Allure has no rename API, so the old project is stranded. Reclaim it
        # best-effort and warn the caller that the suite's past Allure reports /
        # trend are gone (new runs rebuild under the new name).
        self.last_warnings = []
        if name is not None and next_name != group.name:
            from app.services.automation.allure_proxy import delete_renamed_project

            discarded_pid = await delete_renamed_project(
                session=self.session,
                team_id=team_id,
                suite_id=group.id,
                old_name=group.name,
                new_name=next_name,
            )
            if discarded_pid:
                self.last_warnings.append(
                    f"改名後，舊的 Allure 報表與趨勢歷史已清除（專案 {discarded_pid}）；"
                    "之後的執行會以新名稱重新建立報表。"
                )

        group.name = next_name
        if description_provided:
            group.description = description
        if script_ids is not None:
            group.script_paths_json = json.dumps(script_paths, ensure_ascii=False)
            group.ref_repo = scripts[0].ref_repo or ""
        group.updated_by = actor
        group.updated_at = _utcnow()
        await self.session.flush()
        return group

    async def delete_group(
        self,
        *,
        team_id: int,
        group_id: int,
        ci_provider: CIProvider | None = None,
    ) -> AutomationScriptGroup:
        group = await self.get_group(team_id=team_id, group_id=group_id)
        if group.ci_job_name or group.ci_job_name_webhook:
            _, provider, _ = await self._resolve_ci_provider(team_id, ci_provider)
            # Delete both trigger-scoped jobs (primary + webhook). delete_suite_job
            # swallows 404, so a never-created webhook job is a no-op.
            for job_name in (group.ci_job_name, group.ci_job_name_webhook):
                if not job_name:
                    continue
                try:
                    await provider.delete_suite_job(str(group.id), job_name)
                except httpx.HTTPStatusError as exc:
                    raise _wrap_ci_http_error(exc, action="delete suite job on CI") from exc

        # Reclaim the suite's Allure report storage (raw results, every report
        # build, trend history). Best-effort: a disabled/unreachable report
        # server must not block suite deletion, so this never raises.
        from app.services.automation.allure_proxy import delete_project_for_group

        await delete_project_for_group(
            session=self.session, team_id=team_id, group=group
        )

        await self.session.delete(group)
        await self.session.flush()
        return group

    async def resync_team_after_rename(
        self,
        *,
        team_id: int,
        old_team_name: str,
        new_team_name: str,
        ci_provider: CIProvider | None = None,
    ) -> None:
        """Re-sync a team's Jenkins jobs / view + Allure projects after a rename.

        The view name embeds the team name, and job + Allure project ids embed
        the team slug — all derived from the team name — so a rename strands the
        old view, jobs, and projects. For each suite this relocates the primary
        and webhook jobs to the new name (``doRename`` via ``update_suite_job``,
        preserving build history) and adds them to the new team view; then it
        deletes the now-orphaned old view and reclaims the old Allure projects.

        Best-effort per suite: a CI/report failure on one suite is logged and
        skipped so the rest still re-sync (the caller treats the whole thing as
        non-fatal — a rename must never be blocked by a CI/report outage).
        """
        if old_team_name == new_team_name:
            return
        groups = (
            await self.session.execute(
                select(AutomationScriptGroup).where(AutomationScriptGroup.team_id == team_id)
            )
        ).scalars().all()
        if not groups:
            return

        _, provider, provider_config = await self._resolve_ci_provider(team_id, ci_provider)
        tcrt_webhook_url = await self._resolve_tcrt_webhook_url(team_id)

        for group in groups:
            try:
                scripts = await self.load_group_scripts(group=group)
                git_context = await _build_git_context_for_group(self.session, scripts)
                label = _default_runner_label(provider_config, group.ci_job_type)
                script_paths = _load_script_paths(group.script_paths_json)
                # Relocate each existing trigger-scoped job to the new team name.
                # Mirror the trigger self-heal: if the old job is already gone on
                # CI (rename probe → 404), create it fresh under the new name
                # instead of failing — the suite still ends up with a valid job.
                for field, suffix in (("ci_job_name", ""), ("ci_job_name_webhook", "_hook")):
                    existing = getattr(group, field)
                    if not existing:
                        continue
                    try:
                        new_name = await provider.update_suite_job(
                            str(group.id),
                            group.name,
                            script_paths,
                            label,
                            git_context=git_context,
                            team_id=team_id,
                            team_name=new_team_name,
                            tcrt_webhook_url=tcrt_webhook_url,
                            existing_job_name=existing,
                            job_suffix=suffix,
                        )
                    except httpx.HTTPStatusError as exc:
                        if exc.response.status_code != 404:
                            raise
                        new_name = await provider.create_suite_job(
                            str(group.id),
                            group.name,
                            script_paths,
                            label,
                            git_context=git_context,
                            team_id=team_id,
                            team_name=new_team_name,
                            tcrt_webhook_url=tcrt_webhook_url,
                            job_suffix=suffix,
                        )
                    setattr(group, field, new_name)
            except Exception:  # best-effort: one suite must not abort the rest
                logger.warning(
                    "Suite %s CI re-sync after team %s rename failed (non-fatal)",
                    group.id,
                    team_id,
                    exc_info=True,
                )

        # The jobs now live in the new-name view; drop the orphaned old view.
        try:
            await provider.delete_view(team_id=team_id, team_name=old_team_name)
        except Exception:
            logger.warning(
                "Old team view delete after team %s rename failed (non-fatal)",
                team_id,
                exc_info=True,
            )

        # Reclaim the Allure projects stranded under the old team slug.
        try:
            from app.services.automation.allure_proxy import delete_projects_for_team_rename

            await delete_projects_for_team_rename(
                session=self.session,
                team_id=team_id,
                old_team_name=old_team_name,
                new_team_name=new_team_name,
            )
        except Exception:
            logger.warning(
                "Allure reclaim after team %s rename failed (non-fatal)",
                team_id,
                exc_info=True,
            )

    async def validate_script_paths(self, *, team_id: int, script_ids: list[int]) -> list[AutomationScript]:
        ordered_ids = _dedupe_ints(script_ids)
        if not ordered_ids:
            raise AutomationScriptGroupScriptNotFoundError("At least one automation script is required")

        result = await self.session.execute(
            select(AutomationScript).where(
                AutomationScript.team_id == team_id,
                AutomationScript.id.in_(ordered_ids),
            )
        )
        scripts_by_id = {script.id: script for script in result.scalars().all()}
        missing_ids = [script_id for script_id in ordered_ids if script_id not in scripts_by_id]
        if missing_ids:
            raise AutomationScriptGroupScriptNotFoundError(
                f"Automation scripts not found for team {team_id}: {missing_ids}"
            )
        scripts = [scripts_by_id[script_id] for script_id in ordered_ids]
        self._assert_single_repo(scripts)
        return scripts

    @staticmethod
    def _assert_single_repo(scripts: list[AutomationScript]) -> str:
        """A suite is bound to a single repo (B1). Returns the common repo slug."""
        repos = {(script.ref_repo or "") for script in scripts}
        if len(repos) > 1:
            shown = ", ".join(sorted(r or "(none)" for r in repos))
            raise AutomationScriptGroupServiceError(
                f"A suite must contain scripts from a single repository; got: {shown}"
            )
        return next(iter(repos), "")

    async def load_group_scripts(self, *, group: AutomationScriptGroup) -> list[AutomationScript]:
        script_paths = _load_script_paths(group.script_paths_json)
        if not script_paths:
            return []
        result = await self.session.execute(
            select(AutomationScript).where(
                AutomationScript.team_id == group.team_id,
                AutomationScript.ref_repo == (group.ref_repo or ""),
                AutomationScript.ref_path.in_(script_paths),
            )
        )
        scripts_by_path = {script.ref_path: script for script in result.scalars().all()}
        return [scripts_by_path[path] for path in script_paths if path in scripts_by_path]

    async def resolve_env_bundle(
        self,
        *,
        team_id: int,
        scripts: list[AutomationScript],
        environment: str | None,
    ) -> tuple[str | None, dict[str, dict[str, str]] | None]:
        """Resolve the automation environment for a suite run + build its bundle.

        - If no script declares a *required* variable → ``(None, None)``: env not
          needed, nothing injected (backward compatible).
        - Else resolve the environment by ``environment`` name, falling back to
          the team catalog default. Unresolved → ``AutomationEnvironmentRequiredError``.
        - Validate required coverage; unmet → ``AutomationEnvironmentIncompleteError``.

        Returns ``(env_name, bundle)`` where ``bundle = {ref_path: {KEY: value}}``
        (secret values already decrypted, ready to inject into the CI run).
        """
        from app.services.automation.environment_service import EnvironmentService

        svc = EnvironmentService(self.session)
        has_required = any(
            dv.get("required", True)
            for script in scripts
            for dv in svc._declared_vars(script)
        )
        if not has_required:
            return None, None

        envs = (
            await self.session.execute(
                select(AutomationEnvironment).where(AutomationEnvironment.team_id == team_id)
            )
        ).scalars().all()
        if environment:
            env = next((e for e in envs if e.name == environment), None)
        else:
            env = next((e for e in envs if e.is_default), None)
        if env is None:
            raise AutomationEnvironmentRequiredError(
                "此 suite 的腳本宣告了必填變數，請先選擇一個已設定的環境",
                available=[e.name for e in envs],
            )

        bundle, missing = await svc.resolve_effective_bundle(
            team_id=team_id, env_id=env.id, scripts=scripts
        )
        if missing:
            raise AutomationEnvironmentIncompleteError(
                f"環境 {env.name} 缺少必填變數值，請至 Script view 變數設定補齊",
                missing=missing,
            )
        return env.name, (bundle or None)

    async def trigger_group_run(
        self,
        *,
        team_id: int,
        group_id: int,
        actor: str | None = None,
        branch: str | None = None,
        runner_label: str | None = None,
        inputs: dict[str, str] | None = None,
        environment: str | None = None,
        ci_provider: CIProvider | None = None,
        triggered_by: AutomationRunTrigger = AutomationRunTrigger.USER,
        triggered_by_webhook_id: int | None = None,
        test_run_set_id: int | None = None,
    ) -> AutomationRun:
        """Internal helper used by the webhook service AND `TestRunSetAutomationService`.

        The Test Run Set trigger flow calls this method with ``test_run_set_id``
        so the resulting ``automation_runs`` row is linked back to its source
        set. The webhook flow leaves ``test_run_set_id=None`` (no set context).
        Public trigger paths on the Automation Hub have been removed; see
        `move-automation-execution-to-test-run-set`.
        """
        group = await self.get_group(team_id=team_id, group_id=group_id)
        if not group.ci_job_name:
            raise AutomationScriptGroupCIJobMissingError(f"Automation script group {group_id} has no CI job")

        provider_record, provider, provider_config = await self._resolve_ci_provider(team_id, ci_provider)
        script_paths = _load_script_paths(group.script_paths_json)
        tcrt_correlation_id = str(uuid.uuid4())
        resolved_branch = branch or str(provider_config.get("default_branch") or "main")
        resolved_runner_label = runner_label or _default_runner_label(provider_config, group.ci_job_type)
        scripts = await self.load_group_scripts(group=group)
        # Resolve the automation environment (if the suite's scripts declare
        # variables) and build the per-script effective-value bundle. Raises
        # AutomationEnvironment{Required,Incomplete}Error → mapped to 422 by the
        # API. Returns (None, None) when no env is needed (backward compatible).
        env_name, env_bundle = await self.resolve_env_bundle(
            team_id=team_id, scripts=scripts, environment=environment,
        )
        git_context = await _build_git_context_for_group(
            self.session, scripts, override_branch=resolved_branch
        )
        # Self-heal the CI job before triggering. Mirrors `_resolve_script_workflow`
        # for single scripts: the user may have deleted/renamed the job out-of-band
        # from the Jenkins UI, leaving our `ci_job_name` stale. update→404→create
        # restores it; on success we refresh `ci_job_name` because Jenkins may
        # canonicalise the name differently from our local slug.
        default_label = _default_runner_label(provider_config, group.ci_job_type)
        team_name = await self._get_team_name(team_id)
        tcrt_webhook_url = await self._resolve_tcrt_webhook_url(team_id)
        # Route by trigger source: webhook-triggered runs execute on the suite's
        # dedicated webhook job (`*_hook`), everything else on the primary job.
        # The two jobs keep separate build history / queue / Allure project. The
        # webhook job is created lazily here on the suite's first webhook trigger
        # (the same update→404→create self-heal that recovers a deleted job).
        is_webhook = triggered_by == AutomationRunTrigger.WEBHOOK
        job_suffix = "_hook" if is_webhook else ""
        try:
            resolved_job_name = await provider.update_suite_job(
                str(group.id), group.name, script_paths, default_label,
                git_context=git_context, team_id=team_id, team_name=team_name,
                tcrt_webhook_url=tcrt_webhook_url, job_suffix=job_suffix,
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 404:
                raise _wrap_ci_http_error(exc, action="ensure suite job on CI") from exc
            try:
                resolved_job_name = await provider.create_suite_job(
                    str(group.id), group.name, script_paths, default_label,
                    git_context=git_context, team_id=team_id, team_name=team_name,
                    tcrt_webhook_url=tcrt_webhook_url, job_suffix=job_suffix,
                )
            except httpx.HTTPStatusError as create_exc:
                raise _wrap_ci_http_error(create_exc, action="recreate suite job on CI") from create_exc
        except TypeError:
            # Provider doesn't accept git_context kwarg (older test fakes) —
            # fall back to the legacy positional signature.
            try:
                resolved_job_name = await provider.update_suite_job(
                    str(group.id), group.name, script_paths, default_label,
                )
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code != 404:
                    raise _wrap_ci_http_error(exc, action="ensure suite job on CI") from exc
                resolved_job_name = await provider.create_suite_job(
                    str(group.id), group.name, script_paths, default_label,
                )
        # Persist the resolved job name back to the trigger-scoped field.
        if is_webhook:
            group.ci_job_name_webhook = resolved_job_name
        else:
            group.ci_job_name = resolved_job_name

        run_inputs = {
            **(inputs or {}),
            "runner_label": resolved_runner_label,
            "test_paths": json.dumps(script_paths, ensure_ascii=False),
        }
        if git_context:
            if git_context.get("url"):
                run_inputs["git_url"] = git_context["url"]
            if git_context.get("branch"):
                run_inputs["git_branch"] = git_context["branch"]
            if git_context.get("token"):
                run_inputs["git_token"] = git_context["token"]
        # Inject the selected environment's per-script effective values as a
        # single namespaced bundle. The CIProvider marshals this as a masked
        # parameter (see automation-hub-provider-framework).
        if env_bundle:
            run_inputs["TCRT_ENV_BUNDLE"] = json.dumps(env_bundle, ensure_ascii=False)
        try:
            external_run = await provider.trigger_run(resolved_job_name, resolved_branch, run_inputs)
        except httpx.HTTPStatusError as exc:
            raise _wrap_ci_http_error(exc, action="trigger suite run on CI") from exc
        now = _utcnow()
        # Never persist the decrypted env bundle: mask it in the stored inputs.
        persisted_inputs = dict(run_inputs)
        if "TCRT_ENV_BUNDLE" in persisted_inputs:
            persisted_inputs["TCRT_ENV_BUNDLE"] = "***"
        run = AutomationRun(
            team_id=team_id,
            automation_script_id=None,
            script_group_id=group.id,
            test_run_set_id=test_run_set_id,
            provider_id=provider_record.id,
            external_run_id=external_run.external_run_id,
            external_run_url=external_run.external_run_url,
            status=AutomationRunStatus.QUEUED,
            triggered_by=triggered_by,
            triggered_by_user_id=actor,
            triggered_by_webhook_id=triggered_by_webhook_id,
            tcrt_correlation_id=tcrt_correlation_id,
            workflow_id=resolved_job_name,
            branch=resolved_branch,
            inputs_json=json.dumps(persisted_inputs, ensure_ascii=False),
            runner_label=resolved_runner_label,
            environment=env_name,
            started_at=now,
            created_at=now,
            updated_at=now,
        )
        self.session.add(run)
        await self.session.flush()
        return run

    async def _ensure_unique_name(
        self,
        *,
        team_id: int,
        name: str,
        exclude_group_id: int | None = None,
    ) -> None:
        conditions = [AutomationScriptGroup.team_id == team_id, AutomationScriptGroup.name == name]
        if exclude_group_id is not None:
            conditions.append(AutomationScriptGroup.id != exclude_group_id)
        result = await self.session.execute(select(AutomationScriptGroup.id).where(and_(*conditions)).limit(1))
        if result.scalar_one_or_none() is not None:
            raise AutomationScriptGroupNameConflictError(f"Automation script group name already exists: {name}")

    async def _resolve_ci_provider(
        self,
        team_id: int,
        ci_provider: CIProvider | None,
    ) -> tuple[SystemAutomationProvider, CIProvider, dict[str, Any]]:
        provider_record = await get_active_provider_record(team_id, AutomationProviderSlot.CI, self.session)
        provider_config = _load_json_object(provider_record.config_json)
        if ci_provider is not None:
            return provider_record, ci_provider, provider_config
        provider = instantiate_provider(
            provider_record.provider_type,
            provider_config,
            decrypt_credentials(provider_record.credentials_encrypted),
        )
        return provider_record, provider, provider_config


def script_group_to_dict(
    group: AutomationScriptGroup,
    *,
    scripts: list[AutomationScript] | None = None,
) -> dict[str, Any]:
    script_paths = _load_script_paths(group.script_paths_json)
    scripts = scripts or []
    return {
        "id": group.id,
        "team_id": group.team_id,
        "name": group.name,
        "description": group.description,
        "script_ids": [script.id for script in scripts],
        "script_paths": script_paths,
        "script_count": len(script_paths),
        "ci_job_name": group.ci_job_name,
        "ci_job_name_webhook": group.ci_job_name_webhook,
        "ci_job_type": group.ci_job_type,
        "created_by": group.created_by,
        "updated_by": group.updated_by,
        "created_at": group.created_at,
        "updated_at": group.updated_at,
        "scripts": [_script_summary_to_dict(script) for script in scripts],
    }


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


def _script_summary_to_dict(script: AutomationScript) -> dict[str, Any]:
    return {
        "id": script.id,
        "name": script.name,
        "script_format": script.script_format,
        "ref_path": script.ref_path,
        "ref_branch": script.ref_branch,
    }


async def _build_git_context_for_group(
    session: AsyncSession,
    scripts: list[AutomationScript],
    *,
    override_branch: str | None = None,
) -> dict[str, Any] | None:
    """Resolve git checkout context from the group's first script.

    Suites share a team-wide storage provider in practice (all scripts in a
    group point at the same repo), so the first script's provider is the
    authoritative source of GIT_URL / GIT_TOKEN / default branch. Imported
    from run_service to avoid duplicating the GitHub-vs-other-storage logic.
    """
    from app.services.automation.run_service import _build_git_context_for_script

    if not scripts:
        return None
    return await _build_git_context_for_script(
        session=session, script=scripts[0], override_branch=override_branch
    )


def _job_type_for_provider(provider_type: str) -> AutomationScriptGroupJobType:
    if provider_type == "ci:jenkins":
        return AutomationScriptGroupJobType.JENKINS
    raise AutomationScriptGroupServiceError(f"Unsupported CI provider type for script groups: {provider_type}")


def _default_runner_label(
    provider_config: dict[str, Any],
    job_type: AutomationScriptGroupJobType | None,
) -> str:
    fallback = "any" if job_type == AutomationScriptGroupJobType.JENKINS else "ubuntu-latest"
    return str(provider_config.get("default_runner_label") or fallback)


def _load_script_paths(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []
    return [str(item) for item in payload if str(item).strip()]


def _load_json_object(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _dedupe_ints(values: list[int]) -> list[int]:
    seen: set[int] = set()
    result: list[int] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)
