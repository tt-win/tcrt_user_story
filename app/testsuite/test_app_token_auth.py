"""Tests for team app token data model, migration, bootstrap, and auth."""

from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import sys

import pytest
from fastapi import APIRouter, Depends
from fastapi.testclient import TestClient
from sqlalchemy import inspect

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.auth.models import UserRole
from app.database import get_db
from app.main import app
from app.models.database_models import (
    MCPMachineCredential,
    MCPMachineCredentialStatus,
    Team,
    TeamAppToken,
    TeamAppTokenStatus,
    User,
)
from app.testsuite.db_test_helpers import (
    create_managed_test_database,
    dispose_managed_test_database,
    install_main_database_overrides,
)


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    database_bundle = create_managed_test_database(tmp_path / "test_app_token.db")
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


def _hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _seed_team_and_user(session):
    team = Team(
        name="App Token Team",
        description="Test team",
        wiki_token="secret-wiki",
        test_case_table_id="tbl-app",
    )
    session.add(team)
    session.commit()

    user = User(
        username="admin_user",
        email="admin@example.com",
        full_name="Admin",
        role=UserRole.ADMIN,
        is_active=True,
        hashed_password="dummy",
    )
    session.add(user)
    session.commit()
    return team, user


class TestTeamAppTokenTableCreation:
    """Verify the team_app_tokens table is created with correct structure."""

    def test_table_exists_after_bootstrap(self, temp_db):
        session = temp_db()
        try:
            engine = session.bind
            inspector = inspect(engine)
            table_names = set(inspector.get_table_names())
            assert "team_app_tokens" in table_names
        finally:
            session.close()

    def test_table_has_expected_columns(self, temp_db):
        session = temp_db()
        try:
            engine = session.bind
            inspector = inspect(engine)
            columns = {col["name"]: col for col in inspector.get_columns("team_app_tokens")}

            expected_columns = {
                "id",
                "name",
                "description",
                "owner_team_id",
                "token_hash",
                "token_prefix",
                "status",
                "scopes_json",
                "expires_at",
                "last_used_at",
                "created_by_user_id",
                "created_at",
                "updated_at",
                "revoked_at",
            }
            assert expected_columns.issubset(set(columns.keys()))
        finally:
            session.close()

    def test_nullable_fields(self, temp_db):
        session = temp_db()
        try:
            engine = session.bind
            inspector = inspect(engine)
            columns = {col["name"]: col for col in inspector.get_columns("team_app_tokens")}

            nullable_fields = [
                "description",
                "scopes_json",
                "expires_at",
                "last_used_at",
                "created_by_user_id",
                "revoked_at",
            ]
            for field_name in nullable_fields:
                assert columns[field_name]["nullable"], f"{field_name} should be nullable"

            non_nullable_fields = [
                "id",
                "name",
                "owner_team_id",
                "token_hash",
                "token_prefix",
                "status",
                "created_at",
                "updated_at",
            ]
            for field_name in non_nullable_fields:
                assert not columns[field_name]["nullable"], f"{field_name} should NOT be nullable"
        finally:
            session.close()

    def test_indexes_exist(self, temp_db):
        session = temp_db()
        try:
            engine = session.bind
            inspector = inspect(engine)
            indexes = {idx["name"] for idx in inspector.get_indexes("team_app_tokens")}

            expected_indexes = {
                "ix_team_app_tokens_owner_team_id",
                "ix_team_app_tokens_status",
                "ix_team_app_tokens_expires_at",
                "ix_team_app_tokens_created_by_user_id",
            }
            assert expected_indexes.issubset(indexes)
        finally:
            session.close()

    def test_token_hash_unique_constraint(self, temp_db):
        session = temp_db()
        try:
            engine = session.bind
            inspector = inspect(engine)
            unique_constraints = set()
            for constr in inspector.get_unique_constraints("team_app_tokens"):
                unique_constraints.update(constr["column_names"])
            assert "token_hash" in unique_constraints
        finally:
            session.close()


class TestTeamAppTokenModelOperations:
    """Verify ORM model operations work correctly."""

    def test_create_and_read_token(self, temp_db):
        session = temp_db()
        try:
            team, user = _seed_team_and_user(session)
            raw_token = "tcrt_app_" + "a" * 48
            token = TeamAppToken(
                name="CI Bot Token",
                description="For CI automation",
                owner_team_id=team.id,
                token_hash=_hash_token(raw_token),
                token_prefix=raw_token[:16],
                status=TeamAppTokenStatus.ACTIVE,
                scopes_json='["test_case:read","test_case:write"]',
                expires_at=datetime.utcnow() + timedelta(days=90),
                created_by_user_id=user.id,
            )
            session.add(token)
            session.commit()

            loaded = session.query(TeamAppToken).filter_by(name="CI Bot Token").one()
            assert loaded.id is not None
            assert loaded.token_prefix == raw_token[:16]
            assert loaded.status == TeamAppTokenStatus.ACTIVE
            assert loaded.owner_team_id == team.id
        finally:
            session.close()

    def test_token_prefix_is_16_chars(self, temp_db):
        session = temp_db()
        try:
            team, user = _seed_team_and_user(session)
            raw_token = "tcrt_app_" + "b" * 48
            token = TeamAppToken(
                name="Prefix Test",
                owner_team_id=team.id,
                token_hash=_hash_token(raw_token),
                token_prefix=raw_token[:16],
                status=TeamAppTokenStatus.ACTIVE,
                created_by_user_id=user.id,
            )
            session.add(token)
            session.commit()

            loaded = session.query(TeamAppToken).filter_by(name="Prefix Test").one()
            assert len(loaded.token_prefix) == 16
            assert loaded.token_prefix.startswith("tcrt_app_")
        finally:
            session.close()

    def test_non_expiring_token_has_null_expires_at(self, temp_db):
        session = temp_db()
        try:
            team, user = _seed_team_and_user(session)
            raw_token = "tcrt_app_" + "c" * 48
            token = TeamAppToken(
                name="Non-Expiring",
                owner_team_id=team.id,
                token_hash=_hash_token(raw_token),
                token_prefix=raw_token[:16],
                status=TeamAppTokenStatus.ACTIVE,
                expires_at=None,
                created_by_user_id=user.id,
            )
            session.add(token)
            session.commit()

            loaded = session.query(TeamAppToken).filter_by(name="Non-Expiring").one()
            assert loaded.expires_at is None
        finally:
            session.close()

    def test_revoked_token_has_revoked_at(self, temp_db):
        session = temp_db()
        try:
            team, user = _seed_team_and_user(session)
            raw_token = "tcrt_app_" + "d" * 48
            token = TeamAppToken(
                name="To Revoke",
                owner_team_id=team.id,
                token_hash=_hash_token(raw_token),
                token_prefix=raw_token[:16],
                status=TeamAppTokenStatus.ACTIVE,
                created_by_user_id=user.id,
            )
            session.add(token)
            session.commit()

            token.status = TeamAppTokenStatus.REVOKED
            token.revoked_at = datetime.utcnow()
            session.commit()

            loaded = session.query(TeamAppToken).filter_by(name="To Revoke").one()
            assert loaded.status == TeamAppTokenStatus.REVOKED
            assert loaded.revoked_at is not None
        finally:
            session.close()

    def test_duplicate_token_hash_rejected(self, temp_db):
        session = temp_db()
        try:
            team, user = _seed_team_and_user(session)
            raw_token = "tcrt_app_" + "e" * 48
            hash_value = _hash_token(raw_token)

            token1 = TeamAppToken(
                name="First",
                owner_team_id=team.id,
                token_hash=hash_value,
                token_prefix=raw_token[:16],
                status=TeamAppTokenStatus.ACTIVE,
                created_by_user_id=user.id,
            )
            session.add(token1)
            session.commit()

            token2 = TeamAppToken(
                name="Second",
                owner_team_id=team.id,
                token_hash=hash_value,
                token_prefix=raw_token[:16],
                status=TeamAppTokenStatus.ACTIVE,
                created_by_user_id=user.id,
            )
            session.add(token2)
            from sqlalchemy.exc import IntegrityError

            with pytest.raises(IntegrityError):
                session.commit()
            session.rollback()
        finally:
            session.close()


class TestLegacyDatabaseStartup:
    """Verify legacy databases (without team_app_tokens) can start up with the new model."""

    def test_legacy_mcp_credentials_still_work(self, temp_db):
        session = temp_db()
        try:
            team, user = _seed_team_and_user(session)
            raw_token = "legacy_machine_token_123"
            cred = MCPMachineCredential(
                name="Legacy MCP",
                description="Legacy machine token",
                token_hash=_hash_token(raw_token),
                permission="mcp_read",
                status=MCPMachineCredentialStatus.ACTIVE,
                allow_all_teams=False,
                team_scope_json=f"[{team.id}]",
                created_by_user_id=user.id,
            )
            session.add(cred)
            session.commit()

            loaded = session.query(MCPMachineCredential).filter_by(name="Legacy MCP").one()
            assert loaded.status == MCPMachineCredentialStatus.ACTIVE
            assert loaded.permission == "mcp_read"
        finally:
            session.close()

    def test_both_tables_coexist(self, temp_db):
        session = temp_db()
        try:
            engine = session.bind
            inspector = inspect(engine)
            table_names = set(inspector.get_table_names())
            assert "mcp_machine_credentials" in table_names
            assert "team_app_tokens" in table_names
        finally:
            session.close()


# ===================== Auth dependency tests =====================

from app.auth.app_token_dependencies import (  # noqa: E402
    AppTokenErrorCodes,
    generate_app_token,
    get_current_app_token_principal,
    require_app_team_access,
)
from app.models.app_token import AppTokenPrincipal  # noqa: E402

_test_router = APIRouter(prefix="/test/app")


@_test_router.get("/teams/{team_id}/ping")
async def _test_team_endpoint(
    team_id: int,
    principal: AppTokenPrincipal = Depends(get_current_app_token_principal),
):
    return {"team_id": team_id, "principal": principal.credential_name}


@_test_router.get("/teams/{team_id}/scoped")
async def _test_scoped_endpoint(
    team_id: int,
    principal: AppTokenPrincipal = Depends(require_app_team_access),
):
    return {"team_id": team_id, "principal": principal.credential_name}


app.include_router(_test_router)


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _seed_app_tokens(session):
    team, user = _seed_team_and_user(session)

    team_b = Team(
        name="Other Team",
        description="Other",
        wiki_token="secret-wiki-b",
        test_case_table_id="tbl-b",
    )
    session.add(team_b)
    session.commit()

    raw_read_only, hash_read, prefix_read = generate_app_token()
    raw_rw, hash_rw, prefix_rw = generate_app_token()
    raw_admin, hash_admin, prefix_admin = generate_app_token()
    raw_revoked, hash_revoked, prefix_revoked = generate_app_token()
    raw_expired, hash_expired, prefix_expired = generate_app_token()
    raw_no_expiry, hash_no_expiry, prefix_no_expiry = generate_app_token()

    tokens = [
        TeamAppToken(
            name="read-only",
            owner_team_id=team.id,
            token_hash=hash_read,
            token_prefix=prefix_read,
            status=TeamAppTokenStatus.ACTIVE,
            scopes_json=json.dumps(["test_case:read", "test_run:read"]),
            expires_at=datetime.utcnow() + timedelta(days=90),
            created_by_user_id=user.id,
        ),
        TeamAppToken(
            name="read-write",
            owner_team_id=team.id,
            token_hash=hash_rw,
            token_prefix=prefix_rw,
            status=TeamAppTokenStatus.ACTIVE,
            scopes_json=json.dumps(
                ["test_case:read", "test_case:write", "test_run:read", "test_run:write"]
            ),
            expires_at=datetime.utcnow() + timedelta(days=90),
            created_by_user_id=user.id,
        ),
        TeamAppToken(
            name="admin",
            owner_team_id=team.id,
            token_hash=hash_admin,
            token_prefix=prefix_admin,
            status=TeamAppTokenStatus.ACTIVE,
            scopes_json=json.dumps(
                [
                    "test_case:read",
                    "test_case:write",
                    "test_case:admin",
                    "test_run:read",
                    "test_run:write",
                    "test_run:admin",
                    "automation:execute",
                ]
            ),
            expires_at=datetime.utcnow() + timedelta(days=90),
            created_by_user_id=user.id,
        ),
        TeamAppToken(
            name="revoked-token",
            owner_team_id=team.id,
            token_hash=hash_revoked,
            token_prefix=prefix_revoked,
            status=TeamAppTokenStatus.REVOKED,
            scopes_json=json.dumps(["test_case:read"]),
            revoked_at=datetime.utcnow(),
            created_by_user_id=user.id,
        ),
        TeamAppToken(
            name="expired-token",
            owner_team_id=team.id,
            token_hash=hash_expired,
            token_prefix=prefix_expired,
            status=TeamAppTokenStatus.ACTIVE,
            scopes_json=json.dumps(["test_case:read"]),
            expires_at=datetime.utcnow() - timedelta(days=1),
            created_by_user_id=user.id,
        ),
        TeamAppToken(
            name="no-expiry",
            owner_team_id=team.id,
            token_hash=hash_no_expiry,
            token_prefix=prefix_no_expiry,
            status=TeamAppTokenStatus.ACTIVE,
            scopes_json=json.dumps(["test_case:read"]),
            expires_at=None,
            created_by_user_id=user.id,
        ),
    ]
    session.add_all(tokens)
    session.commit()

    legacy_all_token = "legacy_machine_all_teams_123"
    legacy_scoped_token = "legacy_machine_scoped_456"
    legacy_no_perm_token = "legacy_no_perm_789"

    session.add_all(
        [
            MCPMachineCredential(
                name="legacy-all-teams",
                token_hash=_hash_token(legacy_all_token),
                permission="mcp_read",
                status=MCPMachineCredentialStatus.ACTIVE,
                allow_all_teams=True,
                created_by_user_id=user.id,
            ),
            MCPMachineCredential(
                name="legacy-scoped",
                token_hash=_hash_token(legacy_scoped_token),
                permission="mcp_read",
                status=MCPMachineCredentialStatus.ACTIVE,
                allow_all_teams=False,
                team_scope_json=json.dumps([team.id]),
                created_by_user_id=user.id,
            ),
            MCPMachineCredential(
                name="legacy-no-perm",
                token_hash=_hash_token(legacy_no_perm_token),
                permission="other",
                status=MCPMachineCredentialStatus.ACTIVE,
                allow_all_teams=True,
                created_by_user_id=user.id,
            ),
        ]
    )
    session.commit()

    return {
        "team_a_id": team.id,
        "team_b_id": team_b.id,
        "user_id": user.id,
        "read_token": raw_read_only,
        "rw_token": raw_rw,
        "admin_token": raw_admin,
        "revoked_token": raw_revoked,
        "expired_token": raw_expired,
        "no_expiry_token": raw_no_expiry,
        "legacy_all_token": legacy_all_token,
        "legacy_scoped_token": legacy_scoped_token,
        "legacy_no_perm_token": legacy_no_perm_token,
    }


class TestAppTokenAuth:
    """Test app token authentication flows."""

    def test_missing_token_returns_required_error(self, temp_db):
        with temp_db() as session:
            _seed_app_tokens(session)
        with TestClient(app) as client:
            resp = client.get("/test/app/teams/1/ping")
            assert resp.status_code == 401
            assert resp.json()["detail"]["code"] == AppTokenErrorCodes.REQUIRED

    def test_invalid_token_returns_invalid_error(self, temp_db):
        with temp_db() as session:
            _seed_app_tokens(session)
        with TestClient(app) as client:
            resp = client.get(
                "/test/app/teams/1/ping", headers=_bearer("tcrt_app_invalid_token_xyz")
            )
            assert resp.status_code == 401
            assert resp.json()["detail"]["code"] == AppTokenErrorCodes.INVALID

    def test_revoked_token_returns_invalid_error(self, temp_db):
        with temp_db() as session:
            seeded = _seed_app_tokens(session)
        with TestClient(app) as client:
            resp = client.get(
                f"/test/app/teams/{seeded['team_a_id']}/ping",
                headers=_bearer(seeded["revoked_token"]),
            )
            assert resp.status_code == 401
            assert resp.json()["detail"]["code"] == AppTokenErrorCodes.INVALID

    def test_expired_token_returns_invalid_error(self, temp_db):
        with temp_db() as session:
            seeded = _seed_app_tokens(session)
        with TestClient(app) as client:
            resp = client.get(
                f"/test/app/teams/{seeded['team_a_id']}/ping",
                headers=_bearer(seeded["expired_token"]),
            )
            assert resp.status_code == 401
            assert resp.json()["detail"]["code"] == AppTokenErrorCodes.INVALID

    def test_valid_app_token_authenticates(self, temp_db):
        with temp_db() as session:
            seeded = _seed_app_tokens(session)
        with TestClient(app) as client:
            resp = client.get(
                f"/test/app/teams/{seeded['team_a_id']}/ping",
                headers=_bearer(seeded["read_token"]),
            )
            assert resp.status_code == 200
            assert resp.json()["principal"] == "read-only"

    def test_team_scope_denied_for_other_team(self, temp_db):
        with temp_db() as session:
            seeded = _seed_app_tokens(session)
        with TestClient(app) as client:
            resp = client.get(
                f"/test/app/teams/{seeded['team_b_id']}/scoped",
                headers=_bearer(seeded["read_token"]),
            )
            assert resp.status_code == 403
            assert resp.json()["detail"]["code"] == AppTokenErrorCodes.TEAM_SCOPE_DENIED

    def test_team_scope_allowed_for_own_team(self, temp_db):
        with temp_db() as session:
            seeded = _seed_app_tokens(session)
        with TestClient(app) as client:
            resp = client.get(
                f"/test/app/teams/{seeded['team_a_id']}/scoped",
                headers=_bearer(seeded["read_token"]),
            )
            assert resp.status_code == 200

    def test_legacy_all_teams_token_works(self, temp_db):
        with temp_db() as session:
            seeded = _seed_app_tokens(session)
        with TestClient(app) as client:
            resp = client.get(
                f"/test/app/teams/{seeded['team_b_id']}/ping",
                headers=_bearer(seeded["legacy_all_token"]),
            )
            assert resp.status_code == 200

    def test_legacy_scoped_token_can_access_own_team(self, temp_db):
        with temp_db() as session:
            seeded = _seed_app_tokens(session)
        with TestClient(app) as client:
            resp = client.get(
                f"/test/app/teams/{seeded['team_a_id']}/ping",
                headers=_bearer(seeded["legacy_scoped_token"]),
            )
            assert resp.status_code == 200

    def test_legacy_scoped_token_denied_other_team(self, temp_db):
        with temp_db() as session:
            seeded = _seed_app_tokens(session)
        with TestClient(app) as client:
            resp = client.get(
                f"/test/app/teams/{seeded['team_b_id']}/scoped",
                headers=_bearer(seeded["legacy_scoped_token"]),
            )
            assert resp.status_code == 403

    def test_no_expiry_token_works(self, temp_db):
        with temp_db() as session:
            seeded = _seed_app_tokens(session)
        with TestClient(app) as client:
            resp = client.get(
                f"/test/app/teams/{seeded['team_a_id']}/ping",
                headers=_bearer(seeded["no_expiry_token"]),
            )
            assert resp.status_code == 200

    def test_app_token_last_used_updated(self, temp_db):
        with temp_db() as session:
            seeded = _seed_app_tokens(session)
        with TestClient(app) as client:
            resp = client.get(
                f"/test/app/teams/{seeded['team_a_id']}/ping",
                headers=_bearer(seeded["read_token"]),
            )
            assert resp.status_code == 200

        with temp_db() as session:
            token = session.query(TeamAppToken).filter_by(name="read-only").one()
            assert token.last_used_at is not None

    def test_app_token_last_used_throttled(self, temp_db):
        with temp_db() as session:
            seeded = _seed_app_tokens(session)

        old_time = datetime.utcnow() - timedelta(seconds=30)
        with temp_db() as session:
            token = session.query(TeamAppToken).filter_by(name="read-only").one()
            token.last_used_at = old_time
            session.commit()

        with TestClient(app) as client:
            resp = client.get(
                f"/test/app/teams/{seeded['team_a_id']}/ping",
                headers=_bearer(seeded["read_token"]),
            )
            assert resp.status_code == 200

        with temp_db() as session:
            token = session.query(TeamAppToken).filter_by(name="read-only").one()
            assert token.last_used_at == old_time


class TestAppTokenPrincipalModel:
    """Test the AppTokenPrincipal Pydantic model directly."""

    def test_owner_team_access(self):
        principal = AppTokenPrincipal(
            credential_id=1,
            credential_name="test",
            owner_team_id=5,
            scopes=["test_case:read"],
        )
        assert principal.can_access_team(5)
        assert not principal.can_access_team(6)

    def test_allow_all_teams(self):
        principal = AppTokenPrincipal(
            credential_id=1,
            credential_name="test",
            allow_all_teams=True,
            scopes=["test_case:read"],
        )
        assert principal.can_access_team(1)
        assert principal.can_access_team(999)

    def test_multi_team_scope(self):
        principal = AppTokenPrincipal(
            credential_id=1,
            credential_name="test",
            team_scope_ids=[1, 2, 3],
            scopes=["test_case:read"],
        )
        assert principal.can_access_team(2)
        assert not principal.can_access_team(4)

    def test_has_scope(self):
        principal = AppTokenPrincipal(
            credential_id=1,
            credential_name="test",
            owner_team_id=1,
            scopes=["test_case:read", "test_case:write"],
        )
        assert principal.has_scope("test_case:read")
        assert principal.has_scope("test_case:write")
        assert not principal.has_scope("test_case:admin")

    def test_audit_actor(self):
        principal = AppTokenPrincipal(
            credential_id=1,
            credential_name="ci-bot",
            owner_team_id=1,
            scopes=["test_case:read"],
        )
        assert principal.audit_actor == "app-token:ci-bot"

    def test_legacy_flag(self):
        principal = AppTokenPrincipal(
            credential_id=1,
            credential_name="legacy",
            is_legacy=True,
            legacy_permission="mcp_read",
            allow_all_teams=True,
            scopes=["test_case:read", "test_run:read"],
        )
        assert principal.is_legacy
        assert principal.legacy_permission == "mcp_read"
