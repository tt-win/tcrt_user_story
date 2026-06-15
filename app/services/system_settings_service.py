"""Org-level, runtime-mutable key/value settings accessor.

Backed by the ``system_settings`` table. Intentionally minimal — the only
consumer today is the Automation Hub entry-visibility toggle. An absent row
means "use the caller-supplied default", never "off".
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database_models import SystemSetting

# Key for the Automation Hub team-card entry-visibility toggle.
AUTOMATION_HUB_ENTRY_ENABLED_KEY = "automation_hub_entry_enabled"

_TRUE_VALUES = {"true", "1", "yes", "on"}


async def get_setting(session: AsyncSession, key: str) -> Optional[str]:
    result = await session.execute(
        select(SystemSetting.value).where(SystemSetting.key == key)
    )
    return result.scalar_one_or_none()


async def set_setting(
    session: AsyncSession,
    key: str,
    value: str,
    updated_by: Optional[str] = None,
) -> None:
    result = await session.execute(
        select(SystemSetting).where(SystemSetting.key == key)
    )
    row = result.scalar_one_or_none()
    now = datetime.utcnow()
    if row is None:
        session.add(
            SystemSetting(key=key, value=value, updated_at=now, updated_by=updated_by)
        )
    else:
        row.value = value
        row.updated_at = now
        row.updated_by = updated_by


async def get_bool(session: AsyncSession, key: str, default: bool) -> bool:
    raw = await get_setting(session, key)
    if raw is None:
        return default
    return str(raw).strip().lower() in _TRUE_VALUES


async def set_bool(
    session: AsyncSession,
    key: str,
    value: bool,
    updated_by: Optional[str] = None,
) -> None:
    await set_setting(session, key, "true" if value else "false", updated_by)
