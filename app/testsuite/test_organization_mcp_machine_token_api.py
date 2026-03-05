from pathlib import Path
import sys
import asyncio
import hashlib
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import sessionmaker

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.auth.dependencies import get_current_user
from app.auth.models import UserRole
from app.auth.permission_service import permission_service
from app.database import get_db
from app.main import app
from app.models.database_models import Base, MCPMachineCredential, Team, User


@pytest.fixture
def organization_token_test_env(tmp_path, monkeypatch):
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

    current_user_ref = {"value": None}

    def override_get_current_user():
        return current_user_ref["value"]

    app.dependency_overrides[get_db] = override_get_db
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
    asyncio.run(async_engine.dispose())
    sync_engine.dispose()


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
