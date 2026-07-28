"""External read-only queries shared by /api/mcp/* and /api/app/*.

Read-only only: no session open, no commit/rollback, no HTTPException, no mutation.

allowed_team_ids: None = unrestricted; empty frozenset/set = empty result; never emit SQL IN ().

Compare with "is None" and "len(...)==0" only — never "if not allowed_team_ids".
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.models.database_models import (
    AdHocRun,
    AdHocRunSheet,
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
from app.models.test_run_set import TestRunSetStatus
from app.services.automation.linkage_service import AutomationLinkageService
from app.services.external_read.counts import (
    get_section_case_counts,
    get_team_case_counts,
)
from app.services.external_read.errors import (
    MissingLookupFilterError,
    TestCaseNotFoundError,
    TestCaseSetNotFoundError,
    TeamNotFoundError,
)
from app.services.external_read.filters import (
    apply_archive_and_status,
    normalize_priority_filter,
    normalize_result_filter,
    parse_run_types,
    parse_status_filters,
    status_match,
)
from app.services.external_read.payloads import (
    build_case_payload,
    config_payload,
    lookup_match_type,
    to_text,
)
from app.services.test_run_set_status import resolve_status_for_response


async def ensure_team_exists(db: AsyncSession, team_id: int) -> None:
    result = await db.execute(select(TeamDB.id).where(TeamDB.id == team_id))
    if result.scalar_one_or_none() is None:
        raise TeamNotFoundError(team_id)


async def list_teams_read(
    db: AsyncSession,
    *,
    allowed_team_ids: Optional[set[int]] = None,
) -> MCPTeamsResponse:
    if allowed_team_ids is not None and len(allowed_team_ids) == 0:
        return MCPTeamsResponse(total=0, items=[])

    stmt = select(TeamDB).order_by(TeamDB.id.asc())
    if allowed_team_ids is not None:
        stmt = stmt.where(TeamDB.id.in_(allowed_team_ids))

    teams = (await db.execute(stmt)).scalars().all()
    team_case_counts = await get_team_case_counts(db)
    items = [
        MCPTeamItem(
            id=team.id,
            name=team.name,
            description=team.description,
            status=to_text(team.status) or "active",
            test_case_count=team_case_counts.get(team.id, 0),
            created_at=team.created_at,
            updated_at=team.updated_at,
            last_sync_at=team.last_sync_at,
            is_lark_configured=False,
            is_jira_configured=bool(team.jira_project_key),
        )
        for team in teams
    ]
    return MCPTeamsResponse(total=len(items), items=items)


async def list_team_test_cases_read(
    db: AsyncSession,
    team_id: int,
    *,
    set_id: Optional[int] = None,
    search: Optional[str] = None,
    priority: Optional[str] = None,
    test_result: Optional[str] = None,
    assignee: Optional[str] = None,
    tcg: Optional[str] = None,
    ticket: Optional[str] = None,
    section_id: Optional[int] = None,
    strict_set: bool = False,
    include_content: bool = False,
    include_test_data: bool = False,
    skip: int = 0,
    limit: int = 100,
) -> MCPTeamTestCasesResponse:
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
                raise TestCaseSetNotFoundError(team_id, set_id)
            set_not_found = True
            resolved_set_id = None

    set_count_rows = await db.execute(
        select(TestCaseLocalDB.test_case_set_id, func.count(TestCaseLocalDB.id))
        .where(TestCaseLocalDB.team_id == team_id)
        .group_by(TestCaseLocalDB.test_case_set_id)
    )
    set_count_map = {sid: count for sid, count in set_count_rows.all()}

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

    conditions: list[Any] = [TestCaseLocalDB.team_id == team_id]
    if resolved_set_id is not None:
        conditions.append(TestCaseLocalDB.test_case_set_id == resolved_set_id)
    if section_id is not None:
        conditions.append(TestCaseLocalDB.test_case_section_id == section_id)
    if search and search.strip():
        pattern = f"%{search.strip()}%"
        conditions.append(
            or_(
                TestCaseLocalDB.title.ilike(pattern),
                TestCaseLocalDB.test_case_number.ilike(pattern),
                TestCaseLocalDB.tcg_json.ilike(pattern),
            )
        )

    priority_filter = normalize_priority_filter(priority)
    if priority_filter is not None:
        conditions.append(TestCaseLocalDB.priority == priority_filter)

    result_filter = normalize_result_filter(test_result)
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

    cases: list[Dict[str, Any]] = [
        build_case_payload(
            row,
            include_content=include_content,
            include_test_data=include_test_data,
        )
        for row in rows
    ]

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
            "section_id": section_id,
            "strict_set": strict_set,
            "include_content": include_content,
            "include_test_data": include_test_data,
        },
        sets=set_items,
        test_cases=cases,
        page=MCPPageMeta(skip=skip, limit=limit, total=int(total), has_next=has_next),
    )


async def get_team_test_case_detail_read(
    db: AsyncSession,
    team_id: int,
    case_id: int,
) -> MCPTestCaseDetailResponse:
    row = (
        await db.execute(
            select(TestCaseLocalDB).where(
                TestCaseLocalDB.team_id == team_id,
                TestCaseLocalDB.id == case_id,
            )
        )
    ).scalar_one_or_none()

    if row is None:
        raise TestCaseNotFoundError(team_id, case_id)

    linkage_service = AutomationLinkageService(db)
    try:
        linked_automation = await linkage_service.list_linked_automation(
            team_id=team_id,
            test_case_id=case_id,
        )
    except Exception:
        linked_automation = []

    payload = build_case_payload(
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
            "link_type": to_text(item.get("link_type", "")) or "REFERENCES",
        }
        for item in linked_automation
    ]
    return MCPTestCaseDetailResponse(
        team_id=team_id,
        test_case=payload,
    )


async def lookup_test_cases_read(
    db: AsyncSession,
    *,
    q: Optional[str] = None,
    test_case_number: Optional[str] = None,
    ticket: Optional[str] = None,
    team_id: Optional[int] = None,
    team_name: Optional[str] = None,
    include_content: bool = True,
    include_test_data: bool = False,
    skip: int = 0,
    limit: int = 20,
    allowed_team_ids: Optional[set[int]] = None,
) -> MCPTestCaseLookupResponse:
    keyword = (q or "").strip()
    number_filter = (test_case_number or "").strip()
    ticket_filter = (ticket or "").strip()
    team_name_filter = (team_name or "").strip()

    if not keyword and not number_filter and not ticket_filter:
        raise MissingLookupFilterError()

    if allowed_team_ids is not None and len(allowed_team_ids) == 0:
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

    conditions: list[Any] = []
    if allowed_team_ids is not None:
        conditions.append(TestCaseLocalDB.team_id.in_(allowed_team_ids))

    if team_id is not None:
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
                match_type=lookup_match_type(
                    row,
                    keyword=keyword or None,
                    test_case_number=number_filter or None,
                    ticket=ticket_filter or None,
                ),
                test_case=build_case_payload(
                    row,
                    include_content=include_content,
                    include_test_data=include_test_data,
                ),
            )
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


async def list_team_test_case_sections_read(
    db: AsyncSession,
    team_id: int,
    *,
    set_id: Optional[int] = None,
    parent_section_id: Optional[int] = None,
    roots_only: bool = False,
    include_empty: bool = True,
) -> MCPTeamTestCaseSectionsResponse:
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

    count_map = await get_section_case_counts(db, team_id)

    conditions: list[Any] = [TestCaseSetDB.team_id == team_id]
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


async def list_team_test_runs_read(
    db: AsyncSession,
    team_id: int,
    *,
    status_filter: Optional[str] = None,
    run_type: Optional[str] = None,
    include_archived: bool = False,
    include_legacy_summary_aliases: bool = False,
) -> MCPTeamTestRunsResponse:
    status_filters = parse_status_filters(status_filter)
    run_types = parse_run_types(run_type)

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
            set_status = to_text(resolve_status_for_response(run_set))
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
                config_status = to_text(config.status)
                if not include_archived and config_status.lower() == TestRunSetStatus.ARCHIVED.value:
                    continue
                if not status_match(config_status, status_filters):
                    continue
                test_runs.append(config_payload(config))

            if status_filters and not status_match(set_status, status_filters) and not test_runs:
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
        filtered_unassigned = apply_archive_and_status(
            unassigned_rows,
            status_filters,
            include_archived=include_archived,
        )
        unassigned_payloads = [config_payload(config) for config in filtered_unassigned]

    if "adhoc" in run_types:
        adhoc_rows = (
            await db.execute(
                select(AdHocRun)
                .where(AdHocRun.team_id == team_id)
                .options(joinedload(AdHocRun.sheets).joinedload(AdHocRunSheet.items))
                .order_by(AdHocRun.updated_at.desc(), AdHocRun.id.desc())
            )
        ).scalars().unique().all()

        filtered_adhoc = apply_archive_and_status(
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
                    status=to_text(run.status),
                    total_test_cases=total_test_cases,
                    executed_cases=executed_cases,
                    created_at=run.created_at,
                    updated_at=run.updated_at,
                )
            )

    set_run_count = sum(len(run_set.test_runs) for run_set in set_payloads)
    total_runs = set_run_count + len(unassigned_payloads) + len(adhoc_payloads)
    summary: Dict[str, Any] = {
        "set_count": len(set_payloads),
        "set_run_count": set_run_count,
        "unassigned_count": len(unassigned_payloads),
        "adhoc_count": len(adhoc_payloads),
        "total_runs": total_runs,
    }
    if include_legacy_summary_aliases:
        summary["sets"] = len(set_payloads)
        summary["unassigned"] = len(unassigned_payloads)
        summary["adhoc"] = len(adhoc_payloads)

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
        summary=summary,
    )
