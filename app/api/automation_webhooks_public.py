from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Optional

from fastapi import APIRouter, File, Form, Header, HTTPException, Request, UploadFile, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db_access.main import MainAccessBoundary, get_main_access_boundary
from app.models.database_models import AutomationRun, AutomationRunStatus
from app.services.automation.allure_proxy import (
    AllureProxyError,
    AllureProxyNotConfiguredError,
    upload_run_results,
)
from app.services.automation.webhook_service import (
    AutomationRunForWebhookNotFoundError,
    AutomationWebhookInactiveError,
    AutomationWebhookInboundOnlyError,
    AutomationWebhookNotFoundError,
    AutomationWebhookService,
    AutomationWebhookSignatureError,
    dispatch_event_async,
)


_TERMINAL_RUN_STATUSES = {"SUCCEEDED", "FAILED", "CANCELLED"}
_RATE_LIMIT_CAPACITY = 120
_RATE_LIMIT_REFILL_PER_SECOND = _RATE_LIMIT_CAPACITY / 60
_rate_limit_buckets: dict[str, tuple[float, float]] = {}


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/webhooks/ci", tags=["automation-webhooks-public"])


class WebhookRunStatusResponse(BaseModel):
    run_id: int
    tcrt_correlation_id: str
    status: AutomationRunStatus
    external_run_id: Optional[str] = None
    deduped: bool = False

    model_config = ConfigDict(use_enum_values=True)


@router.post(
    "/{token}/run-status",
    response_model=WebhookRunStatusResponse,
)
async def ingest_run_status(
    token: str,
    request: Request,
    x_tcrt_signature: Optional[str] = Header(default=None, alias="X-TCRT-Signature"),
    x_tcrt_delivery: Optional[str] = Header(default=None, alias="X-TCRT-Delivery"),
) -> WebhookRunStatusResponse:
    retry_after = _consume_rate_limit(token)
    if retry_after is not None:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"code": "WEBHOOK_RATE_LIMITED", "message": "Webhook rate limit exceeded"},
            headers={"Retry-After": str(retry_after)},
        )

    body = await request.body()
    try:
        payload = json.loads(body.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_PAYLOAD", "message": "Body must be valid JSON"},
        )
    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_PAYLOAD", "message": "Body must be a JSON object"},
        )

    main_boundary: MainAccessBoundary = get_main_access_boundary()

    async def _verify(session: AsyncSession) -> Any:
        service = AutomationWebhookService(session)
        try:
            webhook = await service.load_inbound_webhook(token=token)
        except AutomationWebhookNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "WEBHOOK_NOT_FOUND", "message": str(exc)},
            ) from exc
        except AutomationWebhookInboundOnlyError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "WEBHOOK_NOT_INBOUND", "message": str(exc)},
            ) from exc
        except AutomationWebhookInactiveError as exc:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"code": "WEBHOOK_INACTIVE", "message": str(exc)},
            ) from exc

        try:
            service.verify_signature(webhook=webhook, body=body, signature=x_tcrt_signature)
        except AutomationWebhookSignatureError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"code": "WEBHOOK_SIGNATURE_INVALID", "message": str(exc)},
            ) from exc
        return webhook

    webhook = await main_boundary.run_read(_verify)

    async def _apply(session: AsyncSession) -> WebhookRunStatusResponse:
        # Re-fetch webhook in the write session so we can mutate counters.
        service = AutomationWebhookService(session)
        webhook_for_write = await service.get_webhook(team_id=webhook.team_id, webhook_id=webhook.id)
        try:
            run = await service.apply_run_status(webhook=webhook_for_write, payload=payload)
        except AutomationRunForWebhookNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "AUTOMATION_RUN_NOT_MATCHED", "message": str(exc)},
            ) from exc

        if not run.triggered_by_webhook_id:
            run.triggered_by_webhook_id = webhook_for_write.id

        # Track delivery id (best-effort) — append to last_status if provided.
        if x_tcrt_delivery:
            webhook_for_write.last_status = f"{webhook_for_write.last_status or 'RECEIVED'} ({x_tcrt_delivery.strip()[:32]})"

        return WebhookRunStatusResponse(
            run_id=run.id,
            tcrt_correlation_id=run.tcrt_correlation_id,
            status=AutomationRunStatus(run.status),
            external_run_id=run.external_run_id,
            deduped=False,
        )

    response = await main_boundary.run_write(_apply)

    # Fan out lifecycle events to OUTBOUND webhooks (independent of inbound flow)
    status_str = str(response.status)
    event_payload = {
        "run_id": response.run_id,
        "tcrt_correlation_id": response.tcrt_correlation_id,
        "status": status_str,
        "external_run_id": response.external_run_id,
    }
    asyncio.create_task(dispatch_event_async(webhook.team_id, "run.tracked", event_payload))
    if status_str in _TERMINAL_RUN_STATUSES:
        asyncio.create_task(dispatch_event_async(webhook.team_id, "run.completed", event_payload))

    return response


class AllureResultsUploadResponse(BaseModel):
    run_id: int
    report_url: str


@router.post(
    "/{token}/allure-results",
    response_model=AllureResultsUploadResponse,
)
async def ingest_allure_results(
    token: str,
    tcrt_run_id: str = Form(...),
    results: UploadFile = File(...),
) -> AllureResultsUploadResponse:
    """Accept a Jenkins-uploaded ``allure-results.tgz`` and proxy to local Allure.

    This endpoint exists so Jenkins agents (typically on a different host than
    TCRT) don't need direct network reachability to the Allure server. The
    operator can keep Allure on TCRT's loopback (``127.0.0.1:5050``) and let
    TCRT do the three-step handshake locally — see ``allure_proxy`` for the
    architectural rationale.

    Auth is the webhook token only — we deliberately skip HMAC here because
    pre-computing a signature over the multipart body in shell would force
    the CI script to buffer the archive twice. The token plus team-scoped
    run lookup is the security boundary.
    """
    retry_after = _consume_rate_limit(token)
    if retry_after is not None:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"code": "WEBHOOK_RATE_LIMITED", "message": "Webhook rate limit exceeded"},
            headers={"Retry-After": str(retry_after)},
        )

    main_boundary: MainAccessBoundary = get_main_access_boundary()

    async def _verify(session: AsyncSession) -> Any:
        service = AutomationWebhookService(session)
        try:
            return await service.load_inbound_webhook(token=token)
        except AutomationWebhookNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "WEBHOOK_NOT_FOUND", "message": str(exc)},
            ) from exc
        except AutomationWebhookInboundOnlyError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "WEBHOOK_NOT_INBOUND", "message": str(exc)},
            ) from exc
        except AutomationWebhookInactiveError as exc:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"code": "WEBHOOK_INACTIVE", "message": str(exc)},
            ) from exc

    webhook = await main_boundary.run_read(_verify)

    archive_bytes = await results.read()

    async def _apply(session: AsyncSession) -> AllureResultsUploadResponse:
        # Look up the run by correlation id within this webhook's team scope.
        # The team scope means a stolen token can't be used to upload results
        # for runs that don't belong to that team.
        result = await session.execute(
            select(AutomationRun)
            .where(
                AutomationRun.team_id == webhook.team_id,
                AutomationRun.tcrt_correlation_id == tcrt_run_id.strip(),
            )
            .limit(1)
        )
        run = result.scalar_one_or_none()
        if run is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "code": "AUTOMATION_RUN_NOT_MATCHED",
                    "message": f"No run for team {webhook.team_id} with correlation {tcrt_run_id}",
                },
            )

        try:
            report_url = await upload_run_results(
                session=session, run=run, archive_bytes=archive_bytes,
            )
        except AllureProxyNotConfiguredError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"code": "ALLURE_NOT_CONFIGURED", "message": str(exc)},
            ) from exc
        except AllureProxyError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={"code": "ALLURE_UPSTREAM_FAILED", "message": str(exc)},
            ) from exc

        await session.flush()
        return AllureResultsUploadResponse(run_id=run.id, report_url=report_url)

    return await main_boundary.run_write(_apply)


def _consume_rate_limit(token: str) -> int | None:
    now = time.monotonic()
    tokens, updated_at = _rate_limit_buckets.get(token, (_RATE_LIMIT_CAPACITY, now))
    elapsed = max(now - updated_at, 0)
    tokens = min(_RATE_LIMIT_CAPACITY, tokens + elapsed * _RATE_LIMIT_REFILL_PER_SECOND)
    if tokens < 1:
        retry_after = max(1, int((1 - tokens) / _RATE_LIMIT_REFILL_PER_SECOND))
        _rate_limit_buckets[token] = (tokens, now)
        return retry_after
    _rate_limit_buckets[token] = (tokens - 1, now)
    return None
