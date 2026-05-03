from pathlib import Path
import sys
import asyncio
import hashlib
import json
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

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
from app.testsuite.db_test_helpers import (
    create_managed_test_database,
    dispose_managed_test_database,
    install_main_database_overrides,
)


def _hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    database_bundle = create_managed_test_database(tmp_path / "test_case_repo.db")
    TestingSessionLocal = database_bundle["sync_session_factory"]
    AsyncTestingSessionLocal = database_bundle["async_session_factory"]

    import app.database as app_database
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

    # Sections endpoint fixtures: hierarchy + multi-set + empty section.
    set_a2 = TestCaseSet(
        team_id=team_a.id,
        name=f"Auxiliary-{team_a.id}",
        description="Team A auxiliary set",
        is_default=False,
    )
    session.add(set_a2)
    session.commit()

    section_a_login = TestCaseSection(
        test_case_set_id=set_a.id,
        name="Login",
        description="Auth flows",
        level=1,
        sort_order=10,
    )
    section_a_empty = TestCaseSection(
        test_case_set_id=set_a.id,
        name="Empty Module",
        description=None,
        level=1,
        sort_order=20,
    )
    session.add_all([section_a_login, section_a_empty])
    session.commit()

    section_a_login_sso = TestCaseSection(
        test_case_set_id=set_a.id,
        parent_section_id=section_a_login.id,
        name="SSO",
        description=None,
        level=2,
        sort_order=0,
    )
    session.add(section_a_login_sso)
    session.commit()

    section_a2_misc = TestCaseSection(
        test_case_set_id=set_a2.id,
        name="Misc",
        description=None,
        level=1,
        sort_order=0,
    )
    session.add(section_a2_misc)
    session.commit()

    tc_a1 = TestCaseLocal(
        team_id=team_a.id,
        lark_record_id="rec-a1",
        test_case_number="TC-A-001",
        title="Login should work",
        priority=Priority.HIGH,
        test_result=TestResultStatus.PASSED,
        precondition="User is on login page",
        steps="1. Input account\n2. Click login",
        expected_result="Redirect to dashboard",
        assignee_json=json.dumps([{"name": "Alice", "email": "alice@example.com"}]),
        attachments_json=json.dumps([{"name": "spec.pdf"}]),
        test_results_files_json=json.dumps([{"name": "result.png"}]),
        user_story_map_json=json.dumps([{"id": "US-1", "title": "Login"}]),
        tcg_json=json.dumps(["TP-1001"]),
        parent_record_json=json.dumps([{"record_id": "rec-parent"}]),
        raw_fields_json=json.dumps({"custom_field": "custom-value"}),
        test_data_json=json.dumps(
            [
                {
                    "id": "td-1",
                    "name": "valid_email",
                    "category": "email",
                    "value": "qa@example.com",
                },
                {
                    "id": "td-2",
                    "name": "admin_password",
                    "category": "credential",
                    "value": "P@ssw0rd!",
                },
            ]
        ),
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
        tcg_json=json.dumps(["TP-2002", "ICR-93178.010.010", "TCG-93178.010.010"]),
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
    # Cases for sections endpoint testing (count > 0 on login + sso, 0 on empty).
    tc_a_login_1 = TestCaseLocal(
        team_id=team_a.id,
        test_case_number="TC-A-LOGIN-001",
        title="Login form renders",
        priority=Priority.MEDIUM,
        test_case_set_id=set_a.id,
        test_case_section_id=section_a_login.id,
    )
    tc_a_login_2 = TestCaseLocal(
        team_id=team_a.id,
        test_case_number="TC-A-LOGIN-002",
        title="Login error message",
        priority=Priority.MEDIUM,
        test_case_set_id=set_a.id,
        test_case_section_id=section_a_login.id,
    )
    tc_a_sso_1 = TestCaseLocal(
        team_id=team_a.id,
        test_case_number="TC-A-SSO-001",
        title="SSO redirect",
        priority=Priority.MEDIUM,
        test_case_set_id=set_a.id,
        test_case_section_id=section_a_login_sso.id,
    )
    session.add_all([tc_a1, tc_a2, tc_b1, tc_a_login_1, tc_a_login_2, tc_a_sso_1])
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
        "set_a2_id": set_a2.id,
        "set_b_id": set_b.id,
        "section_a_id": section_a.id,
        "section_a_login_id": section_a_login.id,
        "section_a_login_sso_id": section_a_login_sso.id,
        "section_a_empty_id": section_a_empty.id,
        "section_a2_misc_id": section_a2_misc.id,
        "tc_a1_id": tc_a1.id,
        "tc_a2_id": tc_a2.id,
        "tc_b1_id": tc_b1.id,
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
        assert "precondition" not in payload["test_cases"][0]

        deny_scope = client.get(
            f"/api/mcp/teams/{seeded['team_b_id']}/test-cases",
            headers=_bearer(seeded["scoped_token"]),
        )
        assert deny_scope.status_code == 403
        assert deny_scope.json()["detail"]["code"] == "TEAM_SCOPE_DENIED"


def test_mcp_lookup_test_case_by_number_without_team(temp_db):
    with temp_db() as session:
        seeded = _seed_mcp_data(session)

    with TestClient(app) as client:
        resp = client.get(
            "/api/mcp/test-cases/lookup",
            headers=_bearer(seeded["all_token"]),
            params={"test_case_number": "TC-B-001"},
        )
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["page"]["total"] == 1
        assert len(payload["items"]) == 1
        first = payload["items"][0]
        assert first["team_id"] == seeded["team_b_id"]
        assert first["team_name"] == "Team B"
        assert first["match_type"] == "test_case_number_exact"
        assert first["test_case"]["test_case_number"] == "TC-B-001"
        assert "precondition" in first["test_case"]


def test_mcp_lookup_by_ticket_across_teams(temp_db):
    with temp_db() as session:
        seeded = _seed_mcp_data(session)

    with TestClient(app) as client:
        resp = client.get(
            "/api/mcp/test-cases/lookup",
            headers=_bearer(seeded["all_token"]),
            params={"ticket": "ICR-93178.010.010"},
        )
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["page"]["total"] == 1
        first = payload["items"][0]
        assert first["team_id"] == seeded["team_a_id"]
        assert first["match_type"] == "ticket"
        assert first["test_case"]["test_case_number"] == "TC-A-002"
        assert "ICR-93178.010.010" in first["test_case"]["tcg"]


def test_mcp_lookup_scope_and_required_filters(temp_db):
    with temp_db() as session:
        seeded = _seed_mcp_data(session)

    with TestClient(app) as client:
        missing_filter = client.get(
            "/api/mcp/test-cases/lookup",
            headers=_bearer(seeded["all_token"]),
        )
        assert missing_filter.status_code == 400

        scoped_hidden = client.get(
            "/api/mcp/test-cases/lookup",
            headers=_bearer(seeded["scoped_token"]),
            params={"test_case_number": "TC-B-001"},
        )
        assert scoped_hidden.status_code == 200
        scoped_payload = scoped_hidden.json()
        assert scoped_payload["page"]["total"] == 0
        assert scoped_payload["items"] == []

        scoped_forbidden_team = client.get(
            "/api/mcp/test-cases/lookup",
            headers=_bearer(seeded["scoped_token"]),
            params={"test_case_number": "TC-B-001", "team_id": seeded["team_b_id"]},
        )
        assert scoped_forbidden_team.status_code == 403
        assert scoped_forbidden_team.json()["detail"]["code"] == "TEAM_SCOPE_DENIED"


def test_mcp_team_test_cases_tcg_and_include_content(temp_db):
    with temp_db() as session:
        seeded = _seed_mcp_data(session)

    with TestClient(app) as client:
        resp = client.get(
            f"/api/mcp/teams/{seeded['team_a_id']}/test-cases",
            headers=_bearer(seeded["all_token"]),
            params={"tcg": "TP-1001", "include_content": "true", "limit": 10},
        )
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["filters"]["tcg"] == "TP-1001"
        assert payload["filters"]["include_content"] is True
        assert payload["page"]["total"] == 1
        assert len(payload["test_cases"]) == 1
        case = payload["test_cases"][0]
        assert case["test_case_number"] == "TC-A-001"
        assert case["precondition"] == "User is on login page"
        assert case["steps"] == "1. Input account\n2. Click login"
        assert case["expected_result"] == "Redirect to dashboard"


def test_mcp_team_test_cases_ticket_alias_filters_tcg_column(temp_db):
    with temp_db() as session:
        seeded = _seed_mcp_data(session)

    with TestClient(app) as client:
        resp = client.get(
            f"/api/mcp/teams/{seeded['team_a_id']}/test-cases",
            headers=_bearer(seeded["all_token"]),
            params={"ticket": "ICR-93178.010.010", "limit": 10},
        )
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["filters"]["ticket"] == "ICR-93178.010.010"
        assert payload["page"]["total"] == 1
        assert payload["test_cases"][0]["test_case_number"] == "TC-A-002"


def test_mcp_team_test_cases_invalid_set_soft_fallback(temp_db):
    with temp_db() as session:
        seeded = _seed_mcp_data(session)

    with TestClient(app) as client:
        soft_resp = client.get(
            f"/api/mcp/teams/{seeded['team_a_id']}/test-cases",
            headers=_bearer(seeded["all_token"]),
            params={
                "set_id": 999999,
                "search": "TC-A-001",
                "limit": 10,
            },
        )
        assert soft_resp.status_code == 200
        soft_payload = soft_resp.json()
        assert soft_payload["filters"]["set_id"] == 999999
        assert soft_payload["filters"]["resolved_set_id"] is None
        assert soft_payload["filters"]["set_not_found"] is True
        assert soft_payload["filters"]["strict_set"] is False
        assert soft_payload["page"]["total"] == 1
        assert soft_payload["test_cases"][0]["test_case_number"] == "TC-A-001"

        strict_resp = client.get(
            f"/api/mcp/teams/{seeded['team_a_id']}/test-cases",
            headers=_bearer(seeded["all_token"]),
            params={
                "set_id": 999999,
                "strict_set": "true",
            },
        )
        assert strict_resp.status_code == 404
        assert strict_resp.json()["detail"] == (
            f"找不到團隊 {seeded['team_a_id']} 的 Test Case Set 999999"
        )


def test_mcp_team_test_case_detail_and_scope(temp_db):
    with temp_db() as session:
        seeded = _seed_mcp_data(session)

    with TestClient(app) as client:
        detail_resp = client.get(
            f"/api/mcp/teams/{seeded['team_a_id']}/test-cases/{seeded['tc_a1_id']}",
            headers=_bearer(seeded["all_token"]),
        )
        assert detail_resp.status_code == 200
        payload = detail_resp.json()
        assert payload["team_id"] == seeded["team_a_id"]
        case = payload["test_case"]
        assert case["id"] == seeded["tc_a1_id"]
        assert case["record_id"] == "rec-a1"
        assert case["precondition"] == "User is on login page"
        assert case["steps"] == "1. Input account\n2. Click login"
        assert case["expected_result"] == "Redirect to dashboard"
        assert case["attachments"] == [{"name": "spec.pdf"}]
        assert case["test_results_files"] == [{"name": "result.png"}]
        assert case["user_story_map"] == [{"id": "US-1", "title": "Login"}]
        assert case["parent_record"] == [{"record_id": "rec-parent"}]
        assert case["raw_fields"] == {"custom_field": "custom-value"}
        assert case["test_data"] == [
            {
                "id": "td-1",
                "name": "valid_email",
                "category": "email",
                "value": "qa@example.com",
            },
            {
                "id": "td-2",
                "name": "admin_password",
                "category": "credential",
                "value": "P@ssw0rd!",
            },
        ]

        deny_scope = client.get(
            f"/api/mcp/teams/{seeded['team_b_id']}/test-cases/{seeded['tc_a1_id']}",
            headers=_bearer(seeded["scoped_token"]),
        )
        assert deny_scope.status_code == 403
        assert deny_scope.json()["detail"]["code"] == "TEAM_SCOPE_DENIED"

        not_found_in_team = client.get(
            f"/api/mcp/teams/{seeded['team_b_id']}/test-cases/{seeded['tc_a1_id']}",
            headers=_bearer(seeded["all_token"]),
        )
        assert not_found_in_team.status_code == 404

        not_found = client.get(
            f"/api/mcp/teams/{seeded['team_a_id']}/test-cases/999999",
            headers=_bearer(seeded["all_token"]),
        )
        assert not_found.status_code == 404


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



def test_mcp_detail_returns_empty_test_data_when_null(temp_db):
    with temp_db() as session:
        seeded = _seed_mcp_data(session)

    with TestClient(app) as client:
        resp = client.get(
            f"/api/mcp/teams/{seeded['team_a_id']}/test-cases/{seeded['tc_a2_id']}",
            headers=_bearer(seeded["all_token"]),
        )
        assert resp.status_code == 200
        case = resp.json()["test_case"]
        assert case["test_data"] == []


def test_mcp_detail_handles_corrupted_test_data_json(temp_db):
    with temp_db() as session:
        seeded = _seed_mcp_data(session)
        target = (
            session.query(TestCaseLocal)
            .filter(TestCaseLocal.id == seeded["tc_a2_id"])
            .one()
        )
        target.test_data_json = "{not valid json"
        session.commit()

    with TestClient(app) as client:
        resp = client.get(
            f"/api/mcp/teams/{seeded['team_a_id']}/test-cases/{seeded['tc_a2_id']}",
            headers=_bearer(seeded["all_token"]),
        )
        assert resp.status_code == 200
        case = resp.json()["test_case"]
        assert case["test_data"] == []


def test_mcp_list_test_cases_include_test_data_flag(temp_db):
    with temp_db() as session:
        seeded = _seed_mcp_data(session)

    with TestClient(app) as client:
        default_resp = client.get(
            f"/api/mcp/teams/{seeded['team_a_id']}/test-cases",
            headers=_bearer(seeded["all_token"]),
        )
        assert default_resp.status_code == 200
        default_payload = default_resp.json()
        assert default_payload["filters"]["include_test_data"] is False
        for case in default_payload["test_cases"]:
            assert "test_data" not in case

        with_resp = client.get(
            f"/api/mcp/teams/{seeded['team_a_id']}/test-cases",
            headers=_bearer(seeded["all_token"]),
            params={"include_test_data": "true"},
        )
        assert with_resp.status_code == 200
        with_payload = with_resp.json()
        assert with_payload["filters"]["include_test_data"] is True
        cases_by_id = {case["id"]: case for case in with_payload["test_cases"]}
        target_case = cases_by_id[seeded["tc_a1_id"]]
        assert target_case["test_data"] == [
            {
                "id": "td-1",
                "name": "valid_email",
                "category": "email",
                "value": "qa@example.com",
            },
            {
                "id": "td-2",
                "name": "admin_password",
                "category": "credential",
                "value": "P@ssw0rd!",
            },
        ]
        # tc_a2 has no test_data set, should still expose empty array
        assert cases_by_id[seeded["tc_a2_id"]]["test_data"] == []


def test_mcp_list_test_cases_decouples_content_and_test_data(temp_db):
    with temp_db() as session:
        seeded = _seed_mcp_data(session)

    with TestClient(app) as client:
        resp = client.get(
            f"/api/mcp/teams/{seeded['team_a_id']}/test-cases",
            headers=_bearer(seeded["all_token"]),
            params={"include_content": "true", "include_test_data": "false"},
        )
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["filters"]["include_content"] is True
        assert payload["filters"]["include_test_data"] is False
        target_case = next(
            case for case in payload["test_cases"] if case["id"] == seeded["tc_a1_id"]
        )
        assert target_case["precondition"] == "User is on login page"
        assert target_case["steps"] == "1. Input account\n2. Click login"
        assert target_case["expected_result"] == "Redirect to dashboard"
        assert "test_data" not in target_case


def test_mcp_lookup_include_test_data_flag(temp_db):
    with temp_db() as session:
        seeded = _seed_mcp_data(session)

    with TestClient(app) as client:
        default_resp = client.get(
            "/api/mcp/test-cases/lookup",
            headers=_bearer(seeded["all_token"]),
            params={"test_case_number": "TC-A-001"},
        )
        assert default_resp.status_code == 200
        default_payload = default_resp.json()
        assert default_payload["filters"]["include_test_data"] is False
        for item in default_payload["items"]:
            assert "test_data" not in item["test_case"]

        with_resp = client.get(
            "/api/mcp/test-cases/lookup",
            headers=_bearer(seeded["all_token"]),
            params={
                "test_case_number": "TC-A-001",
                "include_test_data": "true",
            },
        )
        assert with_resp.status_code == 200
        with_payload = with_resp.json()
        assert with_payload["filters"]["include_test_data"] is True
        assert len(with_payload["items"]) == 1
        item_case = with_payload["items"][0]["test_case"]
        assert any(td["category"] == "credential" for td in item_case["test_data"])
        # Credential value MUST NOT be redacted at the API layer.
        credential_item = next(
            td for td in item_case["test_data"] if td["category"] == "credential"
        )
        assert credential_item["value"] == "P@ssw0rd!"


def test_mcp_test_data_respects_team_scope(temp_db):
    with temp_db() as session:
        seeded = _seed_mcp_data(session)

    with TestClient(app) as client:
        # scoped token (team_a only) cannot see tc_b1 even when asking for test_data
        resp = client.get(
            f"/api/mcp/teams/{seeded['team_b_id']}/test-cases",
            headers=_bearer(seeded["scoped_token"]),
            params={"include_test_data": "true"},
        )
        assert resp.status_code == 403
        assert resp.json()["detail"]["code"] == "TEAM_SCOPE_DENIED"



def test_mcp_sections_default_returns_all_sections_with_counts(temp_db):
    with temp_db() as session:
        seeded = _seed_mcp_data(session)

    with TestClient(app) as client:
        resp = client.get(
            f"/api/mcp/teams/{seeded['team_a_id']}/test-case-sections",
            headers=_bearer(seeded["all_token"]),
        )
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["team_id"] == seeded["team_a_id"]
        assert payload["filters"] == {
            "set_id": None,
            "set_not_found": False,
            "parent_section_id": None,
            "roots_only": False,
            "include_empty": True,
        }
        sections_by_id = {s["id"]: s for s in payload["sections"]}
        # All five team_a sections should appear (Unassigned, Login, SSO, Empty, set_a2's Misc).
        assert seeded["section_a_id"] in sections_by_id
        assert seeded["section_a_login_id"] in sections_by_id
        assert seeded["section_a_login_sso_id"] in sections_by_id
        assert seeded["section_a_empty_id"] in sections_by_id
        assert seeded["section_a2_misc_id"] in sections_by_id
        # Counts are direct (not recursive): Login has 2, SSO has 1, Unassigned has 2 (tc_a1, tc_a2),
        # Empty has 0, set_a2's Misc has 0.
        assert sections_by_id[seeded["section_a_login_id"]]["test_case_count"] == 2
        assert sections_by_id[seeded["section_a_login_sso_id"]]["test_case_count"] == 1
        assert sections_by_id[seeded["section_a_id"]]["test_case_count"] == 2
        assert sections_by_id[seeded["section_a_empty_id"]]["test_case_count"] == 0
        assert sections_by_id[seeded["section_a2_misc_id"]]["test_case_count"] == 0
        assert payload["total"] == len(payload["sections"])
        # Sections ordered by (test_case_set_id, level, sort_order, id) — set_a sections before set_a2.
        set_ids_in_order = [s["test_case_set_id"] for s in payload["sections"]]
        assert set_ids_in_order == sorted(set_ids_in_order)


def test_mcp_sections_set_id_filter(temp_db):
    with temp_db() as session:
        seeded = _seed_mcp_data(session)

    with TestClient(app) as client:
        resp = client.get(
            f"/api/mcp/teams/{seeded['team_a_id']}/test-case-sections",
            headers=_bearer(seeded["all_token"]),
            params={"set_id": seeded["set_a_id"]},
        )
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["filters"]["set_id"] == seeded["set_a_id"]
        assert payload["filters"]["set_not_found"] is False
        assert all(s["test_case_set_id"] == seeded["set_a_id"] for s in payload["sections"])
        # set_a2's Misc section must not leak in.
        assert seeded["section_a2_misc_id"] not in {s["id"] for s in payload["sections"]}

        # Unknown set_id soft-fallback to empty list with set_not_found.
        unknown_resp = client.get(
            f"/api/mcp/teams/{seeded['team_a_id']}/test-case-sections",
            headers=_bearer(seeded["all_token"]),
            params={"set_id": 999999},
        )
        assert unknown_resp.status_code == 200
        unknown_payload = unknown_resp.json()
        assert unknown_payload["filters"]["set_id"] == 999999
        assert unknown_payload["filters"]["set_not_found"] is True
        assert unknown_payload["sections"] == []
        assert unknown_payload["total"] == 0


def test_mcp_sections_parent_filter_returns_direct_children_only(temp_db):
    with temp_db() as session:
        seeded = _seed_mcp_data(session)

    with TestClient(app) as client:
        resp = client.get(
            f"/api/mcp/teams/{seeded['team_a_id']}/test-case-sections",
            headers=_bearer(seeded["all_token"]),
            params={"parent_section_id": seeded["section_a_login_id"]},
        )
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["filters"]["parent_section_id"] == seeded["section_a_login_id"]
        section_ids = [s["id"] for s in payload["sections"]]
        # Only the SSO direct child appears.
        assert section_ids == [seeded["section_a_login_sso_id"]]


def test_mcp_sections_roots_only(temp_db):
    with temp_db() as session:
        seeded = _seed_mcp_data(session)

    with TestClient(app) as client:
        resp = client.get(
            f"/api/mcp/teams/{seeded['team_a_id']}/test-case-sections",
            headers=_bearer(seeded["all_token"]),
            params={"roots_only": "true"},
        )
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["filters"]["roots_only"] is True
        for section in payload["sections"]:
            assert section["parent_section_id"] is None
        # SSO (level=2 child of Login) must NOT be in roots.
        assert seeded["section_a_login_sso_id"] not in {
            s["id"] for s in payload["sections"]
        }


def test_mcp_sections_include_empty_false_excludes_zero_count(temp_db):
    with temp_db() as session:
        seeded = _seed_mcp_data(session)

    with TestClient(app) as client:
        resp = client.get(
            f"/api/mcp/teams/{seeded['team_a_id']}/test-case-sections",
            headers=_bearer(seeded["all_token"]),
            params={"include_empty": "false"},
        )
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["filters"]["include_empty"] is False
        ids = {s["id"] for s in payload["sections"]}
        # Empty + set_a2 Misc both have count=0 — must be excluded.
        assert seeded["section_a_empty_id"] not in ids
        assert seeded["section_a2_misc_id"] not in ids
        # Login (count=2) and SSO (count=1) and Unassigned (count=2) remain.
        assert seeded["section_a_login_id"] in ids
        assert seeded["section_a_login_sso_id"] in ids
        assert seeded["section_a_id"] in ids


def test_mcp_sections_ordering_is_deterministic(temp_db):
    with temp_db() as session:
        seeded = _seed_mcp_data(session)

    with TestClient(app) as client:
        first = client.get(
            f"/api/mcp/teams/{seeded['team_a_id']}/test-case-sections",
            headers=_bearer(seeded["all_token"]),
        ).json()
        second = client.get(
            f"/api/mcp/teams/{seeded['team_a_id']}/test-case-sections",
            headers=_bearer(seeded["all_token"]),
        ).json()
        assert [s["id"] for s in first["sections"]] == [
            s["id"] for s in second["sections"]
        ]


def test_mcp_sections_team_scope_and_404(temp_db):
    with temp_db() as session:
        seeded = _seed_mcp_data(session)

    with TestClient(app) as client:
        # Scoped token can only see team_a; team_b call must be 403.
        forbidden = client.get(
            f"/api/mcp/teams/{seeded['team_b_id']}/test-case-sections",
            headers=_bearer(seeded["scoped_token"]),
        )
        assert forbidden.status_code == 403
        assert forbidden.json()["detail"]["code"] == "TEAM_SCOPE_DENIED"

        # Unknown team must be 404.
        not_found = client.get(
            "/api/mcp/teams/999999/test-case-sections",
            headers=_bearer(seeded["all_token"]),
        )
        assert not_found.status_code == 404


def test_mcp_sections_count_is_direct_not_recursive(temp_db):
    with temp_db() as session:
        seeded = _seed_mcp_data(session)

    with TestClient(app) as client:
        resp = client.get(
            f"/api/mcp/teams/{seeded['team_a_id']}/test-case-sections",
            headers=_bearer(seeded["all_token"]),
        )
        assert resp.status_code == 200
        sections_by_id = {s["id"]: s for s in resp.json()["sections"]}
        login = sections_by_id[seeded["section_a_login_id"]]
        sso = sections_by_id[seeded["section_a_login_sso_id"]]
        # Login has 2 cases directly attached; SSO has 1. Login MUST NOT include SSO's case.
        assert login["test_case_count"] == 2
        assert sso["test_case_count"] == 1


def test_mcp_sections_endpoint_is_read_only(temp_db):
    with temp_db() as session:
        seeded = _seed_mcp_data(session)

    with TestClient(app) as client:
        for method in ("post", "put", "patch", "delete"):
            resp = getattr(client, method)(
                f"/api/mcp/teams/{seeded['team_a_id']}/test-case-sections",
                headers=_bearer(seeded["all_token"]),
            )
            # FastAPI returns 405 for unknown methods on a registered path.
            assert resp.status_code == 405
