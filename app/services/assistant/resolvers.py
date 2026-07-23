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


async def resolve_test_case_team(session: AsyncSession, record_id: int | str) -> Optional[int]:
    """`record_id` 可能是本地整數 id 或 Lark record id 字串——`get_test_case`／`update_test_case`／
    `delete_test_case`／`move_test_case_scope` 的 path 參數現在允許字串（見 tool_registry
    `path_param_schemas`，紅隊發現：Lark 同步的 test case 其 `record_id` 是 `lark_record_id or
    str(item.id)`,並非必為本地整數）。解析順序須與 `app/api/test_cases.py` 的
    `GET/PUT/DELETE .../testcases/{record_id}` 一致：優先本地整數 id，查無才查 lark_record_id。"""
    try:
        local_id = int(record_id)
    except (TypeError, ValueError):
        local_id = None
    if local_id is not None:
        team_id = (
            await session.execute(select(TestCaseLocal.team_id).where(TestCaseLocal.id == local_id))
        ).scalar_one_or_none()
        if team_id is not None:
            return team_id
    return (
        await session.execute(
            select(TestCaseLocal.team_id).where(TestCaseLocal.lark_record_id == str(record_id))
        )
    ).scalar_one_or_none()


async def resolve_test_case_ref_team(session: AsyncSession, source_record_id: str) -> Optional[int]:
    """Bulk clone source：與 `resolve_test_case_team` 同一套本地整數 id／Lark record id 解析語意。"""
    return await resolve_test_case_team(session, source_record_id)


async def resolve_test_case_set_team(session: AsyncSession, set_id: int | str) -> Optional[int]:
    try:
        local_id = int(set_id)
    except (TypeError, ValueError):
        return None
    return (
        await session.execute(select(TestCaseSet.team_id).where(TestCaseSet.id == local_id))
    ).scalar_one_or_none()


async def resolve_test_case_section_team(
    session: AsyncSession, section_id: int | str, expected_set_id: Optional[int | str] = None
) -> Optional[int]:
    try:
        local_section_id = int(section_id)
    except (TypeError, ValueError):
        return None
    row = (
        await session.execute(
            select(TestCaseSection.test_case_set_id).where(TestCaseSection.id == local_section_id)
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    if expected_set_id is not None:
        try:
            if row != int(expected_set_id):
                return None
        except (TypeError, ValueError):
            return None
    return await resolve_test_case_set_team(session, row)


async def resolve_test_run_config_team(session: AsyncSession, config_id: int | str) -> Optional[int]:
    try:
        local_id = int(config_id)
    except (TypeError, ValueError):
        return None
    return (
        await session.execute(select(TestRunConfig.team_id).where(TestRunConfig.id == local_id))
    ).scalar_one_or_none()


async def resolve_test_run_item_team(
    session: AsyncSession, item_id: int | str, expected_config_id: Optional[int | str] = None
) -> Optional[int]:
    try:
        local_item_id = int(item_id)
    except (TypeError, ValueError):
        return None
    row = (
        await session.execute(
            select(TestRunItem.config_id, TestRunItem.team_id).where(TestRunItem.id == local_item_id)
        )
    ).one_or_none()
    if row is None:
        return None
    config_id, team_id = row
    if expected_config_id is not None:
        try:
            if config_id != int(expected_config_id):
                return None
        except (TypeError, ValueError):
            return None
    return team_id


async def resolve_test_run_set_team(session: AsyncSession, set_id: int | str) -> Optional[int]:
    try:
        local_id = int(set_id)
    except (TypeError, ValueError):
        return None
    return (
        await session.execute(select(TestRunSet.team_id).where(TestRunSet.id == local_id))
    ).scalar_one_or_none()


async def resolve_automation_run_team(
    session: AsyncSession, run_id: int | str, expected_set_id: Optional[int | str] = None
) -> Optional[int]:
    try:
        local_run_id = int(run_id)
    except (TypeError, ValueError):
        return None
    row = (
        await session.execute(
            select(AutomationRun.test_run_set_id).where(AutomationRun.id == local_run_id)
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    if expected_set_id is not None:
        try:
            if row != int(expected_set_id):
                return None
        except (TypeError, ValueError):
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


async def resolve_test_case_identity(session: AsyncSession, record_id: int | str) -> Optional[tuple[str, int]]:
    """`record_id` 可能是本地整數 id 或 Lark record id 字串，解析順序須與 `resolve_test_case_team`
    一致（否則 confirmation summary 顯示的目標與 team 驗證認定的目標可能不是同一筆），
    否則 Lark 同步的 test case 會在 confirmation summary 這關被判定 unresolvable（見紅隊發現：
    只修 `resolve_test_case_team` 不夠，這顆姐妹函式是同一個 bug class）。"""
    try:
        local_id = int(record_id)
    except (TypeError, ValueError):
        local_id = None
    row = None
    if local_id is not None:
        row = (
            await session.execute(
                select(TestCaseLocal.test_case_number, TestCaseLocal.local_version).where(
                    TestCaseLocal.id == local_id
                )
            )
        ).one_or_none()
    if row is None:
        row = (
            await session.execute(
                select(TestCaseLocal.test_case_number, TestCaseLocal.local_version).where(
                    TestCaseLocal.lark_record_id == str(record_id)
                )
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


async def resolve_test_case_set_identity(session: AsyncSession, set_id: int | str):
    try:
        local_id = int(set_id)
    except (TypeError, ValueError):
        return None
    row = (
        await session.execute(select(TestCaseSet.name, TestCaseSet.updated_at).where(TestCaseSet.id == local_id))
    ).one_or_none()
    return (row[0], row[1].isoformat()) if row else None


async def resolve_test_case_section_identity(session: AsyncSession, section_id: int | str):
    try:
        local_id = int(section_id)
    except (TypeError, ValueError):
        return None
    row = (
        await session.execute(
            select(TestCaseSection.name, TestCaseSection.updated_at).where(TestCaseSection.id == local_id)
        )
    ).one_or_none()
    return (row[0], row[1].isoformat()) if row else None


async def resolve_test_run_config_identity(session: AsyncSession, config_id: int | str):
    try:
        local_id = int(config_id)
    except (TypeError, ValueError):
        return None
    row = (
        await session.execute(select(TestRunConfig.name, TestRunConfig.updated_at).where(TestRunConfig.id == local_id))
    ).one_or_none()
    return (row[0], row[1].isoformat()) if row else None


async def resolve_test_run_item_identity(session: AsyncSession, item_id: int | str):
    try:
        local_id = int(item_id)
    except (TypeError, ValueError):
        return None
    row = (
        await session.execute(
            select(TestRunItem.test_case_number, TestRunItem.updated_at).where(TestRunItem.id == local_id)
        )
    ).one_or_none()
    return (row[0], row[1].isoformat()) if row else None


async def resolve_test_run_set_identity(session: AsyncSession, set_id: int | str):
    try:
        local_id = int(set_id)
    except (TypeError, ValueError):
        return None
    row = (
        await session.execute(select(TestRunSet.name, TestRunSet.updated_at).where(TestRunSet.id == local_id))
    ).one_or_none()
    return (row[0], row[1].isoformat()) if row else None


async def resolve_automation_run_identity(session: AsyncSession, run_id: int | str):
    try:
        local_id = int(run_id)
    except (TypeError, ValueError):
        return None
    row = (
        await session.execute(select(AutomationRun.id, AutomationRun.status).where(AutomationRun.id == local_id))
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
