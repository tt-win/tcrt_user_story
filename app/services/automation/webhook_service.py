from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy import and_, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import ActionType, AuditSeverity, ResourceType, audit_service
from app.models.database_models import (
    AutomationRun,
    AutomationRunStatus,
    AutomationWebhook,
    AutomationWebhookDelivery,
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


class AutomationWebhookOutboundOnlyError(AutomationWebhookServiceError):
    pass


class AutomationRunForWebhookNotFoundError(AutomationWebhookServiceError):
    pass


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
            .where(AutomationWebhook.team_id == team_id)
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
    ) -> tuple[AutomationWebhook, str, str]:
        await self._ensure_unique_name(team_id=team_id, direction=direction, name=name)
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

    async def dispatch_event(
        self,
        *,
        team_id: int,
        event: str,
        data: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Send `event` to all active OUTBOUND webhooks for the team that are
        either subscribed to it or have an empty subscription list (wildcard).

        Returns one delivery dict per webhook attempted (status / status_code /
        duration_ms / message). Errors are swallowed per-webhook; the caller can
        log the aggregate.
        """
        result = await self.session.execute(
            select(AutomationWebhook).where(
                AutomationWebhook.team_id == team_id,
                AutomationWebhook.direction == AutomationWebhookDirection.OUTBOUND,
                AutomationWebhook.is_active.is_(True),
            )
        )
        webhooks = list(result.scalars().all())
        deliveries: list[dict[str, Any]] = []
        for webhook in webhooks:
            events = _load_events(webhook.events_json)
            if events and event not in events:
                continue
            if not webhook.target_url:
                continue
            deliveries.append(await self._deliver_event(webhook=webhook, event=event, data=data))
        return deliveries

    async def list_deliveries(
        self,
        *,
        team_id: int,
        webhook_id: int,
        limit: int = 50,
    ) -> list[AutomationWebhookDelivery]:
        await self.get_webhook(team_id=team_id, webhook_id=webhook_id)
        result = await self.session.execute(
            select(AutomationWebhookDelivery)
            .where(
                AutomationWebhookDelivery.team_id == team_id,
                AutomationWebhookDelivery.webhook_id == webhook_id,
            )
            .order_by(desc(AutomationWebhookDelivery.created_at), desc(AutomationWebhookDelivery.id))
            .limit(limit)
        )
        return list(result.scalars().all())

    async def replay_delivery(
        self,
        *,
        team_id: int,
        delivery_id: int,
    ) -> AutomationWebhookDelivery:
        original = await self.session.get(AutomationWebhookDelivery, delivery_id)
        if original is None or original.team_id != team_id:
            raise AutomationWebhookNotFoundError(f"Webhook delivery {delivery_id} not found")
        webhook = await self.get_webhook(team_id=team_id, webhook_id=original.webhook_id)
        if AutomationWebhookDirection(webhook.direction) != AutomationWebhookDirection.OUTBOUND:
            raise AutomationWebhookOutboundOnlyError("Only OUTBOUND webhooks can be replayed")
        if not webhook.is_active:
            raise AutomationWebhookInactiveError("Webhook is inactive")
        try:
            payload = json.loads(original.request_body or "{}")
        except json.JSONDecodeError as exc:
            raise AutomationWebhookServiceError("Stored delivery payload is not valid JSON") from exc
        event = str(payload.get("event") or original.event)
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        delivery = await self._deliver_event(webhook=webhook, event=event, data=data)
        replayed = await self.session.get(AutomationWebhookDelivery, delivery["delivery_row_id"])
        if replayed is None:
            raise AutomationWebhookServiceError("Replay delivery was not recorded")
        return replayed

    async def _deliver_event(
        self,
        *,
        webhook: AutomationWebhook,
        event: str,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        delivery_id = str(uuid.uuid4())
        payload = {
            "event": event,
            "delivery_id": delivery_id,
            "occurred_at": _utcnow().isoformat() + "Z",
            "team_id": webhook.team_id,
            "data": data,
        }
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
        body_text = body.decode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "X-TCRT-Event": event,
            "X-TCRT-Delivery": delivery_id,
            "X-TCRT-Signature": f"sha256={_sign_body(webhook.secret, body)}",
        }

        delivery = AutomationWebhookDelivery(
            team_id=webhook.team_id,
            webhook_id=webhook.id,
            event=event,
            delivery_id=delivery_id,
            target_url=webhook.target_url,
            status="PENDING",
            request_body=body_text,
            duration_ms=0,
            created_at=_utcnow(),
        )
        self.session.add(delivery)
        await self.session.flush()

        started = time.perf_counter()
        status_code: int | None = None
        response_body: str | None = None
        error_message: str | None = None
        try:
            async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
                response = await client.post(webhook.target_url, content=body, headers=headers)
            status_code = response.status_code
            response_body = response.text[:1024]
            message = response.text[:200] or response.reason_phrase
            ok = 200 <= response.status_code < 300
        except httpx.TimeoutException:
            message = "Request timed out"
            error_message = message
            ok = False
        except httpx.RequestError as exc:
            message = str(exc)[:200]
            error_message = message
            ok = False
        except Exception as exc:  # noqa: BLE001
            message = f"Unexpected error: {exc}"[:200]
            error_message = message
            ok = False

        duration_ms = int((time.perf_counter() - started) * 1000)
        delivery.status = "OK" if ok else "FAILED"
        delivery.status_code = status_code
        delivery.response_body = response_body
        delivery.error_message = error_message
        delivery.duration_ms = duration_ms
        delivery.completed_at = _utcnow()
        webhook.last_triggered_at = _utcnow()
        suffix = f" {status_code}" if status_code else ""
        webhook.last_status = f"{event.upper()}_{'OK' if ok else 'FAILED'}{suffix}"
        if not ok:
            await _log_delivery_failed(
                webhook=webhook,
                delivery=delivery,
                status_code=status_code,
                message=message,
            )
        return {
            "webhook_id": webhook.id,
            "delivery_row_id": delivery.id,
            "event": event,
            "delivery_id": delivery_id,
            "status": "OK" if ok else "FAILED",
            "status_code": status_code,
            "duration_ms": duration_ms,
            "message": message,
        }

    async def send_test_ping(self, *, team_id: int, webhook_id: int) -> dict[str, Any]:
        webhook = await self.get_webhook(team_id=team_id, webhook_id=webhook_id)
        if AutomationWebhookDirection(webhook.direction) != AutomationWebhookDirection.OUTBOUND:
            raise AutomationWebhookOutboundOnlyError("Test ping is only available for outbound webhooks")
        if not webhook.is_active:
            raise AutomationWebhookInactiveError("Webhook is disabled")
        if not webhook.target_url:
            raise AutomationWebhookServiceError("Outbound webhook requires target_url")

        return await self._deliver_event(
            webhook=webhook,
            event="test",
            data={
                "source": "tcrt",
                "webhook_id": webhook.id,
                "message": "Automation Hub outbound webhook test",
            },
        )

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

    def verify_signature(
        self,
        *,
        webhook: AutomationWebhook,
        body: bytes,
        signature: str | None,
    ) -> None:
        if not webhook.secret:
            # No secret configured = accept (caller may decide to require one)
            return
        if not signature:
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


# ----------------------------------------------------------------- helpers


async def dispatch_event_async(
    team_id: int,
    event: str,
    data: dict[str, Any],
) -> list[dict[str, Any]]:
    """Module-level convenience: opens a write session via the main boundary,
    dispatches the event to all matching OUTBOUND webhooks, and returns the
    deliveries. Safe to wrap with `asyncio.create_task()` for fire-and-forget
    semantics from API handlers.

    All errors are caught and logged; never raises.
    """
    from app.db_access.main import get_main_access_boundary

    boundary = get_main_access_boundary()

    async def _dispatch(session: AsyncSession) -> list[dict[str, Any]]:
        service = AutomationWebhookService(session)
        return await service.dispatch_event(team_id=team_id, event=event, data=data)

    try:
        return await boundary.run_write(_dispatch)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Outbound webhook dispatch failed for team=%s event=%s: %s",
            team_id,
            event,
            exc,
        )
        return []


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


def _sign_body(secret: str | None, body: bytes) -> str:
    return hmac.new((secret or "").encode("utf-8"), body, hashlib.sha256).hexdigest()


async def _log_delivery_failed(
    *,
    webhook: AutomationWebhook,
    delivery: AutomationWebhookDelivery,
    status_code: int | None,
    message: str,
) -> None:
    try:
        await audit_service.log_action(
            user_id=0,
            username="automation-webhook",
            role="system",
            action_type=ActionType.UPDATE,
            resource_type=ResourceType.AUTOMATION_WEBHOOK,
            resource_id=str(webhook.id),
            team_id=webhook.team_id,
            details={
                "event": delivery.event,
                "delivery_id": delivery.delivery_id,
                "status_code": status_code,
                "response_or_error": message[:1024],
                "duration_ms": delivery.duration_ms,
                "audit_event": "WEBHOOK_DELIVERY_FAILED",
            },
            action_brief=f"WEBHOOK_DELIVERY_FAILED: {delivery.event}",
            severity=AuditSeverity.WARNING,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to write webhook delivery audit log: %s", exc, exc_info=True)


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
