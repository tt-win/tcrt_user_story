from __future__ import annotations

import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.automation_scripts import require_team_read
from app.db_access.main import MainAccessBoundary, get_main_access_boundary
from app.models.database_models import AutomationProviderSlot, Team, User
from app.services.automation.provider_credential_service import decrypt_credentials
from app.services.automation.provider_registry import (
    ProviderNotConfiguredError,
    get_active_provider_record,
    instantiate_provider,
)


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/teams/{team_id}/automation-result", tags=["automation-result"])


class ResultDashboardResponse(BaseModel):
    configured: bool
    provider_type: Optional[str] = None
    base_url: Optional[str] = None
    embed_mode: Optional[str] = None
    dashboard_url: Optional[str] = None


@router.get("/dashboard", response_model=ResultDashboardResponse)
async def get_team_automation_dashboard(
    team_id: int,
    current_user: User = Depends(require_team_read),
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
) -> ResultDashboardResponse:
    """Return the configured Result provider's dashboard URL (and embed hints)
    for the current team. Empty payload if no Result provider is configured.

    UI consumers can use this to decide whether to render a "Team Dashboard"
    button and whether to embed it in an iframe vs. open in a new tab.
    """

    async def _load(session: AsyncSession) -> ResultDashboardResponse:
        await _ensure_team_exists(session, team_id)
        try:
            record = await get_active_provider_record(
                team_id, AutomationProviderSlot.RESULT, session
            )
        except ProviderNotConfiguredError:
            return ResultDashboardResponse(configured=False)

        config = _safe_json(record.config_json)
        try:
            instance = instantiate_provider(
                record.provider_type,
                config,
                decrypt_credentials(record.credentials_encrypted),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Failed to instantiate result provider for dashboard (team %s): %s",
                team_id,
                exc,
            )
            instance = None

        dashboard_url: Optional[str] = None
        if instance is not None:
            try:
                dashboard_url = await instance.get_dashboard_url()
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Result provider dashboard URL lookup failed (team %s): %s",
                    team_id,
                    exc,
                )

        return ResultDashboardResponse(
            configured=True,
            provider_type=record.provider_type,
            base_url=config.get("base_url"),
            embed_mode=config.get("embed_mode") or "link",
            dashboard_url=dashboard_url,
        )

    return await main_boundary.run_read(_load)


# --------------------------------------------------------------------- helpers


async def _ensure_team_exists(session: AsyncSession, team_id: int) -> None:
    result = await session.execute(select(Team.id).where(Team.id == team_id))
    if result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "TEAM_NOT_FOUND", "message": f"Team {team_id} not found"},
        )


def _safe_json(value: Optional[str]) -> dict:
    if not value:
        return {}
    try:
        data = json.loads(value)
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}
