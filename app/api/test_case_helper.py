"""
JIRA Ticket -> Test Case Helper API
"""

import logging
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.auth.models import PermissionType, UserRole
from app.auth.permission_service import permission_service
from app.audit import audit_service, ActionType, ResourceType, AuditSeverity
from app.database import get_db, run_sync
from app.models.database_models import Team as TeamDB, User
from app.models.test_case_helper import (
    HelperAnalyzeRequest,
    HelperCommitRequest,
    HelperDraftResponse,
    HelperDraftUpsertRequest,
    HelperGenerateRequest,
    HelperNormalizeRequest,
    HelperSessionResponse,
    HelperSessionStartRequest,
    HelperSessionUpdateRequest,
    HelperStageResultResponse,
    HelperTicketFetchRequest,
    HelperTicketSummaryResponse,
)
from app.services.jira_testcase_helper_service import JiraTestCaseHelperService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/teams/{team_id}/test-case-helper", tags=["test-case-helper"])


def _role_value(user: User) -> str:
    return user.role.value if hasattr(user.role, "value") else str(user.role)


async def _log_helper_action(
    *,
    current_user: User,
    team_id: int,
    resource_id: str,
    action_type: ActionType,
    action_brief: str,
    details: Dict[str, Any],
    severity: AuditSeverity = AuditSeverity.INFO,
) -> None:
    try:
        await audit_service.log_action(
            user_id=current_user.id,
            username=current_user.username,
            role=_role_value(current_user),
            action_type=action_type,
            resource_type=ResourceType.TEST_CASE_SET,
            resource_id=resource_id,
            team_id=team_id,
            details=details,
            action_brief=action_brief,
            severity=severity,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("寫入 helper 審計記錄失敗: %s", exc, exc_info=True)


def _map_exception(exc: Exception) -> HTTPException:
    detail = str(exc)
    if isinstance(exc, ValueError):
        if (
            "找不到 helper session" in detail
            or "Test Case Set 不存在" in detail
            or "JIRA 找不到 ticket" in detail
        ):
            return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)
    if isinstance(exc, RuntimeError):
        return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=detail)
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Helper 流程執行失敗",
    )


async def _verify_team_write_access(
    *,
    team_id: int,
    db: AsyncSession,
    current_user: User,
) -> None:
    def _check_team(sync_db: Session):
        return sync_db.query(TeamDB).filter(TeamDB.id == team_id).first()

    team = await run_sync(db, _check_team)
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
            detail="無權限執行 Test Case Helper",
        )


@router.post("/sessions", response_model=HelperSessionResponse, status_code=status.HTTP_201_CREATED)
async def start_helper_session(
    team_id: int,
    request: HelperSessionStartRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> HelperSessionResponse:
    await _verify_team_write_access(team_id=team_id, db=db, current_user=current_user)
    service = JiraTestCaseHelperService(db)
    try:
        result = await service.start_session(
            team_id=team_id,
            user_id=current_user.id,
            request=request,
        )
        await _log_helper_action(
            current_user=current_user,
            team_id=team_id,
            resource_id=str(result.id),
            action_type=ActionType.CREATE,
            action_brief=f"建立 AI Test Case Helper Session #{result.id}",
            details={
                "session_id": result.id,
                "target_test_case_set_id": result.target_test_case_set_id,
                "output_locale": result.output_locale.value,
                "review_locale": result.review_locale.value,
                "ticket_key": result.ticket_key,
            },
        )
        return result
    except Exception as exc:  # noqa: BLE001
        raise _map_exception(exc) from exc


@router.get("/sessions/{session_id}", response_model=HelperSessionResponse)
async def get_helper_session(
    team_id: int,
    session_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> HelperSessionResponse:
    await _verify_team_write_access(team_id=team_id, db=db, current_user=current_user)
    service = JiraTestCaseHelperService(db)
    try:
        return await service.get_session(team_id=team_id, session_id=session_id)
    except Exception as exc:  # noqa: BLE001
        raise _map_exception(exc) from exc


@router.patch("/sessions/{session_id}", response_model=HelperSessionResponse)
async def update_helper_session(
    team_id: int,
    session_id: int,
    request: HelperSessionUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> HelperSessionResponse:
    await _verify_team_write_access(team_id=team_id, db=db, current_user=current_user)
    service = JiraTestCaseHelperService(db)
    try:
        return await service.update_session(
            team_id=team_id,
            session_id=session_id,
            request=request,
        )
    except Exception as exc:  # noqa: BLE001
        raise _map_exception(exc) from exc


@router.put("/sessions/{session_id}/drafts/{phase}", response_model=HelperDraftResponse)
async def upsert_helper_draft(
    team_id: int,
    session_id: int,
    phase: str,
    request: HelperDraftUpsertRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> HelperDraftResponse:
    await _verify_team_write_access(team_id=team_id, db=db, current_user=current_user)
    service = JiraTestCaseHelperService(db)
    try:
        return await service.upsert_draft(
            team_id=team_id,
            session_id=session_id,
            phase=phase,
            request=request,
        )
    except Exception as exc:  # noqa: BLE001
        raise _map_exception(exc) from exc


@router.post("/sessions/{session_id}/ticket", response_model=HelperTicketSummaryResponse)
async def fetch_helper_ticket(
    team_id: int,
    session_id: int,
    request: HelperTicketFetchRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> HelperTicketSummaryResponse:
    await _verify_team_write_access(team_id=team_id, db=db, current_user=current_user)
    service = JiraTestCaseHelperService(db)
    try:
        return await service.fetch_ticket(
            team_id=team_id,
            session_id=session_id,
            request=request,
        )
    except Exception as exc:  # noqa: BLE001
        raise _map_exception(exc) from exc


@router.post("/sessions/{session_id}/normalize", response_model=HelperStageResultResponse)
async def normalize_helper_requirement(
    team_id: int,
    session_id: int,
    request: HelperNormalizeRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> HelperStageResultResponse:
    await _verify_team_write_access(team_id=team_id, db=db, current_user=current_user)
    service = JiraTestCaseHelperService(db)
    try:
        result = await service.normalize_requirement(
            team_id=team_id,
            session_id=session_id,
            request=request,
        )
        if request.force:
            await _log_helper_action(
                current_user=current_user,
                team_id=team_id,
                resource_id=str(session_id),
                action_type=ActionType.UPDATE,
                action_brief=f"重試需求整理 Session #{session_id}",
                details={
                    "session_id": session_id,
                    "phase": "requirement",
                    "retry": True,
                },
            )
        return result
    except Exception as exc:  # noqa: BLE001
        raise _map_exception(exc) from exc


@router.post("/sessions/{session_id}/analyze", response_model=HelperStageResultResponse)
async def analyze_helper_session(
    team_id: int,
    session_id: int,
    request: HelperAnalyzeRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> HelperStageResultResponse:
    await _verify_team_write_access(team_id=team_id, db=db, current_user=current_user)
    service = JiraTestCaseHelperService(db)
    try:
        result = await service.analyze_and_build_pretestcase(
            team_id=team_id,
            session_id=session_id,
            request=request,
            override_actor={
                "user_id": current_user.id,
                "username": current_user.username,
            },
        )
        if request.retry:
            await _log_helper_action(
                current_user=current_user,
                team_id=team_id,
                resource_id=str(session_id),
                action_type=ActionType.UPDATE,
                action_brief=f"重試 Analysis/Coverage Session #{session_id}",
                details={
                    "session_id": session_id,
                    "phase": "analysis_coverage",
                    "retry": True,
                },
                )
        return result
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "test-case-helper analyze 失敗: team_id=%s session_id=%s",
            team_id,
            session_id,
        )
        raise _map_exception(exc) from exc


@router.post("/sessions/{session_id}/generate", response_model=HelperStageResultResponse)
async def generate_helper_testcases(
    team_id: int,
    session_id: int,
    request: HelperGenerateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> HelperStageResultResponse:
    await _verify_team_write_access(team_id=team_id, db=db, current_user=current_user)
    service = JiraTestCaseHelperService(db)
    try:
        result = await service.generate_testcases(
            team_id=team_id,
            session_id=session_id,
            request=request,
        )
        if request.retry:
            await _log_helper_action(
                current_user=current_user,
                team_id=team_id,
                resource_id=str(session_id),
                action_type=ActionType.UPDATE,
                action_brief=f"重試 Testcase/Audit Session #{session_id}",
                details={
                    "session_id": session_id,
                    "phase": "testcase_audit",
                    "retry": True,
                },
            )
        return result
    except Exception as exc:  # noqa: BLE001
        raise _map_exception(exc) from exc


@router.post("/sessions/{session_id}/commit", response_model=Dict[str, Any])
async def commit_helper_testcases(
    team_id: int,
    session_id: int,
    request: HelperCommitRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    await _verify_team_write_access(team_id=team_id, db=db, current_user=current_user)
    service = JiraTestCaseHelperService(db)
    try:
        result = await service.commit_testcases(
            team_id=team_id,
            session_id=session_id,
            request=request,
        )
        await _log_helper_action(
            current_user=current_user,
            team_id=team_id,
            resource_id=str(session_id),
            action_type=ActionType.CREATE,
            action_brief=f"提交 Helper Session #{session_id} 建立 Test Cases",
            details={
                "session_id": session_id,
                "target_test_case_set_id": result.get("target_test_case_set_id"),
                "created_count": result.get("created_count"),
                "created_test_case_numbers": result.get("created_test_case_numbers", []),
                "section_fallback_count": result.get("section_fallback_count", 0),
            },
            severity=AuditSeverity.INFO,
        )
        return result
    except Exception as exc:  # noqa: BLE001
        raise _map_exception(exc) from exc
