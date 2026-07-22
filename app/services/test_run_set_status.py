"""Test Run Set 狀態計算與同步工具。"""

from __future__ import annotations

from datetime import datetime
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

# Single-edge lifecycle graph (matches UI status.js). Forward multi-hop along the
# main path DRAFT → ACTIVE → COMPLETED is expanded automatically so assistants may
# request "completed" in one call without first activating.
_ALLOWED_TRANSITIONS: dict[TestRunStatus, list[TestRunStatus]] = {
    TestRunStatus.DRAFT: [TestRunStatus.ACTIVE, TestRunStatus.ARCHIVED],
    TestRunStatus.ACTIVE: [TestRunStatus.COMPLETED, TestRunStatus.ARCHIVED],
    TestRunStatus.COMPLETED: [TestRunStatus.ARCHIVED],
    TestRunStatus.ARCHIVED: [TestRunStatus.ACTIVE, TestRunStatus.DRAFT],
}

# Ordered main path used only for multi-hop expansion (not archive/reopen).
_MAIN_LIFECYCLE: tuple[TestRunStatus, ...] = (
    TestRunStatus.DRAFT,
    TestRunStatus.ACTIVE,
    TestRunStatus.COMPLETED,
)


def _coerce_status(value: object) -> TestRunStatus:
    """Normalize ORM/API values to TestRunStatus (handles str enum edge cases)."""
    if isinstance(value, TestRunStatus):
        return value
    if value is None:
        raise ValueError("status is required")
    try:
        return TestRunStatus(str(value).strip().lower())
    except (ValueError, TypeError) as exc:
        raise ValueError(f"invalid status: {value!r}") from exc


def _main_path_hops(old_status: TestRunStatus, new_status: TestRunStatus) -> list[TestRunStatus] | None:
    """If both statuses sit on the main lifecycle and new is strictly ahead, return intermediate targets.

    Example: DRAFT → COMPLETED → [ACTIVE, COMPLETED]. Single-edge hops return None
    (caller applies the direct transition). Non-main or reverse hops return None.
    """
    try:
        old_i = _MAIN_LIFECYCLE.index(old_status)
        new_i = _MAIN_LIFECYCLE.index(new_status)
    except ValueError:
        return None
    if new_i <= old_i + 1:
        return None  # same, adjacent, or reverse — not a multi-hop expand
    return list(_MAIN_LIFECYCLE[old_i + 1 : new_i + 1])


def apply_config_status_transition_sync(
    config_db: TestRunConfigDB, new_status: TestRunStatus
) -> None:
    """套用 Test Run Config 的狀態轉換（合法性驗證 + 日期副作用）。

    供 JWT 與 app-token 的 ``/status`` 端點共用，確保狀態機不在兩條 auth 路徑漂移。
    非法轉換時 raise ``ValueError``；不負責所屬 set 的狀態重算（由呼叫端處理）。

    Multi-hop convenience along the main lifecycle (``DRAFT → ACTIVE → COMPLETED``):
    ``DRAFT → COMPLETED`` is applied as ``DRAFT → ACTIVE → COMPLETED`` so assistants /
    bulk workflows need not issue two status calls for the common "finish" path.
    Archive and reopen edges stay single-hop only (no skip via multi-hop).
    """
    old_status = _coerce_status(config_db.status)
    target = _coerce_status(new_status)
    if old_status == target:
        return

    hops = _main_path_hops(old_status, target)
    if hops is not None:
        for hop in hops:
            apply_config_status_transition_sync(config_db, hop)
        return

    if target not in _ALLOWED_TRANSITIONS.get(old_status, []):
        raise ValueError(f"不允許從 {old_status.value} 轉換到 {target.value}")

    config_db.status = target

    if old_status == TestRunStatus.ARCHIVED and target == TestRunStatus.ACTIVE:
        config_db.start_date = datetime.utcnow()
        config_db.end_date = None
    if target == TestRunStatus.COMPLETED and not config_db.end_date:
        config_db.end_date = datetime.utcnow()
    if target == TestRunStatus.ACTIVE:
        config_db.end_date = None
        if not config_db.start_date:
            config_db.start_date = datetime.utcnow()

    config_db.updated_at = datetime.utcnow()


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


def load_member_statuses_sync(db: Session, set_id: int) -> List[TestRunStatus]:
    """從同步 Session 查詢指定 Test Run Set 成員的狀態清單。"""
    result = db.execute(
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


def recalculate_set_status_sync(db: Session, set_db: TestRunSetDB) -> TestRunSetStatus:
    """
    重新計算並同步 Test Run Set 狀態（同步版本）。

    用於受管 boundary 的單一交易內，避免 route 在寫入後額外補 commit。
    """
    db.flush()
    member_statuses = load_member_statuses_sync(db, set_db.id)
    new_status = compute_set_status(set_db.status, member_statuses)
    if set_db.status != new_status:
        set_db.status = new_status
    return new_status


def resolve_status_for_response(set_db: TestRunSetDB) -> TestRunSetStatus:
    """回傳用於 API 響應的狀態（不觸發額外查詢）。"""
    member_statuses = collect_member_statuses(set_db)
    return compute_set_status(set_db.status, member_statuses)
