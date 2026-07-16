from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.automation_scripts import require_team_admin, require_team_read
from app.audit import ActionType, AuditSeverity, ResourceType, audit_service
from app.db_access.main import MainAccessBoundary, get_main_access_boundary
from app.models.automation_script_group import (
    AutomationScriptGroupCreate,
    AutomationScriptGroupListResponse,
    AutomationScriptGroupResponse,
    AutomationScriptGroupUpdate,
)
from app.models.database_models import Team, User
from app.services.automation.provider_registry import ProviderRegistryError
from app.services.automation.script_group_service import (
    AutomationScriptGroupCIApiError,
    AutomationScriptGroupCIJobMissingError,
    AutomationScriptGroupNameConflictError,
    AutomationScriptGroupNotFoundError,
    AutomationScriptGroupScriptNotFoundError,
    AutomationScriptGroupService,
    AutomationScriptGroupServiceError,
    script_group_to_dict,
)


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/teams/{team_id}/automation-script-groups", tags=["automation-script-groups"])


@router.get("", response_model=AutomationScriptGroupListResponse)
async def list_automation_script_groups(
    team_id: int,
    q: str | None = Query(default=None),
    cursor: int | None = Query(default=None, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    current_user: User = Depends(require_team_read),
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
) -> AutomationScriptGroupListResponse:
    async def _list(session: AsyncSession) -> AutomationScriptGroupListResponse:
        await _ensure_team_exists(session, team_id)
        service = AutomationScriptGroupService(session)
        groups, next_cursor, total = await service.list_groups(team_id=team_id, q=q, cursor=cursor, limit=limit)
        items = []
        for group in groups:
            scripts = await service.load_group_scripts(group=group)
            items.append(AutomationScriptGroupResponse(**script_group_to_dict(group, scripts=scripts)))
        return AutomationScriptGroupListResponse(
            items=items,
            next_cursor=str(next_cursor) if next_cursor is not None else None,
            total=total,
        )

    return await main_boundary.run_read(_list)


@router.post("", response_model=AutomationScriptGroupResponse, status_code=status.HTTP_201_CREATED)
async def create_automation_script_group(
    team_id: int,
    payload: AutomationScriptGroupCreate,
    request: Request,
    current_user: User = Depends(require_team_admin),
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
) -> AutomationScriptGroupResponse:
    async def _create(session: AsyncSession) -> AutomationScriptGroupResponse:
        await _ensure_team_exists(session, team_id)
        service = AutomationScriptGroupService(session)
        group = await service.create_group(
            team_id=team_id,
            name=payload.name,
            description=payload.description,
            script_ids=payload.script_ids,
            actor=str(current_user.id),
        )
        scripts = await service.load_group_scripts(group=group)
        return AutomationScriptGroupResponse(**script_group_to_dict(group, scripts=scripts))

    response = await _run_group_write(main_boundary, _create)
    await _log_group_action(
        ActionType.CREATE,
        current_user,
        team_id,
        str(response.id),
        f"建立 Automation Suite: {response.name}",
        {
            "group_name": response.name,
            "script_count": response.script_count,
            "ci_job_name": response.ci_job_name,
            "ci_job_type": response.ci_job_type,
        },
        request,
    )
    return response


@router.get("/{group_id}", response_model=AutomationScriptGroupResponse)
async def get_automation_script_group(
    team_id: int,
    group_id: int,
    current_user: User = Depends(require_team_read),
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
) -> AutomationScriptGroupResponse:
    async def _get(session: AsyncSession) -> AutomationScriptGroupResponse:
        service = AutomationScriptGroupService(session)
        try:
            group = await service.get_group(team_id=team_id, group_id=group_id)
        except AutomationScriptGroupNotFoundError as exc:
            raise _group_not_found(group_id) from exc
        scripts = await service.load_group_scripts(group=group)
        return AutomationScriptGroupResponse(**script_group_to_dict(group, scripts=scripts))

    return await main_boundary.run_read(_get)


@router.put("/{group_id}", response_model=AutomationScriptGroupResponse)
async def update_automation_script_group(
    team_id: int,
    group_id: int,
    payload: AutomationScriptGroupUpdate,
    request: Request,
    current_user: User = Depends(require_team_admin),
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
) -> AutomationScriptGroupResponse:
    async def _update(session: AsyncSession) -> AutomationScriptGroupResponse:
        service = AutomationScriptGroupService(session)
        try:
            group = await service.update_group(
                team_id=team_id,
                group_id=group_id,
                actor=str(current_user.id),
                name=payload.name,
                description=payload.description,
                description_provided="description" in payload.model_fields_set,
                script_ids=payload.script_ids,
            )
        except AutomationScriptGroupNotFoundError as exc:
            raise _group_not_found(group_id) from exc
        scripts = await service.load_group_scripts(group=group)
        response = AutomationScriptGroupResponse(**script_group_to_dict(group, scripts=scripts))
        response.warnings = service.last_warnings
        return response

    response = await _run_group_write(main_boundary, _update)
    await _log_group_action(
        ActionType.UPDATE,
        current_user,
        team_id,
        str(response.id),
        f"更新 Automation Suite: {response.name}",
        {
            "group_name": response.name,
            "script_count": response.script_count,
            "ci_job_name": response.ci_job_name,
            "updated_fields": sorted(payload.model_fields_set),
        },
        request,
    )
    return response


@router.delete("/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_automation_script_group(
    team_id: int,
    group_id: int,
    request: Request,
    current_user: User = Depends(require_team_admin),
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
) -> Response:
    async def _delete(session: AsyncSession) -> dict[str, Any]:
        service = AutomationScriptGroupService(session)
        try:
            group = await service.delete_group(team_id=team_id, group_id=group_id)
        except AutomationScriptGroupNotFoundError as exc:
            raise _group_not_found(group_id) from exc
        return {
            "group_name": group.name,
            "script_count": _script_count(group.script_paths_json),
            "ci_job_name": group.ci_job_name,
        }

    details = await _run_group_write(main_boundary, _delete)
    await _log_group_action(
        ActionType.DELETE,
        current_user,
        team_id,
        str(group_id),
        f"刪除 Automation Suite: {group_id}",
        details,
        request,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# NOTE: `POST /api/teams/{team_id}/automation-script-groups/{group_id}/runs` 已於
# `move-automation-execution-to-test-run-set` 移除。Automation Hub 對外
# 不再提供任何 run trigger 端點；觸發由 Test Run Set 的
# `POST /api/teams/{team_id}/test-run-sets/{set_id}/run-automation` 統一入口接管。
# 對舊端點送 request 會得到 404 / 405（由 FastAPI 自動回應）。

async def _run_group_write(main_boundary: MainAccessBoundary, operation):
    try:
        return await main_boundary.run_write(operation)
    except AutomationScriptGroupNameConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "AUTOMATION_SCRIPT_GROUP_NAME_CONFLICT", "message": str(exc)},
        ) from exc
    except AutomationScriptGroupScriptNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "AUTOMATION_SCRIPT_GROUP_INVALID_SCRIPTS", "message": str(exc)},
        ) from exc
    except AutomationScriptGroupCIJobMissingError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "AUTOMATION_SCRIPT_GROUP_CI_JOB_MISSING", "message": str(exc)},
        ) from exc
    except AutomationScriptGroupCIApiError as exc:
        # Upstream CI server (Jenkins / GH Actions) rejected the call — surface
        # the underlying hint to the user instead of a bare 500.
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": "AUTOMATION_SCRIPT_GROUP_CI_API_FAILED", "message": str(exc)},
        ) from exc
    except (AutomationScriptGroupServiceError, ProviderRegistryError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "AUTOMATION_SCRIPT_GROUP_OPERATION_FAILED", "message": str(exc)},
        ) from exc


async def _ensure_team_exists(session: AsyncSession, team_id: int) -> None:
    result = await session.execute(select(Team.id).where(Team.id == team_id))
    if result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "TEAM_NOT_FOUND", "message": f"Team {team_id} not found"},
        )


def _group_not_found(group_id: int) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"code": "AUTOMATION_SCRIPT_GROUP_NOT_FOUND", "message": f"Automation script group {group_id} not found"},
    )


def _script_count(value: str | None) -> int:
    if not value:
        return 0
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        return 0
    return len(payload) if isinstance(payload, list) else 0


async def _log_group_action(
    action_type: ActionType,
    current_user: User,
    team_id: int,
    resource_id: str,
    action_brief: str,
    details: dict[str, Any] | None = None,
    request: Request | None = None,
) -> None:
    await _log_action(
        action_type,
        ResourceType.AUTOMATION_SCRIPT_GROUP,
        current_user,
        team_id,
        resource_id,
        action_brief,
        details,
        request,
    )


async def _log_action(
    action_type: ActionType,
    resource_type: ResourceType,
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
            resource_type=resource_type,
            resource_id=resource_id,
            team_id=team_id,
            details=details,
            action_brief=action_brief,
            severity=AuditSeverity.CRITICAL if action_type == ActionType.DELETE else AuditSeverity.INFO,
            ip_address=request.client.host if request and request.client else None,
            user_agent=request.headers.get("user-agent") if request else None,
        )
    except Exception as exc:
        logger.warning("Failed to write automation script group audit log: %s", exc, exc_info=True)
