"""MCP 專用唯讀 API。"""

from __future__ import annotations

from typing import Any, Dict, Iterable, Optional
import json
import orjson

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
    AutomationRun as AutomationRunDB,
    AutomationScript as AutomationScriptDB,
    AutomationScriptCaseLink as AutomationScriptCaseLinkDB,
    AutomationScriptGroup as AutomationScriptGroupDB,
    Team as TeamDB,
    TestCaseLocal as TestCaseLocalDB,
    TestCaseSection as TestCaseSectionDB,
    TestCaseSet as TestCaseSetDB,
    TestRunConfig as TestRunConfigDB,
    TestRunSet as TestRunSetDB,
    TestRunSetMembership as TestRunSetMembershipDB,
)
from app.models.test_case import redact_credential_test_data
from app.models.lark_types import Priority, TestResultStatus
from app.models.mcp import (
    MCPAdhocRunItem,
    MCPAutomationCoverageSummary,
    MCPAutomationCoverageTrendPoint,
    MCPAutomationCoverageUncoveredCase,
    MCPAutomationRunItem,
    MCPAutomationScriptGroupItem,
    MCPAutomationScriptItem,
    MCPCrossTeamTestCaseItem,
    MCPMachinePrincipal,
    MCPPageMeta,
    MCPTeamAutomationCoverageResponse,
    MCPTeamAutomationRunsResponse,
    MCPTeamAutomationScriptGroupsResponse,
    MCPTeamAutomationScriptsResponse,
    MCPTeamItem,
    MCPTeamTestCaseSectionsResponse,
    MCPTeamTestCasesResponse,
    MCPTeamTestRunsResponse,
    MCPTeamsResponse,
    MCPTestCaseDetailResponse,
    MCPTestCaseLookupResponse,
    MCPTestCaseSectionItem,
    MCPTestCaseSetItem,
    MCPTestRunSetItem,
)
from app.services.automation.coverage_service import AutomationCoverageService
from app.services.automation.linkage_service import AutomationLinkageService
from app.services.automation.script_group_service import _load_script_paths
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
    # MCP read API 對 JSON 陣列欄位（如 test_data, attachments）採 dict 直接 passthrough，
    # 不做欄位正規化，保留 id/name/category/value 四欄位；credential 類 test_data 的 value
    # 由 _build_case_payload 於回應組裝時以 redact_credential_test_data() 遮蔽。
    if not raw_json:
        return []
    try:
        parsed = orjson.loads(raw_json)
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
    include_test_data: bool = False,
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
                "test_data": redact_credential_test_data(_parse_json_list(row.test_data_json)),
            }
        )
    elif include_test_data:
        payload["test_data"] = redact_credential_test_data(_parse_json_list(row.test_data_json))
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
    team_case_counts = await _get_team_case_counts(db)
    items = [
        MCPTeamItem(
            id=team.id,
            name=team.name,
            description=team.description,
            status=_to_text(team.status) or "active",
            test_case_count=team_case_counts.get(team.id, 0),
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
    include_test_data: bool = Query(
        False, description="是否回傳每筆 case 的 test_data 陣列（含 id/name/category/value）"
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
                "include_test_data": include_test_data,
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
                test_case=_build_case_payload(
                    row,
                    include_content=include_content,
                    include_test_data=include_test_data,
                ),
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
            "include_test_data": include_test_data,
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
    include_test_data: bool = Query(
        False, description="是否回傳每筆 case 的 test_data 陣列（含 id/name/category/value）"
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
        cases.append(
            _build_case_payload(
                row,
                include_content=include_content,
                include_test_data=include_test_data,
            )
        )

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
            "include_test_data": include_test_data,
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
    """Detail 端點預設回傳完整 extended 欄位（含 test_data），與 attachments / raw_fields 等價對待。"""
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

    linkage_service = AutomationLinkageService(db)
    try:
        linked_automation = await linkage_service.list_linked_automation(
            team_id=team_id,
            test_case_id=test_case_id,
        )
    except Exception:
        linked_automation = []

    payload = _build_case_payload(
        row,
        include_content=True,
        include_extended=True,
    )
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
    return MCPTestCaseDetailResponse(
        team_id=team_id,
        test_case=payload,
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



async def _get_team_case_counts(db: AsyncSession) -> dict[int, int]:
    """回傳 {team_id: 該 team 的 test case 總數}；`Team.test_case_count` 欄位無人維護，勿使用。"""
    rows = await db.execute(
        select(TestCaseLocalDB.team_id, func.count(TestCaseLocalDB.id))
        .group_by(TestCaseLocalDB.team_id)
    )
    return {team_id: int(count or 0) for team_id, count in rows.all()}


async def _get_section_case_counts(
    db: AsyncSession, team_id: int
) -> dict[int, int]:
    """回傳 {section_id: 直接掛在該 section 的 case 數}，section_id 為 NULL 的不計。"""
    rows = await db.execute(
        select(
            TestCaseLocalDB.test_case_section_id,
            func.count(TestCaseLocalDB.id),
        )
        .where(
            TestCaseLocalDB.team_id == team_id,
            TestCaseLocalDB.test_case_section_id.is_not(None),
        )
        .group_by(TestCaseLocalDB.test_case_section_id)
    )
    return {section_id: int(count or 0) for section_id, count in rows.all()}


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

    set_not_found = False
    if set_id is not None:
        set_exists = await db.execute(
            select(TestCaseSetDB.id).where(
                TestCaseSetDB.id == set_id,
                TestCaseSetDB.team_id == team_id,
            )
        )
        if set_exists.scalar_one_or_none() is None:
            set_not_found = True
            return MCPTeamTestCaseSectionsResponse(
                team_id=team_id,
                filters={
                    "set_id": set_id,
                    "set_not_found": set_not_found,
                    "parent_section_id": parent_section_id,
                    "roots_only": roots_only,
                    "include_empty": include_empty,
                },
                sections=[],
                total=0,
            )

    count_map = await _get_section_case_counts(db, team_id)

    conditions = [TestCaseSetDB.team_id == team_id]
    if set_id is not None:
        conditions.append(TestCaseSectionDB.test_case_set_id == set_id)
    if roots_only:
        conditions.append(TestCaseSectionDB.parent_section_id.is_(None))
    elif parent_section_id is not None:
        conditions.append(TestCaseSectionDB.parent_section_id == parent_section_id)

    rows = (
        await db.execute(
            select(TestCaseSectionDB)
            .join(
                TestCaseSetDB,
                TestCaseSetDB.id == TestCaseSectionDB.test_case_set_id,
            )
            .where(*conditions)
            .order_by(
                TestCaseSectionDB.test_case_set_id.asc(),
                TestCaseSectionDB.level.asc(),
                TestCaseSectionDB.sort_order.asc(),
                TestCaseSectionDB.id.asc(),
            )
        )
    ).scalars().all()

    sections: list[MCPTestCaseSectionItem] = []
    for row in rows:
        case_count = count_map.get(row.id, 0)
        if not include_empty and case_count == 0:
            continue
        sections.append(
            MCPTestCaseSectionItem(
                id=row.id,
                test_case_set_id=row.test_case_set_id,
                parent_section_id=row.parent_section_id,
                name=row.name,
                description=row.description,
                level=row.level,
                sort_order=row.sort_order,
                test_case_count=case_count,
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
        )

    return MCPTeamTestCaseSectionsResponse(
        team_id=team_id,
        filters={
            "set_id": set_id,
            "set_not_found": set_not_found,
            "parent_section_id": parent_section_id,
            "roots_only": roots_only,
            "include_empty": include_empty,
        },
        sections=sections,
        total=len(sections),
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
                script_format=_to_text(script.script_format) or "OTHER",
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
                ci_job_type=_to_text(group.ci_job_type) or None,
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
            status=_to_text(run.status) or "UNKNOWN",
            triggered_by=_to_text(run.triggered_by) or "USER",
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
