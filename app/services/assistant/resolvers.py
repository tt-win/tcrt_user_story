"""`resource_team_check` resolver：由參數解析 sub-resource 實際所屬 team（design D2）。

tool-matrix.md「Team resolver」節列出的唯一實作；executor 在 loopback 前呼叫，
解析結果與對話綁定 team 不符即拒絕（不發出請求）。所有 resolver 皆唯讀查詢。
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database_models import (
    AutomationRun,
    TestCaseLocal,
    TestCaseSection,
    TestCaseSet,
    TestRunConfig,
    TestRunItem,
    TestRunSet,
    UserPin,
)


async def resolve_test_case_team(session: AsyncSession, record_id: int) -> Optional[int]:
    return (
        await session.execute(select(TestCaseLocal.team_id).where(TestCaseLocal.id == record_id))
    ).scalar_one_or_none()


async def resolve_test_case_ref_team(session: AsyncSession, source_record_id: str) -> Optional[int]:
    """Bulk clone source 可使用本地整數 id 或 Lark record id，需與 API 解析語意一致。"""
    try:
        local_id = int(source_record_id)
    except (TypeError, ValueError):
        local_id = None
    if local_id is not None:
        team_id = await resolve_test_case_team(session, local_id)
        if team_id is not None:
            return team_id
    return (
        await session.execute(
            select(TestCaseLocal.team_id).where(TestCaseLocal.lark_record_id == str(source_record_id))
        )
    ).scalar_one_or_none()


async def resolve_test_case_set_team(session: AsyncSession, set_id: int) -> Optional[int]:
    return (
        await session.execute(select(TestCaseSet.team_id).where(TestCaseSet.id == set_id))
    ).scalar_one_or_none()


async def resolve_test_case_section_team(
    session: AsyncSession, section_id: int, expected_set_id: Optional[int] = None
) -> Optional[int]:
    row = (
        await session.execute(
            select(TestCaseSection.test_case_set_id).where(TestCaseSection.id == section_id)
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    if expected_set_id is not None and row != expected_set_id:
        return None  # path set_id 與 section 實際所屬 set 不符
    return await resolve_test_case_set_team(session, row)


async def resolve_test_run_config_team(session: AsyncSession, config_id: int) -> Optional[int]:
    return (
        await session.execute(select(TestRunConfig.team_id).where(TestRunConfig.id == config_id))
    ).scalar_one_or_none()


async def resolve_test_run_item_team(
    session: AsyncSession, item_id: int, expected_config_id: Optional[int] = None
) -> Optional[int]:
    row = (
        await session.execute(
            select(TestRunItem.config_id, TestRunItem.team_id).where(TestRunItem.id == item_id)
        )
    ).one_or_none()
    if row is None:
        return None
    config_id, team_id = row
    if expected_config_id is not None and config_id != expected_config_id:
        return None
    return team_id


async def resolve_test_run_set_team(session: AsyncSession, set_id: int) -> Optional[int]:
    return (
        await session.execute(select(TestRunSet.team_id).where(TestRunSet.id == set_id))
    ).scalar_one_or_none()


async def resolve_automation_run_team(
    session: AsyncSession, run_id: int, expected_set_id: Optional[int] = None
) -> Optional[int]:
    row = (
        await session.execute(
            select(AutomationRun.test_run_set_id).where(AutomationRun.id == run_id)
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    if expected_set_id is not None and row != expected_set_id:
        return None
    return await resolve_test_run_set_team(session, row)


_PIN_ENTITY_RESOLVERS = {
    "test_case_set": resolve_test_case_set_team,
    "test_run_set": resolve_test_run_set_team,
}


async def resolve_pin_entity_team(session: AsyncSession, entity_type: str, entity_id: int) -> Optional[int]:
    """pin 僅接受 registry 列舉的 entity_type；未知 type fail-closed（回 None）。

    `test_run`／`adhoc_run` 兩種既有 pin 型別 v1 助手工具目錄未提供 pin/unpin
    （矩陣僅涵蓋 test_case_set/test_run_set 範圍內建立的資源），故不在此列舉。
    """
    resolver = _PIN_ENTITY_RESOLVERS.get(entity_type)
    if resolver is None:
        return None
    return await resolver(session, entity_id)


async def resolve_user_pin_team(session: AsyncSession, user_id: int, entity_type: str, entity_id: int) -> Optional[int]:
    """unpin 用：確認該 pin 屬於這位使用者，回傳其 team_id（供 team 比對）。"""
    return (
        await session.execute(
            select(UserPin.team_id).where(
                UserPin.user_id == user_id,
                UserPin.entity_type == entity_type,
                UserPin.entity_id == entity_id,
            )
        )
    ).scalar_one_or_none()


# --------------------------------------------------------------------------- #
# Confirmation summary 用：stable business key + row version（spec assistant-
# action-confirmation「可信確認摘要」）。與上方 team resolver 共用查詢，只是
# 多投影 identity/version 欄位；僅供 tool_executor 產生 confirmation summary
# 與 fingerprint 使用，不做為 team 驗證的替代。
# --------------------------------------------------------------------------- #


async def resolve_test_case_identity(session: AsyncSession, record_id: int) -> Optional[tuple[str, int]]:
    row = (
        await session.execute(
            select(TestCaseLocal.test_case_number, TestCaseLocal.local_version).where(TestCaseLocal.id == record_id)
        )
    ).one_or_none()
    return (row[0], row[1]) if row else None


async def resolve_test_case_ref_identity(
    session: AsyncSession, source_record_id: str
) -> Optional[tuple[int, str, int]]:
    """回傳 bulk clone source 的 canonical local id、case number 與版本。"""
    try:
        local_id = int(source_record_id)
    except (TypeError, ValueError):
        local_id = None
    row = None
    if local_id is not None:
        row = (
            await session.execute(
                select(TestCaseLocal.id, TestCaseLocal.test_case_number, TestCaseLocal.local_version).where(
                    TestCaseLocal.id == local_id
                )
            )
        ).one_or_none()
    if row is None:
        row = (
            await session.execute(
                select(TestCaseLocal.id, TestCaseLocal.test_case_number, TestCaseLocal.local_version).where(
                    TestCaseLocal.lark_record_id == str(source_record_id)
                )
            )
        ).one_or_none()
    return (row[0], row[1], row[2]) if row else None


async def resolve_test_case_set_identity(session: AsyncSession, set_id: int):
    row = (
        await session.execute(select(TestCaseSet.name, TestCaseSet.updated_at).where(TestCaseSet.id == set_id))
    ).one_or_none()
    return (row[0], row[1].isoformat()) if row else None


async def resolve_test_case_section_identity(session: AsyncSession, section_id: int):
    row = (
        await session.execute(
            select(TestCaseSection.name, TestCaseSection.updated_at).where(TestCaseSection.id == section_id)
        )
    ).one_or_none()
    return (row[0], row[1].isoformat()) if row else None


async def resolve_test_run_config_identity(session: AsyncSession, config_id: int):
    row = (
        await session.execute(select(TestRunConfig.name, TestRunConfig.updated_at).where(TestRunConfig.id == config_id))
    ).one_or_none()
    return (row[0], row[1].isoformat()) if row else None


async def resolve_test_run_item_identity(session: AsyncSession, item_id: int):
    row = (
        await session.execute(
            select(TestRunItem.test_case_number, TestRunItem.updated_at).where(TestRunItem.id == item_id)
        )
    ).one_or_none()
    return (row[0], row[1].isoformat()) if row else None


async def resolve_test_run_set_identity(session: AsyncSession, set_id: int):
    row = (
        await session.execute(select(TestRunSet.name, TestRunSet.updated_at).where(TestRunSet.id == set_id))
    ).one_or_none()
    return (row[0], row[1].isoformat()) if row else None


async def resolve_automation_run_identity(session: AsyncSession, run_id: int):
    row = (
        await session.execute(select(AutomationRun.id, AutomationRun.status).where(AutomationRun.id == run_id))
    ).one_or_none()
    return (str(row[0]), row[1]) if row else None


# 供 tool_executor 依 resource_team_resolver 對應到「單一物件 identity」查詢的字典。
IDENTITY_RESOLVERS = {
    "test_case": resolve_test_case_identity,
    "test_case_set": resolve_test_case_set_identity,
    "test_case_section": resolve_test_case_section_identity,
    "test_run_config": resolve_test_run_config_identity,
    "test_run_item": resolve_test_run_item_identity,
    "test_run_set": resolve_test_run_set_identity,
    "automation_run": resolve_automation_run_identity,
}
