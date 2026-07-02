from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.automation_scripts import require_team_read
from app.db_access.main import MainAccessBoundary, get_main_access_boundary
from app.models.automation_coverage import (
    AutomationCoverageCasesPage,
    AutomationCoverageResponse,
)
from app.models.database_models import Team, User
from app.services.automation.coverage_service import AutomationCoverageService


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/teams/{team_id}/automation-coverage", tags=["automation-coverage"])


@router.get("", response_model=AutomationCoverageResponse)
async def get_automation_coverage(
    team_id: int,
    uncovered_limit: int = Query(default=50, ge=1, le=100),
    current_user: User = Depends(require_team_read),
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
) -> AutomationCoverageResponse:
    async def _get(session: AsyncSession) -> AutomationCoverageResponse:
        await _ensure_team_exists(session, team_id)
        service = AutomationCoverageService(session)
        result = await service.compute_coverage(
            team_id=team_id,
            uncovered_limit=uncovered_limit,
        )
        return AutomationCoverageResponse(**result)

    return await main_boundary.run_read(_get)


@router.get("/cases", response_model=AutomationCoverageCasesPage)
async def list_coverage_cases(
    team_id: int,
    status_filter: str = Query(default="all", alias="status", pattern="^(all|covered|uncovered|primary)$"),
    group: str | None = Query(default=None),
    q: str | None = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    current_user: User = Depends(require_team_read),
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
) -> AutomationCoverageCasesPage:
    """Paginated, filterable case list backing the coverage explorer. Keeps the
    browser responsive when a team has hundreds/thousands of manual cases."""

    async def _get(session: AsyncSession) -> AutomationCoverageCasesPage:
        await _ensure_team_exists(session, team_id)
        items, total = await AutomationCoverageService(session).list_cases(
            team_id=team_id, status=status_filter, group=group, q=q, skip=skip, limit=limit,
        )
        return AutomationCoverageCasesPage(
            items=items, total=total, skip=skip, limit=limit, has_next=(skip + len(items)) < total,
        )

    return await main_boundary.run_read(_get)


async def _ensure_team_exists(session: AsyncSession, team_id: int) -> None:
    result = await session.execute(select(Team.id).where(Team.id == team_id))
    if result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "TEAM_NOT_FOUND", "message": f"Team {team_id} not found"},
        )
