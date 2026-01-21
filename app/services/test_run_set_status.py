"""Test Run Set 狀態計算與同步工具。"""

from __future__ import annotations

from typing import List, Sequence, Union

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.models.database_models import (
    TestRunConfig as TestRunConfigDB,
    TestRunSet as TestRunSetDB,
    TestRunSetMembership as TestRunSetMembershipDB,
)
from app.models.test_run_config import TestRunStatus
from app.models.test_run_set import TestRunSetStatus


def _normalize_status_row(row: Union[TestRunStatus, tuple]) -> TestRunStatus | None:
    """將查詢結果轉換為 TestRunStatus。"""
    value: object
    if isinstance(row, tuple):
        value = row[0] if row else None
    else:
        value = row

    if value is None:
        return None
    if isinstance(value, TestRunStatus):
        return value

    try:
        return TestRunStatus(str(value))
    except (ValueError, TypeError):
        return None


async def load_member_statuses(db: AsyncSession, set_id: int) -> List[TestRunStatus]:
    """從資料庫查詢指定 Test Run Set 成員的狀態清單。"""
    result = await db.execute(
        select(TestRunConfigDB.status)
        .join(
            TestRunSetMembershipDB,
            TestRunSetMembershipDB.config_id == TestRunConfigDB.id,
        )
        .filter(TestRunSetMembershipDB.set_id == set_id)
    )
    rows = result.all()
    statuses: List[TestRunStatus] = []
    for row in rows:
        normalized = _normalize_status_row(row)
        if normalized:
            statuses.append(normalized)
    return statuses


def collect_member_statuses(set_db: TestRunSetDB) -> List[TestRunStatus]:
    """從已載入的 membership 關聯收集成員狀態。"""
    statuses: List[TestRunStatus] = []
    for membership in getattr(set_db, "memberships", []) or []:
        config = getattr(membership, "config", None)
        if config and getattr(config, "status", None):
            statuses.append(config.status)
    return statuses


def compute_set_status(
    current_status: TestRunSetStatus,
    member_statuses: Sequence[TestRunStatus],
) -> TestRunSetStatus:
    """依據成員狀態計算 Test Run Set 的狀態。"""
    if current_status == TestRunSetStatus.ARCHIVED:
        return TestRunSetStatus.ARCHIVED

    if not member_statuses:
        return TestRunSetStatus.ACTIVE

    all_completed = all(
        status in (TestRunStatus.COMPLETED, TestRunStatus.ARCHIVED)
        for status in member_statuses
    )
    if all_completed:
        return TestRunSetStatus.COMPLETED

    return TestRunSetStatus.ACTIVE


async def recalculate_set_status(db: AsyncSession, set_db: TestRunSetDB) -> TestRunSetStatus:
    """
    重新計算並同步 Test Run Set 狀態。

    會先 flush 以確保最新變更可供查詢，再更新狀態欄位。
    """
    await db.flush()
    member_statuses = await load_member_statuses(db, set_db.id)
    new_status = compute_set_status(set_db.status, member_statuses)
    if set_db.status != new_status:
        set_db.status = new_status
    return new_status


def resolve_status_for_response(set_db: TestRunSetDB) -> TestRunSetStatus:
    """回傳用於 API 響應的狀態（不觸發額外查詢）。"""
    member_statuses = collect_member_statuses(set_db)
    return compute_set_status(set_db.status, member_statuses)
