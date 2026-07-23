"""Unit tests for app.services.knowledge.data_sources.

Uses in-memory SQLite via temp file (more reliable than :memory: for async
multi-session tests) and creates a custom MainAccessBoundary /
UsmAccessBoundary with the temp DB session.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.db_access.main import MainAccessBoundary
from app.db_access.usm import UsmAccessBoundary
from app.models.database_models import Team
from app.models.database_models import TestCaseLocal as TestCaseLocalModel
from app.models.database_models import TestCaseSection as TestCaseSectionModel
from app.models.database_models import TestCaseSet as TestCaseSetModel
from app.models.user_story_map_db import Base as UsmBase
from app.models.user_story_map_db import UserStoryMapDB as UserStoryMapDBModel
from app.models.user_story_map_db import UserStoryMapNodeDB as UserStoryMapNodeDBModel
from app.services.knowledge.data_sources import (
    _decode_json_field,
    _row_to_test_case_dict,
    _row_to_usm_node_dict,
    fetch_test_cases,
    fetch_usm_nodes,
)


def _make_boundary(session_factory):
    """Wrap a sessionmaker in a MainAccessBoundary with a custom session provider."""

    @asynccontextmanager
    async def _provider() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    return MainAccessBoundary(session_provider=_provider)


def _make_usm_boundary(session_factory):
    @asynccontextmanager
    async def _provider() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    return UsmAccessBoundary(session_provider=_provider)


@pytest_asyncio.fixture
async def main_boundary(tmp_path: Path) -> AsyncIterator[MainAccessBoundary]:
    """In-memory-style main DB with team / set / section / test_case rows."""
    db_path = tmp_path / "main.db"
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with engine.begin() as conn:
        # Only create the tables we need to avoid pre-existing duplicate index
        # names in other tables in the same Base.metadata.
        for table in [
            Team.__table__,
            TestCaseSetModel.__table__,
            TestCaseSectionModel.__table__,
            TestCaseLocalModel.__table__,
        ]:
            await conn.run_sync(
                lambda sync_conn, t=table: t.create(sync_conn, checkfirst=True)
            )

    # Seed: 2 teams, 2 sets (one per team), 1 section (per set), 3 test cases (1 in t2)
    async with factory() as session:
        team1 = Team(
            id=1,
            name="Team Alpha",
            wiki_token="w1",
            test_case_table_id="tbl1",
            jira_project_key="ALPHA",
        )
        team2 = Team(
            id=2,
            name="Team Beta",
            wiki_token="w2",
            test_case_table_id="tbl2",
            jira_project_key="BETA",
        )
        session.add_all([team1, team2])
        await session.flush()

        set1 = TestCaseSetModel(id=1, team_id=1, name="Regression")
        set2 = TestCaseSetModel(id=2, team_id=2, name="Smoke")
        session.add_all([set1, set2])
        await session.flush()

        sec1 = TestCaseSectionModel(id=1, test_case_set_id=1, name="Login")
        sec2 = TestCaseSectionModel(id=2, test_case_set_id=2, name="Checkout", parent_section_id=None)
        session.add_all([sec1, sec2])
        await session.flush()

        tc1 = TestCaseLocalModel(
            id=1,
            team_id=1,
            test_case_set_id=1,
            test_case_section_id=1,
            test_case_number="TCG-001.001.001",
            title="Login test",
            precondition="user exists",
            steps="1. open login",
            expected_result="logged in",
            tcg_json=json.dumps(["TCG-100", "TCG-101"]),
        )
        tc2 = TestCaseLocalModel(
            id=2,
            team_id=1,
            test_case_set_id=1,
            test_case_section_id=1,
            test_case_number="TCG-001.001.002",
            title="Logout test",
        )
        tc3 = TestCaseLocalModel(
            id=3,
            team_id=2,
            test_case_set_id=2,
            test_case_section_id=2,
            test_case_number="TCG-002.001.001",
            title="Checkout test",
        )
        session.add_all([tc1, tc2, tc3])
        await session.commit()

    boundary = _make_boundary(factory)
    try:
        yield boundary
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def usm_boundary(tmp_path: Path) -> AsyncIterator[UsmAccessBoundary]:
    db_path = tmp_path / "usm.db"
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(UsmBase.metadata.create_all)

    async with factory() as session:
        m1 = UserStoryMapDBModel(
            id=1,
            team_id=1,
            name="Login Journey",
            nodes=[],
            edges=[],
        )
        m2 = UserStoryMapDBModel(
            id=2,
            team_id=2,
            name="Checkout Journey",
            nodes=[],
            edges=[],
        )
        session.add_all([m1, m2])
        await session.flush()

        n1 = UserStoryMapNodeDBModel(
            id=1,
            map_id=1,
            node_id="usm-1.1",
            title="User logs in",
            description="Login flow",
            node_type="story",
            as_a="user",
            i_want="to log in",
            so_that="I can shop",
            jira_tickets=["TCG-100"],
        )
        n2 = UserStoryMapNodeDBModel(
            id=2,
            map_id=1,
            node_id="usm-1.2",
            title="User browses products",
            description="Browse",
            node_type="story",
        )
        n3 = UserStoryMapNodeDBModel(
            id=3,
            map_id=2,
            node_id="usm-2.1",
            title="User checks out",
            description="Checkout",
            node_type="story",
        )
        session.add_all([n1, n2, n3])
        await session.commit()

    boundary = _make_usm_boundary(factory)
    try:
        yield boundary
    finally:
        await engine.dispose()


# ---- helpers ----


def test_decode_json_field_handles_bad_input() -> None:
    assert _decode_json_field(None) == []
    assert _decode_json_field("") == []
    assert _decode_json_field("not json") == []
    assert _decode_json_field(json.dumps(["a", "b"])) == ["a", "b"]


def test_row_to_test_case_dict_includes_joins() -> None:
    """Sanity check on the dict shape produced from a row."""
    row = TestCaseLocalModel(
        id=42,
        team_id=1,
        test_case_set_id=1,
        test_case_section_id=1,
        test_case_number="TCG-X.001",
        title="T",
        precondition="P",
        steps="S",
        expected_result="E",
        tcg_json=json.dumps(["JIRA-1"]),
    )
    out = _row_to_test_case_dict(row, "Team Alpha", "Login", "Regression")
    assert out["test_case_id"] == 42
    assert out["test_case_number"] == "TCG-X.001"
    assert out["team_id"] == 1
    assert out["team_name"] == "Team Alpha"
    assert out["section_id"] == 1
    assert out["section_name"] == "Login"
    assert out["test_case_set_name"] == "Regression"
    assert out["jira_tickets"] == ["JIRA-1"]


def test_row_to_test_case_dict_handles_no_section() -> None:
    row = TestCaseLocalModel(
        id=1,
        team_id=1,
        test_case_set_id=1,
        test_case_section_id=None,
        test_case_number="TCG-X.002",
        title="T",
    )
    out = _row_to_test_case_dict(row, "Team", None, "Set")
    assert "section_id" not in out
    assert "section_name" not in out


def test_row_to_usm_node_dict_shape() -> None:
    row = UserStoryMapNodeDBModel(
        id=1,
        map_id=1,
        node_id="usm-1",
        title="t",
        description="d",
        node_type="story",
        as_a="user",
        i_want="x",
        so_that="y",
        jira_tickets=["A", "B"],
    )
    out = _row_to_usm_node_dict(row, "Map1")
    assert out["node_id"] == "usm-1"
    assert out["map_name"] == "Map1"
    assert out["jira_tickets"] == ["A", "B"]


# ---- fetch streams ----


@pytest.mark.asyncio
async def test_fetch_test_cases_yields_all(main_boundary: MainAccessBoundary) -> None:
    items = [item async for item in fetch_test_cases(main_boundary, batch_size=2)]
    assert len(items) == 3
    numbers = [i["test_case_number"] for i in items]
    assert numbers == [
        "TCG-001.001.001",
        "TCG-001.001.002",
        "TCG-002.001.001",
    ]
    first = items[0]
    assert first["team_name"] == "Team Alpha"
    assert first["section_name"] == "Login"
    assert first["test_case_set_name"] == "Regression"
    assert first["jira_tickets"] == ["TCG-100", "TCG-101"]


@pytest.mark.asyncio
async def test_fetch_test_cases_team_filter(main_boundary: MainAccessBoundary) -> None:
    items = [item async for item in fetch_test_cases(main_boundary, team_id=2)]
    assert len(items) == 1
    assert items[0]["team_name"] == "Team Beta"
    assert items[0]["section_name"] == "Checkout"


@pytest.mark.asyncio
async def test_fetch_test_cases_batch_size_one(main_boundary: MainAccessBoundary) -> None:
    """batch_size=1 should still yield all rows (no off-by-one)."""
    items = [item async for item in fetch_test_cases(main_boundary, batch_size=1)]
    assert len(items) == 3


@pytest.mark.asyncio
async def test_fetch_test_cases_invalid_batch(main_boundary: MainAccessBoundary) -> None:
    with pytest.raises(ValueError):
        async for _ in fetch_test_cases(main_boundary, batch_size=0):
            pass


@pytest.mark.asyncio
async def test_fetch_usm_nodes_yields_all(usm_boundary: UsmAccessBoundary) -> None:
    items = [item async for item in fetch_usm_nodes(usm_boundary, batch_size=2)]
    assert len(items) == 3
    assert [i["node_id"] for i in items] == ["usm-1.1", "usm-1.2", "usm-2.1"]
    first = items[0]
    assert first["map_name"] == "Login Journey"
    assert first["jira_tickets"] == ["TCG-100"]
    assert first["as_a"] == "user"
    assert first["i_want"] == "to log in"
    assert first["so_that"] == "I can shop"


@pytest.mark.asyncio
async def test_fetch_usm_nodes_batch_one(usm_boundary: UsmAccessBoundary) -> None:
    items = [item async for item in fetch_usm_nodes(usm_boundary, batch_size=1)]
    assert len(items) == 3


@pytest.mark.asyncio
async def test_fetch_usm_nodes_invalid_batch(usm_boundary: UsmAccessBoundary) -> None:
    with pytest.raises(ValueError):
        async for _ in fetch_usm_nodes(usm_boundary, batch_size=0):
            pass


# ---- keyset pagination ----


@pytest.mark.asyncio
async def test_fetch_test_cases_after_id_resumes(main_boundary: MainAccessBoundary) -> None:
    """Passing after_id should skip already-yielded rows (keyset pagination)."""
    # First, get all rows to know the boundary
    all_items = [item async for item in fetch_test_cases(main_boundary, batch_size=10)]
    assert len(all_items) == 3
    middle_id = all_items[1]["test_case_id"]
    resumed = [
        item
        async for item in fetch_test_cases(main_boundary, batch_size=10, after_id=middle_id)
    ]
    # Only rows with id > middle_id should be returned (1 row)
    assert len(resumed) == 1
    assert resumed[0]["test_case_id"] > middle_id


@pytest.mark.asyncio
async def test_fetch_usm_nodes_after_id_resumes(usm_boundary: UsmAccessBoundary) -> None:
    """USM keyset pagination: after_id skips already-yielded rows."""
    all_items = [item async for item in fetch_usm_nodes(usm_boundary, batch_size=10)]
    assert len(all_items) == 3
    middle_id = all_items[1]["id"]
    resumed = [
        item
        async for item in fetch_usm_nodes(usm_boundary, batch_size=10, after_id=middle_id)
    ]
    assert len(resumed) == 1
    assert resumed[0]["id"] > middle_id


@pytest.mark.asyncio
async def test_fetch_test_cases_after_id_beyond_end(main_boundary: MainAccessBoundary) -> None:
    """after_id past the last row yields nothing."""
    items = [
        item
        async for item in fetch_test_cases(main_boundary, batch_size=10, after_id=9999)
    ]
    assert items == []
