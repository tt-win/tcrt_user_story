from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.automation_scripts import require_team_admin, require_team_read
from app.audit import ActionType, AuditSeverity, ResourceType, audit_service
from app.db_access.main import MainAccessBoundary, get_main_access_boundary
from app.models.automation_run import AutomationRunListResponse, AutomationRunResponse
from app.models.database_models import (
    AutomationRunStatus,
    AutomationRunTrigger,
    Team,
    User,
)
from app.services.automation.provider_registry import (
    ProviderNotConfiguredError,
    ProviderRegistryError,
)
from app.services.automation.run_service import (
    AutomationRunAlreadyTerminalError,
    AutomationRunExternalIdMissingError,
    AutomationRunNotFoundError,
    AutomationRunService,
    AutomationRunServiceError,
    automation_run_to_dict,
)
from app.services.automation.webhook_service import dispatch_event_async


_TERMINAL_RUN_STATUSES = {"SUCCEEDED", "FAILED", "CANCELLED"}


def _fire_run_lifecycle_events(team_id: int, response: AutomationRunResponse) -> None:
    """Dispatch run.tracked (and run.completed on terminal) for a run mutation."""
    status_str = str(response.status)
    payload = {
        "run_id": response.id,
        "automation_script_id": response.automation_script_id,
        "script_group_id": response.script_group_id,
        "workflow_id": response.workflow_id,
        "branch": response.branch,
        "status": status_str,
        "external_run_id": response.external_run_id,
        "external_run_url": response.external_run_url,
        "report_url": response.report_url,
        "tcrt_correlation_id": response.tcrt_correlation_id,
        "duration_ms": response.duration_ms,
    }
    asyncio.create_task(dispatch_event_async(team_id, "run.tracked", payload))
    if status_str in _TERMINAL_RUN_STATUSES:
        asyncio.create_task(dispatch_event_async(team_id, "run.completed", payload))


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/teams/{team_id}/automation-runs", tags=["automation-runs"])


class AutomationRunReconcileRequest(BaseModel):
    external_run_id: Optional[str] = Field(default=None, max_length=120)


class AutomationRunSyncBatchResponse(BaseModel):
    synced: int
    terminal: int
    items: list[AutomationRunResponse]


@router.get("", response_model=AutomationRunListResponse)
async def list_automation_runs(
    team_id: int,
    run_status: AutomationRunStatus | None = Query(default=None, alias="status"),
    branch: str | None = Query(default=None),
    triggered_by: AutomationRunTrigger | None = Query(default=None),
    script_id: int | None = Query(default=None),
    group_id: int | None = Query(default=None),
    cursor: int | None = Query(default=None, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    current_user: User = Depends(require_team_read),
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
) -> AutomationRunListResponse:
    async def _list(session: AsyncSession) -> AutomationRunListResponse:
        await _ensure_team_exists(session, team_id)
        service = AutomationRunService(session)
        rows, next_cursor, total = await service.list_runs(
            team_id=team_id,
            status=run_status,
            branch=branch,
            triggered_by=triggered_by,
            script_id=script_id,
            group_id=group_id,
            cursor=cursor,
            limit=limit,
        )
        return AutomationRunListResponse(
            items=[AutomationRunResponse(**automation_run_to_dict(row)) for row in rows],
            next_cursor=str(next_cursor) if next_cursor is not None else None,
            total=total,
        )

    return await main_boundary.run_read(_list)


@router.get("/{run_id}", response_model=AutomationRunResponse)
async def get_automation_run(
    team_id: int,
    run_id: int,
    current_user: User = Depends(require_team_read),
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
) -> AutomationRunResponse:
    async def _get(session: AsyncSession) -> AutomationRunResponse:
        service = AutomationRunService(session)
        try:
            run = await service.get_run(team_id=team_id, run_id=run_id)
        except AutomationRunNotFoundError as exc:
            raise _run_not_found(run_id) from exc
        return AutomationRunResponse(**automation_run_to_dict(run))

    return await main_boundary.run_read(_get)


@router.post("/{run_id}/cancel", response_model=AutomationRunResponse)
async def cancel_automation_run(
    team_id: int,
    run_id: int,
    request: Request,
    current_user: User = Depends(require_team_admin),
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
) -> AutomationRunResponse:
    async def _cancel(session: AsyncSession) -> AutomationRunResponse:
        service = AutomationRunService(session)
        try:
            run = await service.cancel_run(team_id=team_id, run_id=run_id, actor=str(current_user.id))
        except AutomationRunNotFoundError as exc:
            raise _run_not_found(run_id) from exc
        return AutomationRunResponse(**automation_run_to_dict(run))

    response = await _run_write(main_boundary, _cancel)
    await _log_run_action(
        ActionType.UPDATE,
        current_user,
        team_id,
        str(response.id),
        f"取消 Automation Run: {run_id}",
        {
            "external_run_id": response.external_run_id,
            "workflow_id": response.workflow_id,
            "status": response.status,
        },
        request,
    )
    _fire_run_lifecycle_events(team_id, response)
    return response


@router.post("/{run_id}/reconcile", response_model=AutomationRunResponse)
async def reconcile_automation_run(
    team_id: int,
    run_id: int,
    payload: AutomationRunReconcileRequest,
    request: Request,
    current_user: User = Depends(require_team_admin),
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
) -> AutomationRunResponse:
    async def _reconcile(session: AsyncSession) -> AutomationRunResponse:
        service = AutomationRunService(session)
        try:
            run = await service.reconcile_run(
                team_id=team_id,
                run_id=run_id,
                external_run_id=payload.external_run_id,
                actor=str(current_user.id),
            )
        except AutomationRunNotFoundError as exc:
            raise _run_not_found(run_id) from exc
        return AutomationRunResponse(**automation_run_to_dict(run))

    response = await _run_write(main_boundary, _reconcile)
    await _log_run_action(
        ActionType.UPDATE,
        current_user,
        team_id,
        str(response.id),
        f"對齊 Automation Run 狀態: {run_id}",
        {
            "external_run_id": response.external_run_id,
            "status": response.status,
            "manual_external_run_id": payload.external_run_id,
        },
        request,
    )
    _fire_run_lifecycle_events(team_id, response)
    return response


@router.post("/{run_id}/sync", response_model=AutomationRunResponse)
async def sync_automation_run(
    team_id: int,
    run_id: int,
    current_user: User = Depends(require_team_admin),
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
) -> AutomationRunResponse:
    async def _sync(session: AsyncSession) -> AutomationRunResponse:
        service = AutomationRunService(session)
        try:
            run = await service.sync_run(team_id=team_id, run_id=run_id)
        except AutomationRunNotFoundError as exc:
            raise _run_not_found(run_id) from exc
        return AutomationRunResponse(**automation_run_to_dict(run))

    return await _run_write(main_boundary, _sync)


@router.post("/sync-pending", response_model=AutomationRunSyncBatchResponse)
async def sync_pending_automation_runs(
    team_id: int,
    limit: int = Query(default=50, ge=1, le=200),
    current_user: User = Depends(require_team_admin),
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
) -> AutomationRunSyncBatchResponse:
    async def _sync(session: AsyncSession) -> AutomationRunSyncBatchResponse:
        service = AutomationRunService(session)
        synced = await service.sync_pending_runs(team_id=team_id, limit=limit)
        # The button only syncs QUEUED/RUNNING runs, so it can't recover an
        # already-terminal run whose report_url never filled (artifacts weren't
        # archived yet at the terminal tick). Retry those here too.
        await service.backfill_pending_reports(team_id=team_id, limit=limit)
        terminal_count = sum(
            1
            for run in synced
            if AutomationRunStatus(run.status)
            in {AutomationRunStatus.SUCCEEDED, AutomationRunStatus.FAILED, AutomationRunStatus.CANCELLED}
        )
        return AutomationRunSyncBatchResponse(
            synced=len(synced),
            terminal=terminal_count,
            items=[AutomationRunResponse(**automation_run_to_dict(row)) for row in synced],
        )

    return await _run_write(main_boundary, _sync)


# --------------------------------------------------------------------- helpers


async def _run_write(main_boundary: MainAccessBoundary, operation):
    try:
        return await main_boundary.run_write(operation)
    except AutomationRunAlreadyTerminalError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "AUTOMATION_RUN_ALREADY_TERMINAL", "message": str(exc)},
        ) from exc
    except AutomationRunExternalIdMissingError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "AUTOMATION_RUN_EXTERNAL_ID_MISSING", "message": str(exc)},
        ) from exc
    except ProviderNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "AUTOMATION_PROVIDER_NOT_CONFIGURED", "message": str(exc)},
        ) from exc
    except (AutomationRunServiceError, ProviderRegistryError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "AUTOMATION_RUN_OPERATION_FAILED", "message": str(exc)},
        ) from exc


async def _ensure_team_exists(session: AsyncSession, team_id: int) -> None:
    result = await session.execute(select(Team.id).where(Team.id == team_id))
    if result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "TEAM_NOT_FOUND", "message": f"Team {team_id} not found"},
        )


def _run_not_found(run_id: int) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"code": "AUTOMATION_RUN_NOT_FOUND", "message": f"Automation run {run_id} not found"},
    )


async def _log_run_action(
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
            resource_type=ResourceType.AUTOMATION_RUN,
            resource_id=resource_id,
            team_id=team_id,
            details=details,
            action_brief=action_brief,
            severity=AuditSeverity.INFO,
            ip_address=request.client.host if request and request.client else None,
            user_agent=request.headers.get("user-agent") if request else None,
        )
    except Exception as exc:
        logger.warning("Failed to write automation run audit log: %s", exc, exc_info=True)
