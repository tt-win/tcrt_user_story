# ruff: noqa: E402
"""Tests for the JWT per-user pins API (/api/pins), including its merge with
team-scoped app-token pins (AppTokenPin) in the list response."""

from __future__ import annotations

from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.auth.dependencies import get_current_user
from app.auth.models import UserRole
from app.database import get_db
from app.main import app
from app.models.database_models import AppTokenPin, Team
from app.testsuite.db_test_helpers import (
    create_managed_test_database,
    dispose_managed_test_database,
    install_main_database_overrides,
)

FAKE_USER = SimpleNamespace(
    id=1,
    username="pytest-user",
    full_name="Pytest User",
    role=UserRole.ADMIN,
)


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    database_bundle = create_managed_test_database(tmp_path / "test_pins.db")
    TestingSessionLocal = database_bundle["sync_session_factory"]
    AsyncTestingSessionLocal = database_bundle["async_session_factory"]

    import app.main as app_main
    import app.models.user_story_map_db as usm_db_module

    install_main_database_overrides(
        monkeypatch=monkeypatch,
        app=app,
        get_db_dependency=get_db,
        async_engine=database_bundle["async_engine"],
        async_session_factory=AsyncTestingSessionLocal,
    )

    async def _noop_async(*args, **kwargs):
        return None

    monkeypatch.setattr(app_main, "init_audit_database", _noop_async)
    monkeypatch.setattr(app_main, "cleanup_audit_database", _noop_async)
    monkeypatch.setattr(app_main.audit_service, "force_flush", _noop_async)
    monkeypatch.setattr(usm_db_module, "init_usm_db", _noop_async)

    app.dependency_overrides[get_current_user] = lambda: FAKE_USER

    yield TestingSessionLocal

    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_db, None)
    dispose_managed_test_database(database_bundle)


def _seed_teams(session):
    team = Team(name="Pins Team", description="Test", wiki_token="secret-pins-a", test_case_table_id="tbl-pins-a")
    other_team = Team(
        name="Other Pins Team", description="Other", wiki_token="secret-pins-b", test_case_table_id="tbl-pins-b"
    )
    session.add(team)
    session.add(other_team)
    session.commit()
    return {"team_id": team.id, "other_team_id": other_team.id}


class TestPersonalPinCrud:
    def test_list_empty(self, temp_db):
        with temp_db() as session:
            seeded = _seed_teams(session)
        with TestClient(app) as client:
            resp = client.get(f"/api/pins?team_id={seeded['team_id']}")
            assert resp.status_code == 200
            data = resp.json()
            assert set(data["test_case_set"]) == set()
            assert data["token_pinned"] == {
                "test_case_set": [],
                "test_run_set": [],
                "test_run": [],
                "adhoc_run": [],
            }

    def test_create_is_idempotent_and_listed(self, temp_db):
        with temp_db() as session:
            seeded = _seed_teams(session)
        with TestClient(app) as client:
            payload = {"team_id": seeded["team_id"], "entity_type": "test_case_set", "entity_id": 10}
            first = client.post("/api/pins", json=payload)
            second = client.post("/api/pins", json=payload)
            assert first.json() == {"success": True, "already_pinned": False}
            assert second.json() == {"success": True, "already_pinned": True}

            listed = client.get(f"/api/pins?team_id={seeded['team_id']}")
            assert listed.json()["test_case_set"] == [10]
            assert listed.json()["token_pinned"]["test_case_set"] == []

    def test_delete_is_idempotent(self, temp_db):
        with temp_db() as session:
            seeded = _seed_teams(session)
        with TestClient(app) as client:
            client.post(
                "/api/pins",
                json={"team_id": seeded["team_id"], "entity_type": "test_case_set", "entity_id": 11},
            )
            first = client.delete(f"/api/pins/test_case_set/11?team_id={seeded['team_id']}")
            second = client.delete(f"/api/pins/test_case_set/11?team_id={seeded['team_id']}")
            assert first.json() == {"success": True, "deleted": 1}
            assert second.json() == {"success": True, "deleted": 0}


class TestAppTokenPinMerge:
    def test_app_token_pin_appears_in_list_and_token_pinned(self, temp_db):
        with temp_db() as session:
            seeded = _seed_teams(session)
            session.add(
                AppTokenPin(
                    owner_team_id=seeded["team_id"],
                    entity_type="test_case_set",
                    entity_id=302,
                    created_by_credential_id=2,
                )
            )
            session.commit()
        with TestClient(app) as client:
            resp = client.get(f"/api/pins?team_id={seeded['team_id']}")
            data = resp.json()
            assert data["test_case_set"] == [302]
            assert data["token_pinned"]["test_case_set"] == [302]

    def test_personal_and_token_pin_on_same_id_merge_without_duplication(self, temp_db):
        with temp_db() as session:
            seeded = _seed_teams(session)
            session.add(
                AppTokenPin(
                    owner_team_id=seeded["team_id"],
                    entity_type="test_run_set",
                    entity_id=55,
                    created_by_credential_id=2,
                )
            )
            session.commit()
        with TestClient(app) as client:
            client.post(
                "/api/pins",
                json={"team_id": seeded["team_id"], "entity_type": "test_run_set", "entity_id": 55},
            )
            resp = client.get(f"/api/pins?team_id={seeded['team_id']}")
            data = resp.json()
            assert data["test_run_set"] == [55]
            assert data["token_pinned"]["test_run_set"] == [55]


class TestMutationIndependence:
    def test_deleting_personal_pin_does_not_touch_app_token_pins(self, temp_db):
        with temp_db() as session:
            seeded = _seed_teams(session)
            session.add(
                AppTokenPin(
                    owner_team_id=seeded["team_id"],
                    entity_type="test_case_set",
                    entity_id=303,
                    created_by_credential_id=2,
                )
            )
            session.commit()
        with TestClient(app) as client:
            client.post(
                "/api/pins",
                json={"team_id": seeded["team_id"], "entity_type": "test_case_set", "entity_id": 999},
            )
            client.delete(f"/api/pins/test_case_set/999?team_id={seeded['team_id']}")

            resp = client.get(f"/api/pins?team_id={seeded['team_id']}")
            data = resp.json()
            assert data["test_case_set"] == [303]
            assert data["token_pinned"]["test_case_set"] == [303]

    def test_creating_personal_pin_does_not_create_app_token_pin_row(self, temp_db):
        with temp_db() as session:
            seeded = _seed_teams(session)
        with TestClient(app) as client:
            client.post(
                "/api/pins",
                json={"team_id": seeded["team_id"], "entity_type": "test_case_set", "entity_id": 20},
            )
        with temp_db() as session:
            count = session.query(AppTokenPin).count()
            assert count == 0


class TestCrossTeamIsolation:
    def test_token_pinned_does_not_leak_other_team(self, temp_db):
        with temp_db() as session:
            seeded = _seed_teams(session)
            session.add(
                AppTokenPin(
                    owner_team_id=seeded["other_team_id"],
                    entity_type="test_case_set",
                    entity_id=404,
                    created_by_credential_id=3,
                )
            )
            session.commit()
        with TestClient(app) as client:
            resp = client.get(f"/api/pins?team_id={seeded['team_id']}")
            data = resp.json()
            assert data["test_case_set"] == []
            assert data["token_pinned"]["test_case_set"] == []
