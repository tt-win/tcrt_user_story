from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.main import app
from app.database import get_db
from app.models.database_models import Base, Team, TestRunConfig, TestRunSetMembership


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test_case_repo.db"
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False, "timeout": 30},
        pool_pre_ping=True,
    )

    TestingSessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    Base.metadata.create_all(bind=engine)

    import app.database as app_database

    monkeypatch.setattr(app_database, "engine", engine)
    monkeypatch.setattr(app_database, "SessionLocal", TestingSessionLocal)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    yield engine, TestingSessionLocal

    app.dependency_overrides.pop(get_db, None)
    engine.dispose()


def _seed_team_with_runs(session):
    team = Team(
        name="QA Team",
        description="",
        wiki_token="test-wiki",
        test_case_table_id="tbl-test",
    )
    session.add(team)
    session.commit()

    config1 = TestRunConfig(team_id=team.id, name="Regression")
    config2 = TestRunConfig(team_id=team.id, name="Smoke")
    session.add_all([config1, config2])
    session.commit()

    return team.id, config1.id, config2.id


def _get_memberships(session):
    return session.query(TestRunSetMembership).all()


def test_test_run_set_crud_and_membership(temp_db):
    _, SessionLocal = temp_db
    client = TestClient(app)

    with SessionLocal() as session:
        team_id, config1_id, config2_id = _seed_team_with_runs(session)

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
