"""API for the rewritten QA AI Helper."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.auth.models import PermissionType, UserRole
from app.auth.permission_service import permission_service
from app.db_access.main import get_main_access_boundary
from app.models.database_models import Team as TeamDB, User
from app.models.qa_ai_helper import (
    QAAIHelperCanonicalRevisionCreateRequest,
    QAAIHelperCommitResponse,
    QAAIHelperDeleteResponse,
    QAAIHelperDraftUpdateRequest,
    QAAIHelperGenerateRequest,
    QAAIHelperPlanRequest,
    QAAIHelperPlanningLockRequest,
    QAAIHelperPlanningOverrideApplyRequest,
    QAAIHelperRequirementDeltaCreateRequest,
    QAAIHelperSessionCreateRequest,
    QAAIHelperSessionListResponse,
    QAAIHelperTicketFetchRequest,
    QAAIHelperWorkspaceResponse,
)
from app.services.qa_ai_helper_service import QAAIHelperService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/teams/{team_id}/qa-ai-helper", tags=["qa-ai-helper"])


def _map_exception(exc: Exception) -> HTTPException:
    detail = str(exc)
    if isinstance(exc, ValueError):
        if "找不到" in detail:
            return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)
    if isinstance(exc, RuntimeError):
        return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=detail)
    logger.exception("qa_ai_helper API 執行失敗: %s", exc)
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="QA AI Helper 流程執行失敗",
    )


async def _verify_team_write_access(
    *,
    team_id: int,
    current_user: User,
) -> None:
    def _check_team(sync_db: Session):
        return sync_db.query(TeamDB).filter(TeamDB.id == team_id).first()

    main_boundary = get_main_access_boundary()
    team = await main_boundary.run_sync_read(_check_team)
    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Team {team_id} not found",
        )
    if current_user.role == UserRole.SUPER_ADMIN:
        return
    permission_check = await permission_service.check_team_permission(
        current_user.id,
        team_id,
        PermissionType.WRITE,
        current_user.role,
    )
    if not permission_check.has_permission:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="無權限執行 QA AI Helper",
        )


@router.post("/sessions", response_model=QAAIHelperWorkspaceResponse, status_code=status.HTTP_201_CREATED)
async def create_session(
    team_id: int,
    request: QAAIHelperSessionCreateRequest,
    current_user: User = Depends(get_current_user),
) -> QAAIHelperWorkspaceResponse:
    await _verify_team_write_access(team_id=team_id, current_user=current_user)
    service = QAAIHelperService()
    try:
        return await service.start_session(
            team_id=team_id,
            user_id=current_user.id,
            request=request,
        )
    except Exception as exc:  # noqa: BLE001
        raise _map_exception(exc) from exc


@router.get("/sessions", response_model=QAAIHelperSessionListResponse)
async def list_sessions(
    team_id: int,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
) -> QAAIHelperSessionListResponse:
    await _verify_team_write_access(team_id=team_id, current_user=current_user)
    service = QAAIHelperService()
    try:
        return await service.list_sessions(team_id=team_id, limit=limit, offset=offset)
    except Exception as exc:  # noqa: BLE001
        raise _map_exception(exc) from exc


@router.get("/sessions/{session_id}", response_model=QAAIHelperWorkspaceResponse)
async def get_workspace(
    team_id: int,
    session_id: int,
    current_user: User = Depends(get_current_user),
) -> QAAIHelperWorkspaceResponse:
    await _verify_team_write_access(team_id=team_id, current_user=current_user)
    service = QAAIHelperService()
    try:
        return await service.get_workspace(team_id=team_id, session_id=session_id)
    except Exception as exc:  # noqa: BLE001
        raise _map_exception(exc) from exc


@router.delete("/sessions/{session_id}", response_model=QAAIHelperDeleteResponse)
async def delete_session(
    team_id: int,
    session_id: int,
    current_user: User = Depends(get_current_user),
) -> QAAIHelperDeleteResponse:
    await _verify_team_write_access(team_id=team_id, current_user=current_user)
    service = QAAIHelperService()
    try:
        return await service.delete_session(team_id=team_id, session_id=session_id)
    except Exception as exc:  # noqa: BLE001
        raise _map_exception(exc) from exc


@router.post("/sessions/{session_id}/ticket", response_model=QAAIHelperWorkspaceResponse)
async def fetch_ticket(
    team_id: int,
    session_id: int,
    request: QAAIHelperTicketFetchRequest,
    current_user: User = Depends(get_current_user),
) -> QAAIHelperWorkspaceResponse:
    await _verify_team_write_access(team_id=team_id, current_user=current_user)
    service = QAAIHelperService()
    try:
        return await service.fetch_ticket(
            team_id=team_id,
            session_id=session_id,
            request=request,
        )
    except Exception as exc:  # noqa: BLE001
        raise _map_exception(exc) from exc


@router.post("/sessions/{session_id}/canonical-revisions", response_model=QAAIHelperWorkspaceResponse)
async def save_canonical_revision(
    team_id: int,
    session_id: int,
    request: QAAIHelperCanonicalRevisionCreateRequest,
    current_user: User = Depends(get_current_user),
) -> QAAIHelperWorkspaceResponse:
    await _verify_team_write_access(team_id=team_id, current_user=current_user)
    service = QAAIHelperService()
    try:
        return await service.save_canonical_revision(
            team_id=team_id,
            session_id=session_id,
            user_id=current_user.id,
            request=request,
        )
    except Exception as exc:  # noqa: BLE001
        raise _map_exception(exc) from exc


@router.post("/sessions/{session_id}/plan", response_model=QAAIHelperWorkspaceResponse)
async def plan_session(
    team_id: int,
    session_id: int,
    request: QAAIHelperPlanRequest,
    current_user: User = Depends(get_current_user),
) -> QAAIHelperWorkspaceResponse:
    await _verify_team_write_access(team_id=team_id, current_user=current_user)
    service = QAAIHelperService()
    try:
        return await service.plan_session(
            team_id=team_id,
            session_id=session_id,
            user_id=current_user.id,
            request=request,
        )
    except Exception as exc:  # noqa: BLE001
        raise _map_exception(exc) from exc


@router.post("/sessions/{session_id}/planning-overrides", response_model=QAAIHelperWorkspaceResponse)
async def apply_planning_overrides(
    team_id: int,
    session_id: int,
    request: QAAIHelperPlanningOverrideApplyRequest,
    current_user: User = Depends(get_current_user),
) -> QAAIHelperWorkspaceResponse:
    await _verify_team_write_access(team_id=team_id, current_user=current_user)
    service = QAAIHelperService()
    try:
        return await service.apply_planning_overrides(
            team_id=team_id,
            session_id=session_id,
            user_id=current_user.id,
            request=request,
        )
    except Exception as exc:  # noqa: BLE001
        raise _map_exception(exc) from exc


@router.post("/sessions/{session_id}/requirement-deltas", response_model=QAAIHelperWorkspaceResponse)
async def apply_requirement_delta(
    team_id: int,
    session_id: int,
    request: QAAIHelperRequirementDeltaCreateRequest,
    current_user: User = Depends(get_current_user),
) -> QAAIHelperWorkspaceResponse:
    await _verify_team_write_access(team_id=team_id, current_user=current_user)
    service = QAAIHelperService()
    try:
        return await service.apply_requirement_delta(
            team_id=team_id,
            session_id=session_id,
            user_id=current_user.id,
            request=request,
        )
    except Exception as exc:  # noqa: BLE001
        raise _map_exception(exc) from exc


@router.post("/sessions/{session_id}/lock", response_model=QAAIHelperWorkspaceResponse)
async def lock_planning(
    team_id: int,
    session_id: int,
    request: QAAIHelperPlanningLockRequest,
    current_user: User = Depends(get_current_user),
) -> QAAIHelperWorkspaceResponse:
    await _verify_team_write_access(team_id=team_id, current_user=current_user)
    service = QAAIHelperService()
    try:
        return await service.lock_planning(
            team_id=team_id,
            session_id=session_id,
            user_id=current_user.id,
            request=request,
        )
    except Exception as exc:  # noqa: BLE001
        raise _map_exception(exc) from exc


@router.post("/sessions/{session_id}/unlock", response_model=QAAIHelperWorkspaceResponse)
async def unlock_planning(
    team_id: int,
    session_id: int,
    current_user: User = Depends(get_current_user),
) -> QAAIHelperWorkspaceResponse:
    await _verify_team_write_access(team_id=team_id, current_user=current_user)
    service = QAAIHelperService()
    try:
        return await service.unlock_planning(team_id=team_id, session_id=session_id)
    except Exception as exc:  # noqa: BLE001
        raise _map_exception(exc) from exc


@router.post("/sessions/{session_id}/generate", response_model=QAAIHelperWorkspaceResponse)
async def generate_drafts(
    team_id: int,
    session_id: int,
    request: QAAIHelperGenerateRequest,
    current_user: User = Depends(get_current_user),
) -> QAAIHelperWorkspaceResponse:
    await _verify_team_write_access(team_id=team_id, current_user=current_user)
    service = QAAIHelperService()
    try:
        return await service.generate_drafts(
            team_id=team_id,
            session_id=session_id,
            user_id=current_user.id,
            request=request,
        )
    except Exception as exc:  # noqa: BLE001
        raise _map_exception(exc) from exc


@router.put("/sessions/{session_id}/draft-sets/{draft_set_id}/drafts", response_model=QAAIHelperWorkspaceResponse)
async def update_draft(
    team_id: int,
    session_id: int,
    draft_set_id: int,
    request: QAAIHelperDraftUpdateRequest,
    current_user: User = Depends(get_current_user),
) -> QAAIHelperWorkspaceResponse:
    await _verify_team_write_access(team_id=team_id, current_user=current_user)
    service = QAAIHelperService()
    try:
        return await service.update_draft(
            team_id=team_id,
            session_id=session_id,
            draft_set_id=draft_set_id,
            user_id=current_user.id,
            request=request,
        )
    except Exception as exc:  # noqa: BLE001
        raise _map_exception(exc) from exc


@router.post("/sessions/{session_id}/draft-sets/{draft_set_id}/discard", response_model=QAAIHelperWorkspaceResponse)
async def discard_draft_set(
    team_id: int,
    session_id: int,
    draft_set_id: int,
    current_user: User = Depends(get_current_user),
) -> QAAIHelperWorkspaceResponse:
    await _verify_team_write_access(team_id=team_id, current_user=current_user)
    service = QAAIHelperService()
    try:
        return await service.discard_draft_set(
            team_id=team_id,
            session_id=session_id,
            draft_set_id=draft_set_id,
        )
    except Exception as exc:  # noqa: BLE001
        raise _map_exception(exc) from exc


@router.post("/sessions/{session_id}/draft-sets/{draft_set_id}/commit", response_model=QAAIHelperCommitResponse)
async def commit_draft_set(
    team_id: int,
    session_id: int,
    draft_set_id: int,
    current_user: User = Depends(get_current_user),
) -> QAAIHelperCommitResponse:
    await _verify_team_write_access(team_id=team_id, current_user=current_user)
    service = QAAIHelperService()
    try:
        return await service.commit_draft_set(
            team_id=team_id,
            session_id=session_id,
            draft_set_id=draft_set_id,
        )
    except Exception as exc:  # noqa: BLE001
        raise _map_exception(exc) from exc
