# ruff: noqa: E402
"""End-to-end tests for the MCP automation read endpoints."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.main import app
from app.database import get_db
from app.models.database_models import (
    AutomationProviderSlot,
    AutomationRun,
    AutomationRunStatus,
    AutomationRunTrigger,
    AutomationScript,
    AutomationScriptCaseLink,
    AutomationScriptFormat,
    AutomationScriptLinkType,
    MCPMachineCredential,
    MCPMachineCredentialStatus,
    SystemAutomationProvider,
    Team,
    TeamAutomationProvider,
    TestCaseLocal,
    TestCaseSection,
    TestCaseSet,
    TestRunSet as TestRunSetDB,
    TestRunSetStatus as TestRunSetStatusEnum,
)
from app.models.lark_types import Priority
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


def _seed(session) -> dict:
    team = Team(
        name="Auto Team",
        description="",
        wiki_token="wiki-auto",
        test_case_table_id="tbl-auto",
    )
    session.add(team)
    session.commit()

    case_set = TestCaseSet(team_id=team.id, name=f"Default-{team.id}", description="", is_default=True)
    session.add(case_set)
    session.commit()

    section = TestCaseSection(
        test_case_set_id=case_set.id,
        name="Unassigned",
        description="",
        level=1,
        sort_order=0,
    )
    session.add(section)
    session.commit()

    case_one = TestCaseLocal(
        team_id=team.id,
        test_case_set_id=case_set.id,
        test_case_section_id=section.id,
        lark_record_id="rec-1",
        test_case_number="TC-001",
        title="login should work",
        priority=Priority.HIGH,
    )
    case_two = TestCaseLocal(
        team_id=team.id,
        test_case_set_id=case_set.id,
        test_case_section_id=section.id,
        lark_record_id=None,
        test_case_number="TC-002",
        title="logout should work",
        priority=Priority.MEDIUM,
    )
    session.add_all([case_one, case_two])
    session.commit()

    provider = TeamAutomationProvider(
        team_id=team.id,
        provider_slot=AutomationProviderSlot.STORAGE,
        provider_type="storage:github",
        name="GitHub",
        config_json=json.dumps({}),
        credentials_encrypted=None,
        is_active=True,
    )
    ci_provider = SystemAutomationProvider(
        provider_slot=AutomationProviderSlot.CI,
        provider_type="ci:jenkins",
        name="Jenkins",
        config_json=json.dumps({}),
        credentials_encrypted=None,
        is_active=True,
    )
    session.add_all([provider, ci_provider])
    session.commit()

    script_login = AutomationScript(
        team_id=team.id,
        provider_id=provider.id,
        name="test_login.py",
        script_format=AutomationScriptFormat.PYTEST,
        ref_path="tests/test_login.py",
        ref_branch="main",
        tags_json=json.dumps(["smoke", "auth"]),
        description="login regression",
    )
    script_logout = AutomationScript(
        team_id=team.id,
        provider_id=provider.id,
        name="test_logout.py",
        script_format=AutomationScriptFormat.PYTEST,
        ref_path="tests/test_logout.py",
        ref_branch="main",
        tags_json="[]",
    )
    session.add_all([script_login, script_logout])
    session.commit()

    link = AutomationScriptCaseLink(
        team_id=team.id,
        automation_script_id=script_login.id,
        test_case_id=case_one.id,
        link_type=AutomationScriptLinkType.PRIMARY,
    )
    session.add(link)
    session.commit()

    # Seed a Test Run Set so the MCP automation-runs endpoint (now
    # scoped to a set) has something to read.
    run_set = TestRunSetDB(
        team_id=team.id,
        name="MCP Set",
        description="",
        status=TestRunSetStatusEnum.ACTIVE,
        automation_suite_ids_json=json.dumps([]),
    )
    session.add(run_set)
    session.commit()

    run = AutomationRun(
        team_id=team.id,
        test_run_set_id=run_set.id,
        provider_id=ci_provider.id,
        external_run_id="ext-1",
        external_run_url="https://ci.example/run/1",
        status=AutomationRunStatus.SUCCEEDED,
        triggered_by=AutomationRunTrigger.USER,
        tcrt_correlation_id="corr-1",
        workflow_id="job-login",
        branch="main",
        inputs_json="{}",
        runner_label="linux",
        started_at=datetime.utcnow() - timedelta(hours=1),
        finished_at=datetime.utcnow() - timedelta(minutes=58),
        duration_ms=120000,
    )
    session.add(run)
    session.commit()

    raw_token = "automation-mcp-token"
    cred = MCPMachineCredential(
        name="cred-auto",
        token_hash=_hash_token(raw_token),
        permission="mcp_read",
        team_scope_json=json.dumps([team.id]),
        status=MCPMachineCredentialStatus.ACTIVE,
        expires_at=datetime.utcnow() + timedelta(days=30),
    )
    session.add(cred)
    session.commit()

    return {
        "team_id": team.id,
        "case_one_id": case_one.id,
        "case_two_id": case_two.id,
        "script_login_id": script_login.id,
        "script_logout_id": script_logout.id,
        "run_id": run.id,
        "run_set_id": run_set.id,
        "token": raw_token,
    }


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_mcp_automation_scripts_lists_with_linked_cases_and_last_run(temp_db):
    with temp_db() as session:
        seeded = _seed(session)

    with TestClient(app) as client:
        resp = client.get(
            f"/api/mcp/teams/{seeded['team_id']}/automation-scripts",
            headers=_bearer(seeded["token"]),
        )
        assert resp.status_code == 200, resp.text
        payload = resp.json()
        assert payload["team_id"] == seeded["team_id"]
        assert payload["page"]["total"] == 2
        items_by_id = {item["id"]: item for item in payload["items"]}
        login = items_by_id[seeded["script_login_id"]]
        assert login["name"] == "test_login.py"
        assert login["script_format"] == "PYTEST"
        assert login["ref_path"] == "tests/test_login.py"
        assert login["tags"] == ["smoke", "auth"]
        # last_run_* removed from script response: run history is owned by
        # Test Run Set (see move-run-history-to-test-run-set).
        assert "last_run_status" not in login
        assert "last_run_url" not in login
        assert login["linked_test_case_numbers"] == ["TC-001"]

        logout = items_by_id[seeded["script_logout_id"]]
        assert "last_run_status" not in logout
        assert logout["linked_test_case_numbers"] == []


def test_mcp_automation_runs_filters(temp_db):
    with temp_db() as session:
        seeded = _seed(session)

    with TestClient(app) as client:
        all_resp = client.get(
            f"/api/mcp/teams/{seeded['team_id']}/test-run-sets/{seeded['run_set_id']}/automation-runs",
            headers=_bearer(seeded["token"]),
        )
        assert all_resp.status_code == 200, all_resp.text
        payload = all_resp.json()
        assert payload["page"]["total"] == 1
        run = payload["items"][0]
        assert run["status"] == "SUCCEEDED"
        assert run["triggered_by"] == "USER"
        assert run["external_run_id"] == "ext-1"
        assert run["tcrt_correlation_id"] == "corr-1"
        assert run["duration_ms"] == 120000
        assert run["test_run_set_id"] == seeded["run_set_id"]

        # status filter
        running_only = client.get(
            f"/api/mcp/teams/{seeded['team_id']}/test-run-sets/{seeded['run_set_id']}/automation-runs",
            headers=_bearer(seeded["token"]),
            params={"status": "RUNNING"},
        )
        assert running_only.status_code == 200
        assert running_only.json()["page"]["total"] == 0

        # unknown set id within the team surfaces 404
        missing = client.get(
            f"/api/mcp/teams/{seeded['team_id']}/test-run-sets/99999/automation-runs",
            headers=_bearer(seeded["token"]),
        )
        assert missing.status_code == 404
        assert missing.json()["detail"]["code"] == "TEST_RUN_SET_NOT_FOUND"


def test_mcp_automation_coverage_returns_summary_and_trend(temp_db):
    with temp_db() as session:
        seeded = _seed(session)

    with TestClient(app) as client:
        resp = client.get(
            f"/api/mcp/teams/{seeded['team_id']}/automation-coverage",
            headers=_bearer(seeded["token"]),
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        summary = data["summary"]
        assert summary["total_test_cases"] == 2
        assert summary["with_primary_link"] == 1
        assert summary["with_any_link"] == 1
        assert summary["uncovered_count"] == 1
        uncovered = data["uncovered_sample"]
        assert len(uncovered) == 1
        assert uncovered[0]["test_case_number"] == "TC-002"
        assert isinstance(data["trend"], list)
        assert len(data["trend"]) == 30


def test_mcp_test_case_detail_includes_linked_automation(temp_db):
    with temp_db() as session:
        seeded = _seed(session)

    with TestClient(app) as client:
        resp = client.get(
            f"/api/mcp/teams/{seeded['team_id']}/test-cases/{seeded['case_one_id']}",
            headers=_bearer(seeded["token"]),
        )
        assert resp.status_code == 200, resp.text
        case = resp.json()["test_case"]
        linked = case.get("linked_automation_scripts", [])
        assert len(linked) == 1
        first = linked[0]
        assert first["script_id"] == seeded["script_login_id"]
        assert first["name"] == "test_login.py"
        assert first["link_type"] == "PRIMARY"
        # last_run_status removed: run history lives in Test Run Set detail
        # (see move-run-history-to-test-run-set).
        assert "last_run_status" not in first


def test_mcp_automation_endpoints_respect_team_scope(temp_db):
    with temp_db() as session:
        seeded = _seed(session)

    with TestClient(app) as client:
        # bogus team id within scope check returns 404
        resp = client.get(
            "/api/mcp/teams/9999/automation-scripts",
            headers=_bearer(seeded["token"]),
        )
        # Either MCP_TEAM_FORBIDDEN (403) or TEAM_NOT_FOUND (404) — both are acceptable
        # contracts since dependency runs before _ensure_team_exists.
        assert resp.status_code in {403, 404}
