"""Aggregation/count helpers for the shared external read surface.

Moved verbatim from ``app/api/mcp.py`` (Phase 2).
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database_models import TestCaseLocal as TestCaseLocalDB


async def get_team_case_counts(db: AsyncSession) -> dict[int, int]:
    """回傳 {team_id: 該 team 的 test case 總數}；`Team.test_case_count` 欄位無人維護，勿使用。"""
    rows = await db.execute(
        select(TestCaseLocalDB.team_id, func.count(TestCaseLocalDB.id))
        .group_by(TestCaseLocalDB.team_id)
    )
    return {team_id: int(count or 0) for team_id, count in rows.all()}


async def get_section_case_counts(
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
