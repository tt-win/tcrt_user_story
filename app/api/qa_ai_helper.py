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
    QAAIHelperCommitRequest,
    QAAIHelperCommitResponse,
    QAAIHelperDeleteResponse,
    QAAIHelperDraftUpdateRequest,
    QAAIHelperGenerateRequest,
    QAAIHelperPlanRequest,
    QAAIHelperPlanningLockRequest,
    QAAIHelperPlanningOverrideApplyRequest,
    QAAIHelperRequirementDeltaCreateRequest,
    QAAIHelperRequirementPlanSaveRequest,
    QAAIHelperRestartResponse,
    QAAIHelperSeedItemReviewUpdateRequest,
    QAAIHelperSeedRefineRequest,
    QAAIHelperSeedSectionInclusionRequest,
    QAAIHelperNoTicketSessionRequest,
    QAAIHelperSessionCreateRequest,
    QAAIHelperSessionListResponse,
    QAAIHelperTicketFetchRequest,
    QAAIHelperTicketReparseRequest,
    QAAIHelperTestcaseDraftSelectionRequest,
    QAAIHelperTestcaseDraftUpdateRequest,
    QAAIHelperTestcaseGenerateRequest,
    QAAIHelperTestcaseSetSelectionRequest,
    QAAIHelperTestcaseSectionSelectionRequest,
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


@router.post("/sessions/no-ticket", response_model=QAAIHelperWorkspaceResponse, status_code=status.HTTP_201_CREATED)
async def create_no_ticket_session(
    team_id: int,
    request: QAAIHelperNoTicketSessionRequest,
    current_user: User = Depends(get_current_user),
) -> QAAIHelperWorkspaceResponse:
    """建立無需求單模式的 session，直接進入 verification_planning 階段。"""
    await _verify_team_write_access(team_id=team_id, current_user=current_user)
    service = QAAIHelperService()
    try:
        return await service.start_no_ticket_session(
            team_id=team_id,
            user_id=current_user.id,
            section_header=request.section_header,
            output_locale=request.output_locale,
        )
    except Exception as exc:  # noqa: BLE001
        raise _map_exception(exc) from exc


@router.get("/sessions", response_model=QAAIHelperSessionListResponse)
async def list_sessions(
    team_id: int,
    limit: int = Query(50, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    search: str = Query("", max_length=200),
    current_user: User = Depends(get_current_user),
) -> QAAIHelperSessionListResponse:
    await _verify_team_write_access(team_id=team_id, current_user=current_user)
    service = QAAIHelperService()
    try:
        return await service.list_sessions(team_id=team_id, limit=limit, offset=offset, search=search.strip())
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


@router.post("/sessions/{session_id}/restart", response_model=QAAIHelperRestartResponse)
async def restart_session(
    team_id: int,
    session_id: int,
    current_user: User = Depends(get_current_user),
) -> QAAIHelperRestartResponse:
    await _verify_team_write_access(team_id=team_id, current_user=current_user)
    service = QAAIHelperService()
    try:
        return await service.restart_session(team_id=team_id, session_id=session_id)
    except Exception as exc:  # noqa: BLE001
        raise _map_exception(exc) from exc


@router.post("/sessions/{session_id}/reopen", response_model=QAAIHelperWorkspaceResponse)
async def reopen_session(
    team_id: int,
    session_id: int,
    target_screen: str = Query(..., description="目標畫面 (seed_review / testcase_review / verification_planning)"),
    current_user: User = Depends(get_current_user),
) -> QAAIHelperWorkspaceResponse:
    await _verify_team_write_access(team_id=team_id, current_user=current_user)
    service = QAAIHelperService()
    try:
        return await service.reopen_session(
            team_id=team_id,
            session_id=session_id,
            target_screen=target_screen,
        )
    except Exception as exc:  # noqa: BLE001
        raise _map_exception(exc) from exc


@router.post("/sessions/{session_id}/requirement-plan", response_model=QAAIHelperWorkspaceResponse)
async def initialize_requirement_plan(
    team_id: int,
    session_id: int,
    current_user: User = Depends(get_current_user),
) -> QAAIHelperWorkspaceResponse:
    await _verify_team_write_access(team_id=team_id, current_user=current_user)
    service = QAAIHelperService()
    try:
        return await service.initialize_requirement_plan(team_id=team_id, session_id=session_id)
    except Exception as exc:  # noqa: BLE001
        raise _map_exception(exc) from exc


@router.put("/sessions/{session_id}/requirement-plan", response_model=QAAIHelperWorkspaceResponse)
async def save_requirement_plan(
    team_id: int,
    session_id: int,
    request: QAAIHelperRequirementPlanSaveRequest,
    current_user: User = Depends(get_current_user),
) -> QAAIHelperWorkspaceResponse:
    await _verify_team_write_access(team_id=team_id, current_user=current_user)
    service = QAAIHelperService()
    try:
        return await service.save_requirement_plan(
            team_id=team_id,
            session_id=session_id,
            user_id=current_user.id,
            request=request,
        )
    except Exception as exc:  # noqa: BLE001
        raise _map_exception(exc) from exc


@router.post("/sessions/{session_id}/requirement-plan/lock", response_model=QAAIHelperWorkspaceResponse)
async def lock_requirement_plan(
    team_id: int,
    session_id: int,
    current_user: User = Depends(get_current_user),
) -> QAAIHelperWorkspaceResponse:
    await _verify_team_write_access(team_id=team_id, current_user=current_user)
    service = QAAIHelperService()
    try:
        return await service.lock_requirement_plan(
            team_id=team_id,
            session_id=session_id,
            user_id=current_user.id,
        )
    except Exception as exc:  # noqa: BLE001
        raise _map_exception(exc) from exc


@router.post("/sessions/{session_id}/requirement-plan/unlock", response_model=QAAIHelperWorkspaceResponse)
async def unlock_requirement_plan(
    team_id: int,
    session_id: int,
    current_user: User = Depends(get_current_user),
) -> QAAIHelperWorkspaceResponse:
    await _verify_team_write_access(team_id=team_id, current_user=current_user)
    service = QAAIHelperService()
    try:
        return await service.unlock_requirement_plan(team_id=team_id, session_id=session_id)
    except Exception as exc:  # noqa: BLE001
        raise _map_exception(exc) from exc


@router.post("/sessions/{session_id}/seed-sets", response_model=QAAIHelperWorkspaceResponse)
async def generate_seed_set(
    team_id: int,
    session_id: int,
    request: QAAIHelperTestcaseGenerateRequest | None = None,
    current_user: User = Depends(get_current_user),
) -> QAAIHelperWorkspaceResponse:
    await _verify_team_write_access(team_id=team_id, current_user=current_user)
    service = QAAIHelperService()
    force_regenerate = bool(request and request.force_regenerate)
    try:
        return await service.generate_seed_set(
            team_id=team_id,
            session_id=session_id,
            user_id=current_user.id,
            force_regenerate=force_regenerate,
        )
    except Exception as exc:  # noqa: BLE001
        raise _map_exception(exc) from exc


@router.put(
    "/sessions/{session_id}/seed-sets/{seed_set_id}/items/{seed_item_id}",
    response_model=QAAIHelperWorkspaceResponse,
)
async def update_seed_item_review(
    team_id: int,
    session_id: int,
    seed_set_id: int,
    seed_item_id: int,
    request: QAAIHelperSeedItemReviewUpdateRequest,
    current_user: User = Depends(get_current_user),
) -> QAAIHelperWorkspaceResponse:
    await _verify_team_write_access(team_id=team_id, current_user=current_user)
    service = QAAIHelperService()
    try:
        return await service.update_seed_item_review(
            team_id=team_id,
            session_id=session_id,
            seed_set_id=seed_set_id,
            seed_item_id=seed_item_id,
            request=request,
        )
    except Exception as exc:  # noqa: BLE001
        raise _map_exception(exc) from exc


@router.post(
    "/sessions/{session_id}/seed-sets/{seed_set_id}/sections/{section_id}/inclusion",
    response_model=QAAIHelperWorkspaceResponse,
)
async def update_seed_section_inclusion(
    team_id: int,
    session_id: int,
    seed_set_id: int,
    section_id: str,
    request: QAAIHelperSeedSectionInclusionRequest,
    current_user: User = Depends(get_current_user),
) -> QAAIHelperWorkspaceResponse:
    await _verify_team_write_access(team_id=team_id, current_user=current_user)
    service = QAAIHelperService()
    try:
        return await service.update_seed_section_inclusion(
            team_id=team_id,
            session_id=session_id,
            seed_set_id=seed_set_id,
            section_id=section_id,
            request=request,
        )
    except Exception as exc:  # noqa: BLE001
        raise _map_exception(exc) from exc


@router.post(
    "/sessions/{session_id}/seed-sets/{seed_set_id}/refine",
    response_model=QAAIHelperWorkspaceResponse,
)
async def refine_seed_set(
    team_id: int,
    session_id: int,
    seed_set_id: int,
    request: QAAIHelperSeedRefineRequest,
    current_user: User = Depends(get_current_user),
) -> QAAIHelperWorkspaceResponse:
    await _verify_team_write_access(team_id=team_id, current_user=current_user)
    service = QAAIHelperService()
    try:
        return await service.refine_seed_set(
            team_id=team_id,
            session_id=session_id,
            seed_set_id=seed_set_id,
            request=request,
        )
    except Exception as exc:  # noqa: BLE001
        raise _map_exception(exc) from exc


@router.post(
    "/sessions/{session_id}/seed-sets/{seed_set_id}/lock",
    response_model=QAAIHelperWorkspaceResponse,
)
async def lock_seed_set(
    team_id: int,
    session_id: int,
    seed_set_id: int,
    current_user: User = Depends(get_current_user),
) -> QAAIHelperWorkspaceResponse:
    await _verify_team_write_access(team_id=team_id, current_user=current_user)
    service = QAAIHelperService()
    try:
        return await service.lock_seed_set(
            team_id=team_id,
            session_id=session_id,
            seed_set_id=seed_set_id,
        )
    except Exception as exc:  # noqa: BLE001
        raise _map_exception(exc) from exc


@router.post(
    "/sessions/{session_id}/seed-sets/{seed_set_id}/unlock",
    response_model=QAAIHelperWorkspaceResponse,
)
async def unlock_seed_set(
    team_id: int,
    session_id: int,
    seed_set_id: int,
    current_user: User = Depends(get_current_user),
) -> QAAIHelperWorkspaceResponse:
    await _verify_team_write_access(team_id=team_id, current_user=current_user)
    service = QAAIHelperService()
    try:
        return await service.unlock_seed_set(
            team_id=team_id,
            session_id=session_id,
            seed_set_id=seed_set_id,
        )
    except Exception as exc:  # noqa: BLE001
        raise _map_exception(exc) from exc


@router.post("/sessions/{session_id}/testcase-draft-sets", response_model=QAAIHelperWorkspaceResponse)
async def generate_testcase_draft_set(
    team_id: int,
    session_id: int,
    request: QAAIHelperTestcaseGenerateRequest,
    current_user: User = Depends(get_current_user),
) -> QAAIHelperWorkspaceResponse:
    await _verify_team_write_access(team_id=team_id, current_user=current_user)
    service = QAAIHelperService()
    try:
        return await service.generate_testcase_draft_set(
            team_id=team_id,
            session_id=session_id,
            user_id=current_user.id,
            request=request,
        )
    except Exception as exc:  # noqa: BLE001
        raise _map_exception(exc) from exc


@router.put(
    "/sessions/{session_id}/testcase-draft-sets/{draft_set_id}/drafts/{draft_id}",
    response_model=QAAIHelperWorkspaceResponse,
)
async def update_testcase_draft(
    team_id: int,
    session_id: int,
    draft_set_id: int,
    draft_id: int,
    request: QAAIHelperTestcaseDraftUpdateRequest,
    current_user: User = Depends(get_current_user),
) -> QAAIHelperWorkspaceResponse:
    await _verify_team_write_access(team_id=team_id, current_user=current_user)
    service = QAAIHelperService()
    try:
        return await service.update_testcase_draft(
            team_id=team_id,
            session_id=session_id,
            draft_set_id=draft_set_id,
            draft_id=draft_id,
            request=request,
        )
    except Exception as exc:  # noqa: BLE001
        raise _map_exception(exc) from exc


@router.post(
    "/sessions/{session_id}/testcase-draft-sets/{draft_set_id}/drafts/{draft_id}/selection",
    response_model=QAAIHelperWorkspaceResponse,
)
async def update_testcase_draft_selection(
    team_id: int,
    session_id: int,
    draft_set_id: int,
    draft_id: int,
    request: QAAIHelperTestcaseDraftSelectionRequest,
    current_user: User = Depends(get_current_user),
) -> QAAIHelperWorkspaceResponse:
    await _verify_team_write_access(team_id=team_id, current_user=current_user)
    service = QAAIHelperService()
    try:
        return await service.update_testcase_draft_selection(
            team_id=team_id,
            session_id=session_id,
            draft_set_id=draft_set_id,
            draft_id=draft_id,
            request=request,
        )
    except Exception as exc:  # noqa: BLE001
        raise _map_exception(exc) from exc


@router.post(
    "/sessions/{session_id}/testcase-draft-sets/{draft_set_id}/sections/{section_id}/selection",
    response_model=QAAIHelperWorkspaceResponse,
)
async def update_testcase_section_selection(
    team_id: int,
    session_id: int,
    draft_set_id: int,
    section_id: str,
    request: QAAIHelperTestcaseSectionSelectionRequest,
    current_user: User = Depends(get_current_user),
) -> QAAIHelperWorkspaceResponse:
    await _verify_team_write_access(team_id=team_id, current_user=current_user)
    service = QAAIHelperService()
    try:
        return await service.update_testcase_section_selection(
            team_id=team_id,
            session_id=session_id,
            draft_set_id=draft_set_id,
            section_id=section_id,
            request=request,
        )
    except Exception as exc:  # noqa: BLE001
        raise _map_exception(exc) from exc


@router.post(
    "/sessions/{session_id}/testcase-draft-sets/{draft_set_id}/set-selection",
    response_model=QAAIHelperWorkspaceResponse,
)
async def open_testcase_set_selection(
    team_id: int,
    session_id: int,
    draft_set_id: int,
    current_user: User = Depends(get_current_user),
) -> QAAIHelperWorkspaceResponse:
    await _verify_team_write_access(team_id=team_id, current_user=current_user)
    service = QAAIHelperService()
    try:
        return await service.open_testcase_set_selection(
            team_id=team_id,
            session_id=session_id,
            request=QAAIHelperTestcaseSetSelectionRequest(testcase_draft_set_id=draft_set_id),
        )
    except Exception as exc:  # noqa: BLE001
        raise _map_exception(exc) from exc


@router.post(
    "/sessions/{session_id}/testcase-draft-sets/{draft_set_id}/review",
    response_model=QAAIHelperWorkspaceResponse,
)
async def return_to_testcase_review(
    team_id: int,
    session_id: int,
    draft_set_id: int,
    current_user: User = Depends(get_current_user),
) -> QAAIHelperWorkspaceResponse:
    await _verify_team_write_access(team_id=team_id, current_user=current_user)
    service = QAAIHelperService()
    try:
        return await service.return_to_testcase_review(
            team_id=team_id,
            session_id=session_id,
            request=QAAIHelperTestcaseSetSelectionRequest(testcase_draft_set_id=draft_set_id),
        )
    except Exception as exc:  # noqa: BLE001
        raise _map_exception(exc) from exc


@router.post(
    "/sessions/{session_id}/testcase-draft-sets/{draft_set_id}/commit",
    response_model=QAAIHelperWorkspaceResponse,
)
async def commit_selected_testcases(
    team_id: int,
    session_id: int,
    draft_set_id: int,
    request: QAAIHelperCommitRequest,
    current_user: User = Depends(get_current_user),
) -> QAAIHelperWorkspaceResponse:
    await _verify_team_write_access(team_id=team_id, current_user=current_user)
    service = QAAIHelperService()
    try:
        if request.testcase_draft_set_id != draft_set_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="body testcase_draft_set_id 與路徑 draft_set_id 不一致",
            )
        return await service.commit_selected_testcases(
            team_id=team_id,
            session_id=session_id,
            request=request,
            user_id=current_user.id,
        )
    except HTTPException:
        raise
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


@router.post("/sessions/{session_id}/ticket/reparse", response_model=QAAIHelperWorkspaceResponse)
async def reparse_ticket(
    team_id: int,
    session_id: int,
    request: QAAIHelperTicketReparseRequest,
    current_user: User = Depends(get_current_user),
) -> QAAIHelperWorkspaceResponse:
    await _verify_team_write_access(team_id=team_id, current_user=current_user)
    service = QAAIHelperService()
    try:
        return await service.reparse_ticket(
            team_id=team_id,
            session_id=session_id,
            raw_ticket_markdown=request.raw_ticket_markdown,
        )
    except Exception as exc:  # noqa: BLE001
        raise _map_exception(exc) from exc


@router.post("/sessions/{session_id}/ticket/reload", response_model=QAAIHelperWorkspaceResponse)
async def reload_ticket_from_jira(
    team_id: int,
    session_id: int,
    current_user: User = Depends(get_current_user),
) -> QAAIHelperWorkspaceResponse:
    """從 JIRA 重新取得 ticket 內容並更新 ticket_snapshot（不進入 canonical revision 流程）。"""
    await _verify_team_write_access(team_id=team_id, current_user=current_user)
    service = QAAIHelperService()
    try:
        return await service.reload_ticket_from_jira(
            team_id=team_id,
            session_id=session_id,
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
