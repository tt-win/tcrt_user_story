"""App token read API - /api/app/* read endpoints equivalent to /api/mcp/*."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.app_token_dependencies import (
    AppTokenErrorCodes,
    get_current_app_token_principal,
    log_app_token_audit,
    require_app_team_access,
)
from app.database import get_db
from app.models.app_token import READ_SCOPES, AppTokenPrincipal
from app.models.mcp import (
    MCPTestCaseDetailResponse,
    MCPTestCaseLookupResponse,
    MCPTeamTestCasesResponse,
    MCPTeamTestCaseSectionsResponse,
    MCPTeamTestRunsResponse,
    MCPTeamsResponse,
)
from app.services.external_read import (
    MissingLookupFilterError,
    TestCaseNotFoundError,
    TestCaseSetNotFoundError,
    TeamNotFoundError,
    UnknownRunTypeError,
    ensure_team_exists,
    get_team_test_case_detail_read,
    list_team_test_case_sections_read,
    list_team_test_cases_read,
    list_team_test_runs_read,
    list_teams_read,
    lookup_test_cases_read,
)

router = APIRouter(prefix="/app", tags=["app-read"])


async def _require_read_scope(
    request: Request,
    principal: AppTokenPrincipal = Depends(get_current_app_token_principal),
) -> AppTokenPrincipal:
    if not principal.has_any_scope(*READ_SCOPES):
        await log_app_token_audit(
            request, principal, allowed=False, reason="missing_read_scope"
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": AppTokenErrorCodes.SCOPE_DENIED,
                "message": "App token missing required read scope",
            },
        )
    return principal


@router.get("/teams", response_model=MCPTeamsResponse)
async def list_app_teams(
    request: Request,
    db: AsyncSession = Depends(get_db),
    principal: AppTokenPrincipal = Depends(_require_read_scope),
):
    """List teams accessible to the app token (sanitized metadata only)."""
    return await list_teams_read(db, allowed_team_ids=principal.accessible_team_ids())


@router.get("/teams/{team_id}/test-cases", response_model=MCPTeamTestCasesResponse)
async def list_app_team_test_cases(
    team_id: int,
    request: Request,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    search: Optional[str] = Query(None),
    priority: Optional[str] = Query(None),
    test_result: Optional[str] = Query(None),
    set_id: Optional[int] = Query(None),
    section_id: Optional[int] = Query(None),
    assignee: Optional[str] = Query(None, description="Assignee 關鍵字過濾"),
    tcg: Optional[str] = Query(None, description="Issue/Ticket 關鍵字過濾（對應 tcg 欄位）"),
    ticket: Optional[str] = Query(None, description="Issue/Ticket/單號關鍵字（同 tcg 欄位）"),
    strict_set: bool = Query(False),
    include_content: bool = Query(False),
    include_test_data: bool = Query(
        False, description="是否回傳每筆 case 的 test_data 陣列（含 id/name/category/value）"
    ),
    db: AsyncSession = Depends(get_db),
    principal: AppTokenPrincipal = Depends(_require_read_scope),
):
    """List test cases for a team (app-token read)."""
    try:
        await ensure_team_exists(db, team_id)
    except TeamNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    await require_app_team_access(team_id, request, principal)
    try:
        return await list_team_test_cases_read(
            db,
            team_id,
            set_id=set_id,
            search=search,
            priority=priority,
            test_result=test_result,
            assignee=assignee,
            tcg=tcg,
            ticket=ticket,
            section_id=section_id,
            strict_set=strict_set,
            include_content=include_content,
            include_test_data=include_test_data,
            skip=skip,
            limit=limit,
        )
    except TestCaseSetNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": AppTokenErrorCodes.RESOURCE_NOT_FOUND, "message": str(exc)},
        ) from exc


@router.get("/teams/{team_id}/test-cases/{case_id}", response_model=MCPTestCaseDetailResponse)
async def get_app_team_test_case_detail(
    team_id: int,
    case_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    principal: AppTokenPrincipal = Depends(_require_read_scope),
):
    """Get test case detail (app-token read)."""
    try:
        await ensure_team_exists(db, team_id)
    except TeamNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    await require_app_team_access(team_id, request, principal)
    try:
        return await get_team_test_case_detail_read(db, team_id, case_id)
    except TestCaseNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": AppTokenErrorCodes.RESOURCE_NOT_FOUND, "message": str(exc)},
        ) from exc


@router.get("/test-cases/lookup", response_model=MCPTestCaseLookupResponse)
async def lookup_app_test_cases(
    request: Request,
    q: Optional[str] = Query(None),
    test_case_number: Optional[str] = Query(None),
    ticket: Optional[str] = Query(None),
    team_id: Optional[int] = Query(None),
    include_content: bool = Query(False),
    include_test_data: bool = Query(
        False, description="是否回傳每筆 case 的 test_data 陣列（含 id/name/category/value）"
    ),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    principal: AppTokenPrincipal = Depends(_require_read_scope),
):
    """Cross-team test case lookup (app-token read)."""
    if team_id is not None:
        try:
            await ensure_team_exists(db, team_id)
        except TeamNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(exc),
            ) from exc

    try:
        return await lookup_test_cases_read(
            db,
            q=q,
            test_case_number=test_case_number,
            ticket=ticket,
            team_id=team_id,
            include_content=include_content,
            include_test_data=include_test_data,
            skip=skip,
            limit=limit,
            allowed_team_ids=principal.accessible_team_ids(),
        )
    except MissingLookupFilterError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": AppTokenErrorCodes.VALIDATION_ERROR, "message": str(exc)},
        ) from exc


@router.get("/teams/{team_id}/test-case-sections", response_model=MCPTeamTestCaseSectionsResponse)
async def list_app_team_test_case_sections(
    team_id: int,
    request: Request,
    set_id: Optional[int] = Query(None),
    parent_section_id: Optional[int] = Query(None),
    roots_only: bool = Query(False),
    include_empty: bool = Query(True),
    db: AsyncSession = Depends(get_db),
    principal: AppTokenPrincipal = Depends(_require_read_scope),
):
    """List test case sections for a team (app-token read)."""
    try:
        await ensure_team_exists(db, team_id)
    except TeamNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    await require_app_team_access(team_id, request, principal)
    return await list_team_test_case_sections_read(
        db,
        team_id,
        set_id=set_id,
        parent_section_id=parent_section_id,
        roots_only=roots_only,
        include_empty=include_empty,
    )


@router.get("/teams/{team_id}/test-runs", response_model=MCPTeamTestRunsResponse)
async def list_app_team_test_runs(
    team_id: int,
    request: Request,
    status_filter: Optional[str] = Query(None, alias="status"),
    run_type: Optional[str] = Query("all"),
    include_archived: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    principal: AppTokenPrincipal = Depends(_require_read_scope),
):
    """List test runs for a team (app-token read)."""
    try:
        await ensure_team_exists(db, team_id)
    except TeamNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    await require_app_team_access(team_id, request, principal)
    try:
        return await list_team_test_runs_read(
            db,
            team_id,
            status_filter=status_filter,
            run_type=run_type,
            include_archived=include_archived,
            include_legacy_summary_aliases=True,
        )
    except UnknownRunTypeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
