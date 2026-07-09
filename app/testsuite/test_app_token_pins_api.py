"""Tests for the app token pins API (/api/app/teams/{team_id}/pins)."""

from __future__ import annotations

from datetime import datetime, timedelta
import json
from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.auth.app_token_dependencies import generate_app_token
from app.database import get_db
from app.main import app
from app.models.database_models import Team, TeamAppToken, TeamAppTokenStatus, User
from app.testsuite.db_test_helpers import (
    create_managed_test_database,
    dispose_managed_test_database,
    install_main_database_overrides,
)


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    database_bundle = create_managed_test_database(tmp_path / "test_app_pins.db")
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

    yield TestingSessionLocal

    app.dependency_overrides.pop(get_db, None)
    dispose_managed_test_database(database_bundle)


def _seed_data(session):
    team = Team(
        name="Pin Team", description="Test", wiki_token="secret-pin", test_case_table_id="tbl-pin"
    )
    session.add(team)
    other_team = Team(
        name="Other Pin Team",
        description="Other",
        wiki_token="secret-pin-2",
        test_case_table_id="tbl-pin-2",
    )
    session.add(other_team)
    session.commit()

    user = User(
        username="pin-creator",
        email="pin-creator@example.com",
        full_name="Pin Creator",
        role="admin",
        is_active=True,
        hashed_password="dummy",
    )
    session.add(user)
    session.commit()

    def _make_token(name: str, owner_team_id: int, scopes: list[str]) -> str:
        raw_token, token_hash, token_prefix = generate_app_token()
        token = TeamAppToken(
            name=name,
            owner_team_id=owner_team_id,
            token_hash=token_hash,
            token_prefix=token_prefix,
            status=TeamAppTokenStatus.ACTIVE,
            scopes_json=json.dumps(scopes),
            expires_at=datetime.utcnow() + timedelta(days=90),
            created_by_user_id=user.id,
        )
        session.add(token)
        session.commit()
        return raw_token

    return {
        "team_id": team.id,
        "other_team_id": other_team.id,
        "full_token": _make_token(
            "pin-full-token",
            team.id,
            ["test_case:read", "test_case:write", "test_run:read", "test_run:write"],
        ),
        "tc_write_token": _make_token(
            "pin-tc-write-token", team.id, ["test_case:read", "test_case:write"]
        ),
        "tr_write_token": _make_token(
            "pin-tr-write-token", team.id, ["test_run:read", "test_run:write"]
        ),
        "read_token": _make_token("pin-read-only-token", team.id, ["test_case:read"]),
        "no_read_token": _make_token("pin-no-read-token", team.id, ["automation:execute"]),
        "other_team_token": _make_token(
            "pin-other-team-token",
            other_team.id,
            ["test_case:read", "test_case:write", "test_run:read", "test_run:write"],
        ),
    }


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


class TestListPins:
    def test_list_empty_returns_all_entity_types(self, temp_db):
        with temp_db() as session:
            seeded = _seed_data(session)
        with TestClient(app) as client:
            resp = client.get(
                f"/api/app/teams/{seeded['team_id']}/pins", headers=_bearer(seeded["read_token"])
            )
            assert resp.status_code == 200
            data = resp.json()
            assert set(data.keys()) == {"test_case_set", "test_run_set", "test_run", "adhoc_run"}
            assert all(v == [] for v in data.values())

    def test_list_after_create(self, temp_db):
        with temp_db() as session:
            seeded = _seed_data(session)
        with TestClient(app) as client:
            client.post(
                f"/api/app/teams/{seeded['team_id']}/pins",
                json={"entity_type": "test_case_set", "entity_id": 42},
                headers=_bearer(seeded["tc_write_token"]),
            )
            resp = client.get(
                f"/api/app/teams/{seeded['team_id']}/pins", headers=_bearer(seeded["read_token"])
            )
            assert resp.json()["test_case_set"] == [42]

    def test_list_requires_read_scope(self, temp_db):
        with temp_db() as session:
            seeded = _seed_data(session)
        with TestClient(app) as client:
            resp = client.get(
                f"/api/app/teams/{seeded['team_id']}/pins", headers=_bearer(seeded["no_read_token"])
            )
            assert resp.status_code == 403
            assert resp.json()["detail"]["code"] == "APP_TOKEN_SCOPE_DENIED"

    def test_list_team_scope_denied(self, temp_db):
        with temp_db() as session:
            seeded = _seed_data(session)
        with TestClient(app) as client:
            resp = client.get(
                f"/api/app/teams/{seeded['other_team_id']}/pins",
                headers=_bearer(seeded["full_token"]),
            )
            assert resp.status_code == 403
            assert resp.json()["detail"]["code"] == "APP_TOKEN_TEAM_SCOPE_DENIED"


class TestCreatePin:
    def test_create_test_case_set_pin(self, temp_db):
        with temp_db() as session:
            seeded = _seed_data(session)
        with TestClient(app) as client:
            resp = client.post(
                f"/api/app/teams/{seeded['team_id']}/pins",
                json={"entity_type": "test_case_set", "entity_id": 7},
                headers=_bearer(seeded["tc_write_token"]),
            )
            assert resp.status_code == 201
            assert resp.json() == {"success": True, "already_pinned": False}

    @pytest.mark.parametrize("entity_type", ["test_run_set", "test_run", "adhoc_run"])
    def test_create_test_run_family_pin(self, temp_db, entity_type):
        with temp_db() as session:
            seeded = _seed_data(session)
        with TestClient(app) as client:
            resp = client.post(
                f"/api/app/teams/{seeded['team_id']}/pins",
                json={"entity_type": entity_type, "entity_id": 1},
                headers=_bearer(seeded["tr_write_token"]),
            )
            assert resp.status_code == 201
            assert resp.json()["already_pinned"] is False

    def test_create_is_idempotent(self, temp_db):
        with temp_db() as session:
            seeded = _seed_data(session)
        with TestClient(app) as client:
            payload = {"entity_type": "test_case_set", "entity_id": 9}
            first = client.post(
                f"/api/app/teams/{seeded['team_id']}/pins",
                json=payload,
                headers=_bearer(seeded["tc_write_token"]),
            )
            second = client.post(
                f"/api/app/teams/{seeded['team_id']}/pins",
                json=payload,
                headers=_bearer(seeded["tc_write_token"]),
            )
            assert first.json()["already_pinned"] is False
            assert second.json()["already_pinned"] is True

            listed = client.get(
                f"/api/app/teams/{seeded['team_id']}/pins", headers=_bearer(seeded["read_token"])
            )
            assert listed.json()["test_case_set"] == [9]

    def test_create_test_case_set_requires_test_case_write(self, temp_db):
        with temp_db() as session:
            seeded = _seed_data(session)
        with TestClient(app) as client:
            resp = client.post(
                f"/api/app/teams/{seeded['team_id']}/pins",
                json={"entity_type": "test_case_set", "entity_id": 1},
                headers=_bearer(seeded["tr_write_token"]),
            )
            assert resp.status_code == 403
            assert resp.json()["detail"]["code"] == "APP_TOKEN_SCOPE_DENIED"

    def test_create_test_run_entity_requires_test_run_write(self, temp_db):
        with temp_db() as session:
            seeded = _seed_data(session)
        with TestClient(app) as client:
            resp = client.post(
                f"/api/app/teams/{seeded['team_id']}/pins",
                json={"entity_type": "test_run", "entity_id": 1},
                headers=_bearer(seeded["tc_write_token"]),
            )
            assert resp.status_code == 403
            assert resp.json()["detail"]["code"] == "APP_TOKEN_SCOPE_DENIED"

    def test_create_invalid_entity_type(self, temp_db):
        with temp_db() as session:
            seeded = _seed_data(session)
        with TestClient(app) as client:
            resp = client.post(
                f"/api/app/teams/{seeded['team_id']}/pins",
                json={"entity_type": "bogus_type", "entity_id": 1},
                headers=_bearer(seeded["full_token"]),
            )
            assert resp.status_code == 400
            assert resp.json()["detail"]["code"] == "APP_TOKEN_VALIDATION_ERROR"

    def test_create_team_scope_denied(self, temp_db):
        with temp_db() as session:
            seeded = _seed_data(session)
        with TestClient(app) as client:
            resp = client.post(
                f"/api/app/teams/{seeded['other_team_id']}/pins",
                json={"entity_type": "test_case_set", "entity_id": 1},
                headers=_bearer(seeded["full_token"]),
            )
            assert resp.status_code == 403
            assert resp.json()["detail"]["code"] == "APP_TOKEN_TEAM_SCOPE_DENIED"


class TestDeletePin:
    def test_delete_existing_pin(self, temp_db):
        with temp_db() as session:
            seeded = _seed_data(session)
        with TestClient(app) as client:
            client.post(
                f"/api/app/teams/{seeded['team_id']}/pins",
                json={"entity_type": "test_case_set", "entity_id": 3},
                headers=_bearer(seeded["tc_write_token"]),
            )
            resp = client.delete(
                f"/api/app/teams/{seeded['team_id']}/pins/test_case_set/3",
                headers=_bearer(seeded["tc_write_token"]),
            )
            assert resp.status_code == 200
            assert resp.json() == {"success": True, "deleted": 1}

            listed = client.get(
                f"/api/app/teams/{seeded['team_id']}/pins", headers=_bearer(seeded["read_token"])
            )
            assert listed.json()["test_case_set"] == []

    def test_delete_nonexistent_pin_is_idempotent(self, temp_db):
        with temp_db() as session:
            seeded = _seed_data(session)
        with TestClient(app) as client:
            resp = client.delete(
                f"/api/app/teams/{seeded['team_id']}/pins/test_case_set/999",
                headers=_bearer(seeded["tc_write_token"]),
            )
            assert resp.status_code == 200
            assert resp.json() == {"success": True, "deleted": 0}

    def test_delete_requires_matching_scope(self, temp_db):
        with temp_db() as session:
            seeded = _seed_data(session)
        with TestClient(app) as client:
            client.post(
                f"/api/app/teams/{seeded['team_id']}/pins",
                json={"entity_type": "test_case_set", "entity_id": 5},
                headers=_bearer(seeded["tc_write_token"]),
            )
            resp = client.delete(
                f"/api/app/teams/{seeded['team_id']}/pins/test_case_set/5",
                headers=_bearer(seeded["tr_write_token"]),
            )
            assert resp.status_code == 403
            assert resp.json()["detail"]["code"] == "APP_TOKEN_SCOPE_DENIED"

    def test_delete_invalid_entity_type(self, temp_db):
        with temp_db() as session:
            seeded = _seed_data(session)
        with TestClient(app) as client:
            resp = client.delete(
                f"/api/app/teams/{seeded['team_id']}/pins/bogus_type/1",
                headers=_bearer(seeded["full_token"]),
            )
            assert resp.status_code == 400
            assert resp.json()["detail"]["code"] == "APP_TOKEN_VALIDATION_ERROR"


class TestCrossTeamIsolation:
    def test_pins_are_isolated_per_team(self, temp_db):
        with temp_db() as session:
            seeded = _seed_data(session)
        with TestClient(app) as client:
            client.post(
                f"/api/app/teams/{seeded['team_id']}/pins",
                json={"entity_type": "test_case_set", "entity_id": 100},
                headers=_bearer(seeded["full_token"]),
            )
            client.post(
                f"/api/app/teams/{seeded['other_team_id']}/pins",
                json={"entity_type": "test_case_set", "entity_id": 200},
                headers=_bearer(seeded["other_team_token"]),
            )

            team_pins = client.get(
                f"/api/app/teams/{seeded['team_id']}/pins", headers=_bearer(seeded["full_token"])
            ).json()
            other_team_pins = client.get(
                f"/api/app/teams/{seeded['other_team_id']}/pins",
                headers=_bearer(seeded["other_team_token"]),
            ).json()

            assert team_pins["test_case_set"] == [100]
            assert other_team_pins["test_case_set"] == [200]
