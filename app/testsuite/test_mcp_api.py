from pathlib import Path
import sys
import asyncio
import hashlib
import json
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import sessionmaker

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.main import app
from app.database import get_db
from app.models.database_models import (
    AdHocRun,
    AdHocRunItem,
    AdHocRunSheet,
    Base,
    MCPMachineCredential,
    Team,
    TestCaseLocal,
    TestCaseSection,
    TestCaseSet,
    TestRunConfig,
    TestRunSet,
    TestRunSetMembership,
)
from app.models.lark_types import Priority, TestResultStatus
from app.models.test_run_config import TestRunStatus
from app.models.test_run_set import TestRunSetStatus


def _hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


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

    yield TestingSessionLocal

    app.dependency_overrides.pop(get_db, None)
    asyncio.run(async_engine.dispose())
    sync_engine.dispose()


def _seed_mcp_data(session):
    team_a = Team(
        name="Team A",
        description="Alpha",
        wiki_token="secret-wiki-a",
        test_case_table_id="tbl-a",
    )
    team_b = Team(
        name="Team B",
        description="Beta",
        wiki_token="secret-wiki-b",
        test_case_table_id="tbl-b",
    )
    session.add_all([team_a, team_b])
    session.commit()

    set_a = TestCaseSet(
        team_id=team_a.id,
        name=f"Default-{team_a.id}",
        description="Team A Default Set",
        is_default=True,
    )
    set_b = TestCaseSet(
        team_id=team_b.id,
        name=f"Default-{team_b.id}",
        description="Team B Default Set",
        is_default=True,
    )
    session.add_all([set_a, set_b])
    session.commit()

    section_a = TestCaseSection(
        test_case_set_id=set_a.id,
        name="Unassigned",
        description="",
        level=1,
        sort_order=0,
    )
    section_b = TestCaseSection(
        test_case_set_id=set_b.id,
        name="Unassigned",
        description="",
        level=1,
        sort_order=0,
    )
    session.add_all([section_a, section_b])
    session.commit()

    tc_a1 = TestCaseLocal(
        team_id=team_a.id,
        test_case_number="TC-A-001",
        title="Login should work",
        priority=Priority.HIGH,
        test_result=TestResultStatus.PASSED,
        assignee_json=json.dumps([{"name": "Alice", "email": "alice@example.com"}]),
        tcg_json=json.dumps(["TP-1001"]),
        test_case_set_id=set_a.id,
        test_case_section_id=section_a.id,
    )
    tc_a2 = TestCaseLocal(
        team_id=team_a.id,
        test_case_number="TC-A-002",
        title="Logout should work",
        priority=Priority.LOW,
        test_result=TestResultStatus.FAILED,
        assignee_json=json.dumps([{"name": "Bob", "email": "bob@example.com"}]),
        tcg_json=json.dumps(["TP-2002"]),
        test_case_set_id=set_a.id,
        test_case_section_id=section_a.id,
    )
    tc_b1 = TestCaseLocal(
        team_id=team_b.id,
        test_case_number="TC-B-001",
        title="Cross team case",
        priority=Priority.MEDIUM,
        test_result=TestResultStatus.PENDING,
        test_case_set_id=set_b.id,
        test_case_section_id=section_b.id,
    )
    session.add_all([tc_a1, tc_a2, tc_b1])
    session.commit()

    set_run = TestRunSet(
        team_id=team_a.id,
        name="Release Cycle",
        description="",
        status=TestRunSetStatus.ACTIVE,
    )
    session.add(set_run)
    session.commit()

    config_in_set = TestRunConfig(
        team_id=team_a.id,
        name="Regression Run",
        status=TestRunStatus.ACTIVE,
        total_test_cases=10,
        executed_cases=5,
        passed_cases=4,
        failed_cases=1,
    )
    config_unassigned = TestRunConfig(
        team_id=team_a.id,
        name="Smoke Run",
        status=TestRunStatus.COMPLETED,
        total_test_cases=8,
        executed_cases=8,
        passed_cases=8,
        failed_cases=0,
    )
    config_archived = TestRunConfig(
        team_id=team_a.id,
        name="Legacy Run",
        status=TestRunStatus.ARCHIVED,
        total_test_cases=3,
        executed_cases=3,
        passed_cases=2,
        failed_cases=1,
    )
    session.add_all([config_in_set, config_unassigned, config_archived])
    session.commit()

    membership = TestRunSetMembership(
        team_id=team_a.id,
        set_id=set_run.id,
        config_id=config_in_set.id,
        position=1,
    )
    session.add(membership)

    adhoc_active = AdHocRun(
        team_id=team_a.id,
        name="Adhoc Active",
        status=TestRunStatus.ACTIVE,
    )
    adhoc_archived = AdHocRun(
        team_id=team_a.id,
        name="Adhoc Archived",
        status=TestRunStatus.ARCHIVED,
    )
    session.add_all([adhoc_active, adhoc_archived])
    session.flush()

    active_sheet = AdHocRunSheet(
        adhoc_run_id=adhoc_active.id,
        name="Sheet1",
        sort_order=0,
    )
    archived_sheet = AdHocRunSheet(
        adhoc_run_id=adhoc_archived.id,
        name="Sheet1",
        sort_order=0,
    )
    session.add_all([active_sheet, archived_sheet])
    session.flush()

    session.add_all(
        [
            AdHocRunItem(
                sheet_id=active_sheet.id,
                row_index=0,
                test_case_number="ADHOC-A-001",
                title="Active case passed",
                test_result=TestResultStatus.PASSED,
            ),
            AdHocRunItem(
                sheet_id=active_sheet.id,
                row_index=1,
                test_case_number="ADHOC-A-002",
                title="Active case pending",
                test_result=None,
            ),
            AdHocRunItem(
                sheet_id=archived_sheet.id,
                row_index=0,
                test_case_number="ADHOC-B-001",
                title="Archived case failed",
                test_result=TestResultStatus.FAILED,
            ),
        ]
    )

    scoped_token = "mcp-token-scoped"
    all_token = "mcp-token-all"
    no_permission_token = "mcp-token-no-permission"
    expired_token = "mcp-token-expired"

    session.add_all(
        [
            MCPMachineCredential(
                name="scoped-reader",
                token_hash=_hash_token(scoped_token),
                permission="mcp_read",
                allow_all_teams=False,
                team_scope_json=json.dumps([team_a.id]),
            ),
            MCPMachineCredential(
                name="all-reader",
                token_hash=_hash_token(all_token),
                permission="mcp_read",
                allow_all_teams=True,
            ),
            MCPMachineCredential(
                name="no-perm",
                token_hash=_hash_token(no_permission_token),
                permission="read",
                allow_all_teams=True,
            ),
            MCPMachineCredential(
                name="expired-reader",
                token_hash=_hash_token(expired_token),
                permission="mcp_read",
                allow_all_teams=True,
                expires_at=datetime.utcnow() - timedelta(hours=1),
            ),
        ]
    )
    session.commit()

    return {
        "team_a_id": team_a.id,
        "team_b_id": team_b.id,
        "set_a_id": set_a.id,
        "config_in_set_id": config_in_set.id,
        "config_unassigned_id": config_unassigned.id,
        "config_archived_id": config_archived.id,
        "scoped_token": scoped_token,
        "all_token": all_token,
        "no_permission_token": no_permission_token,
        "expired_token": expired_token,
    }


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_mcp_auth_requires_valid_machine_token(temp_db):
    with temp_db() as session:
        seeded = _seed_mcp_data(session)

    with TestClient(app) as client:
        no_token = client.get("/api/mcp/teams")
        assert no_token.status_code == 401
        assert no_token.json()["detail"]["code"] == "MCP_AUTH_REQUIRED"

        invalid = client.get("/api/mcp/teams", headers=_bearer("invalid-token"))
        assert invalid.status_code == 401
        assert invalid.json()["detail"]["code"] == "INVALID_MACHINE_TOKEN"

        no_perm = client.get("/api/mcp/teams", headers=_bearer(seeded["no_permission_token"]))
        assert no_perm.status_code == 403
        assert no_perm.json()["detail"]["code"] == "INSUFFICIENT_MACHINE_PERMISSION"

        expired = client.get("/api/mcp/teams", headers=_bearer(seeded["expired_token"]))
        assert expired.status_code == 401
        assert expired.json()["detail"]["code"] == "MACHINE_TOKEN_EXPIRED"


def test_mcp_teams_returns_sanitized_and_count(temp_db):
    with temp_db() as session:
        seeded = _seed_mcp_data(session)

    with TestClient(app) as client:
        all_resp = client.get("/api/mcp/teams", headers=_bearer(seeded["all_token"]))
        assert all_resp.status_code == 200
        all_payload = all_resp.json()
        assert all_payload["total"] == 2
        assert len(all_payload["items"]) == 2

        first_item = all_payload["items"][0]
        assert "wiki_token" not in first_item
        assert "test_case_table_id" not in first_item

        scoped_resp = client.get("/api/mcp/teams", headers=_bearer(seeded["scoped_token"]))
        assert scoped_resp.status_code == 200
        scoped_payload = scoped_resp.json()
        assert scoped_payload["total"] == 1
        assert scoped_payload["items"][0]["id"] == seeded["team_a_id"]


def test_mcp_team_test_cases_filters_and_scope(temp_db):
    with temp_db() as session:
        seeded = _seed_mcp_data(session)

    with TestClient(app) as client:
        resp = client.get(
            f"/api/mcp/teams/{seeded['team_a_id']}/test-cases",
            headers=_bearer(seeded["scoped_token"]),
            params={
                "set_id": seeded["set_a_id"],
                "search": "TC-A-001",
                "priority": "High",
                "test_result": "Passed",
                "assignee": "Alice",
                "skip": 0,
                "limit": 10,
            },
        )
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["team_id"] == seeded["team_a_id"]
        assert payload["page"]["total"] == 1
        assert len(payload["test_cases"]) == 1
        assert payload["test_cases"][0]["test_case_number"] == "TC-A-001"
        assert payload["test_cases"][0]["assignee"] == "Alice"

        deny_scope = client.get(
            f"/api/mcp/teams/{seeded['team_b_id']}/test-cases",
            headers=_bearer(seeded["scoped_token"]),
        )
        assert deny_scope.status_code == 403
        assert deny_scope.json()["detail"]["code"] == "TEAM_SCOPE_DENIED"


def test_mcp_team_test_runs_unified_filters(temp_db):
    with temp_db() as session:
        seeded = _seed_mcp_data(session)

    with TestClient(app) as client:
        default_resp = client.get(
            f"/api/mcp/teams/{seeded['team_a_id']}/test-runs",
            headers=_bearer(seeded["all_token"]),
        )
        assert default_resp.status_code == 200
        default_payload = default_resp.json()
        assert len(default_payload["sets"]) == 1
        assert default_payload["sets"][0]["test_runs"][0]["id"] == seeded["config_in_set_id"]
        assert [item["id"] for item in default_payload["unassigned"]] == [seeded["config_unassigned_id"]]
        assert [item["name"] for item in default_payload["adhoc"]] == ["Adhoc Active"]

        status_resp = client.get(
            f"/api/mcp/teams/{seeded['team_a_id']}/test-runs",
            headers=_bearer(seeded["all_token"]),
            params={"status": "completed"},
        )
        assert status_resp.status_code == 200
        status_payload = status_resp.json()
        assert status_payload["sets"] == []
        assert [item["id"] for item in status_payload["unassigned"]] == [seeded["config_unassigned_id"]]
        assert status_payload["adhoc"] == []

        adhoc_archived_resp = client.get(
            f"/api/mcp/teams/{seeded['team_a_id']}/test-runs",
            headers=_bearer(seeded["all_token"]),
            params={"run_type": "adhoc", "status": "archived", "include_archived": "true"},
        )
        assert adhoc_archived_resp.status_code == 200
        adhoc_archived_payload = adhoc_archived_resp.json()
        assert adhoc_archived_payload["sets"] == []
        assert adhoc_archived_payload["unassigned"] == []
        assert [item["name"] for item in adhoc_archived_payload["adhoc"]] == ["Adhoc Archived"]
