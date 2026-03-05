"""MCP 專用唯讀 API。"""

from __future__ import annotations

from typing import Any, Dict, Iterable, Optional
import json

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.auth.mcp_dependencies import (
    get_current_machine_principal,
    log_mcp_allow,
    require_mcp_team_access,
)
from app.database import get_db
from app.models.database_models import (
    AdHocRun,
    AdHocRunSheet,
    Team as TeamDB,
    TestCaseLocal as TestCaseLocalDB,
    TestCaseSet as TestCaseSetDB,
    TestRunConfig as TestRunConfigDB,
    TestRunSet as TestRunSetDB,
    TestRunSetMembership as TestRunSetMembershipDB,
)
from app.models.lark_types import Priority, TestResultStatus
from app.models.mcp import (
    MCPCrossTeamTestCaseItem,
    MCPAdhocRunItem,
    MCPMachinePrincipal,
    MCPPageMeta,
    MCPTeamItem,
    MCPTestCaseLookupResponse,
    MCPTeamTestCasesResponse,
    MCPTeamTestRunsResponse,
    MCPTeamsResponse,
    MCPTestCaseDetailResponse,
    MCPTestCaseSetItem,
    MCPTestRunSetItem,
)
from app.models.test_run_set import TestRunSetStatus
from app.services.test_run_set_status import resolve_status_for_response


router = APIRouter(prefix="/mcp", tags=["mcp"])


def _to_text(value: Any) -> str:
    if value is None:
        return ""
    return value.value if hasattr(value, "value") else str(value)


def _parse_assignee(assignee_json: Optional[str]) -> Optional[str]:
    if not assignee_json:
        return None
    try:
        payload = json.loads(assignee_json)
    except (TypeError, ValueError):
        return assignee_json

    if isinstance(payload, dict):
        return payload.get("name") or payload.get("en_name") or payload.get("email")

    if isinstance(payload, list):
        names: list[str] = []
        for item in payload:
            if isinstance(item, dict):
                candidate = item.get("name") or item.get("en_name") or item.get("email")
                if candidate:
                    names.append(str(candidate))
            elif item:
                names.append(str(item))
        if names:
            return ", ".join(names)

    return assignee_json


def _parse_tcg_list(tcg_json: Optional[str]) -> list[str]:
    if not tcg_json:
        return []
    try:
        parsed = json.loads(tcg_json)
    except (TypeError, ValueError):
        return []

    if isinstance(parsed, list):
        return [str(item) for item in parsed if item]
    if isinstance(parsed, str):
        return [parsed]
    return []


def _parse_json_list(raw_json: Optional[str]) -> list[Dict[str, Any]]:
    if not raw_json:
        return []
    try:
        parsed = json.loads(raw_json)
    except (TypeError, ValueError):
        return []

    if not isinstance(parsed, list):
        return []

    normalized: list[Dict[str, Any]] = []
    for item in parsed:
        if isinstance(item, dict):
            normalized.append(item)
        elif item is not None:
            normalized.append({"value": item})
    return normalized


def _parse_json_dict(raw_json: Optional[str]) -> Optional[Dict[str, Any]]:
    if not raw_json:
        return None
    try:
        parsed = json.loads(raw_json)
    except (TypeError, ValueError):
        return None
    if isinstance(parsed, dict):
        return parsed
    return None


def _build_case_payload(
    row: TestCaseLocalDB,
    *,
    include_content: bool = False,
    include_extended: bool = False,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "id": row.id,
        "record_id": row.lark_record_id or str(row.id),
        "test_case_number": row.test_case_number,
        "title": row.title,
        "priority": _to_text(row.priority),
        "test_result": _to_text(row.test_result) or None,
        "assignee": _parse_assignee(row.assignee_json),
        "tcg": _parse_tcg_list(row.tcg_json),
        "test_case_set_id": row.test_case_set_id,
        "test_case_section_id": row.test_case_section_id,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "last_sync_at": row.last_sync_at,
    }
    if include_content:
        payload.update(
            {
                "precondition": row.precondition,
                "steps": row.steps,
                "expected_result": row.expected_result,
            }
        )
    if include_extended:
        payload.update(
            {
                "attachments": _parse_json_list(row.attachments_json),
                "test_results_files": _parse_json_list(row.test_results_files_json),
                "user_story_map": _parse_json_list(row.user_story_map_json),
                "parent_record": _parse_json_list(row.parent_record_json),
                "raw_fields": _parse_json_dict(row.raw_fields_json),
            }
        )
    return payload


def _lookup_match_type(
    row: TestCaseLocalDB,
    *,
    keyword: Optional[str],
    test_case_number: Optional[str],
    ticket: Optional[str],
) -> str:
    number_value = (row.test_case_number or "").lower()
    title_value = (row.title or "").lower()
    tcg_values = [item.lower() for item in _parse_tcg_list(row.tcg_json)]

    if test_case_number:
        normalized = test_case_number.lower()
        if number_value == normalized:
            return "test_case_number_exact"
        if normalized in number_value:
            return "test_case_number_partial"

    if ticket:
        normalized = ticket.lower()
        if any(normalized in item for item in tcg_values):
            return "ticket"

    if keyword:
        normalized = keyword.lower()
        if number_value == normalized:
            return "keyword_number_exact"
        if normalized in number_value:
            return "keyword_number_partial"
        if any(normalized in item for item in tcg_values):
            return "keyword_ticket"
        if normalized in title_value:
            return "keyword_title"

    return "matched"


def _normalize_priority_filter(raw: Optional[str]) -> Optional[Any]:
    if not raw:
        return None
    normalized = raw.strip().lower()
    if not normalized:
        return None
    for enum_item in Priority:
        if normalized in {enum_item.name.lower(), enum_item.value.lower()}:
            return enum_item
    return raw.strip()


def _normalize_result_filter(raw: Optional[str]) -> Optional[Any]:
    if not raw:
        return None
    normalized = raw.strip().lower()
    if not normalized:
        return None
    for enum_item in TestResultStatus:
        if normalized in {enum_item.name.lower(), enum_item.value.lower()}:
            return enum_item
    return raw.strip()


def _parse_status_filters(raw: Optional[str]) -> set[str]:
    if not raw:
        return set()
    return {item.strip().lower() for item in raw.split(",") if item.strip()}


def _parse_run_types(raw: Optional[str]) -> set[str]:
    if not raw:
        return {"set", "unassigned", "adhoc"}
    values = {item.strip().lower() for item in raw.split(",") if item.strip()}
    if "all" in values:
        return {"set", "unassigned", "adhoc"}
    allowed = {"set", "unassigned", "adhoc"}
    unknown = values - allowed
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"run_type 不支援的值: {', '.join(sorted(unknown))}",
        )
    if not values:
        return {"set", "unassigned", "adhoc"}
    return values


def _status_match(value: Any, filters: set[str]) -> bool:
    if not filters:
        return True
    return _to_text(value).lower() in filters


async def _ensure_team_exists(db: AsyncSession, team_id: int) -> None:
    result = await db.execute(select(TeamDB.id).where(TeamDB.id == team_id))
    if result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"找不到團隊 ID {team_id}",
        )


@router.get("/teams", response_model=MCPTeamsResponse)
async def list_teams(
    request: Request,
    db: AsyncSession = Depends(get_db),
    principal: MCPMachinePrincipal = Depends(get_current_machine_principal),
):
    stmt = select(TeamDB).order_by(TeamDB.id.asc())
    if not principal.allow_all_teams:
        if not principal.team_scope_ids:
            await log_mcp_allow(request, principal, reason="teams_list_allowed_no_scope")
            return MCPTeamsResponse(total=0, items=[])
        stmt = stmt.where(TeamDB.id.in_(principal.team_scope_ids))

    teams = (await db.execute(stmt)).scalars().all()
    items = [
        MCPTeamItem(
            id=team.id,
            name=team.name,
            description=team.description,
            status=_to_text(team.status) or "active",
            test_case_count=team.test_case_count or 0,
            created_at=team.created_at,
            updated_at=team.updated_at,
            last_sync_at=team.last_sync_at,
            is_lark_configured=bool(team.wiki_token and team.test_case_table_id),
            is_jira_configured=bool(team.jira_project_key),
        )
        for team in teams
    ]
    await log_mcp_allow(request, principal, reason="teams_list_allowed")
    return MCPTeamsResponse(total=len(items), items=items)


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
    skip: int = Query(0, ge=0, description="分頁 offset"),
    limit: int = Query(20, ge=1, le=200, description="分頁大小"),
):
    keyword = (q or "").strip()
    number_filter = (test_case_number or "").strip()
    ticket_filter = (ticket or "").strip()
    team_name_filter = (team_name or "").strip()

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
            },
            items=[],
            page=MCPPageMeta(skip=skip, limit=limit, total=0, has_next=False),
        )

    conditions = []
    if not principal.allow_all_teams:
        conditions.append(TestCaseLocalDB.team_id.in_(principal.team_scope_ids))

    if team_id is not None:
        if not principal.allow_all_teams and team_id not in principal.team_scope_ids:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "TEAM_SCOPE_DENIED",
                    "message": "無權限存取此 team 的 MCP 資料",
                },
            )
        conditions.append(TestCaseLocalDB.team_id == team_id)

    if team_name_filter:
        conditions.append(TeamDB.name.ilike(f"%{team_name_filter}%"))

    if number_filter:
        conditions.append(TestCaseLocalDB.test_case_number.ilike(f"%{number_filter}%"))

    if ticket_filter:
        conditions.append(TestCaseLocalDB.tcg_json.ilike(f"%{ticket_filter}%"))

    if keyword:
        pattern = f"%{keyword}%"
        conditions.append(
            or_(
                TestCaseLocalDB.test_case_number.ilike(pattern),
                TestCaseLocalDB.title.ilike(pattern),
                TestCaseLocalDB.tcg_json.ilike(pattern),
            )
        )

    total = (
        await db.execute(
            select(func.count(TestCaseLocalDB.id))
            .select_from(TestCaseLocalDB)
            .join(TeamDB, TeamDB.id == TestCaseLocalDB.team_id)
            .where(*conditions)
        )
    ).scalar_one()
    has_next = bool(total > skip + limit)

    rows = (
        await db.execute(
            select(TestCaseLocalDB, TeamDB.name)
            .join(TeamDB, TeamDB.id == TestCaseLocalDB.team_id)
            .where(*conditions)
            .order_by(TestCaseLocalDB.created_at.desc(), TestCaseLocalDB.id.desc())
            .offset(skip)
            .limit(limit)
        )
    ).all()

    items: list[MCPCrossTeamTestCaseItem] = []
    for row, resolved_team_name in rows:
        items.append(
            MCPCrossTeamTestCaseItem(
                team_id=row.team_id,
                team_name=resolved_team_name,
                match_type=_lookup_match_type(
                    row,
                    keyword=keyword or None,
                    test_case_number=number_filter or None,
                    ticket=ticket_filter or None,
                ),
                test_case=_build_case_payload(row, include_content=include_content),
            )
        )

    await log_mcp_allow(
        request,
        principal,
        reason="test_case_lookup_allowed",
        team_id=team_id,
    )
    return MCPTestCaseLookupResponse(
        filters={
            "q": q,
            "test_case_number": test_case_number,
            "ticket": ticket,
            "team_id": team_id,
            "team_name": team_name,
            "include_content": include_content,
        },
        items=items,
        page=MCPPageMeta(skip=skip, limit=limit, total=int(total), has_next=has_next),
    )


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
    skip: int = Query(0, ge=0, description="分頁 offset"),
    limit: int = Query(100, ge=1, le=1000, description="分頁大小"),
):
    del principal  # 由 dependency 完成 team scope 驗證
    await _ensure_team_exists(db, team_id)

    set_not_found = False
    resolved_set_id: Optional[int] = set_id
    if set_id is not None:
        set_exists = await db.execute(
            select(TestCaseSetDB.id).where(
                TestCaseSetDB.id == set_id,
                TestCaseSetDB.team_id == team_id,
            )
        )
        if set_exists.scalar_one_or_none() is None:
            if strict_set:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"找不到團隊 {team_id} 的 Test Case Set {set_id}",
                )
            set_not_found = True
            resolved_set_id = None

    set_count_rows = await db.execute(
        select(TestCaseLocalDB.test_case_set_id, func.count(TestCaseLocalDB.id))
        .where(TestCaseLocalDB.team_id == team_id)
        .group_by(TestCaseLocalDB.test_case_set_id)
    )
    set_count_map = {set_id_value: count for set_id_value, count in set_count_rows.all()}

    set_rows = await db.execute(
        select(TestCaseSetDB)
        .where(TestCaseSetDB.team_id == team_id)
        .order_by(TestCaseSetDB.created_at.desc(), TestCaseSetDB.id.desc())
    )
    set_items = [
        MCPTestCaseSetItem(
            id=case_set.id,
            name=case_set.name,
            description=case_set.description,
            is_default=bool(case_set.is_default),
            test_case_count=int(set_count_map.get(case_set.id, 0) or 0),
            created_at=case_set.created_at,
            updated_at=case_set.updated_at,
        )
        for case_set in set_rows.scalars().all()
    ]

    conditions = [TestCaseLocalDB.team_id == team_id]
    if resolved_set_id is not None:
        conditions.append(TestCaseLocalDB.test_case_set_id == resolved_set_id)
    if search and search.strip():
        pattern = f"%{search.strip()}%"
        conditions.append(
            or_(
                TestCaseLocalDB.title.ilike(pattern),
                TestCaseLocalDB.test_case_number.ilike(pattern),
                TestCaseLocalDB.tcg_json.ilike(pattern),
            )
        )

    priority_filter = _normalize_priority_filter(priority)
    if priority_filter is not None:
        conditions.append(TestCaseLocalDB.priority == priority_filter)

    result_filter = _normalize_result_filter(test_result)
    if result_filter is not None:
        conditions.append(TestCaseLocalDB.test_result == result_filter)

    if assignee and assignee.strip():
        conditions.append(TestCaseLocalDB.assignee_json.ilike(f"%{assignee.strip()}%"))
    tcg_filters = [value.strip() for value in (tcg, ticket) if value and value.strip()]
    if tcg_filters:
        if len(tcg_filters) == 1:
            conditions.append(TestCaseLocalDB.tcg_json.ilike(f"%{tcg_filters[0]}%"))
        else:
            conditions.append(
                or_(*[TestCaseLocalDB.tcg_json.ilike(f"%{value}%") for value in tcg_filters])
            )

    total = (
        await db.execute(select(func.count(TestCaseLocalDB.id)).where(*conditions))
    ).scalar_one()
    has_next = bool(total > skip + limit)

    rows = (
        await db.execute(
            select(TestCaseLocalDB)
            .where(*conditions)
            .order_by(TestCaseLocalDB.created_at.desc(), TestCaseLocalDB.id.desc())
            .offset(skip)
            .limit(limit)
        )
    ).scalars().all()

    cases: list[Dict[str, Any]] = []
    for row in rows:
        cases.append(_build_case_payload(row, include_content=include_content))

    return MCPTeamTestCasesResponse(
        team_id=team_id,
        filters={
            "set_id": set_id,
            "resolved_set_id": resolved_set_id,
            "set_not_found": set_not_found,
            "search": search,
            "priority": priority,
            "test_result": test_result,
            "assignee": assignee,
            "tcg": tcg,
            "ticket": ticket,
            "strict_set": strict_set,
            "include_content": include_content,
        },
        sets=set_items,
        test_cases=cases,
        page=MCPPageMeta(skip=skip, limit=limit, total=int(total), has_next=has_next),
    )


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
    del principal  # 由 dependency 完成 team scope 驗證
    await _ensure_team_exists(db, team_id)

    row = (
        await db.execute(
            select(TestCaseLocalDB).where(
                TestCaseLocalDB.team_id == team_id,
                TestCaseLocalDB.id == test_case_id,
            )
        )
    ).scalar_one_or_none()

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"找不到團隊 {team_id} 的 Test Case {test_case_id}",
        )

    return MCPTestCaseDetailResponse(
        team_id=team_id,
        test_case=_build_case_payload(
            row,
            include_content=True,
            include_extended=True,
        ),
    )


def _config_payload(config: TestRunConfigDB) -> Dict[str, Any]:
    return {
        "id": config.id,
        "name": config.name,
        "status": _to_text(config.status),
        "total_test_cases": config.total_test_cases or 0,
        "executed_cases": config.executed_cases or 0,
        "passed_cases": config.passed_cases or 0,
        "failed_cases": config.failed_cases or 0,
        "created_at": config.created_at,
        "updated_at": config.updated_at,
    }


def _apply_archive_and_status(
    items: Iterable[Any],
    status_filters: set[str],
    *,
    include_archived: bool,
) -> list[Any]:
    result_items: list[Any] = []
    for item in items:
        item_status = _to_text(getattr(item, "status", ""))
        if not include_archived and item_status.lower() == TestRunSetStatus.ARCHIVED.value:
            continue
        if not _status_match(item_status, status_filters):
            continue
        result_items.append(item)
    return result_items


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

    status_filters = _parse_status_filters(status_filter)
    run_types = _parse_run_types(run_type)

    set_payloads: list[MCPTestRunSetItem] = []
    unassigned_payloads: list[Dict[str, Any]] = []
    adhoc_payloads: list[MCPAdhocRunItem] = []

    if "set" in run_types:
        set_rows = (
            await db.execute(
                select(TestRunSetDB)
                .where(TestRunSetDB.team_id == team_id)
                .options(
                    joinedload(TestRunSetDB.memberships).joinedload(
                        TestRunSetMembershipDB.config
                    )
                )
                .order_by(TestRunSetDB.created_at.desc(), TestRunSetDB.id.desc())
            )
        ).scalars().unique().all()

        for run_set in set_rows:
            set_status = _to_text(resolve_status_for_response(run_set))
            if not include_archived and set_status.lower() == TestRunSetStatus.ARCHIVED.value:
                continue

            test_runs: list[Dict[str, Any]] = []
            memberships = sorted(
                run_set.memberships or [],
                key=lambda item: ((item.position or 0), item.id),
            )
            for membership in memberships:
                config = membership.config
                if not config:
                    continue
                config_status = _to_text(config.status)
                if not include_archived and config_status.lower() == TestRunSetStatus.ARCHIVED.value:
                    continue
                if not _status_match(config_status, status_filters):
                    continue
                test_runs.append(_config_payload(config))

            if status_filters and not _status_match(set_status, status_filters) and not test_runs:
                continue

            set_payloads.append(
                MCPTestRunSetItem(
                    id=run_set.id,
                    name=run_set.name,
                    status=set_status,
                    test_runs=test_runs,
                )
            )

    if "unassigned" in run_types:
        unassigned_rows = (
            await db.execute(
                select(TestRunConfigDB)
                .outerjoin(
                    TestRunSetMembershipDB,
                    TestRunSetMembershipDB.config_id == TestRunConfigDB.id,
                )
                .where(
                    TestRunConfigDB.team_id == team_id,
                    TestRunSetMembershipDB.id.is_(None),
                )
                .order_by(TestRunConfigDB.created_at.desc(), TestRunConfigDB.id.desc())
            )
        ).scalars().all()
        filtered_unassigned = _apply_archive_and_status(
            unassigned_rows,
            status_filters,
            include_archived=include_archived,
        )
        unassigned_payloads = [_config_payload(config) for config in filtered_unassigned]

    if "adhoc" in run_types:
        adhoc_rows = (
            await db.execute(
                select(AdHocRun)
                .where(AdHocRun.team_id == team_id)
                .options(joinedload(AdHocRun.sheets).joinedload(AdHocRunSheet.items))
                .order_by(AdHocRun.updated_at.desc(), AdHocRun.id.desc())
            )
        ).scalars().unique().all()

        filtered_adhoc = _apply_archive_and_status(
            adhoc_rows,
            status_filters,
            include_archived=include_archived,
        )
        def _adhoc_counts(run: AdHocRun) -> tuple[int, int]:
            total = 0
            executed = 0
            for sheet in run.sheets or []:
                items = sheet.items or []
                total += len(items)
                executed += sum(1 for item in items if getattr(item, "test_result", None))
            return total, executed

        adhoc_payloads = []
        for run in filtered_adhoc:
            total_test_cases, executed_cases = _adhoc_counts(run)
            adhoc_payloads.append(
                MCPAdhocRunItem(
                    id=run.id,
                    name=run.name,
                    status=_to_text(run.status),
                    total_test_cases=total_test_cases,
                    executed_cases=executed_cases,
                    created_at=run.created_at,
                    updated_at=run.updated_at,
                )
            )

    set_run_count = sum(len(run_set.test_runs) for run_set in set_payloads)
    total_runs = set_run_count + len(unassigned_payloads) + len(adhoc_payloads)
    return MCPTeamTestRunsResponse(
        team_id=team_id,
        filters={
            "status": status_filter,
            "run_type": run_type,
            "include_archived": include_archived,
        },
        sets=set_payloads,
        unassigned=unassigned_payloads,
        adhoc=adhoc_payloads,
        summary={
            "set_count": len(set_payloads),
            "set_run_count": set_run_count,
            "unassigned_count": len(unassigned_payloads),
            "adhoc_count": len(adhoc_payloads),
            "total_runs": total_runs,
        },
    )
