"""Tests for /api/app/* read API compatibility with /api/mcp/*."""

from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.database import get_db
from app.main import app
from app.models.database_models import (
    MCPMachineCredential,
    MCPMachineCredentialStatus,
    Team,
    TeamAppToken,
    TeamAppTokenStatus,
    TestCaseLocal,
    TestCaseSection,
    TestCaseSet,
    TestRunConfig,
    TestRunSet,
    User,
)
from app.models.lark_types import Priority, TestResultStatus
from app.models.test_run_config import TestRunStatus
from app.models.test_run_set import TestRunSetStatus
from app.testsuite.db_test_helpers import (
    create_managed_test_database,
    dispose_managed_test_database,
    install_main_database_overrides,
)


def _hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    database_bundle = create_managed_test_database(tmp_path / "test_app_read.db")
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


def _seed_read_data(session):
    team_a = Team(
        name="Read Team A",
        description="Alpha",
        wiki_token="secret-a",
        test_case_table_id="tbl-a",
    )
    team_b = Team(
        name="Read Team B",
        description="Beta",
        wiki_token="secret-b",
        test_case_table_id="tbl-b",
    )
    session.add_all([team_a, team_b])
    session.commit()

    set_a = TestCaseSet(
        team_id=team_a.id,
        name=f"Default-{team_a.id}",
        description="Default",
        is_default=True,
    )
    session.add(set_a)
    session.commit()

    section_a = TestCaseSection(
        test_case_set_id=set_a.id,
        name="Unassigned",
        description="",
        level=1,
        sort_order=0,
    )
    session.add(section_a)
    session.commit()

    tc = TestCaseLocal(
        team_id=team_a.id,
        test_case_number="TC-A-001",
        title="Login test",
        priority=Priority.HIGH,
        test_result=TestResultStatus.PASSED,
        precondition="On login page",
        steps="1. Enter credentials",
        expected_result="Dashboard shows",
        test_case_set_id=set_a.id,
        test_case_section_id=section_a.id,
    )
    session.add(tc)
    session.commit()

    config = TestRunConfig(
        team_id=team_a.id,
        name="Config A",
        status=TestRunStatus.DRAFT,
    )
    session.add(config)
    session.commit()

    run_set = TestRunSet(
        team_id=team_a.id,
        name="Set A",
        status=TestRunSetStatus.ACTIVE,
    )
    session.add(run_set)
    session.commit()

    user = User(
        username="token_creator",
        email="tc@example.com",
        full_name="TC",
        role="admin",
        is_active=True,
        hashed_password="dummy",
    )
    session.add(user)
    session.commit()

    from app.auth.app_token_dependencies import generate_app_token

    raw_app_token, hash_app, prefix_app = generate_app_token()
    app_token = TeamAppToken(
        name="read-test-token",
        owner_team_id=team_a.id,
        token_hash=hash_app,
        token_prefix=prefix_app,
        status=TeamAppTokenStatus.ACTIVE,
        scopes_json=json.dumps(["test_case:read", "test_run:read"]),
        expires_at=datetime.utcnow() + timedelta(days=90),
        created_by_user_id=user.id,
    )
    session.add(app_token)

    legacy_token = "legacy_read_token_123"
    legacy_cred = MCPMachineCredential(
        name="legacy-reader",
        token_hash=_hash_token(legacy_token),
        permission="mcp_read",
        status=MCPMachineCredentialStatus.ACTIVE,
        allow_all_teams=True,
        created_by_user_id=user.id,
    )
    session.add(legacy_cred)
    session.commit()

    return {
        "team_a_id": team_a.id,
        "team_b_id": team_b.id,
        "set_a_id": set_a.id,
        "section_a_id": section_a.id,
        "tc_id": tc.id,
        "config_id": config.id,
        "run_set_id": run_set.id,
        "app_token": raw_app_token,
        "legacy_token": legacy_token,
    }


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


class TestAppReadTeams:
    def test_app_teams_with_app_token(self, temp_db):
        with temp_db() as session:
            seeded = _seed_read_data(session)
        with TestClient(app) as client:
            resp = client.get("/api/app/teams", headers=_bearer(seeded["app_token"]))
            assert resp.status_code == 200
            data = resp.json()
            team_ids = [t["id"] for t in data["items"]]
            assert seeded["team_a_id"] in team_ids
            assert seeded["team_b_id"] not in team_ids

    def test_app_teams_with_legacy_token(self, temp_db):
        with temp_db() as session:
            seeded = _seed_read_data(session)
        with TestClient(app) as client:
            resp = client.get("/api/app/teams", headers=_bearer(seeded["legacy_token"]))
            assert resp.status_code == 200

    def test_app_teams_no_token_rejected(self, temp_db):
        with temp_db() as session:
            _seed_read_data(session)
        with TestClient(app) as client:
            resp = client.get("/api/app/teams")
            assert resp.status_code == 401


class TestAppReadTestCases:
    def test_app_test_cases_list(self, temp_db):
        with temp_db() as session:
            seeded = _seed_read_data(session)
        with TestClient(app) as client:
            resp = client.get(
                f"/api/app/teams/{seeded['team_a_id']}/test-cases",
                headers=_bearer(seeded["app_token"]),
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["team_id"] == seeded["team_a_id"]
            assert len(data["test_cases"]) >= 1

    def test_app_test_case_detail(self, temp_db):
        with temp_db() as session:
            seeded = _seed_read_data(session)
        with TestClient(app) as client:
            resp = client.get(
                f"/api/app/teams/{seeded['team_a_id']}/test-cases/{seeded['tc_id']}",
                headers=_bearer(seeded["app_token"]),
            )
            assert resp.status_code == 200
            assert resp.json()["test_case"]["id"] == seeded["tc_id"]

    def test_app_test_case_denied_other_team(self, temp_db):
        with temp_db() as session:
            seeded = _seed_read_data(session)
        with TestClient(app) as client:
            resp = client.get(
                f"/api/app/teams/{seeded['team_b_id']}/test-cases",
                headers=_bearer(seeded["app_token"]),
            )
            assert resp.status_code == 403


class TestAppReadTestRuns:
    def test_app_test_runs_list(self, temp_db):
        with temp_db() as session:
            seeded = _seed_read_data(session)
        with TestClient(app) as client:
            resp = client.get(
                f"/api/app/teams/{seeded['team_a_id']}/test-runs",
                headers=_bearer(seeded["app_token"]),
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["team_id"] == seeded["team_a_id"]


class TestAppReadSections:
    def test_app_sections_list(self, temp_db):
        with temp_db() as session:
            seeded = _seed_read_data(session)
        with TestClient(app) as client:
            resp = client.get(
                f"/api/app/teams/{seeded['team_a_id']}/test-case-sections",
                headers=_bearer(seeded["app_token"]),
            )
            assert resp.status_code == 200
            data = resp.json()
            assert len(data["sections"]) >= 1


class TestAppReadLookup:
    def test_app_lookup_by_number(self, temp_db):
        with temp_db() as session:
            seeded = _seed_read_data(session)
        with TestClient(app) as client:
            resp = client.get(
                "/api/app/test-cases/lookup?test_case_number=TC-A-001",
                headers=_bearer(seeded["app_token"]),
            )
            assert resp.status_code == 200
            data = resp.json()
            assert len(data["items"]) >= 1


class TestMcpCompatWithAppToken:
    """Verify MCP endpoints work with app tokens (task 4.4)."""

    def test_mcp_teams_with_app_token(self, temp_db):
        with temp_db() as session:
            seeded = _seed_read_data(session)
        with TestClient(app) as client:
            resp = client.get("/api/mcp/teams", headers=_bearer(seeded["app_token"]))
            assert resp.status_code == 200

    def test_mcp_test_cases_with_app_token(self, temp_db):
        with temp_db() as session:
            seeded = _seed_read_data(session)
        with TestClient(app) as client:
            resp = client.get(
                f"/api/mcp/teams/{seeded['team_a_id']}/test-cases",
                headers=_bearer(seeded["app_token"]),
            )
            assert resp.status_code == 200

    def test_mcp_with_legacy_token_still_works(self, temp_db):
        with temp_db() as session:
            seeded = _seed_read_data(session)
        with TestClient(app) as client:
            resp = client.get(
                f"/api/mcp/teams/{seeded['team_a_id']}/test-cases",
                headers=_bearer(seeded["legacy_token"]),
            )
            assert resp.status_code == 200
