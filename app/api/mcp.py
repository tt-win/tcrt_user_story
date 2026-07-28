"""MCP 專用唯讀 API。"""

from __future__ import annotations

from typing import Dict, Optional
import json

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.mcp_dependencies import (
    get_current_machine_principal,
    log_mcp_allow,
    require_mcp_team_access,
)
from app.database import get_db
from app.models.database_models import (
    AutomationRun as AutomationRunDB,
    AutomationScript as AutomationScriptDB,
    AutomationScriptCaseLink as AutomationScriptCaseLinkDB,
    AutomationScriptGroup as AutomationScriptGroupDB,
    TestCaseLocal as TestCaseLocalDB,
    TestRunSet as TestRunSetDB,
)
from app.models.mcp import (
    MCPAutomationCoverageSummary,
    MCPAutomationCoverageTrendPoint,
    MCPAutomationCoverageUncoveredCase,
    MCPAutomationRunItem,
    MCPAutomationScriptGroupItem,
    MCPAutomationScriptItem,
    MCPMachinePrincipal,
    MCPPageMeta,
    MCPTeamAutomationCoverageResponse,
    MCPTeamAutomationRunsResponse,
    MCPTeamAutomationScriptGroupsResponse,
    MCPTeamAutomationScriptsResponse,
    MCPTeamTestCaseSectionsResponse,
    MCPTeamTestCasesResponse,
    MCPTeamTestRunsResponse,
    MCPTeamsResponse,
    MCPTestCaseDetailResponse,
    MCPTestCaseLookupResponse,
)
from app.services.automation.coverage_service import AutomationCoverageService
from app.services.automation.script_group_service import _load_script_paths
from app.services.external_read import (
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
    parse_run_types,
    to_text,
)


router = APIRouter(prefix="/mcp", tags=["mcp"])


def _parse_run_types(raw: Optional[str]) -> set[str]:
    try:
        return parse_run_types(raw)
    except UnknownRunTypeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


async def _ensure_team_exists(db: AsyncSession, team_id: int) -> None:
    try:
        await ensure_team_exists(db, team_id)
    except TeamNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.get("/teams", response_model=MCPTeamsResponse)
async def list_teams(
    request: Request,
    db: AsyncSession = Depends(get_db),
    principal: MCPMachinePrincipal = Depends(get_current_machine_principal),
):
    if not principal.allow_all_teams:
        if not principal.team_scope_ids:
            await log_mcp_allow(request, principal, reason="teams_list_allowed_no_scope")
            return MCPTeamsResponse(total=0, items=[])
        allowed: Optional[set[int]] = set(principal.team_scope_ids)
    else:
        allowed = None

    response = await list_teams_read(db, allowed_team_ids=allowed)
    await log_mcp_allow(request, principal, reason="teams_list_allowed")
    return response


@router.get("/test-cases/lookup", response_model=MCPTestCaseLookupResponse)
async def lookup_test_cases(
    request: Request,
    db: AsyncSession = Depends(get_db),
    principal: MCPMachinePrincipal = Depends(get_current_machine_principal),
    q: Optional[str] = Query(
        None, description="關鍵字（可放 test case number / ticket / title）"
    ),
    test_case_number: Optional[str] = Query(
        None, description="Test Case Number（精確或部分匹配）"
    ),
    ticket: Optional[str] = Query(
        None, description="Issue/Ticket/單號（對應 tcg 欄位，支援 TCG/ICR/其他前綴）"
    ),
    team_id: Optional[int] = Query(None, description="限制單一 team_id"),
    team_name: Optional[str] = Query(None, description="Team 名稱模糊搜尋"),
    include_content: bool = Query(
        True, description="是否回傳 precondition/steps/expected_result"
    ),
    include_test_data: bool = Query(
        False, description="是否回傳每筆 case 的 test_data 陣列（含 id/name/category/value）"
    ),
    skip: int = Query(0, ge=0, description="分頁 offset"),
    limit: int = Query(20, ge=1, le=200, description="分頁大小"),
):
    keyword = (q or "").strip()
    number_filter = (test_case_number or "").strip()
    ticket_filter = (ticket or "").strip()

    if not keyword and not number_filter and not ticket_filter:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="至少需要提供 q、test_case_number、ticket 其中之一",
        )

    if team_id is not None:
        await _ensure_team_exists(db, team_id)

    if not principal.allow_all_teams and not principal.team_scope_ids:
        await log_mcp_allow(request, principal, reason="test_case_lookup_no_scope")
        return MCPTestCaseLookupResponse(
            filters={
                "q": q,
                "test_case_number": test_case_number,
                "ticket": ticket,
                "team_id": team_id,
                "team_name": team_name,
                "include_content": include_content,
                "include_test_data": include_test_data,
            },
            items=[],
            page=MCPPageMeta(skip=skip, limit=limit, total=0, has_next=False),
        )

    if team_id is not None:
        if not principal.allow_all_teams and team_id not in principal.team_scope_ids:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "TEAM_SCOPE_DENIED",
                    "message": "無權限存取此 team 的 MCP 資料",
                },
            )

    allowed: Optional[set[int]] = (
        None if principal.allow_all_teams else set(principal.team_scope_ids)
    )

    response = await lookup_test_cases_read(
        db,
        q=q,
        test_case_number=test_case_number,
        ticket=ticket,
        team_id=team_id,
        team_name=team_name,
        include_content=include_content,
        include_test_data=include_test_data,
        skip=skip,
        limit=limit,
        allowed_team_ids=allowed,
    )
    await log_mcp_allow(
        request,
        principal,
        reason="test_case_lookup_allowed",
        team_id=team_id,
    )
    return response


@router.get("/teams/{team_id}/test-cases", response_model=MCPTeamTestCasesResponse)
async def list_team_test_cases(
    team_id: int,
    db: AsyncSession = Depends(get_db),
    principal: MCPMachinePrincipal = Depends(require_mcp_team_access),
    set_id: Optional[int] = Query(None, description="Test Case Set ID"),
    search: Optional[str] = Query(
        None, description="標題/編號模糊搜尋（ticket/單號請用 ticket 或 tcg）"
    ),
    priority: Optional[str] = Query(None, description="Priority 過濾"),
    test_result: Optional[str] = Query(None, description="Test Result 過濾"),
    assignee: Optional[str] = Query(None, description="Assignee 關鍵字過濾"),
    tcg: Optional[str] = Query(
        None, description="Issue/Ticket 關鍵字過濾（對應 tcg 欄位，支援 TCG/ICR/其他前綴）"
    ),
    ticket: Optional[str] = Query(
        None, description="Issue/Ticket/單號關鍵字（同 tcg 欄位）"
    ),
    strict_set: bool = Query(
        False,
        description="set_id 不存在時是否回傳 404（預設 false，會忽略 set 過濾）",
    ),
    include_content: bool = Query(
        False, description="是否回傳 precondition/steps/expected_result"
    ),
    include_test_data: bool = Query(
        False, description="是否回傳每筆 case 的 test_data 陣列（含 id/name/category/value）"
    ),
    skip: int = Query(0, ge=0, description="分頁 offset"),
    limit: int = Query(100, ge=1, le=1000, description="分頁大小"),
):
    del principal  # 由 dependency 完成 team scope 驗證
    await _ensure_team_exists(db, team_id)
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
            strict_set=strict_set,
            include_content=include_content,
            include_test_data=include_test_data,
            skip=skip,
            limit=limit,
        )
    except TestCaseSetNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.get(
    "/teams/{team_id}/test-cases/{test_case_id}",
    response_model=MCPTestCaseDetailResponse,
)
async def get_team_test_case_detail(
    team_id: int,
    test_case_id: int,
    db: AsyncSession = Depends(get_db),
    principal: MCPMachinePrincipal = Depends(require_mcp_team_access),
):
    """Detail 端點預設回傳完整 extended 欄位（含 test_data），與 attachments / raw_fields 等價對待。"""
    del principal  # 由 dependency 完成 team scope 驗證
    await _ensure_team_exists(db, team_id)
    try:
        return await get_team_test_case_detail_read(db, team_id, test_case_id)
    except TestCaseNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.get("/teams/{team_id}/test-runs", response_model=MCPTeamTestRunsResponse)
async def list_team_test_runs(
    team_id: int,
    db: AsyncSession = Depends(get_db),
    principal: MCPMachinePrincipal = Depends(require_mcp_team_access),
    status_filter: Optional[str] = Query(None, alias="status", description="狀態過濾（可逗號分隔）"),
    run_type: Optional[str] = Query("all", description="set / unassigned / adhoc / all"),
    include_archived: bool = Query(False, description="是否包含 archived 狀態"),
):
    del principal  # 由 dependency 完成 team scope 驗證
    await _ensure_team_exists(db, team_id)
    try:
        return await list_team_test_runs_read(
            db,
            team_id,
            status_filter=status_filter,
            run_type=run_type,
            include_archived=include_archived,
        )
    except UnknownRunTypeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc



@router.get(
    "/teams/{team_id}/test-case-sections",
    response_model=MCPTeamTestCaseSectionsResponse,
)
async def list_team_test_case_sections(
    team_id: int,
    db: AsyncSession = Depends(get_db),
    principal: MCPMachinePrincipal = Depends(require_mcp_team_access),
    set_id: Optional[int] = Query(None, description="限制單一 Test Case Set"),
    parent_section_id: Optional[int] = Query(
        None,
        description="限制單一 parent section（取直系 children）；要查 root section 請改用 roots_only",
    ),
    roots_only: bool = Query(
        False, description="是否只回傳 parent_section_id IS NULL 的 root sections"
    ),
    include_empty: bool = Query(
        True, description="是否包含 test_case_count == 0 的 section（預設 true）"
    ),
):
    """列出 team 範圍內的 test case sections（扁平 list，含 parent_section_id 供 client 重組樹）。"""
    del principal  # 由 dependency 完成 team scope 驗證
    await _ensure_team_exists(db, team_id)
    return await list_team_test_case_sections_read(
        db,
        team_id,
        set_id=set_id,
        parent_section_id=parent_section_id,
        roots_only=roots_only,
        include_empty=include_empty,
    )


# ---------------------------------------------------------------- Automation Hub


def _parse_string_list(raw: Optional[str]) -> list[str]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    return [str(item) for item in data if item is not None]


async def _batch_linked_case_numbers(
    db: AsyncSession,
    team_id: int,
    script_ids: list[int],
    *,
    per_script_limit: int = 20,
) -> Dict[int, list[str]]:
    if not script_ids:
        return {}
    result = await db.execute(
        select(
            AutomationScriptCaseLinkDB.automation_script_id,
            TestCaseLocalDB.test_case_number,
            AutomationScriptCaseLinkDB.id,
        )
        .join(
            TestCaseLocalDB,
            TestCaseLocalDB.id == AutomationScriptCaseLinkDB.test_case_id,
        )
        .where(
            AutomationScriptCaseLinkDB.team_id == team_id,
            AutomationScriptCaseLinkDB.automation_script_id.in_(script_ids),
        )
        .order_by(AutomationScriptCaseLinkDB.automation_script_id, AutomationScriptCaseLinkDB.id)
    )
    grouped: Dict[int, list[str]] = {}
    for script_id, test_case_number, _link_id in result.all():
        bucket = grouped.setdefault(int(script_id), [])
        if len(bucket) < per_script_limit and test_case_number:
            bucket.append(str(test_case_number))
    return grouped


@router.get(
    "/teams/{team_id}/automation-scripts",
    response_model=MCPTeamAutomationScriptsResponse,
)
async def list_team_automation_scripts(
    team_id: int,
    db: AsyncSession = Depends(get_db),
    principal: MCPMachinePrincipal = Depends(require_mcp_team_access),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    script_format: Optional[str] = Query(None, description="Filter by script_format"),
    keyword: Optional[str] = Query(None, description="Partial match against name or ref_path"),
):
    del principal
    await _ensure_team_exists(db, team_id)

    conditions = [AutomationScriptDB.team_id == team_id]
    if script_format:
        conditions.append(AutomationScriptDB.script_format == script_format)
    if keyword:
        like = f"%{keyword.strip()}%"
        conditions.append(or_(AutomationScriptDB.name.ilike(like), AutomationScriptDB.ref_path.ilike(like)))

    total_stmt = select(func.count(AutomationScriptDB.id)).where(*conditions)
    total = int((await db.execute(total_stmt)).scalar_one() or 0)

    rows_stmt = (
        select(AutomationScriptDB)
        .where(*conditions)
        .order_by(AutomationScriptDB.id.desc())
        .offset(skip)
        .limit(limit)
    )
    scripts = list((await db.execute(rows_stmt)).scalars().all())
    script_ids = [int(script.id) for script in scripts]

    # last_run batch lookup removed: run history is owned by Test Run Set
    # (see move-run-history-to-test-run-set). Callers wanting the latest
    # run status for a script should follow the script's groups to their
    # triggering Test Run Set.
    linked_numbers = await _batch_linked_case_numbers(db, team_id, script_ids, per_script_limit=20)

    items: list[MCPAutomationScriptItem] = []
    for script in scripts:
        items.append(
            MCPAutomationScriptItem(
                id=int(script.id),
                name=script.name,
                script_format=to_text(script.script_format) or "OTHER",
                ref_path=script.ref_path,
                ref_branch=script.ref_branch,
                description=script.description,
                preferred_runner_label=script.preferred_runner_label,
                tags=_parse_string_list(script.tags_json),
                linked_test_case_count=int(script.linked_test_case_count or 0),
                linked_test_case_numbers=linked_numbers.get(int(script.id), []),
                # last_run_* removed: run history is owned by Test Run Set
                # (see move-run-history-to-test-run-set).
                last_synced_at=script.last_synced_at,
                created_at=script.created_at,
                updated_at=script.updated_at,
            )
        )

    return MCPTeamAutomationScriptsResponse(
        team_id=team_id,
        items=items,
        page=MCPPageMeta(skip=skip, limit=limit, total=total, has_next=(skip + len(items)) < total),
    )


@router.get(
    "/teams/{team_id}/automation-script-groups",
    response_model=MCPTeamAutomationScriptGroupsResponse,
)
async def list_team_automation_script_groups(
    team_id: int,
    db: AsyncSession = Depends(get_db),
    principal: MCPMachinePrincipal = Depends(require_mcp_team_access),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    keyword: Optional[str] = Query(None, description="Partial match against name or description"),
):
    """List executable suites (``AutomationScriptGroup``) for a team.

    Fills the read gap between scripts and runs: a client can enumerate which
    suites exist, what scripts compose them, and the CI job each maps to. The
    ``script_group_id`` carried on automation-run items resolves here.
    """
    del principal
    await _ensure_team_exists(db, team_id)

    conditions = [AutomationScriptGroupDB.team_id == team_id]
    if keyword:
        like = f"%{keyword.strip()}%"
        conditions.append(
            or_(
                AutomationScriptGroupDB.name.ilike(like),
                AutomationScriptGroupDB.description.ilike(like),
            )
        )

    total = int((await db.execute(select(func.count(AutomationScriptGroupDB.id)).where(*conditions))).scalar_one() or 0)

    rows_stmt = (
        select(AutomationScriptGroupDB)
        .where(*conditions)
        .order_by(AutomationScriptGroupDB.id.desc())
        .offset(skip)
        .limit(limit)
    )
    groups = list((await db.execute(rows_stmt)).scalars().all())

    # Resolve each suite's stored ref_paths → current script ids in one query.
    # ref_path is NOT unique within a team (uq is team+provider+ref_repo+ref_path+
    # ref_branch), so a suite must resolve against its OWN repo — key the lookup by
    # (ref_repo, ref_path), mirroring AutomationScriptGroupService.load_group_scripts.
    # Parse with the same _load_script_paths the run path uses so MCP and the Test
    # Run Set trigger agree on a suite's composition.
    paths_by_group = {int(g.id): _load_script_paths(g.script_paths_json) for g in groups}
    all_paths = {path for paths in paths_by_group.values() for path in paths}
    repo_path_to_id: Dict[tuple[str, str], int] = {}
    if all_paths:
        id_rows = await db.execute(
            select(
                AutomationScriptDB.ref_repo,
                AutomationScriptDB.ref_path,
                AutomationScriptDB.id,
            ).where(
                AutomationScriptDB.team_id == team_id,
                AutomationScriptDB.ref_path.in_(all_paths),
            )
        )
        for ref_repo, ref_path, script_id in id_rows.all():
            repo_path_to_id[(ref_repo or "", str(ref_path))] = int(script_id)

    items: list[MCPAutomationScriptGroupItem] = []
    for group in groups:
        repo = group.ref_repo or ""
        paths = paths_by_group[int(group.id)]
        items.append(
            MCPAutomationScriptGroupItem(
                id=int(group.id),
                name=group.name,
                description=group.description,
                ref_repo=group.ref_repo or None,
                script_ids=[
                    repo_path_to_id[(repo, path)]
                    for path in paths
                    if (repo, path) in repo_path_to_id
                ],
                script_paths=paths,
                script_count=len(paths),
                ci_job_name=group.ci_job_name,
                ci_job_type=to_text(group.ci_job_type) or None,
                created_at=group.created_at,
                updated_at=group.updated_at,
            )
        )

    return MCPTeamAutomationScriptGroupsResponse(
        team_id=team_id,
        items=items,
        page=MCPPageMeta(skip=skip, limit=limit, total=total, has_next=(skip + len(items)) < total),
    )


@router.get(
    "/teams/{team_id}/test-run-sets/{set_id}/automation-runs",
    response_model=MCPTeamAutomationRunsResponse,
)
async def list_team_test_run_set_automation_runs(
    team_id: int,
    set_id: int,
    db: AsyncSession = Depends(get_db),
    principal: MCPMachinePrincipal = Depends(require_mcp_team_access),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    status_filter: Optional[str] = Query(None, alias="status"),
    branch: Optional[str] = Query(None),
):
    """List automation runs triggered by a specific Test Run Set.

    Replaces the removed ``GET /api/mcp/teams/{team_id}/automation-runs``
    team-wide endpoint; runs are now scoped to their owning Test Run Set.
    """
    del principal
    await _ensure_team_exists(db, team_id)
    # Verify the set belongs to the team (defensive — surfaces 404 cleanly).
    set_exists = await db.execute(
        select(TestRunSetDB.id).where(
            TestRunSetDB.id == set_id, TestRunSetDB.team_id == team_id
        )
    )
    if set_exists.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "TEST_RUN_SET_NOT_FOUND",
                "message": f"Test Run Set {set_id} not found in team {team_id}",
            },
        )

    conditions = [
        AutomationRunDB.team_id == team_id,
        AutomationRunDB.test_run_set_id == set_id,
    ]
    if status_filter:
        conditions.append(AutomationRunDB.status == status_filter)
    if branch:
        conditions.append(AutomationRunDB.branch == branch.strip())

    total = int((await db.execute(select(func.count(AutomationRunDB.id)).where(*conditions))).scalar_one() or 0)

    rows_stmt = (
        select(AutomationRunDB)
        .where(*conditions)
        .order_by(AutomationRunDB.id.desc())
        .offset(skip)
        .limit(limit)
    )
    rows = list((await db.execute(rows_stmt)).scalars().all())
    items = [
        MCPAutomationRunItem(
            id=int(run.id),
            automation_script_id=run.automation_script_id,
            script_group_id=run.script_group_id,
            test_run_set_id=run.test_run_set_id,
            workflow_id=run.workflow_id,
            branch=run.branch,
            status=to_text(run.status) or "UNKNOWN",
            triggered_by=to_text(run.triggered_by) or "USER",
            triggered_by_user_id=run.triggered_by_user_id,
            external_run_id=run.external_run_id,
            external_run_url=run.external_run_url,
            report_url=run.report_url,
            runner_label=run.runner_label,
            started_at=run.started_at,
            finished_at=run.finished_at,
            duration_ms=run.duration_ms,
            tcrt_correlation_id=run.tcrt_correlation_id,
            error_summary=run.error_summary,
            created_at=run.created_at,
            updated_at=run.updated_at,
        )
        for run in rows
    ]

    return MCPTeamAutomationRunsResponse(
        team_id=team_id,
        items=items,
        page=MCPPageMeta(skip=skip, limit=limit, total=total, has_next=(skip + len(items)) < total),
    )


@router.get(
    "/teams/{team_id}/automation-coverage",
    response_model=MCPTeamAutomationCoverageResponse,
)
async def get_team_automation_coverage(
    team_id: int,
    db: AsyncSession = Depends(get_db),
    principal: MCPMachinePrincipal = Depends(require_mcp_team_access),
    uncovered_limit: int = Query(50, ge=1, le=200),
):
    del principal
    await _ensure_team_exists(db, team_id)

    service = AutomationCoverageService(db)
    data = await service.compute_coverage(
        team_id=team_id,
        uncovered_limit=uncovered_limit,
    )

    summary = MCPAutomationCoverageSummary(
        total_test_cases=int(data.get("total_test_cases", 0) or 0),
        with_primary_link=int(data.get("with_primary_link", 0) or 0),
        with_covers_link=int(data.get("with_covers_link", 0) or 0),
        with_any_link=int(data.get("with_any_link", 0) or 0),
        uncovered_count=int(data.get("uncovered_count", 0) or 0),
        by_format={str(k): int(v or 0) for k, v in (data.get("by_format") or {}).items()},
    )
    uncovered = [
        MCPAutomationCoverageUncoveredCase(
            test_case_id=int(item["test_case_id"]),
            test_case_number=item.get("test_case_number"),
            title=item.get("title"),
        )
        for item in (data.get("uncovered_sample") or [])
    ]
    trend = [
        MCPAutomationCoverageTrendPoint(
            date=item["date"],
            with_primary_link=int(item.get("with_primary_link", 0) or 0),
            with_any_link=int(item.get("with_any_link", 0) or 0),
            uncovered_count=int(item.get("uncovered_count", 0) or 0),
            coverage_rate=float(item.get("coverage_rate", 0.0) or 0.0),
        )
        for item in (data.get("trend") or [])
    ]
    return MCPTeamAutomationCoverageResponse(
        team_id=team_id,
        summary=summary,
        uncovered_sample=uncovered,
        trend=trend,
    )
