from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.automation_scripts import require_team_admin
from app.audit import ActionType, AuditSeverity, ResourceType, audit_service
from app.db_access.main import MainAccessBoundary, get_main_access_boundary
from app.models.automation_webhook import (
    AutomationWebhookCreate,
    AutomationWebhookCreateResponse,
    AutomationWebhookDeliveryListResponse,
    AutomationWebhookDeliveryResponse,
    AutomationWebhookReplayResponse,
    AutomationWebhookResponse,
    AutomationWebhookTestPingResponse,
    AutomationWebhookUpdate,
)
from app.models.database_models import AutomationWebhookDirection, Team, User
from app.services.automation.webhook_service import (
    AutomationWebhookInactiveError,
    AutomationWebhookNameConflictError,
    AutomationWebhookNotFoundError,
    AutomationWebhookOutboundOnlyError,
    AutomationWebhookService,
    AutomationWebhookServiceError,
    AutomationWebhookSuiteBindingError,
    webhook_to_dict,
)


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/teams/{team_id}/automation-webhooks", tags=["automation-webhooks"])


@router.get("", response_model=list[AutomationWebhookResponse])
async def list_automation_webhooks(
    team_id: int,
    current_user: User = Depends(require_team_admin),
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
) -> list[AutomationWebhookResponse]:
    async def _list(session: AsyncSession) -> list[AutomationWebhookResponse]:
        await _ensure_team_exists(session, team_id)
        service = AutomationWebhookService(session)
        rows = await service.list_webhooks(team_id=team_id)
        return [AutomationWebhookResponse(**webhook_to_dict(row)) for row in rows]

    return await main_boundary.run_read(_list)


@router.post("", response_model=AutomationWebhookCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_automation_webhook(
    team_id: int,
    payload: AutomationWebhookCreate,
    request: Request,
    current_user: User = Depends(require_team_admin),
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
) -> AutomationWebhookCreateResponse:
    async def _create(session: AsyncSession) -> tuple[int, str, str, AutomationWebhookDirection, str]:
        await _ensure_team_exists(session, team_id)
        service = AutomationWebhookService(session)
        webhook, token, secret = await service.create_webhook(
            team_id=team_id,
            direction=payload.direction,
            name=payload.name,
            target_url=payload.target_url,
            events=payload.events,
            is_active=payload.is_active,
            actor=str(current_user.id),
            script_group_id=payload.script_group_id,
        )
        return webhook.id, token, secret, AutomationWebhookDirection(webhook.direction), webhook.name

    try:
        webhook_id, token, secret, direction, name = await main_boundary.run_write(_create)
    except AutomationWebhookNameConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "AUTOMATION_WEBHOOK_NAME_CONFLICT", "message": str(exc)},
        ) from exc
    except AutomationWebhookSuiteBindingError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "AUTOMATION_WEBHOOK_SUITE_BINDING_INVALID", "message": str(exc)},
        ) from exc

    await _log_webhook_action(
        ActionType.CREATE,
        current_user,
        team_id,
        str(webhook_id),
        f"建立 Automation Webhook: {name}",
        {"direction": direction.value, "name": name},
        request,
    )
    return AutomationWebhookCreateResponse(id=webhook_id, token=token, secret=secret)


@router.get("/{webhook_id}", response_model=AutomationWebhookResponse)
async def get_automation_webhook(
    team_id: int,
    webhook_id: int,
    current_user: User = Depends(require_team_admin),
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
) -> AutomationWebhookResponse:
    async def _get(session: AsyncSession) -> AutomationWebhookResponse:
        service = AutomationWebhookService(session)
        try:
            webhook = await service.get_webhook(team_id=team_id, webhook_id=webhook_id)
        except AutomationWebhookNotFoundError as exc:
            raise _webhook_not_found(webhook_id) from exc
        return AutomationWebhookResponse(**webhook_to_dict(webhook))

    return await main_boundary.run_read(_get)


@router.patch("/{webhook_id}", response_model=AutomationWebhookResponse)
async def update_automation_webhook(
    team_id: int,
    webhook_id: int,
    payload: AutomationWebhookUpdate,
    request: Request,
    current_user: User = Depends(require_team_admin),
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
) -> AutomationWebhookResponse:
    async def _update(session: AsyncSession) -> AutomationWebhookResponse:
        service = AutomationWebhookService(session)
        try:
            webhook = await service.update_webhook(
                team_id=team_id,
                webhook_id=webhook_id,
                actor=str(current_user.id),
                name=payload.name,
                target_url=payload.target_url,
                target_url_provided="target_url" in payload.model_fields_set,
                events=payload.events,
                is_active=payload.is_active,
                script_group_id=payload.script_group_id,
                script_group_id_provided="script_group_id" in payload.model_fields_set,
            )
        except AutomationWebhookNotFoundError as exc:
            raise _webhook_not_found(webhook_id) from exc
        return AutomationWebhookResponse(**webhook_to_dict(webhook))

    try:
        response = await main_boundary.run_write(_update)
    except AutomationWebhookNameConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "AUTOMATION_WEBHOOK_NAME_CONFLICT", "message": str(exc)},
        ) from exc
    except AutomationWebhookSuiteBindingError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "AUTOMATION_WEBHOOK_SUITE_BINDING_INVALID", "message": str(exc)},
        ) from exc
    except AutomationWebhookServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "AUTOMATION_WEBHOOK_OPERATION_FAILED", "message": str(exc)},
        ) from exc

    await _log_webhook_action(
        ActionType.UPDATE,
        current_user,
        team_id,
        str(response.id),
        f"更新 Automation Webhook: {response.name}",
        {"updated_fields": sorted(payload.model_fields_set)},
        request,
    )
    return response


@router.delete("/{webhook_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_automation_webhook(
    team_id: int,
    webhook_id: int,
    request: Request,
    current_user: User = Depends(require_team_admin),
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
) -> Response:
    async def _delete(session: AsyncSession) -> str:
        service = AutomationWebhookService(session)
        try:
            webhook = await service.delete_webhook(team_id=team_id, webhook_id=webhook_id)
        except AutomationWebhookNotFoundError as exc:
            raise _webhook_not_found(webhook_id) from exc
        return webhook.name

    name = await main_boundary.run_write(_delete)
    await _log_webhook_action(
        ActionType.DELETE,
        current_user,
        team_id,
        str(webhook_id),
        f"刪除 Automation Webhook: {name}",
        {"webhook_id": webhook_id, "name": name},
        request,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{webhook_id}/regenerate-secret", response_model=AutomationWebhookCreateResponse)
async def regenerate_automation_webhook_secret(
    team_id: int,
    webhook_id: int,
    request: Request,
    current_user: User = Depends(require_team_admin),
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
) -> AutomationWebhookCreateResponse:
    async def _regen(session: AsyncSession) -> tuple[int, str, str]:
        service = AutomationWebhookService(session)
        try:
            webhook, secret = await service.regenerate_secret(
                team_id=team_id,
                webhook_id=webhook_id,
                actor=str(current_user.id),
            )
        except AutomationWebhookNotFoundError as exc:
            raise _webhook_not_found(webhook_id) from exc
        return webhook.id, webhook.token, secret

    webhook_id_out, token, secret = await main_boundary.run_write(_regen)
    await _log_webhook_action(
        ActionType.UPDATE,
        current_user,
        team_id,
        str(webhook_id_out),
        f"重新產生 Automation Webhook secret: {webhook_id_out}",
        {"webhook_id": webhook_id_out},
        request,
    )
    return AutomationWebhookCreateResponse(id=webhook_id_out, token=token, secret=secret)


@router.get("/{webhook_id}/deliveries", response_model=AutomationWebhookDeliveryListResponse)
async def list_automation_webhook_deliveries(
    team_id: int,
    webhook_id: int,
    limit: int = 50,
    current_user: User = Depends(require_team_admin),
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
) -> AutomationWebhookDeliveryListResponse:
    async def _list(session: AsyncSession) -> AutomationWebhookDeliveryListResponse:
        service = AutomationWebhookService(session)
        try:
            rows = await service.list_deliveries(
                team_id=team_id,
                webhook_id=webhook_id,
                limit=min(max(limit, 1), 50),
            )
        except AutomationWebhookNotFoundError as exc:
            raise _webhook_not_found(webhook_id) from exc
        return AutomationWebhookDeliveryListResponse(
            items=[AutomationWebhookDeliveryResponse.model_validate(row) for row in rows]
        )

    return await main_boundary.run_read(_list)


@router.post("/deliveries/{delivery_id}/replay", response_model=AutomationWebhookReplayResponse)
async def replay_automation_webhook_delivery(
    team_id: int,
    delivery_id: int,
    request: Request,
    current_user: User = Depends(require_team_admin),
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
) -> AutomationWebhookReplayResponse:
    async def _replay(session: AsyncSession) -> AutomationWebhookReplayResponse:
        service = AutomationWebhookService(session)
        try:
            delivery = await service.replay_delivery(team_id=team_id, delivery_id=delivery_id)
        except AutomationWebhookNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "WEBHOOK_DELIVERY_NOT_FOUND", "message": str(exc)},
            ) from exc
        return AutomationWebhookReplayResponse(
            status=delivery.status,
            delivery=AutomationWebhookDeliveryResponse.model_validate(delivery),
        )

    response = await main_boundary.run_write(_replay)
    await _log_webhook_action(
        ActionType.UPDATE,
        current_user,
        team_id,
        str(response.delivery.webhook_id),
        f"重發 Automation Webhook delivery: {delivery_id}",
        {"delivery_id": delivery_id, "new_delivery_id": response.delivery.delivery_id},
        request,
    )
    return response


@router.post("/{webhook_id}/test", response_model=AutomationWebhookTestPingResponse)
async def test_automation_webhook(
    team_id: int,
    webhook_id: int,
    request: Request,
    current_user: User = Depends(require_team_admin),
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
) -> AutomationWebhookTestPingResponse:
    async def _test(session: AsyncSession) -> AutomationWebhookTestPingResponse:
        service = AutomationWebhookService(session)
        try:
            result = await service.send_test_ping(team_id=team_id, webhook_id=webhook_id)
        except AutomationWebhookNotFoundError as exc:
            raise _webhook_not_found(webhook_id) from exc
        return AutomationWebhookTestPingResponse(**result)

    try:
        response = await main_boundary.run_write(_test)
    except AutomationWebhookOutboundOnlyError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "AUTOMATION_WEBHOOK_NOT_OUTBOUND", "message": str(exc)},
        ) from exc
    except AutomationWebhookInactiveError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "AUTOMATION_WEBHOOK_INACTIVE", "message": str(exc)},
        ) from exc
    except AutomationWebhookServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "AUTOMATION_WEBHOOK_OPERATION_FAILED", "message": str(exc)},
        ) from exc

    await _log_webhook_action(
        ActionType.UPDATE,
        current_user,
        team_id,
        str(webhook_id),
        f"測試 Automation Webhook: {webhook_id}",
        response.model_dump(),
        request,
    )
    return response


# --------------------------------------------------------------------- helpers


async def _ensure_team_exists(session: AsyncSession, team_id: int) -> None:
    result = await session.execute(select(Team.id).where(Team.id == team_id))
    if result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "TEAM_NOT_FOUND", "message": f"Team {team_id} not found"},
        )


def _webhook_not_found(webhook_id: int) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={
            "code": "AUTOMATION_WEBHOOK_NOT_FOUND",
            "message": f"Automation webhook {webhook_id} not found",
        },
    )


async def _log_webhook_action(
    action_type: ActionType,
    current_user: User,
    team_id: int,
    resource_id: str,
    action_brief: str,
    details: dict[str, Any] | None = None,
    request: Request | None = None,
) -> None:
    try:
        role_value = current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role)
        await audit_service.log_action(
            user_id=current_user.id,
            username=current_user.username,
            role=role_value,
            action_type=action_type,
            resource_type=ResourceType.AUTOMATION_WEBHOOK,
            resource_id=resource_id,
            team_id=team_id,
            details=details,
            action_brief=action_brief,
            severity=AuditSeverity.CRITICAL if action_type == ActionType.DELETE else AuditSeverity.INFO,
            ip_address=request.client.host if request and request.client else None,
            user_agent=request.headers.get("user-agent") if request else None,
        )
    except Exception as exc:
        logger.warning("Failed to write automation webhook audit log: %s", exc, exc_info=True)
