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
from app.models.database_models import Base, Team, TestCaseSet, TestRunConfig, TestRunSetMembership


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


def _seed_team_with_runs(session):
    team = Team(
        name="QA Team",
        description="",
        wiki_token="test-wiki",
        test_case_table_id="tbl-test",
    )
    session.add(team)
    session.commit()

    default_case_set = TestCaseSet(
        team_id=team.id,
        name=f"Default-{team.id}",
        description="",
        is_default=True,
    )
    session.add(default_case_set)
    session.commit()

    config1 = TestRunConfig(team_id=team.id, name="Regression")
    config2 = TestRunConfig(team_id=team.id, name="Smoke")
    config1.test_case_set_ids_json = f"[{default_case_set.id}]"
    config2.test_case_set_ids_json = f"[{default_case_set.id}]"
    session.add_all([config1, config2])
    session.commit()

    return team.id, config1.id, config2.id, default_case_set.id


def _get_memberships(session):
    return session.query(TestRunSetMembership).all()


def test_test_run_set_crud_and_membership(temp_db):
    _, SessionLocal = temp_db
    client = TestClient(app)

    with SessionLocal() as session:
        team_id, config1_id, config2_id, _ = _seed_team_with_runs(session)

    # 建立 Test Run Set 並一次加入一個 Test Run
    response = client.post(
        f"/api/teams/{team_id}/test-run-sets",
        json={
            "name": "Release Cycle",
            "description": "Release regression",
            "initial_config_ids": [config1_id],
            "related_tp_tickets": ["TP-1001"],
        },
    )
    assert response.status_code == 201
    set_payload = response.json()
    set_id = set_payload["id"]
    assert set_payload.get("related_tp_tickets") == ["TP-1001"]
    assert any(run["id"] == config1_id for run in set_payload["test_runs"])

    with SessionLocal() as session:
        memberships = _get_memberships(session)
        assert len(memberships) == 1
        assert memberships[0].set_id == set_id

    # 加入既有 Test Run
    response = client.post(
        f"/api/teams/{team_id}/test-run-sets/{set_id}/members",
        json={"config_ids": [config2_id]},
    )
    assert response.status_code == 200
    detail_payload = response.json()
    assert len(detail_payload["test_runs"]) == 2

    # 建立第二個 Set 以測試搬移
    response = client.post(
        f"/api/teams/{team_id}/test-run-sets",
        json={"name": "Hotfix", "related_tp_tickets": ["TP-2002", "TP-3003"]},
    )
    assert response.status_code == 201
    second_set = response.json()
    second_set_id = second_set["id"]
    assert second_set.get("related_tp_tickets") == ["TP-2002", "TP-3003"]

    # 更新第一個 Set 的 TP 票號
    response = client.put(
        f"/api/teams/{team_id}/test-run-sets/{set_id}",
        json={"related_tp_tickets": ["TP-9000", "TP-9001"]},
    )
    assert response.status_code == 200
    updated_set = response.json()
    assert updated_set.get("related_tp_tickets") == ["TP-9000", "TP-9001"]

    # 搬移 config2 到第二個 Set
    response = client.post(
        f"/api/teams/{team_id}/test-run-sets/members/{config2_id}/move",
        json={"target_set_id": second_set_id},
    )
    assert response.status_code == 200
    moved_payload = response.json()
    assert moved_payload["set_id"] == second_set_id

    with SessionLocal() as session:
        memberships = _get_memberships(session)
        assert len(memberships) == 2
        mapping = {m.config_id: m.set_id for m in memberships}
        assert mapping[config2_id] == second_set_id

    # 移出 config2 成為未歸組
    response = client.post(
        f"/api/teams/{team_id}/test-run-sets/members/{config2_id}/move",
        json={"target_set_id": None},
    )
    assert response.status_code == 200
    unassigned_payload = response.json()
    assert unassigned_payload["set_id"] is None

    with SessionLocal() as session:
        memberships = _get_memberships(session)
        ids = {m.config_id for m in memberships}
        assert config2_id not in ids

    # Overview 應顯示一個 Set 與一個未歸組 Test Run
    response = client.get(f"/api/teams/{team_id}/test-run-sets/overview")
    assert response.status_code == 200
    overview = response.json()
    assert len(overview["sets"]) == 2  # Second set still exists but empty
    related_sets = {s["id"]: s.get("related_tp_tickets") for s in overview["sets"]}
    assert related_sets.get(set_id) == ["TP-9000", "TP-9001"]
    assert related_sets.get(second_set_id) == ["TP-2002", "TP-3003"]
    assert any(run["id"] == config2_id for run in overview["unassigned"])

    # 刪除第一個 Set 時應連其 Test Run 一併刪除
    response = client.delete(f"/api/teams/{team_id}/test-run-sets/{set_id}")
    assert response.status_code == 204

    with SessionLocal() as session:
        remaining_config1 = session.query(TestRunConfig).filter_by(id=config1_id).first()
        assert remaining_config1 is None
        remaining_config2 = session.query(TestRunConfig).filter_by(id=config2_id).first()
        assert remaining_config2 is not None


def test_test_run_set_status_auto_updates(temp_db):
    _, SessionLocal = temp_db
    client = TestClient(app)

    with SessionLocal() as session:
        team_id, config1_id, config2_id, default_case_set_id = _seed_team_with_runs(session)

    response = client.post(
        f"/api/teams/{team_id}/test-run-sets",
        json={
            "name": "Cycle",
            "initial_config_ids": [config1_id, config2_id],
        },
    )
    assert response.status_code == 201
    set_payload = response.json()
    set_id = set_payload["id"]
    assert set_payload["status"] == "active"

    for cfg_id in (config1_id, config2_id):
        resp = client.put(
            f"/api/teams/{team_id}/test-run-configs/{cfg_id}/status",
            json={"status": "active"},
        )
        assert resp.status_code == 200
        resp = client.put(
            f"/api/teams/{team_id}/test-run-configs/{cfg_id}/status",
            json={"status": "completed"},
        )
        assert resp.status_code == 200

    detail = client.get(f"/api/teams/{team_id}/test-run-sets/{set_id}")
    assert detail.status_code == 200
    detail_payload = detail.json()
    assert detail_payload["status"] == "completed"

    response = client.post(
        f"/api/teams/{team_id}/test-run-configs",
        json={
            "name": "Extra Cycle",
            "set_id": set_id,
            "test_case_set_ids": [default_case_set_id],
        },
    )
    assert response.status_code == 201
    new_config = response.json()
    assert new_config["set_id"] == set_id

    refreshed = client.get(f"/api/teams/{team_id}/test-run-sets/{set_id}")
    assert refreshed.status_code == 200
    refreshed_payload = refreshed.json()
    assert refreshed_payload["status"] == "active"
