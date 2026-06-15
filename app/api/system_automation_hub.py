"""Org-level Automation Hub settings router.

Exposes the Automation Hub entry-visibility toggle:

- ``GET /api/system/automation-hub/settings`` — readable by ANY authenticated
  user, because the home page and team-management page must decide team-card
  entry visibility for every role.
- ``PUT /api/system/automation-hub/settings`` — Super Admin only; persists the
  toggle and writes an audit record.

UI-only governance: this toggle hides the two team-card entry points; it does
NOT block the ``/automation-hub`` page or automation APIs (capability retained,
mirroring ``ai-assist-ui-exposure-control``).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import ActionType, AuditSeverity, ResourceType, audit_service
from app.auth.dependencies import get_current_user, require_super_admin
from app.db_access.main import MainAccessBoundary, get_main_access_boundary
from app.models.database_models import User
from app.services.system_settings_service import (
    AUTOMATION_HUB_ENTRY_ENABLED_KEY,
    get_bool,
    set_bool,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/system/automation-hub", tags=["system-automation-hub"])

# Default ON preserves existing behavior before the toggle is ever set.
AUTOMATION_HUB_ENTRY_ENABLED_DEFAULT = True


class AutomationHubSettingsResponse(BaseModel):
    enabled: bool


class AutomationHubSettingsUpdate(BaseModel):
    enabled: bool = Field(..., description="是否顯示 Automation Hub 入口")


@router.get("/settings", response_model=AutomationHubSettingsResponse)
async def get_automation_hub_settings(
    current_user: User = Depends(get_current_user),
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
) -> AutomationHubSettingsResponse:
    del current_user  # 僅用於要求登入

    async def _read(session: AsyncSession) -> bool:
        return await get_bool(
            session,
            AUTOMATION_HUB_ENTRY_ENABLED_KEY,
            AUTOMATION_HUB_ENTRY_ENABLED_DEFAULT,
        )

    enabled = await main_boundary.run_read(_read)
    return AutomationHubSettingsResponse(enabled=enabled)


@router.put("/settings", response_model=AutomationHubSettingsResponse)
async def update_automation_hub_settings(
    payload: AutomationHubSettingsUpdate,
    request: Request,
    current_user: User = Depends(require_super_admin()),
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
) -> AutomationHubSettingsResponse:
    async def _write(session: AsyncSession) -> None:
        await set_bool(
            session,
            AUTOMATION_HUB_ENTRY_ENABLED_KEY,
            payload.enabled,
            updated_by=str(getattr(current_user, "id", "") or "") or None,
        )

    await main_boundary.run_write(_write)

    try:
        role_value = (
            current_user.role.value
            if hasattr(current_user.role, "value")
            else str(current_user.role)
        )
        await audit_service.log_action(
            user_id=getattr(current_user, "id", 0) or 0,
            username=getattr(current_user, "username", "unknown"),
            role=role_value,
            action_type=ActionType.UPDATE,
            resource_type=ResourceType.SYSTEM,
            resource_id=AUTOMATION_HUB_ENTRY_ENABLED_KEY,
            team_id=0,
            details={"enabled": payload.enabled},
            action_brief=f"設定 Automation Hub 入口開關: {'開啟' if payload.enabled else '關閉'}",
            severity=AuditSeverity.INFO,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Automation Hub 入口開關審計紀錄寫入失敗: %s", exc, exc_info=True)

    return AutomationHubSettingsResponse(enabled=payload.enabled)
