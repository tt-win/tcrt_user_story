from pathlib import Path
import sys
import asyncio
import hashlib
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.auth.dependencies import get_current_user
from app.auth.models import UserRole
from app.auth.permission_service import permission_service
from app.database import get_db
from app.main import app
from app.models.database_models import MCPMachineCredential, Team, User
from app.testsuite.db_test_helpers import (
    create_managed_test_database,
    dispose_managed_test_database,
    install_main_database_overrides,
)


@pytest.fixture
def organization_token_test_env(tmp_path, monkeypatch):
    database_bundle = create_managed_test_database(tmp_path / "test_case_repo.db")
    TestingSessionLocal = database_bundle["sync_session_factory"]
    AsyncTestingSessionLocal = database_bundle["async_session_factory"]

    install_main_database_overrides(
        monkeypatch=monkeypatch,
        app=app,
        get_db_dependency=get_db,
        async_engine=database_bundle["async_engine"],
        async_session_factory=AsyncTestingSessionLocal,
    )

    current_user_ref = {"value": None}

    def override_get_current_user():
        return current_user_ref["value"]
    app.dependency_overrides[get_current_user] = override_get_current_user

    session = TestingSessionLocal()
    try:
        super_admin = User(
            username="super-admin",
            email="super-admin@example.com",
            hashed_password="x",
            role=UserRole.SUPER_ADMIN,
            is_active=True,
        )
        admin = User(
            username="admin-user",
            email="admin-user@example.com",
            hashed_password="x",
            role=UserRole.ADMIN,
            is_active=True,
        )
        team_a = Team(
            name="Team A",
            description="A",
            wiki_token="wiki-a",
            test_case_table_id="tbl-a",
        )
        team_b = Team(
            name="Team B",
            description="B",
            wiki_token="wiki-b",
            test_case_table_id="tbl-b",
        )
        session.add_all([super_admin, admin, team_a, team_b])
        session.commit()

        current_user_ref["value"] = SimpleNamespace(
            id=super_admin.id,
            username=super_admin.username,
            role=UserRole.SUPER_ADMIN.value,
            is_active=True,
        )
    finally:
        session.close()

    asyncio.run(permission_service.cache.clear_all())

    yield {
        "session_factory": TestingSessionLocal,
        "current_user_ref": current_user_ref,
    }

    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_current_user, None)
    asyncio.run(permission_service.cache.clear_all())
    dispose_managed_test_database(database_bundle)


def test_super_admin_can_create_mcp_machine_token(organization_token_test_env):
    client = TestClient(app)
    session_factory = organization_token_test_env["session_factory"]

    with session_factory() as session:
        team_ids = [team.id for team in session.query(Team).order_by(Team.id.asc()).all()]

    payload = {
        "name": "mcp-ci-reader",
        "description": "CI use",
        "allow_all_teams": False,
        "team_scope_ids": team_ids,
        "expires_in_days": 120,
    }

    response = client.post("/api/organization/mcp/machine-tokens", json=payload)
    assert response.status_code == 200

    data = response.json()
    assert data["success"] is True
    assert data["data"]["name"] == payload["name"]
    assert data["data"]["permission"] == "mcp_read"
    assert data["data"]["allow_all_teams"] is False
    assert data["data"]["team_scope_ids"] == team_ids

    raw_token = data["data"]["raw_token"]
    assert isinstance(raw_token, str)
    assert len(raw_token) >= 64

    with session_factory() as session:
        saved = (
            session.query(MCPMachineCredential)
            .filter(MCPMachineCredential.id == data["data"]["credential_id"])
            .one_or_none()
        )
        assert saved is not None
        assert saved.name == payload["name"]
        assert saved.permission == "mcp_read"
        assert saved.allow_all_teams is False
        assert saved.token_hash == hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        assert saved.token_hash != raw_token
        assert json.loads(saved.team_scope_json or "[]") == team_ids


def test_create_mcp_machine_token_requires_scope_when_not_allow_all(organization_token_test_env):
    client = TestClient(app)

    response = client.post(
        "/api/organization/mcp/machine-tokens",
        json={
            "name": "mcp-no-scope",
            "allow_all_teams": False,
            "team_scope_ids": [],
        },
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["detail"]["code"] == "MCP_MACHINE_TOKEN_SCOPE_REQUIRED"


def test_create_mcp_machine_token_rejects_invalid_team_scope(organization_token_test_env):
    client = TestClient(app)

    response = client.post(
        "/api/organization/mcp/machine-tokens",
        json={
            "name": "mcp-invalid-scope",
            "allow_all_teams": False,
            "team_scope_ids": [999999],
        },
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["detail"]["code"] == "MCP_MACHINE_TOKEN_SCOPE_INVALID_TEAM"


def test_admin_cannot_create_mcp_machine_token(organization_token_test_env):
    client = TestClient(app)
    session_factory = organization_token_test_env["session_factory"]
    current_user_ref = organization_token_test_env["current_user_ref"]

    with session_factory() as session:
        admin = session.query(User).filter(User.role == UserRole.ADMIN).one()
        current_user_ref["value"] = SimpleNamespace(
            id=admin.id,
            username=admin.username,
            role=UserRole.ADMIN.value,
            is_active=True,
        )

    response = client.post(
        "/api/organization/mcp/machine-tokens",
        json={
            "name": "mcp-by-admin",
            "allow_all_teams": True,
        },
    )

    assert response.status_code == 403


# ---------------------------------------------------------------- list / revoke


def _create_token(client, name, *, allow_all_teams=True, team_scope_ids=None, expires_in_days=None):
    payload = {"name": name, "allow_all_teams": allow_all_teams}
    if team_scope_ids is not None:
        payload["team_scope_ids"] = team_scope_ids
    if expires_in_days is not None:
        payload["expires_in_days"] = expires_in_days
    resp = client.post("/api/organization/mcp/machine-tokens", json=payload)
    assert resp.status_code == 200
    return resp.json()["data"]


def _switch_to_admin(env):
    session_factory = env["session_factory"]
    current_user_ref = env["current_user_ref"]
    with session_factory() as session:
        admin = session.query(User).filter(User.role == UserRole.ADMIN).one()
        current_user_ref["value"] = SimpleNamespace(
            id=admin.id,
            username=admin.username,
            role=UserRole.ADMIN.value,
            is_active=True,
        )


def _status_value(credential):
    status = credential.status
    return status.value if hasattr(status, "value") else str(status)


def test_super_admin_can_list_mcp_machine_tokens(organization_token_test_env):
    client = TestClient(app)
    _create_token(client, "mcp-list-a", allow_all_teams=True)
    _create_token(client, "mcp-list-b", allow_all_teams=True)

    response = client.get("/api/organization/mcp/machine-tokens")
    assert response.status_code == 200

    data = response.json()
    assert data["success"] is True
    items = data["data"]["items"]
    assert data["data"]["total"] == 2
    # 依 created_at 由新到舊（id desc 作為同秒 tiebreak），後建立者在前
    assert [item["name"] for item in items] == ["mcp-list-b", "mcp-list-a"]

    expected_keys = {
        "credential_id",
        "name",
        "description",
        "permission",
        "status",
        "allow_all_teams",
        "team_scope_ids",
        "expires_at",
        "last_used_at",
        "created_at",
        "updated_at",
    }
    for item in items:
        assert expected_keys <= set(item.keys())
        assert item["status"] == "active"
        assert item["permission"] == "mcp_read"


def test_list_excludes_token_secret(organization_token_test_env):
    client = TestClient(app)
    _create_token(client, "mcp-secret", allow_all_teams=True)

    response = client.get("/api/organization/mcp/machine-tokens")
    assert response.status_code == 200
    for item in response.json()["data"]["items"]:
        assert "token_hash" not in item
        assert "raw_token" not in item


def test_admin_cannot_list_mcp_machine_tokens(organization_token_test_env):
    client = TestClient(app)
    _switch_to_admin(organization_token_test_env)

    response = client.get("/api/organization/mcp/machine-tokens")
    assert response.status_code == 403


def test_super_admin_can_revoke_mcp_machine_token(organization_token_test_env):
    client = TestClient(app)
    session_factory = organization_token_test_env["session_factory"]
    created = _create_token(client, "mcp-revoke", allow_all_teams=True)
    credential_id = created["credential_id"]

    response = client.delete(f"/api/organization/mcp/machine-tokens/{credential_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"]["status"] == "revoked"

    with session_factory() as session:
        saved = (
            session.query(MCPMachineCredential)
            .filter(MCPMachineCredential.id == credential_id)
            .one_or_none()
        )
        assert saved is not None  # 軟刪：資料列保留
        assert _status_value(saved) == "revoked"


def test_revoke_nonexistent_token_returns_404(organization_token_test_env):
    client = TestClient(app)

    response = client.delete("/api/organization/mcp/machine-tokens/999999")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "MCP_MACHINE_TOKEN_NOT_FOUND"


def test_revoke_is_idempotent(organization_token_test_env):
    client = TestClient(app)
    session_factory = organization_token_test_env["session_factory"]
    created = _create_token(client, "mcp-revoke-twice", allow_all_teams=True)
    credential_id = created["credential_id"]

    first = client.delete(f"/api/organization/mcp/machine-tokens/{credential_id}")
    assert first.status_code == 200
    second = client.delete(f"/api/organization/mcp/machine-tokens/{credential_id}")
    assert second.status_code == 200
    assert second.json()["data"]["status"] == "revoked"

    with session_factory() as session:
        saved = (
            session.query(MCPMachineCredential)
            .filter(MCPMachineCredential.id == credential_id)
            .one()
        )
        assert _status_value(saved) == "revoked"


def test_admin_cannot_revoke_mcp_machine_token(organization_token_test_env):
    client = TestClient(app)
    session_factory = organization_token_test_env["session_factory"]
    created = _create_token(client, "mcp-revoke-by-admin", allow_all_teams=True)
    credential_id = created["credential_id"]

    _switch_to_admin(organization_token_test_env)

    response = client.delete(f"/api/organization/mcp/machine-tokens/{credential_id}")
    assert response.status_code == 403

    with session_factory() as session:
        saved = (
            session.query(MCPMachineCredential)
            .filter(MCPMachineCredential.id == credential_id)
            .one()
        )
        assert _status_value(saved) == "active"
