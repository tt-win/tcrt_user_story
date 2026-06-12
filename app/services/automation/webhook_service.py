from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database_models import (
    AutomationRun,
    AutomationRunStatus,
    AutomationRunTrigger,
    AutomationWebhook,
    AutomationWebhookDirection,
)


logger = logging.getLogger(__name__)


TERMINAL_STATUSES = {
    AutomationRunStatus.SUCCEEDED,
    AutomationRunStatus.FAILED,
    AutomationRunStatus.CANCELLED,
}

_STATUS_MAP: dict[str, AutomationRunStatus] = {
    "QUEUED": AutomationRunStatus.QUEUED,
    "RUNNING": AutomationRunStatus.RUNNING,
    "SUCCEEDED": AutomationRunStatus.SUCCEEDED,
    "SUCCESS": AutomationRunStatus.SUCCEEDED,
    "PASSED": AutomationRunStatus.SUCCEEDED,
    "COMPLETED": AutomationRunStatus.SUCCEEDED,
    "FAILED": AutomationRunStatus.FAILED,
    "FAILURE": AutomationRunStatus.FAILED,
    "ERROR": AutomationRunStatus.FAILED,
    "UNSTABLE": AutomationRunStatus.FAILED,
    "CANCELLED": AutomationRunStatus.CANCELLED,
    "ABORTED": AutomationRunStatus.CANCELLED,
    "UNKNOWN": AutomationRunStatus.UNKNOWN,
}


class AutomationWebhookServiceError(ValueError):
    """Base error from webhook service."""


class AutomationWebhookNotFoundError(AutomationWebhookServiceError):
    pass


class AutomationWebhookNameConflictError(AutomationWebhookServiceError):
    pass


class AutomationWebhookSignatureError(AutomationWebhookServiceError):
    pass


class AutomationWebhookInactiveError(AutomationWebhookServiceError):
    pass


class AutomationWebhookInboundOnlyError(AutomationWebhookServiceError):
    pass


class AutomationRunForWebhookNotFoundError(AutomationWebhookServiceError):
    pass


class AutomationWebhookSuiteBindingError(AutomationWebhookServiceError):
    """Raised when a script_group_id binding is invalid (wrong direction / team)."""


class AutomationWebhookNoSuiteBoundError(AutomationWebhookServiceError):
    """Raised when a /trigger call hits an inbound webhook with no bound suite."""


class AutomationWebhookSuiteNotFoundError(AutomationWebhookServiceError):
    """Raised when the webhook's bound script group no longer exists."""


_DEFAULT_AUTO_WEBHOOK_NAME = "TCRT default (auto)"


def build_inbound_webhook_url(webhook: AutomationWebhook) -> str:
    """Compose the public ``/run-status`` URL for ``webhook``.

    Returns an empty string when ``app.public_base_url`` isn't configured —
    callers treat empty as "skip baking into CI job XML", which keeps the
    existing graceful no-op path in the Jenkins template.
    """
    from app.config import get_settings

    base = (get_settings().app.public_base_url or "").rstrip("/")
    if not base:
        return ""
    return f"{base}/api/v1/webhooks/ci/{webhook.token}/run-status"


class AutomationWebhookService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # -------------------------------------------------------------- CRUD

    async def ensure_default_inbound_webhook(
        self,
        *,
        team_id: int,
        actor: str | None = None,
    ) -> AutomationWebhook:
        """Find-or-create the per-team auto-managed inbound webhook.

        Used by the Jenkins job renderer so the generated job XML can carry a
        baked TCRT_WEBHOOK_URL default — operators don't need to click around
        in the UI before single-script / suite Allure callbacks start working.
        Idempotent: subsequent calls return the same row (looked up by the
        sentinel name). If the operator deletes it from the UI, the next job
        render re-creates it.
        """
        result = await self.session.execute(
            select(AutomationWebhook).where(
                AutomationWebhook.team_id == team_id,
                AutomationWebhook.direction == AutomationWebhookDirection.INBOUND.value,
                AutomationWebhook.name == _DEFAULT_AUTO_WEBHOOK_NAME,
            )
        )
        existing = result.scalar_one_or_none()
        if existing is not None:
            return existing
        webhook, _token, _secret = await self.create_webhook(
            team_id=team_id,
            direction=AutomationWebhookDirection.INBOUND,
            name=_DEFAULT_AUTO_WEBHOOK_NAME,
            target_url=None,
            events=[],
            is_active=True,
            actor=actor or "system",
        )
        return webhook

    async def list_webhooks(self, *, team_id: int) -> list[AutomationWebhook]:
        result = await self.session.execute(
            select(AutomationWebhook)
            .where(
                AutomationWebhook.team_id == team_id,
                # Hide the system-managed run-status receiver baked into Jenkins
                # jobs; it's an internal sink, not a user-facing webhook.
                AutomationWebhook.name != _DEFAULT_AUTO_WEBHOOK_NAME,
            )
            .order_by(AutomationWebhook.id.desc())
        )
        return list(result.scalars().all())

    async def get_webhook(self, *, team_id: int, webhook_id: int) -> AutomationWebhook:
        result = await self.session.execute(
            select(AutomationWebhook).where(
                AutomationWebhook.id == webhook_id,
                AutomationWebhook.team_id == team_id,
            )
        )
        webhook = result.scalar_one_or_none()
        if webhook is None:
            raise AutomationWebhookNotFoundError(f"Webhook {webhook_id} not found")
        return webhook

    async def create_webhook(
        self,
        *,
        team_id: int,
        direction: AutomationWebhookDirection,
        name: str,
        target_url: str | None,
        events: list[str] | None,
        is_active: bool,
        actor: str | None,
        script_group_id: int | None = None,
    ) -> tuple[AutomationWebhook, str, str]:
        await self._ensure_unique_name(team_id=team_id, direction=direction, name=name)
        await self._validate_suite_binding(
            team_id=team_id, direction=direction, script_group_id=script_group_id
        )
        token = _generate_token()
        secret = _generate_secret()
        now = _utcnow()
        webhook = AutomationWebhook(
            team_id=team_id,
            direction=direction,
            name=name.strip(),
            token=token,
            secret=secret,
            target_url=(target_url or None),
            events_json=json.dumps(events or [], ensure_ascii=False, sort_keys=True),
            script_group_id=script_group_id,
            is_active=is_active,
            created_by=actor,
            updated_by=actor,
            created_at=now,
            updated_at=now,
        )
        self.session.add(webhook)
        await self.session.flush()
        await self.session.refresh(webhook)
        return webhook, token, secret

    async def update_webhook(
        self,
        *,
        team_id: int,
        webhook_id: int,
        actor: str | None,
        name: str | None = None,
        target_url: str | None = None,
        target_url_provided: bool = False,
        events: list[str] | None = None,
        is_active: bool | None = None,
        script_group_id: int | None = None,
        script_group_id_provided: bool = False,
    ) -> AutomationWebhook:
        webhook = await self.get_webhook(team_id=team_id, webhook_id=webhook_id)
        if name is not None and name != webhook.name:
            await self._ensure_unique_name(
                team_id=team_id,
                direction=AutomationWebhookDirection(webhook.direction),
                name=name,
                exclude_id=webhook.id,
            )
            webhook.name = name.strip()
        if target_url_provided:
            webhook.target_url = target_url or None
        if events is not None:
            webhook.events_json = json.dumps(events, ensure_ascii=False, sort_keys=True)
        if script_group_id_provided:
            await self._validate_suite_binding(
                team_id=team_id,
                direction=AutomationWebhookDirection(webhook.direction),
                script_group_id=script_group_id,
            )
            webhook.script_group_id = script_group_id
        if is_active is not None:
            webhook.is_active = bool(is_active)
        webhook.updated_by = actor
        webhook.updated_at = _utcnow()
        await self.session.flush()
        await self.session.refresh(webhook)
        return webhook

    async def delete_webhook(self, *, team_id: int, webhook_id: int) -> AutomationWebhook:
        webhook = await self.get_webhook(team_id=team_id, webhook_id=webhook_id)
        await self.session.delete(webhook)
        return webhook

    async def regenerate_secret(
        self, *, team_id: int, webhook_id: int, actor: str | None
    ) -> tuple[AutomationWebhook, str]:
        webhook = await self.get_webhook(team_id=team_id, webhook_id=webhook_id)
        secret = _generate_secret()
        webhook.secret = secret
        webhook.updated_by = actor
        webhook.updated_at = _utcnow()
        await self.session.flush()
        await self.session.refresh(webhook)
        return webhook, secret

    # -------------------------------------------------------------- inbound

    async def load_inbound_webhook(self, *, token: str) -> AutomationWebhook:
        cleaned = (token or "").strip()
        if not cleaned:
            raise AutomationWebhookNotFoundError("Missing webhook token")
        result = await self.session.execute(
            select(AutomationWebhook).where(AutomationWebhook.token == cleaned)
        )
        webhook = result.scalar_one_or_none()
        if webhook is None:
            raise AutomationWebhookNotFoundError("Webhook token not recognised")
        if AutomationWebhookDirection(webhook.direction) != AutomationWebhookDirection.INBOUND:
            raise AutomationWebhookInboundOnlyError("Webhook is not configured for inbound traffic")
        if not webhook.is_active:
            raise AutomationWebhookInactiveError("Webhook is disabled")
        return webhook

    async def load_triggered_run(
        self,
        *,
        webhook: AutomationWebhook,
        tcrt_run_id: str,
    ) -> AutomationRun:
        """Fetch a run THIS webhook triggered, keyed by its ``tcrt_correlation_id``.

        Backs the public ``GET /{token}/runs/{tcrt_run_id}`` polling endpoint:
        external software captures ``tcrt_correlation_id`` from the ``/trigger``
        response, then polls here until the status is terminal.

        Scoped to ``triggered_by_webhook_id == webhook.id`` (not just team) so a
        leaked token can only read back runs it fired itself — it can't enumerate
        UI-triggered runs or runs fired by a different webhook in the same team.
        """
        cleaned = (tcrt_run_id or "").strip()
        if not cleaned:
            raise AutomationRunForWebhookNotFoundError("Missing tcrt_run_id")
        result = await self.session.execute(
            select(AutomationRun)
            .where(
                AutomationRun.tcrt_correlation_id == cleaned,
                AutomationRun.triggered_by_webhook_id == webhook.id,
            )
            .limit(1)
        )
        run = result.scalar_one_or_none()
        if run is None:
            raise AutomationRunForWebhookNotFoundError(
                f"No run {cleaned} triggered by webhook {webhook.id}"
            )
        return run

    async def trigger_suite_run(
        self,
        *,
        webhook: AutomationWebhook,
        branch: str | None = None,
        runner_label: str | None = None,
        inputs: dict[str, str] | None = None,
        ci_provider: Any = None,
    ) -> AutomationRun:
        """Trigger the suite (script group) bound to ``webhook`` on CI.

        Reuses ``AutomationScriptGroupService.trigger_group_run`` (CI self-heal +
        provider trigger), tagging the run as WEBHOOK-triggered. Imported locally
        to avoid a circular import (script_group_service imports this module).
        Returns the freshly created QUEUED run; final status flows back via the
        existing ``/run-status`` inbound callback.
        """
        if not webhook.script_group_id:
            raise AutomationWebhookNoSuiteBoundError(
                "Webhook is not bound to a test suite"
            )

        from app.services.automation.script_group_service import (
            AutomationScriptGroupNotFoundError,
            AutomationScriptGroupService,
        )

        group_service = AutomationScriptGroupService(self.session)
        try:
            run = await group_service.trigger_group_run(
                team_id=webhook.team_id,
                group_id=webhook.script_group_id,
                actor=None,
                branch=branch,
                runner_label=runner_label,
                inputs=inputs,
                ci_provider=ci_provider,
                triggered_by=AutomationRunTrigger.WEBHOOK,
                triggered_by_webhook_id=webhook.id,
            )
        except AutomationScriptGroupNotFoundError as exc:
            raise AutomationWebhookSuiteNotFoundError(str(exc)) from exc

        now = _utcnow()
        webhook.last_triggered_at = now
        webhook.last_status = "TRIGGERED"
        await self.session.flush()
        return run

    def verify_signature(
        self,
        *,
        webhook: AutomationWebhook,
        body: bytes,
        signature: str | None,
        require_signature: bool = True,
    ) -> None:
        if not webhook.secret:
            # No secret configured = accept (caller may decide to require one)
            return
        if not signature:
            if not require_signature:
                # The URL token is treated as the bearer credential; a signature
                # is optional defence-in-depth. Used by /trigger so the copied
                # curl is a single line with no HMAC step.
                return
            raise AutomationWebhookSignatureError("Missing X-TCRT-Signature header")
        cleaned = signature.strip()
        # Accept either "sha256=<hex>" or "<hex>"
        if cleaned.lower().startswith("sha256="):
            cleaned = cleaned.split("=", 1)[1]
        expected = hmac.new(webhook.secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, cleaned):
            raise AutomationWebhookSignatureError("Signature mismatch")

    async def apply_run_status(
        self,
        *,
        webhook: AutomationWebhook,
        payload: dict[str, Any],
    ) -> AutomationRun:
        run = await self._lookup_run(team_id=webhook.team_id, payload=payload)

        raw_status = str(payload.get("status") or "").upper()
        new_status = _STATUS_MAP.get(raw_status, AutomationRunStatus.UNKNOWN)
        now = _utcnow()

        if payload.get("external_run_id") and not run.external_run_id:
            run.external_run_id = str(payload["external_run_id"])
        if payload.get("external_run_url") and not run.external_run_url:
            run.external_run_url = str(payload["external_run_url"])
        if payload.get("report_url"):
            run.report_url = str(payload["report_url"])

        started = _parse_iso_datetime(payload.get("started_at"))
        finished = _parse_iso_datetime(payload.get("finished_at"))
        if started and not run.started_at:
            run.started_at = started
        if finished:
            run.finished_at = finished
        duration_ms = payload.get("duration_ms")
        if isinstance(duration_ms, (int, float)) and duration_ms >= 0:
            run.duration_ms = int(duration_ms)
        elif run.started_at and run.finished_at and run.duration_ms is None:
            run.duration_ms = _duration_ms(run.started_at, run.finished_at)

        if payload.get("error_summary"):
            run.error_summary = str(payload["error_summary"])

        # Only allow forward transitions; terminal runs only update info, not status flip
        if AutomationRunStatus(run.status) not in TERMINAL_STATUSES:
            run.status = new_status
        run.last_synced_at = now
        run.updated_at = now

        webhook.last_triggered_at = now
        webhook.last_status = raw_status or "RECEIVED"

        # Backfill report_url from team's Result provider if the run reached terminal
        # state but the CI payload didn't include one.
        try:
            from app.services.automation.run_service import maybe_fill_report_url

            await maybe_fill_report_url(session=self.session, run=run)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Result provider backfill failed for run %s: %s", run.id, exc)

        await self.session.flush()
        await self.session.refresh(run)
        return run

    async def _lookup_run(self, *, team_id: int, payload: dict[str, Any]) -> AutomationRun:
        correlation_id = (payload.get("tcrt_run_id") or "").strip() if isinstance(payload.get("tcrt_run_id"), str) else ""
        external_run_id = (payload.get("external_run_id") or "").strip() if isinstance(payload.get("external_run_id"), str) else ""

        conditions = [AutomationRun.team_id == team_id]
        if correlation_id:
            conditions.append(AutomationRun.tcrt_correlation_id == correlation_id)
        elif external_run_id:
            conditions.append(AutomationRun.external_run_id == external_run_id)
        else:
            raise AutomationRunForWebhookNotFoundError(
                "Payload must include tcrt_run_id or external_run_id"
            )

        result = await self.session.execute(select(AutomationRun).where(and_(*conditions)).limit(1))
        run = result.scalar_one_or_none()
        if run is None:
            raise AutomationRunForWebhookNotFoundError(
                f"No matching run for team {team_id}; correlation={correlation_id or '-'}, external={external_run_id or '-'}"
            )
        return run

    async def _ensure_unique_name(
        self,
        *,
        team_id: int,
        direction: AutomationWebhookDirection,
        name: str,
        exclude_id: int | None = None,
    ) -> None:
        conditions = [
            AutomationWebhook.team_id == team_id,
            AutomationWebhook.direction == direction,
            AutomationWebhook.name == name.strip(),
        ]
        if exclude_id is not None:
            conditions.append(AutomationWebhook.id != exclude_id)
        result = await self.session.execute(select(AutomationWebhook.id).where(and_(*conditions)).limit(1))
        if result.scalar_one_or_none() is not None:
            raise AutomationWebhookNameConflictError(
                f"Webhook name '{name}' already exists for direction {direction.value}"
            )

    async def _validate_suite_binding(
        self,
        *,
        team_id: int,
        direction: AutomationWebhookDirection,
        script_group_id: int | None,
    ) -> None:
        if script_group_id is None:
            return
        if direction != AutomationWebhookDirection.INBOUND:
            raise AutomationWebhookSuiteBindingError(
                "script_group_id can only be set on INBOUND webhooks"
            )
        from app.models.database_models import AutomationScriptGroup

        result = await self.session.execute(
            select(AutomationScriptGroup.id).where(
                AutomationScriptGroup.id == script_group_id,
                AutomationScriptGroup.team_id == team_id,
            )
        )
        if result.scalar_one_or_none() is None:
            raise AutomationWebhookSuiteBindingError(
                f"Script group {script_group_id} not found for team {team_id}"
            )


# ----------------------------------------------------------------- helpers


def webhook_to_dict(
    webhook: AutomationWebhook,
    *,
    include_token: str | None = None,
    include_secret: str | None = None,
) -> dict[str, Any]:
    return {
        "id": webhook.id,
        "team_id": webhook.team_id,
        "direction": webhook.direction,
        "name": webhook.name,
        "token_fingerprint": _fingerprint(webhook.token),
        "secret_fingerprint": _fingerprint(webhook.secret),
        "target_url": webhook.target_url,
        "events": _load_events(webhook.events_json),
        "script_group_id": webhook.script_group_id,
        "is_active": webhook.is_active,
        "last_triggered_at": webhook.last_triggered_at,
        "last_status": webhook.last_status,
        "created_by": webhook.created_by,
        "updated_by": webhook.updated_by,
        "created_at": webhook.created_at,
        "updated_at": webhook.updated_at,
        # Token/secret are returned once at create / regenerate time:
        **({"token": include_token} if include_token is not None else {}),
        **({"secret": include_secret} if include_secret is not None else {}),
    }


def _fingerprint(value: str | None) -> str | None:
    if not value:
        return None
    if len(value) <= 4:
        return f"***{value}"
    return f"***{value[-4:]}"


def _load_events(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        data = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    return [str(item) for item in data if str(item).strip()]


def _generate_token() -> str:
    # url-safe, ~43 chars from 32 random bytes (fits in VARCHAR(64))
    return secrets.token_urlsafe(32)


def _generate_secret() -> str:
    # ~43 chars from 32 random bytes (fits in VARCHAR(128))
    return secrets.token_urlsafe(32)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _duration_ms(start: datetime, end: datetime) -> int | None:
    if not start or not end:
        return None
    delta = end - start
    return int(delta.total_seconds() * 1000)


def _parse_iso_datetime(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
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
