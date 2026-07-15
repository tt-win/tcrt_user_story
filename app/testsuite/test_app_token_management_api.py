"""Tests for team app token management API (JWT-authenticated admin endpoints)."""

from __future__ import annotations

import hashlib
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.auth.dependencies import get_current_user
from app.auth.models import PermissionType, UserRole
from app.database import get_db
from app.main import app
from app.models.database_models import (
    Team,
    TeamAppToken,
    User,
    UserTeamPermission,
)
from app.testsuite.db_test_helpers import (
    create_managed_test_database,
    dispose_managed_test_database,
    install_main_database_overrides,
)


def _hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    database_bundle = create_managed_test_database(tmp_path / "test_app_token_mgmt.db")
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

    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_db, None)
    import asyncio
    from app.auth.permission_service import permission_service
    asyncio.run(permission_service.cache.clear_all())
    dispose_managed_test_database(database_bundle)


def _seed_data(session, role=UserRole.ADMIN, team_permission=PermissionType.ADMIN):
    team = Team(
        name="Management Team",
        description="Test",
        wiki_token="secret-wiki",
        test_case_table_id="tbl-mgmt",
    )
    session.add(team)
    session.commit()

    user = User(
        username="admin_user",
        email="admin@example.com",
        full_name="Admin",
        role=role,
        is_active=True,
        hashed_password="dummy",
    )
    session.add(user)
    session.commit()

    if team_permission:
        perm = UserTeamPermission(
            user_id=user.id,
            team_id=team.id,
            permission=team_permission,
            granted_by_id=user.id,
        )
        session.add(perm)
        session.commit()

    return {"team_id": team.id, "user_id": user.id, "role": role}


def _override_user(data):
    user = SimpleNamespace(
        id=data["user_id"],
        username="admin_user",
        email="admin@example.com",
        full_name="Admin",
        role=data["role"],
        is_active=True,
    )

    async def _override():
        return user

    app.dependency_overrides[get_current_user] = _override


def _bearer_jwt():
    return {"Authorization": "Bearer fake-jwt-for-test"}


class TestCreateAppToken:
    def test_create_token_returns_raw_token_once(self, temp_db):
        with temp_db() as session:
            data = _seed_data(session)
        _override_user(data)

        with TestClient(app) as client:
            resp = client.post(
                f"/api/teams/{data['team_id']}/app-tokens",
                json={
                    "name": "CI Bot",
                    "description": "For CI",
                    "scopes": ["test_case:read", "test_case:write"],
                },
                headers=_bearer_jwt(),
            )
            assert resp.status_code == 201
            body = resp.json()
            assert body["raw_token"].startswith("tcrt_app_")
            assert body["token_prefix"].startswith("tcrt_app_")
            assert body["status"] == "active"
            assert "test_case:read" in body["scopes"]
            assert body["owner_team_id"] == data["team_id"]

    def test_create_token_default_90_day_expiry(self, temp_db):
        with temp_db() as session:
            data = _seed_data(session)
        _override_user(data)

        with TestClient(app) as client:
            resp = client.post(
                f"/api/teams/{data['team_id']}/app-tokens",
                json={"name": "Default Expiry", "scopes": ["test_case:read"]},
                headers=_bearer_jwt(),
            )
            assert resp.status_code == 201
            body = resp.json()
            assert body["expires_at"] is not None

    def test_create_token_explicit_zero_expiry(self, temp_db):
        with temp_db() as session:
            data = _seed_data(session)
        _override_user(data)

        with TestClient(app) as client:
            resp = client.post(
                f"/api/teams/{data['team_id']}/app-tokens",
                json={"name": "No Expiry", "scopes": ["test_case:read"], "expires_in_days": 0},
                headers=_bearer_jwt(),
            )
            assert resp.status_code == 201
            assert resp.json()["expires_at"] is None

    def test_create_token_invalid_scope_rejected(self, temp_db):
        with temp_db() as session:
            data = _seed_data(session)
        _override_user(data)

        with TestClient(app) as client:
            resp = client.post(
                f"/api/teams/{data['team_id']}/app-tokens",
                json={"name": "Bad Scope", "scopes": ["invalid:scope"]},
                headers=_bearer_jwt(),
            )
            assert resp.status_code == 400

    def test_create_token_negative_expiry_rejected(self, temp_db):
        with temp_db() as session:
            data = _seed_data(session)
        _override_user(data)

        with TestClient(app) as client:
            resp = client.post(
                f"/api/teams/{data['team_id']}/app-tokens",
                json={"name": "Neg", "scopes": ["test_case:read"], "expires_in_days": -1},
                headers=_bearer_jwt(),
            )
            assert resp.status_code == 422

    def test_create_token_excessive_expiry_rejected(self, temp_db):
        with temp_db() as session:
            data = _seed_data(session)
        _override_user(data)

        with TestClient(app) as client:
            resp = client.post(
                f"/api/teams/{data['team_id']}/app-tokens",
                json={"name": "Huge", "scopes": ["test_case:read"], "expires_in_days": 10**9},
                headers=_bearer_jwt(),
            )
            # bounded validation returns 422, never a 500 from timedelta overflow
            assert resp.status_code == 422

    def test_non_admin_cannot_create_token(self, temp_db):
        with temp_db() as session:
            data = _seed_data(session, role=UserRole.USER, team_permission=PermissionType.READ)
        _override_user(data)

        with TestClient(app) as client:
            resp = client.post(
                f"/api/teams/{data['team_id']}/app-tokens",
                json={"name": "Should Fail", "scopes": ["test_case:read"]},
                headers=_bearer_jwt(),
            )
            assert resp.status_code == 403


class TestListAppTokens:
    def test_list_returns_metadata_only(self, temp_db):
        with temp_db() as session:
            data = _seed_data(session)
        _override_user(data)

        with TestClient(app) as client:
            client.post(
                f"/api/teams/{data['team_id']}/app-tokens",
                json={"name": "Token 1", "scopes": ["test_case:read"]},
                headers=_bearer_jwt(),
            )
            resp = client.get(f"/api/teams/{data['team_id']}/app-tokens", headers=_bearer_jwt())
            assert resp.status_code == 200
            body = resp.json()
            assert body["total"] == 1
            item = body["items"][0]
            assert "raw_token" not in item
            assert "token_hash" not in item
            assert "token_prefix" in item
            assert item["name"] == "Token 1"


class TestRevokeAppToken:
    def test_revoke_active_token(self, temp_db):
        with temp_db() as session:
            data = _seed_data(session)
        _override_user(data)

        with TestClient(app) as client:
            create_resp = client.post(
                f"/api/teams/{data['team_id']}/app-tokens",
                json={"name": "To Revoke", "scopes": ["test_case:read"]},
                headers=_bearer_jwt(),
            )
            token_id = create_resp.json()["id"]

            resp = client.delete(
                f"/api/teams/{data['team_id']}/app-tokens/{token_id}",
                headers=_bearer_jwt(),
            )
            assert resp.status_code == 200
            assert resp.json()["status"] == "revoked"
            assert resp.json()["revoked_at"] is not None

    def test_revoke_idempotent(self, temp_db):
        with temp_db() as session:
            data = _seed_data(session)
        _override_user(data)

        with TestClient(app) as client:
            create_resp = client.post(
                f"/api/teams/{data['team_id']}/app-tokens",
                json={"name": "Double Revoke", "scopes": ["test_case:read"]},
                headers=_bearer_jwt(),
            )
            token_id = create_resp.json()["id"]

            client.delete(f"/api/teams/{data['team_id']}/app-tokens/{token_id}", headers=_bearer_jwt())
            resp = client.delete(f"/api/teams/{data['team_id']}/app-tokens/{token_id}", headers=_bearer_jwt())
            assert resp.status_code == 200
            assert resp.json()["status"] == "revoked"

    def test_revoke_nonexistent_token_404(self, temp_db):
        with temp_db() as session:
            data = _seed_data(session)
        _override_user(data)

        with TestClient(app) as client:
            resp = client.delete(
                f"/api/teams/{data['team_id']}/app-tokens/99999",
                headers=_bearer_jwt(),
            )
            assert resp.status_code == 404


class TestRotateAppToken:
    def test_rotate_invalidates_old_token(self, temp_db):
        with temp_db() as session:
            data = _seed_data(session)
        _override_user(data)

        with TestClient(app) as client:
            create_resp = client.post(
                f"/api/teams/{data['team_id']}/app-tokens",
                json={"name": "To Rotate", "scopes": ["test_case:read"]},
                headers=_bearer_jwt(),
            )
            token_id = create_resp.json()["id"]
            old_raw = create_resp.json()["raw_token"]
            old_prefix = create_resp.json()["token_prefix"]

            rotate_resp = client.post(
                f"/api/teams/{data['team_id']}/app-tokens/{token_id}/rotate",
                headers=_bearer_jwt(),
            )
            assert rotate_resp.status_code == 200
            new_raw = rotate_resp.json()["raw_token"]
            assert new_raw != old_raw
            assert new_raw.startswith("tcrt_app_")
            assert rotate_resp.json()["token_prefix"] != old_prefix

        with temp_db() as session:
            token = session.query(TeamAppToken).filter_by(id=token_id).one()
            assert token.token_hash == _hash_token(new_raw)
            assert token.token_hash != _hash_token(old_raw)

    def test_rotate_non_active_token_rejected(self, temp_db):
        with temp_db() as session:
            data = _seed_data(session)
        _override_user(data)

        with TestClient(app) as client:
            create_resp = client.post(
                f"/api/teams/{data['team_id']}/app-tokens",
                json={"name": "Revoke First", "scopes": ["test_case:read"]},
                headers=_bearer_jwt(),
            )
            token_id = create_resp.json()["id"]
            client.delete(f"/api/teams/{data['team_id']}/app-tokens/{token_id}", headers=_bearer_jwt())

            resp = client.post(
                f"/api/teams/{data['team_id']}/app-tokens/{token_id}/rotate",
                headers=_bearer_jwt(),
            )
            assert resp.status_code == 400


class TestSuperAdminAppTokens:
    def test_super_admin_lists_all_tokens(self, temp_db):
        with temp_db() as session:
            data = _seed_data(session, role=UserRole.SUPER_ADMIN, team_permission=None)
        _override_user(data)

        with TestClient(app) as client:
            client.post(
                f"/api/teams/{data['team_id']}/app-tokens",
                json={"name": "SA Token", "scopes": ["test_case:read"]},
                headers=_bearer_jwt(),
            )
            resp = client.get("/api/app-tokens", headers=_bearer_jwt())
            assert resp.status_code == 200
            assert resp.json()["total"] >= 1

    def test_non_super_admin_cannot_list_all(self, temp_db):
        with temp_db() as session:
            data = _seed_data(session, role=UserRole.ADMIN)
        _override_user(data)

        with TestClient(app) as client:
            resp = client.get("/api/app-tokens", headers=_bearer_jwt())
            assert resp.status_code == 403

    def test_super_admin_can_revoke_any_token(self, temp_db):
        with temp_db() as session:
            admin_data = _seed_data(session, role=UserRole.ADMIN)
            sa = User(
                username="super_admin",
                email="sa@example.com",
                full_name="SA",
                role=UserRole.SUPER_ADMIN,
                is_active=True,
                hashed_password="dummy",
            )
            session.add(sa)
            session.commit()
            sa_data = {"team_id": admin_data["team_id"], "user_id": sa.id, "role": UserRole.SUPER_ADMIN}

        _override_user(admin_data)
        with TestClient(app) as client:
            create_resp = client.post(
                f"/api/teams/{admin_data['team_id']}/app-tokens",
                json={"name": "SA Revoke Target", "scopes": ["test_case:read"]},
                headers=_bearer_jwt(),
            )
            token_id = create_resp.json()["id"]

        _override_user(sa_data)
        with TestClient(app) as client:
            resp = client.delete(f"/api/app-tokens/{token_id}", headers=_bearer_jwt())
            assert resp.status_code == 200
            assert resp.json()["status"] == "revoked"
