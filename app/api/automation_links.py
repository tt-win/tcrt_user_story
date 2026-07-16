from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.automation_scripts import require_team_read
from app.db_access.main import MainAccessBoundary, get_main_access_boundary
from app.models.automation_link import (
    AutomationScriptLinkDetailResponse,
    LinkedAutomationSummary,
)
from app.models.database_models import TestCaseLocal, User
from app.services.automation.linkage_service import (
    AutomationLinkageService,
    AutomationLinkNotFoundError,
)

logger = logging.getLogger(__name__)

# Marker sync is the single write path for `automation_script_case_links`
# (see `openspec/changes/remove-manual-automation-link-ui-and-write-api/`).
# The historical write endpoints (POST /links, POST /links/batch,
# PATCH /links/{id}, DELETE /links/{id}) have been removed; this router now
# exposes **read-only** access.
router = APIRouter(prefix="/teams/{team_id}", tags=["automation-links"])


@router.get(
    "/automation-scripts/{script_id}/links",
    response_model=list[AutomationScriptLinkDetailResponse],
)
async def list_automation_script_links(
    team_id: int,
    script_id: int,
    current_user: User = Depends(require_team_read),
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
) -> list[AutomationScriptLinkDetailResponse]:
    """List a script's case links, enriched with case number/title + source.

    Rows are created exclusively by the marker sync — the `created_by` field
    carries the sentinel value `marker-sync` (or a historical human/AI id).
    """
    async def _list(session: AsyncSession) -> list[AutomationScriptLinkDetailResponse]:
        service = AutomationLinkageService(session)
        try:
            rows = await service.list_links_for_script_detailed(
                team_id=team_id, script_id=script_id
            )
        except AutomationLinkNotFoundError as exc:
            raise _not_found(str(exc)) from exc
        return [AutomationScriptLinkDetailResponse(**row) for row in rows]

    return await main_boundary.run_read(_list)


@router.get(
    "/test-cases/{case_identifier}/linked-automation",
    response_model=list[LinkedAutomationSummary],
)
async def list_linked_automation_for_test_case(
    team_id: int,
    case_identifier: str,
    current_user: User = Depends(require_team_read),
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
) -> list[LinkedAutomationSummary]:
    async def _list(session: AsyncSession) -> list[LinkedAutomationSummary]:
        case_id = await _resolve_case_id(session, team_id, case_identifier)
        service = AutomationLinkageService(session)
        summaries = await service.list_linked_automation(
            team_id=team_id, test_case_id=case_id
        )
        return [LinkedAutomationSummary(**item) for item in summaries]

    try:
        return await main_boundary.run_read(_list)
    except AutomationLinkNotFoundError as exc:
        raise _not_found(str(exc)) from exc


async def _resolve_case_id(session: AsyncSession, team_id: int, case_identifier: str) -> int:
    """Accept either local int id (as string) or lark_record_id; return local int id."""
    cleaned = (case_identifier or "").strip()
    if not cleaned:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "TEST_CASE_NOT_FOUND", "message": "Missing test case identifier"},
        )
    if cleaned.isdigit():
        local_id = int(cleaned)
        result = await session.execute(
            select(TestCaseLocal.id).where(
                TestCaseLocal.id == local_id,
                TestCaseLocal.team_id == team_id,
            )
        )
        if result.scalar_one_or_none() is not None:
            return local_id
    result = await session.execute(
        select(TestCaseLocal.id).where(
            TestCaseLocal.lark_record_id == cleaned,
            TestCaseLocal.team_id == team_id,
        )
    )
    resolved = result.scalar_one_or_none()
    if resolved is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "TEST_CASE_NOT_FOUND",
                "message": f"Test case {case_identifier} not found in team {team_id}",
            },
        )
    return int(resolved)


def _not_found(message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"code": "AUTOMATION_LINK_NOT_FOUND", "message": message},
    )
