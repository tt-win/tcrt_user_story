"""App token read API - /api/app/* read endpoints equivalent to /api/mcp/*."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.api.mcp import (
    _build_case_payload,
    _config_payload,
    _ensure_team_exists,
    _get_section_case_counts,
    _get_team_case_counts,
    _lookup_match_type,
    _normalize_priority_filter,
    _normalize_result_filter,
    _parse_run_types,
    _parse_status_filters,
    _status_match,
)
from app.auth.app_token_dependencies import (
    AppTokenErrorCodes,
    get_current_app_token_principal,
    log_app_token_audit,
    require_app_team_access,
)
from app.database import get_db
from app.models.app_token import READ_SCOPES, AppTokenPrincipal
from app.models.database_models import (
    AdHocRun,
    Team as TeamDB,
    TestCaseLocal as TestCaseLocalDB,
    TestCaseSection as TestCaseSectionDB,
    TestCaseSet as TestCaseSetDB,
    TestRunConfig as TestRunConfigDB,
    TestRunSet as TestRunSetDB,
    TestRunSetMembership as TestRunSetMembershipDB,
)
from app.models.mcp import (
    MCPAdhocRunItem,
    MCPCrossTeamTestCaseItem,
    MCPPageMeta,
    MCPTestCaseDetailResponse,
    MCPTestCaseLookupResponse,
    MCPTestCaseSectionItem,
    MCPTestCaseSetItem,
    MCPTeamItem,
    MCPTeamTestCasesResponse,
    MCPTeamTestCaseSectionsResponse,
    MCPTeamTestRunsResponse,
    MCPTeamsResponse,
    MCPTestRunSetItem,
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
    result = await db.execute(select(TeamDB).order_by(TeamDB.id))
    teams = result.scalars().all()

    filtered = []
    for team in teams:
        if principal.can_access_team(team.id):
            filtered.append(team)

    team_case_counts = await _get_team_case_counts(db)
    items = [
        MCPTeamItem(
            id=team.id,
            name=team.name,
            description=team.description,
            status=team.status.value if hasattr(team.status, "value") else str(team.status),
            test_case_count=team_case_counts.get(team.id, 0),
            created_at=team.created_at,
            updated_at=team.updated_at,
            last_sync_at=team.last_sync_at,
            is_lark_configured=bool(team.wiki_token),
            is_jira_configured=bool(team.jira_project_key),
        )
        for team in filtered
    ]
    return MCPTeamsResponse(total=len(items), items=items)


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
    tcg: Optional[str] = Query(None),
    ticket: Optional[str] = Query(None),
    include_content: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    principal: AppTokenPrincipal = Depends(_require_read_scope),
):
    """List test cases for a team (app-token read)."""
    await _ensure_team_exists(db, team_id)
    await require_app_team_access(team_id, request, principal)

    query = select(TestCaseLocalDB).where(TestCaseLocalDB.team_id == team_id)
    count_query = select(func.count()).select_from(TestCaseLocalDB).where(
        TestCaseLocalDB.team_id == team_id
    )

    if search:
        query = query.where(TestCaseLocalDB.title.ilike(f"%{search}%"))
        count_query = count_query.where(TestCaseLocalDB.title.ilike(f"%{search}%"))

    priority_filter = _normalize_priority_filter(priority)
    if priority_filter is not None:
        query = query.where(TestCaseLocalDB.priority == priority_filter)
        count_query = count_query.where(TestCaseLocalDB.priority == priority_filter)

    result_filter = _normalize_result_filter(test_result)
    if result_filter is not None:
        query = query.where(TestCaseLocalDB.test_result == result_filter)
        count_query = count_query.where(TestCaseLocalDB.test_result == result_filter)

    if set_id:
        query = query.where(TestCaseLocalDB.test_case_set_id == set_id)
        count_query = count_query.where(TestCaseLocalDB.test_case_set_id == set_id)

    if section_id:
        query = query.where(TestCaseLocalDB.test_case_section_id == section_id)
        count_query = count_query.where(TestCaseLocalDB.test_case_section_id == section_id)

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    set_count_rows = await db.execute(
        select(TestCaseLocalDB.test_case_set_id, func.count(TestCaseLocalDB.id))
        .where(TestCaseLocalDB.team_id == team_id)
        .group_by(TestCaseLocalDB.test_case_set_id)
    )
    set_count_map = {set_id_value: count for set_id_value, count in set_count_rows.all()}

    query = query.order_by(TestCaseLocalDB.id).offset(skip).limit(limit)
    result = await db.execute(query)
    test_cases = result.scalars().all()

    sets_result = await db.execute(
        select(TestCaseSetDB).where(TestCaseSetDB.team_id == team_id).order_by(TestCaseSetDB.id)
    )
    sets = sets_result.scalars().all()

    case_payloads = [
        _build_case_payload(tc, include_content=include_content) for tc in test_cases
    ]

    return MCPTeamTestCasesResponse(
        team_id=team_id,
        filters={"search": search, "priority": priority, "test_result": test_result, "set_id": set_id, "section_id": section_id},
        sets=[
            MCPTestCaseSetItem(
                id=s.id,
                name=s.name,
                description=s.description,
                is_default=s.is_default,
                test_case_count=int(set_count_map.get(s.id, 0) or 0),
                created_at=s.created_at,
                updated_at=s.updated_at,
            )
            for s in sets
        ],
        test_cases=case_payloads,
        page=MCPPageMeta(skip=skip, limit=limit, total=total, has_next=skip + limit < total),
    )


@router.get("/teams/{team_id}/test-cases/{case_id}", response_model=MCPTestCaseDetailResponse)
async def get_app_team_test_case_detail(
    team_id: int,
    case_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    principal: AppTokenPrincipal = Depends(_require_read_scope),
):
    """Get test case detail (app-token read)."""
    await _ensure_team_exists(db, team_id)
    await require_app_team_access(team_id, request, principal)

    result = await db.execute(
        select(TestCaseLocalDB)
        .options(joinedload(TestCaseLocalDB.test_case_set))
        .where(
            TestCaseLocalDB.id == case_id,
            TestCaseLocalDB.team_id == team_id,
        )
    )
    tc = result.scalar_one_or_none()
    if not tc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": AppTokenErrorCodes.RESOURCE_NOT_FOUND, "message": "Test case not found"},
        )

    from app.api.mcp import _to_text
    from app.services.automation.linkage_service import AutomationLinkageService

    linkage_service = AutomationLinkageService(db)
    try:
        linked_automation = await linkage_service.list_linked_automation(
            team_id=team_id,
            test_case_id=case_id,
        )
    except Exception:
        linked_automation = []

    payload = _build_case_payload(tc, include_content=True, include_extended=True)
    payload["linked_automation_scripts"] = [
        {
            "script_id": item.get("script_id"),
            "name": item.get("name", ""),
            "script_format": item.get("script_format", "OTHER"),
            "ref_path": item.get("ref_path"),
            "link_type": _to_text(item.get("link_type", "")) or "REFERENCES",
        }
        for item in linked_automation
    ]
    return MCPTestCaseDetailResponse(team_id=team_id, test_case=payload)


@router.get("/test-cases/lookup", response_model=MCPTestCaseLookupResponse)
async def lookup_app_test_cases(
    request: Request,
    q: Optional[str] = Query(None),
    test_case_number: Optional[str] = Query(None),
    ticket: Optional[str] = Query(None),
    team_id: Optional[int] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    principal: AppTokenPrincipal = Depends(_require_read_scope),
):
    """Cross-team test case lookup (app-token read)."""
    if not q and not test_case_number and not ticket:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": AppTokenErrorCodes.VALIDATION_ERROR, "message": "At least one filter is required"},
        )

    query = select(TestCaseLocalDB, TeamDB).join(TeamDB, TestCaseLocalDB.team_id == TeamDB.id)

    conditions = []
    if test_case_number:
        conditions.append(TestCaseLocalDB.test_case_number == test_case_number)
    if q:
        conditions.append(or_(
            TestCaseLocalDB.title.ilike(f"%{q}%"),
            TestCaseLocalDB.test_case_number.ilike(f"%{q}%"),
        ))
    if ticket:
        conditions.append(TestCaseLocalDB.tcg_json.ilike(f"%{ticket}%"))

    if conditions:
        query = query.where(or_(*conditions))

    if team_id:
        query = query.where(TestCaseLocalDB.team_id == team_id)

    query = query.offset(skip).limit(limit)
    result = await db.execute(query)
    rows = result.all()

    items = []
    for tc, team in rows:
        if not principal.can_access_team(team.id):
            continue
        match_type = _lookup_match_type(
            tc, keyword=q, test_case_number=test_case_number, ticket=ticket
        )
        items.append(
            MCPCrossTeamTestCaseItem(
                team_id=team.id,
                team_name=team.name,
                match_type=match_type,
                test_case=_build_case_payload(tc, include_content=False),
            )
        )

    total = len(items)
    paged = items[skip : skip + limit] if skip > 0 else items[:limit]

    return MCPTestCaseLookupResponse(
        filters={"q": q, "test_case_number": test_case_number, "ticket": ticket, "team_id": team_id},
        items=paged,
        page=MCPPageMeta(skip=skip, limit=limit, total=total, has_next=skip + limit < total),
    )


@router.get("/teams/{team_id}/test-case-sections", response_model=MCPTeamTestCaseSectionsResponse)
async def list_app_team_test_case_sections(
    team_id: int,
    request: Request,
    set_id: Optional[int] = Query(None),
    parent_section_id: Optional[int] = Query(None),
    roots_only: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    principal: AppTokenPrincipal = Depends(_require_read_scope),
):
    """List test case sections for a team (app-token read)."""
    await _ensure_team_exists(db, team_id)
    await require_app_team_access(team_id, request, principal)

    query = select(TestCaseSectionDB).join(
        TestCaseSetDB, TestCaseSectionDB.test_case_set_id == TestCaseSetDB.id
    ).where(TestCaseSetDB.team_id == team_id)

    if set_id:
        query = query.where(TestCaseSectionDB.test_case_set_id == set_id)
    if parent_section_id is not None:
        if roots_only:
            query = query.where(TestCaseSectionDB.parent_section_id.is_(None))
        else:
            query = query.where(TestCaseSectionDB.parent_section_id == parent_section_id)
    elif roots_only:
        query = query.where(TestCaseSectionDB.parent_section_id.is_(None))

    query = query.order_by(TestCaseSectionDB.sort_order, TestCaseSectionDB.id)
    result = await db.execute(query)
    sections = result.scalars().all()

    case_counts = await _get_section_case_counts(db, team_id)

    items = [
        MCPTestCaseSectionItem(
            id=s.id,
            test_case_set_id=s.test_case_set_id,
            parent_section_id=s.parent_section_id,
            name=s.name,
            description=s.description,
            level=s.level,
            sort_order=s.sort_order,
            test_case_count=case_counts.get(s.id, 0),
            created_at=s.created_at,
            updated_at=s.updated_at,
        )
        for s in sections
    ]
    return MCPTeamTestCaseSectionsResponse(
        team_id=team_id,
        filters={"set_id": set_id, "parent_section_id": parent_section_id, "roots_only": roots_only},
        sections=items,
        total=len(items),
    )


@router.get("/teams/{team_id}/test-runs", response_model=MCPTeamTestRunsResponse)
async def list_app_team_test_runs(
    team_id: int,
    request: Request,
    status_filter: Optional[str] = Query(None, alias="status"),
    run_type: str = Query("all"),
    db: AsyncSession = Depends(get_db),
    principal: AppTokenPrincipal = Depends(_require_read_scope),
):
    """List test runs for a team (app-token read)."""
    await _ensure_team_exists(db, team_id)
    await require_app_team_access(team_id, request, principal)

    status_filters = _parse_status_filters(status_filter)
    run_type_filters = _parse_run_types(run_type)

    sets_result = await db.execute(
        select(TestRunSetDB).where(TestRunSetDB.team_id == team_id).order_by(TestRunSetDB.id)
    )
    sets = sets_result.scalars().all()

    set_items = []
    for trs in sets:
        if status_filters and not _status_match(trs.status, status_filters):
            continue
        members_result = await db.execute(
            select(TestRunConfigDB)
            .join(TestRunSetMembershipDB, TestRunSetMembershipDB.config_id == TestRunConfigDB.id)
            .where(TestRunSetMembershipDB.set_id == trs.id)
        )
        configs = members_result.scalars().all()
        set_items.append(
            MCPTestRunSetItem(
                id=trs.id,
                name=trs.name,
                status=trs.status.value if hasattr(trs.status, "value") else str(trs.status),
                test_runs=[_config_payload(c) for c in configs],
            )
        )

    unassigned_configs = []
    if "unassigned" in run_type_filters:
        assigned_ids_result = await db.execute(
            select(TestRunSetMembershipDB.config_id)
        )
        assigned_ids = {r[0] for r in assigned_ids_result.all()}

        unassigned_query = select(TestRunConfigDB).where(TestRunConfigDB.team_id == team_id)
        if assigned_ids:
            unassigned_query = unassigned_query.where(~TestRunConfigDB.id.in_(assigned_ids))
        unassigned_result = await db.execute(unassigned_query)
        unassigned_configs = unassigned_result.scalars().all()

        if status_filters:
            unassigned_configs = [c for c in unassigned_configs if _status_match(c.status, status_filters)]

    adhoc_items = []
    if "adhoc" in run_type_filters:
        adhoc_result = await db.execute(
            select(AdHocRun).where(AdHocRun.team_id == team_id).order_by(AdHocRun.id.desc())
        )
        adhoc_runs = adhoc_result.scalars().all()
        for ar in adhoc_runs:
            if status_filters and not _status_match(ar.status, status_filters):
                continue
            adhoc_items.append(
                MCPAdhocRunItem(
                    id=ar.id,
                    name=ar.name,
                    status=ar.status.value if hasattr(ar.status, "value") else str(ar.status),
                    created_at=ar.created_at,
                    updated_at=ar.updated_at,
                )
            )

    summary = {
        "sets": len(set_items),
        "unassigned": len(unassigned_configs),
        "adhoc": len(adhoc_items),
    }

    return MCPTeamTestRunsResponse(
        team_id=team_id,
        filters={"status": status_filter, "run_type": run_type},
        sets=set_items,
        unassigned=[_config_payload(c) for c in unassigned_configs],
        adhoc=adhoc_items,
        summary=summary,
    )
