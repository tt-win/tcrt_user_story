from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import ActionType, AuditSeverity, ResourceType, audit_service
from app.auth.dependencies import get_current_user
from app.auth.models import PermissionType
from app.auth.permission_service import permission_service
from app.db_access.main import MainAccessBoundary, get_main_access_boundary
from app.models.automation_script import (
    AILinkSuggestRequest,
    AILinkSuggestResponse,
    AutomationScriptListResponse,
    AutomationScriptResponse,
    AutomationScriptSyncRequest,
    AutomationScriptSyncResponse,
    AutomationScriptUpdate,
)
from app.models.database_models import AutomationScriptFormat, Team, User
from app.services.automation.provider_registry import (
    ProviderNotConfiguredError,
    ProviderRegistryError,
)
from app.services.automation.ai_link_suggest_service import (
    AILinkSuggestError,
    AILinkSuggestService,
)
from app.services.automation.script_service import (
    AutomationScriptNotFoundError,
    AutomationScriptService,
    AutomationScriptServiceError,
    RepoContractRequiredError,
    script_to_dict,
)


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/teams/{team_id}/automation-scripts", tags=["automation-scripts"])


async def require_team_read(
    team_id: int,
    current_user: User = Depends(get_current_user),
) -> User:
    permission_check = await permission_service.check_team_permission(
        current_user.id,
        team_id,
        PermissionType.READ,
        current_user.role,
    )
    if not permission_check.has_permission:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "INSUFFICIENT_PERMISSION", "message": "無權限讀取此團隊 Automation Scripts"},
        )
    return current_user


async def require_team_admin(
    team_id: int,
    current_user: User = Depends(get_current_user),
) -> User:
    permission_check = await permission_service.check_team_permission(
        current_user.id,
        team_id,
        PermissionType.ADMIN,
        current_user.role,
    )
    if not permission_check.has_permission:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "INSUFFICIENT_PERMISSION", "message": "無權限管理此團隊 Automation Scripts"},
        )
    return current_user


@router.get("", response_model=AutomationScriptListResponse)
async def list_automation_scripts(
    team_id: int,
    provider_id: int | None = Query(default=None),
    script_format: AutomationScriptFormat | None = Query(default=None, alias="format"),
    linked_test_case_id: int | None = Query(default=None),
    q: str | None = Query(default=None),
    cursor: int | None = Query(default=None, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    current_user: User = Depends(require_team_read),
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
) -> AutomationScriptListResponse:
    async def _list(session: AsyncSession) -> AutomationScriptListResponse:
        await _ensure_team_exists(session, team_id)
        service = AutomationScriptService(session)
        rows, next_cursor, total = await service.list_scripts(
            team_id=team_id,
            provider_id=provider_id,
            script_format=script_format,
            linked_test_case_id=linked_test_case_id,
            q=q,
            cursor=cursor,
            limit=limit,
        )
        return AutomationScriptListResponse(
            items=[AutomationScriptResponse(**script_to_dict(row)) for row in rows],
            next_cursor=str(next_cursor) if next_cursor is not None else None,
            total=total,
        )

    return await main_boundary.run_read(_list)


@router.post("/sync", response_model=AutomationScriptSyncResponse)
async def sync_automation_scripts(
    team_id: int,
    payload: AutomationScriptSyncRequest,
    request: Request,
    current_user: User = Depends(require_team_admin),
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
) -> AutomationScriptSyncResponse:
    async def _sync(session: AsyncSession) -> AutomationScriptSyncResponse:
        await _ensure_team_exists(session, team_id)
        service = AutomationScriptService(session)
        summary = await service.sync_scripts(
            team_id=team_id,
            provider_id=payload.provider_id,
            branch=payload.branch,
            actor=str(current_user.id),
            fetch_content=True,
            reconcile_markers=True,
        )
        return AutomationScriptSyncResponse(**summary.to_dict())

    try:
        response = await main_boundary.run_write(_sync)
    except (ProviderNotConfiguredError, ProviderRegistryError) as exc:
        # First entry into the hub auto-syncs before any storage provider is
        # configured — a precondition gap, not a server fault. Return 400 so the
        # UI can swallow the silent auto-sync (and show an actionable message on
        # an explicit rescan) instead of surfacing a 500 + traceback.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "PROVIDER_NOT_CONFIGURED", "message": str(exc)},
        ) from exc
    except RepoContractRequiredError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "REPO_CONTRACT_REQUIRED", "message": str(exc)},
        ) from exc
    except AutomationScriptServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "AUTOMATION_SCRIPT_SYNC_FAILED", "message": str(exc)},
        ) from exc

    await _log_script_action(
        ActionType.UPDATE,
        current_user,
        team_id,
        "sync",
        "同步 Automation Scripts",
        {
            "provider_id": response.provider_id,
            "branch": response.branch,
            "scanned_path": response.scanned_path,
            "added": response.added,
            "updated": response.updated,
            "removed": response.removed,
            "total": response.total,
            "repo_contract_status": response.repo_contract.contract_status,
            "manifest_found": response.repo_contract.manifest_found,
        },
        request,
    )
    return response


@router.get("/{script_id}", response_model=AutomationScriptResponse)
async def get_automation_script(
    team_id: int,
    script_id: int,
    current_user: User = Depends(require_team_read),
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
) -> AutomationScriptResponse:
    async def _get(session: AsyncSession) -> AutomationScriptResponse:
        service = AutomationScriptService(session)
        try:
            script = await service.get_script(team_id=team_id, script_id=script_id)
        except AutomationScriptNotFoundError as exc:
            raise _script_not_found(script_id) from exc
        return AutomationScriptResponse(**script_to_dict(script))

    return await main_boundary.run_read(_get)


@router.post("/{script_id}/sync", response_model=AutomationScriptResponse)
async def sync_automation_script_content(
    team_id: int,
    script_id: int,
    request: Request,
    current_user: User = Depends(require_team_admin),
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
) -> AutomationScriptResponse:
    async def _sync_one(session: AsyncSession) -> AutomationScriptResponse:
        service = AutomationScriptService(session)
        try:
            script = await service.sync_single_content(
                team_id=team_id,
                script_id=script_id,
                actor=str(current_user.id),
            )
        except AutomationScriptNotFoundError as exc:
            raise _script_not_found(script_id) from exc
        return AutomationScriptResponse(**script_to_dict(script))

    response = await main_boundary.run_write(_sync_one)
    await _log_script_action(
        ActionType.UPDATE,
        current_user,
        team_id,
        str(script_id),
        f"同步 Automation Script 內容: {script_id}",
        {"script_id": script_id},
        request,
    )
    return response


@router.put("/{script_id}", response_model=AutomationScriptResponse)
async def update_automation_script_metadata(
    team_id: int,
    script_id: int,
    payload: AutomationScriptUpdate,
    request: Request,
    current_user: User = Depends(require_team_admin),
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
) -> AutomationScriptResponse:
    async def _update(session: AsyncSession) -> AutomationScriptResponse:
        service = AutomationScriptService(session)
        try:
            script = await service.update_metadata(
                team_id=team_id,
                script_id=script_id,
                actor=str(current_user.id),
                name=payload.name,
                description=payload.description,
                script_format=payload.script_format,
                tags=payload.tags,
                preferred_runner_label=payload.preferred_runner_label,
            )
        except AutomationScriptNotFoundError as exc:
            raise _script_not_found(script_id) from exc
        return AutomationScriptResponse(**script_to_dict(script))

    response = await main_boundary.run_write(_update)
    await _log_script_action(
        ActionType.UPDATE,
        current_user,
        team_id,
        str(script_id),
        f"更新 Automation Script metadata: {script_id}",
        {"script_id": script_id, "updated_fields": sorted(payload.model_fields_set)},
        request,
    )
    return response


@router.delete("/{script_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_automation_script_cache(
    team_id: int,
    script_id: int,
    request: Request,
    current_user: User = Depends(require_team_admin),
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
) -> Response:
    async def _delete(session: AsyncSession) -> None:
        service = AutomationScriptService(session)
        try:
            await service.delete_script_cache(team_id=team_id, script_id=script_id)
        except AutomationScriptNotFoundError as exc:
            raise _script_not_found(script_id) from exc

    await main_boundary.run_write(_delete)
    await _log_script_action(
        ActionType.DELETE,
        current_user,
        team_id,
        str(script_id),
        f"刪除 Automation Script cache: {script_id}",
        {"script_id": script_id},
        request,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# NOTE: `POST /api/teams/{team_id}/automation-scripts/{script_id}/runs` 已於
# `move-automation-execution-to-test-run-set` 移除。Automation Hub 對外
# 不再提供任何 run trigger 端點；觸發由 Test Run Set 的
# `POST /api/teams/{team_id}/test-run-sets/{set_id}/run-automation` 統一入口接管。
# 對舊端點送 request 會得到 404 / 405（由 FastAPI 自動回應，
# response body 為 generic JSON 格式）。

@router.post(
    "/{script_id}/ai-link-suggestions",
    response_model=AILinkSuggestResponse,
)
async def ai_link_suggestions(
    team_id: int,
    script_id: int,
    payload: AILinkSuggestRequest,
    request: Request,
    current_user: User = Depends(require_team_read),
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
) -> AILinkSuggestResponse:
    """Return top-N suggested manual test cases for a given test function.

    Suggestion-only — never writes links. Caller must call `POST .../links`
    to materialise an accepted suggestion (with `created_by="ai-suggest:<id>"`).
    """

    async def _run(session: AsyncSession) -> dict[str, Any]:
        await _ensure_team_exists(session, team_id)
        service = AILinkSuggestService(session)
        try:
            result = await service.suggest(
                team_id=team_id,
                script_id=script_id,
                test_name=payload.test_name,
                limit=payload.limit,
                actor=str(current_user.id),
            )
        except AILinkSuggestError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "AI_LINK_SUGGEST_PRECONDITION", "message": str(exc)},
            ) from exc
        return result.to_dict()

    payload_dict = await main_boundary.run_read(_run)
    return AILinkSuggestResponse(**payload_dict)


async def _ensure_team_exists(session: AsyncSession, team_id: int) -> None:
    result = await session.execute(select(Team.id).where(Team.id == team_id))
    if result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "TEAM_NOT_FOUND", "message": f"Team {team_id} not found"},
        )


def _script_not_found(script_id: int) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"code": "AUTOMATION_SCRIPT_NOT_FOUND", "message": f"Automation script {script_id} not found"},
    )


async def _log_script_action(
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
            resource_type=ResourceType.AUTOMATION_SCRIPT,
            resource_id=resource_id,
            team_id=team_id,
            details=details,
            action_brief=action_brief,
            severity=AuditSeverity.CRITICAL if action_type == ActionType.DELETE else AuditSeverity.INFO,
            ip_address=request.client.host if request and request.client else None,
            user_agent=request.headers.get("user-agent") if request else None,
        )
    except Exception as exc:
        logger.warning("Failed to write automation script audit log: %s", exc, exc_info=True)


async def _log_run_action(
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
            action_type=ActionType.CREATE,
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
