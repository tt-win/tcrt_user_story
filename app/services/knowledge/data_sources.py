"""Data source fetchers for knowledge graph backfill.

提供從 TCRT main DB（test_cases）與 USM DB（user_story_map_nodes）
串流資料的 async generator。資料流以批次（batch_size）切分，避免
一次把所有 row 載入記憶體；每個 entity yield 為符合 backfill 契約的
dict 結構。

安全契約：
- 不直接開 session；呼叫端必須提供 AccessBoundary（boundary pattern）。
- async generator 結束後 session 會被 boundary 自動釋放。
- 失敗時 raise，呼叫端的 backfill 邏輯會 catch 並寫入 progress。
"""

from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db_access.main import MainAccessBoundary
from app.db_access.usm import UsmAccessBoundary
from app.models.database_models import (
    Team,
    TestCaseLocal,
    TestCaseSection,
    TestCaseSet,
)
from app.models.user_story_map_db import (
    UserStoryMapDB,
    UserStoryMapNodeDB,
)

LOGGER = logging.getLogger(__name__)


# ---- helpers ----


def _decode_json_field(raw: str | None) -> Any:
    """Decode a JSON-encoded text column. Returns [] / None safely."""
    if not raw:
        return []
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []


def _row_to_test_case_dict(
    row: TestCaseLocal,
    team_name: str | None,
    section_name: str | None,
    set_name: str | None,
) -> dict[str, Any]:
    """Convert a TestCaseLocal ORM row to the dict shape expected by backfill."""
    tcg_json: str | None = getattr(row, "tcg_json", None)
    payload: dict[str, Any] = {
        "test_case_id": row.id,
        "test_case_number": row.test_case_number,
        "title": row.title or "",
        "priority": row.priority.value if row.priority is not None else None,
        "precondition": row.precondition or "",
        "steps": row.steps or "",
        "expected_result": row.expected_result or "",
        "team_id": row.team_id,
        "team_name": team_name or "",
        "test_case_set_id": row.test_case_set_id,
        "test_case_set_name": set_name or "",
    }
    if row.test_case_section_id is not None:
        payload["section_id"] = row.test_case_section_id
        if section_name:
            payload["section_name"] = section_name
    jira_tickets = _decode_json_field(tcg_json)
    if jira_tickets:
        payload["jira_tickets"] = jira_tickets
    return payload


def _row_to_usm_node_dict(
    row: UserStoryMapNodeDB,
    map_name: str | None,
) -> dict[str, Any]:
    """Convert a UserStoryMapNodeDB ORM row to the dict shape expected by backfill."""
    jira_tickets_attr = getattr(row, "jira_tickets", None) or []
    return {
        "id": row.id,  # internal DB PK — used for keyset pagination
        "node_id": row.node_id,
        "title": row.title or "",
        "description": row.description or "",
        "node_type": row.node_type,
        "map_id": row.map_id,
        "map_name": map_name or "",
        "as_a": row.as_a or "",
        "i_want": row.i_want or "",
        "so_that": row.so_that or "",
        "jira_tickets": list(jira_tickets_attr),
    }


# ---- stream functions ----


async def fetch_test_cases(
    boundary: MainAccessBoundary,
    *,
    batch_size: int = 100,
    team_id: int | None = None,
    after_id: int | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Stream test cases from main DB with team / set / section joins.

    Uses keyset pagination (WHERE id > after_id) when ``after_id`` is
    provided, which is O(log n) per page; falls back to OFFSET when
    ``after_id`` is None (initial run).

    Args:
        boundary: MainAccessBoundary instance (boundary pattern).
        batch_size: rows per page (default 100).
        team_id: optional filter for a single team.
        after_id: pagination cursor (last id from previous batch).
    """
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")

    cursor = after_id
    total_yielded = 0
    while True:
        async def _op(
            session: AsyncSession,
            _cursor: int | None = cursor,
            _limit: int = batch_size,
            _team_id: int | None = team_id,
        ) -> list[dict[str, Any]]:
            stmt = (
                select(TestCaseLocal, Team.name, TestCaseSet.name, TestCaseSection.name)
                .join(Team, Team.id == TestCaseLocal.team_id)
                .join(TestCaseSet, TestCaseSet.id == TestCaseLocal.test_case_set_id)
                .outerjoin(
                    TestCaseSection, TestCaseSection.id == TestCaseLocal.test_case_section_id
                )
                .order_by(TestCaseLocal.id.asc())
                .limit(_limit)
            )
            if _team_id is not None:
                stmt = stmt.where(TestCaseLocal.team_id == _team_id)
            if _cursor is not None:
                # Keyset pagination: skip already-yielded rows
                stmt = stmt.where(TestCaseLocal.id > _cursor)
            result = await session.execute(stmt)
            rows = result.all()
            return [
                _row_to_test_case_dict(tc, team_name, section_name, set_name)
                for tc, team_name, set_name, section_name in rows
            ]

        batch = await boundary.run_read(_op)
        if not batch:
            break
        for item in batch:
            yield item
            total_yielded += 1
        if len(batch) < batch_size:
            break
        # Advance the keyset cursor to the last yielded primary key
        cursor = batch[-1]["test_case_id"]

    LOGGER.info("fetch_test_cases: yielded %d rows", total_yielded)


async def fetch_usm_nodes(
    boundary: UsmAccessBoundary,
    *,
    batch_size: int = 100,
    after_id: int | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Stream USM nodes from USM DB with parent map name.

    Uses keyset pagination (WHERE id > after_id) when ``after_id`` is
    provided; falls back to OFFSET otherwise.
    """
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")

    cursor = after_id
    total_yielded = 0
    while True:
        async def _op(
            session: AsyncSession,
            _cursor: int | None = cursor,
            _limit: int = batch_size,
        ) -> list[dict[str, Any]]:
            stmt = (
                select(UserStoryMapNodeDB, UserStoryMapDB.name)
                .join(UserStoryMapDB, UserStoryMapDB.id == UserStoryMapNodeDB.map_id)
                .order_by(UserStoryMapNodeDB.id.asc())
                .limit(_limit)
            )
            if _cursor is not None:
                stmt = stmt.where(UserStoryMapNodeDB.id > _cursor)
            result = await session.execute(stmt)
            rows = result.all()
            return [
                _row_to_usm_node_dict(node, map_name)
                for node, map_name in rows
            ]

        batch = await boundary.run_read(_op)
        if not batch:
            break
        for item in batch:
            yield item
            total_yielded += 1
        if len(batch) < batch_size:
            break
        # Advance the keyset cursor to the last yielded internal id
        cursor = batch[-1]["id"]

    LOGGER.info("fetch_usm_nodes: yielded %d rows", total_yielded)


async def fetch_test_case_by_number(
    boundary: MainAccessBoundary,
    test_case_number: str,
) -> dict[str, Any] | None:
    """Fetch a single test case dict by test_case_number for KG sync fallback."""
    if not test_case_number:
        return None

    async def _op(session: AsyncSession) -> dict[str, Any] | None:
        stmt = (
            select(TestCaseLocal, Team.name, TestCaseSet.name, TestCaseSection.name)
            .join(Team, Team.id == TestCaseLocal.team_id)
            .join(TestCaseSet, TestCaseSet.id == TestCaseLocal.test_case_set_id)
            .outerjoin(
                TestCaseSection, TestCaseSection.id == TestCaseLocal.test_case_section_id
            )
            .where(TestCaseLocal.test_case_number == test_case_number)
        )
        result = await session.execute(stmt)
        row = result.first()
        if not row:
            return None
        tc, team_name, set_name, section_name = row
        return _row_to_test_case_dict(tc, team_name, section_name, set_name)

    return await boundary.run_read(_op)


async def fetch_usm_node_by_id(
    boundary: UsmAccessBoundary,
    node_id: str,
) -> dict[str, Any] | None:
    """Fetch a single USM node dict by node_id for KG sync fallback."""
    if not node_id:
        return None

    async def _op(session: AsyncSession) -> dict[str, Any] | None:
        stmt = (
            select(UserStoryMapNodeDB, UserStoryMapDB.name)
            .join(UserStoryMapDB, UserStoryMapDB.id == UserStoryMapNodeDB.map_id)
            .where(UserStoryMapNodeDB.node_id == node_id)
        )
        result = await session.execute(stmt)
        row = result.first()
        if not row:
            return None
        node, map_name = row
        return _row_to_usm_node_dict(node, map_name)

    return await boundary.run_read(_op)

