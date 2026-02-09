from pathlib import Path
import sys
import asyncio
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.main import app
from app.database import get_db
from app.auth.dependencies import get_current_user
from app.auth.models import UserRole
from app.models.database_models import (
    Base,
    Team,
    TestCaseLocal,
    TestCaseSection,
    TestCaseSet,
)
from app.models.lark_types import Priority


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test_case_repo.db"
    sync_engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False, "timeout": 30},
        pool_pre_ping=True,
    )
    async_engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}",
        connect_args={"timeout": 30},
        pool_pre_ping=True,
    )

    TestingSessionLocal = sessionmaker(bind=sync_engine, autocommit=False, autoflush=False)
    AsyncTestingSessionLocal = async_sessionmaker(
        bind=async_engine,
        expire_on_commit=False,
        autoflush=False,
        class_=AsyncSession,
    )
    Base.metadata.create_all(bind=sync_engine)

    import app.database as app_database

    monkeypatch.setattr(app_database, "engine", async_engine)
    monkeypatch.setattr(app_database, "SessionLocal", AsyncTestingSessionLocal)

    async def override_get_db():
        async with AsyncTestingSessionLocal() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=1,
        username="pytest-admin",
        full_name="Pytest Admin",
        role=UserRole.SUPER_ADMIN,
    )

    yield sync_engine, TestingSessionLocal

    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_current_user, None)
    asyncio.run(async_engine.dispose())
    sync_engine.dispose()


def _seed_multi_set_team(session):
    team = Team(
        name="QA Team",
        description="",
        wiki_token="wiki-team-1",
        test_case_table_id="tbl-team-1",
    )
    other_team = Team(
        name="Other Team",
        description="",
        wiki_token="wiki-team-2",
        test_case_table_id="tbl-team-2",
    )
    session.add_all([team, other_team])
    session.commit()

    set_a = TestCaseSet(
        team_id=team.id,
        name=f"Default-{team.id}",
        description="",
        is_default=True,
    )
    set_b = TestCaseSet(
        team_id=team.id,
        name=f"Regression-{team.id}",
        description="",
        is_default=False,
    )
    other_team_set = TestCaseSet(
        team_id=other_team.id,
        name=f"Default-{other_team.id}",
        description="",
        is_default=True,
    )
    session.add_all([set_a, set_b, other_team_set])
    session.commit()

    unassigned_a = TestCaseSection(
        test_case_set_id=set_a.id,
        name="Unassigned",
        description="",
        level=1,
        sort_order=0,
        parent_section_id=None,
    )
    unassigned_b = TestCaseSection(
        test_case_set_id=set_b.id,
        name="Unassigned",
        description="",
        level=1,
        sort_order=0,
        parent_section_id=None,
    )
    session.add_all([unassigned_a, unassigned_b])
    session.commit()

    case_a = TestCaseLocal(
        team_id=team.id,
        test_case_number="TC-A-001",
        title="Case A",
        priority=Priority.MEDIUM,
        test_case_set_id=set_a.id,
        test_case_section_id=unassigned_a.id,
    )
    case_b = TestCaseLocal(
        team_id=team.id,
        test_case_number="TC-B-001",
        title="Case B",
        priority=Priority.MEDIUM,
        test_case_set_id=set_b.id,
        test_case_section_id=unassigned_b.id,
    )
    session.add_all([case_a, case_b])
    session.commit()

    return {
        "team_id": team.id,
        "set_a_id": set_a.id,
        "set_b_id": set_b.id,
        "other_team_set_id": other_team_set.id,
        "case_a_id": case_a.id,
        "case_b_id": case_b.id,
        "case_a_no": case_a.test_case_number,
        "case_b_no": case_b.test_case_number,
    }


def _create_multi_set_config(client: TestClient, team_id: int, set_ids: list[int], name: str):
    response = client.post(
        f"/api/teams/{team_id}/test-run-configs",
        json={
            "name": name,
            "test_case_set_ids": set_ids,
        },
    )
    assert response.status_code == 201
    return response.json()


def test_create_config_rejects_cross_team_set_ids(temp_db):
    _, SessionLocal = temp_db
    client = TestClient(app)

    with SessionLocal() as session:
        seeded = _seed_multi_set_team(session)

    ok_response = client.post(
        f"/api/teams/{seeded['team_id']}/test-run-configs",
        json={
            "name": "Release Scope",
            "test_case_set_ids": [seeded["set_a_id"], seeded["set_b_id"]],
        },
    )
    assert ok_response.status_code == 201
    assert ok_response.json()["test_case_set_ids"] == [seeded["set_a_id"], seeded["set_b_id"]]

    bad_response = client.post(
        f"/api/teams/{seeded['team_id']}/test-run-configs",
        json={
            "name": "Invalid Scope",
            "test_case_set_ids": [seeded["set_a_id"], seeded["other_team_set_id"]],
        },
    )
    assert bad_response.status_code == 400


def test_scope_reduction_prunes_out_of_scope_items(temp_db):
    _, SessionLocal = temp_db
    client = TestClient(app)

    with SessionLocal() as session:
        seeded = _seed_multi_set_team(session)

    config = _create_multi_set_config(
        client,
        team_id=seeded["team_id"],
        set_ids=[seeded["set_a_id"], seeded["set_b_id"]],
        name="Nightly Regression",
    )
    config_id = config["id"]

    add_resp = client.post(
        f"/api/teams/{seeded['team_id']}/test-run-configs/{config_id}/items",
        json={
            "items": [
                {"test_case_number": seeded["case_a_no"]},
                {"test_case_number": seeded["case_b_no"]},
            ]
        },
    )
    assert add_resp.status_code == 201
    assert add_resp.json()["created_count"] == 2

    update_resp = client.put(
        f"/api/teams/{seeded['team_id']}/test-run-configs/{config_id}",
        json={"test_case_set_ids": [seeded["set_a_id"]]},
    )
    assert update_resp.status_code == 200
    payload = update_resp.json()
    assert payload["test_case_set_ids"] == [seeded["set_a_id"]]
    assert payload["cleanup_summary"]["removed_item_count"] == 1

    items_resp = client.get(
        f"/api/teams/{seeded['team_id']}/test-run-configs/{config_id}/items?limit=100"
    )
    assert items_resp.status_code == 200
    items = items_resp.json()
    assert len(items) == 1
    assert items[0]["test_case_number"] == seeded["case_a_no"]


def test_move_test_case_preview_and_cleanup_summary(temp_db):
    _, SessionLocal = temp_db
    client = TestClient(app)

    with SessionLocal() as session:
        seeded = _seed_multi_set_team(session)

    config = _create_multi_set_config(
        client,
        team_id=seeded["team_id"],
        set_ids=[seeded["set_a_id"]],
        name="Smoke Scope",
    )
    config_id = config["id"]

    add_resp = client.post(
        f"/api/teams/{seeded['team_id']}/test-run-configs/{config_id}/items",
        json={"items": [{"test_case_number": seeded["case_a_no"]}]},
    )
    assert add_resp.status_code == 201
    assert add_resp.json()["created_count"] == 1

    preview_resp = client.post(
        f"/api/teams/{seeded['team_id']}/testcases/impact-preview/move-test-set",
        json={
            "record_ids": [str(seeded["case_a_id"])],
            "target_test_set_id": seeded["set_b_id"],
        },
    )
    assert preview_resp.status_code == 200
    preview = preview_resp.json()
    assert preview["impacted_item_count"] == 1
    assert len(preview["impacted_test_runs"]) == 1
    assert preview["impacted_test_runs"][0]["config_id"] == config_id

    move_resp = client.post(
        f"/api/teams/{seeded['team_id']}/testcases/batch",
        json={
            "operation": "update_test_set",
            "record_ids": [str(seeded["case_a_id"])],
            "update_data": {"test_set_id": seeded["set_b_id"]},
        },
    )
    assert move_resp.status_code == 200
    move_payload = move_resp.json()
    assert move_payload["success"] is True
    assert move_payload["cleanup_summary"]["removed_item_count"] == 1

    items_resp = client.get(
        f"/api/teams/{seeded['team_id']}/test-run-configs/{config_id}/items?limit=100"
    )
    assert items_resp.status_code == 200
    assert items_resp.json() == []
