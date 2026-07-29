from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.api import dashboard as dashboard_api
from app.auth.dependencies import get_current_user
from app.auth.models import UserRole
from app.database import get_db
from app.main import app
from app.models.database_models import (
    AutomationProviderSlot,
    ScheduledService,
    SystemAutomationProvider,
    SystemSetting,
    Team,
    TestCaseLocal,
    TestCaseSet,
    TestRunConfig,
    TestRunItem,
    TestRunItemResultHistory,
    User,
)
from app.models.lark_types import TestResultStatus
from app.models.test_run_config import TestRunStatus
from app.models.team import TeamStatus
from app.services.dashboard_service import DashboardService
from app.services.system_settings_service import AUTOMATION_HUB_ENTRY_ENABLED_KEY
from app.testsuite.db_test_helpers import (
    create_managed_test_database,
    dispose_managed_test_database,
    install_main_database_overrides,
)


class _UnavailableAuditBoundary:
    async def run_read(self, _operation):
        raise RuntimeError("audit storage unavailable")


class _UnavailableMainBoundary:
    async def run_sync_read(self, _operation):
        raise RuntimeError("main storage secret diagnostic")


class _AuditSessionWithSensitiveColumns:
    async def execute(self, _statement):
        return [
            SimpleNamespace(
                id=1,
                timestamp=datetime(2026, 7, 28, 10, 0, 0),
                action_type="UPDATE",
                resource_type="test_run",
                resource_id="private-resource-id",
                team_id=1,
                event_code="test_run.updated",
                outcome="success",
                action_brief="private action brief",
                details="private details",
            )
        ]


class _AuditBoundaryWithSensitiveColumns:
    async def run_read(self, operation):
        return await operation(_AuditSessionWithSensitiveColumns())


class _AuditSessionWithResumeRows:
    def __init__(self, rows):
        self.rows = rows

    async def execute(self, _statement):
        return self.rows


class _AuditBoundaryWithResumeRows:
    def __init__(self, rows):
        self.rows = rows

    async def run_read(self, operation):
        return await operation(_AuditSessionWithResumeRows(self.rows))


@pytest.fixture
def dashboard_db(tmp_path, monkeypatch):
    bundle = create_managed_test_database(tmp_path / "dashboard.db")
    install_main_database_overrides(
        monkeypatch=monkeypatch,
        app=app,
        get_db_dependency=get_db,
        async_engine=bundle["async_engine"],
        async_session_factory=bundle["async_session_factory"],
    )
    app.dependency_overrides[dashboard_api.get_audit_access_boundary] = lambda: _UnavailableAuditBoundary()
    auth_context = {}
    app.dependency_overrides[get_current_user] = lambda: auth_context["user"]

    now = datetime.utcnow()
    with bundle["sync_session_factory"]() as session:
        team = Team(name="Dashboard Team", description="", wiki_token="", test_case_table_id="")
        session.add(team)
        session.flush()
        case_set = TestCaseSet(team_id=team.id, name="Dashboard Cases", description="", is_default=True)
        session.add(case_set)
        session.flush()
        session.add_all(
            [
                TestCaseLocal(
                    team_id=team.id,
                    test_case_set_id=case_set.id,
                    test_case_number="TC-DASH-1",
                    title="Current assigned case",
                ),
                TestCaseLocal(
                    team_id=team.id,
                    test_case_set_id=case_set.id,
                    test_case_number="TC-DASH-2",
                    title="Legacy assigned case",
                ),
                TestCaseLocal(
                    team_id=team.id,
                    test_case_set_id=case_set.id,
                    test_case_number="TC-DASH-3",
                    title="Draft assigned case",
                ),
            ]
        )
        current = User(
            username="dashboard-user",
            email="dashboard@example.com",
            lark_user_id="ou-dashboard",
            full_name="Dashboard User",
            hashed_password="hashed",
            role=UserRole.USER,
            is_active=True,
        )
        viewer = User(
            username="dashboard-viewer",
            email="viewer@example.com",
            hashed_password="hashed",
            role=UserRole.VIEWER,
            is_active=True,
        )
        super_admin = User(
            username="dashboard-super-admin",
            email="super@example.com",
            hashed_password="hashed",
            role=UserRole.SUPER_ADMIN,
            is_active=True,
        )
        session.add_all([current, viewer, super_admin])
        session.flush()
        active_run = TestRunConfig(team_id=team.id, name="Active run", status=TestRunStatus.ACTIVE)
        draft_run = TestRunConfig(team_id=team.id, name="Draft run", status=TestRunStatus.DRAFT)
        session.add_all([active_run, draft_run])
        session.flush()
        direct_item = TestRunItem(
            team_id=team.id,
            config_id=active_run.id,
            test_case_number="TC-DASH-1",
            assignee_user_id=current.id,
            assignee_name=current.full_name,
            test_result=TestResultStatus.FAILED,
            updated_at=now,
        )
        legacy_item = TestRunItem(
            team_id=team.id,
            config_id=active_run.id,
            test_case_number="TC-DASH-2",
            assignee_id=current.lark_user_id,
            assignee_name="Legacy user",
            test_result=TestResultStatus.PASSED,
            updated_at=now - timedelta(minutes=1),
        )
        draft_item = TestRunItem(
            team_id=team.id,
            config_id=draft_run.id,
            test_case_number="TC-DASH-3",
            assignee_user_id=current.id,
            assignee_name=current.full_name,
            updated_at=now - timedelta(minutes=2),
        )
        stale_item = TestRunItem(
            team_id=team.id,
            config_id=active_run.id,
            test_case_number="TC-DASH-3-stale",
            assignee_user_id=viewer.id,
            assignee_id=current.lark_user_id,
            assignee_name="Must not use fallback when FK exists",
        )
        session.add_all([direct_item, legacy_item, draft_item, stale_item])
        session.flush()
        session.add_all(
            [
                TestRunItemResultHistory(
                    team_id=team.id,
                    config_id=active_run.id,
                    item_id=direct_item.id,
                    prev_result=None,
                    new_result=TestResultStatus.FAILED,
                    prev_executed_at=None,
                    new_executed_at=now - timedelta(hours=1),
                    changed_by_id=str(current.id),
                    changed_at=now - timedelta(hours=1),
                    change_source="single",
                ),
                TestRunItemResultHistory(
                    team_id=team.id,
                    config_id=active_run.id,
                    item_id=legacy_item.id,
                    prev_result=None,
                    new_result=TestResultStatus.PASSED,
                    prev_executed_at=None,
                    new_executed_at=now - timedelta(hours=2),
                    changed_by_id=str(current.id),
                    changed_at=now - timedelta(hours=2),
                    change_source="single",
                ),
                TestRunItemResultHistory(
                    team_id=team.id,
                    config_id=active_run.id,
                    item_id=direct_item.id,
                    prev_result=TestResultStatus.FAILED,
                    new_result=TestResultStatus.FAILED,
                    prev_executed_at=now - timedelta(hours=1),
                    new_executed_at=now - timedelta(hours=1),
                    changed_by_id=str(current.id),
                    changed_at=now - timedelta(minutes=30),
                    change_source="comment",
                    change_reason="Must not become an outcome",
                ),
            ]
        )
        session.add_all(
            [
                ScheduledService(
                    service_key="safe-service",
                    display_name="Do not leak this display text",
                    enabled=True,
                    is_running=False,
                    last_run_status="failed",
                    last_error="secret-error-detail",
                    last_run_message="secret-run-message",
                    last_run_finished_at=now,
                ),
                SystemAutomationProvider(
                    provider_slot=AutomationProviderSlot.CI,
                    provider_type="private-provider-type",
                    name="private-provider-name",
                    config_json='{"url":"https://private.example"}',
                    credentials_encrypted="encrypted-secret",
                    is_active=True,
                ),
            ]
        )
        session.commit()
        auth_context["user"] = SimpleNamespace(
            id=current.id,
            username=current.username,
            full_name=current.full_name,
            email=current.email,
            lark_user_id=current.lark_user_id,
            role=UserRole.USER,
        )
        auth_context["viewer"] = SimpleNamespace(
            id=current.id,
            username=current.username,
            full_name=current.full_name,
            email=current.email,
            lark_user_id=current.lark_user_id,
            role=UserRole.VIEWER,
        )
        auth_context["super_admin"] = SimpleNamespace(
            id=super_admin.id,
            username=super_admin.username,
            full_name=super_admin.full_name,
            email=super_admin.email,
            lark_user_id=super_admin.lark_user_id,
            role=UserRole.SUPER_ADMIN,
        )
        auth_context["bundle"] = bundle

    yield auth_context

    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(dashboard_api.get_audit_access_boundary, None)
    app.dependency_overrides.pop(get_db, None)
    dispose_managed_test_database(bundle)


def test_personal_dashboard_uses_fk_before_legacy_fallback_and_is_no_store(dashboard_db):
    with TestClient(app) as client:
        response = client.get("/api/dashboard?role=super_admin&team_id=999")

    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    payload = response.json()
    assert payload["dashboard_type"] == "personal"
    assert payload["current_user"] == {
        "id": dashboard_db["user"].id,
        "display_name": dashboard_db["user"].username,
    }
    assigned = payload["sections"]["assigned"]["items"]
    assigned_by_run = {item["run"]["name"]: item for item in assigned}
    assert set(assigned_by_run) == {"Active run", "Draft run"}
    assert assigned_by_run["Active run"]["item_count"] == 2
    assert assigned_by_run["Draft run"]["item_count"] == 1
    assert set(assigned_by_run["Active run"]) == {
        "team",
        "run",
        "item_count",
        "preview_items",
        "action_mode",
        "run_link",
    }
    assert "&tc=" not in assigned_by_run["Active run"]["run_link"]
    assert len(assigned_by_run["Active run"]["preview_items"]) == 2
    assert set(assigned_by_run["Active run"]["preview_items"][0]) == {
        "test_case",
        "test_result",
        "item_link",
    }
    assert "&tc=" in assigned_by_run["Active run"]["preview_items"][0]["item_link"]
    resume_item = payload["sections"]["resume"]["items"][0]
    assert set(resume_item) == {"kind", "team", "run", "last_activity_at", "link"}
    assert resume_item["kind"] == "test_run"
    assert resume_item["run"]["name"] == "Active run"
    assert "&tc=" not in resume_item["link"]
    assert payload["sections"]["outcomes"]["counts"] == {"Failed": 1, "Passed": 1}
    assert payload["sections"]["audit"]["state"] == "unavailable"
    quick_action_hrefs = {action["href"] for action in payload["quick_actions"]}
    assert "/automation-hub" in quick_action_hrefs
    assert "/user-story-map/{team_id}" in quick_action_hrefs
    assert "dashboard.quickAction.appToken" not in {
        action["key"] for action in payload["quick_actions"]
    }


def test_resume_keeps_latest_active_run_after_result_is_completed(dashboard_db):
    bundle = dashboard_db["bundle"]
    current = dashboard_db["user"]
    now = datetime.utcnow()
    with bundle["sync_session_factory"]() as session:
        item = (
            session.query(TestRunItem)
            .filter(TestRunItem.test_case_number == "TC-DASH-1")
            .one()
        )
        item.test_result = TestResultStatus.PASSED
        item.updated_at = now
        session.add(
            TestRunItemResultHistory(
                team_id=item.team_id,
                config_id=item.config_id,
                item_id=item.id,
                prev_result=TestResultStatus.FAILED,
                new_result=TestResultStatus.PASSED,
                prev_executed_at=now - timedelta(hours=1),
                new_executed_at=now,
                changed_by_id=str(current.id),
                changed_at=now,
                change_source="single",
            )
        )
        session.commit()

    with TestClient(app) as client:
        response = client.get("/api/dashboard")

    assert response.status_code == 200, response.text
    resume = response.json()["sections"]["resume"]["items"]
    assert len(resume) == 1
    assert resume[0]["run"]["name"] == "Active run"
    assert set(resume[0]) == {"kind", "team", "run", "last_activity_at", "link"}
    assert "&tc=" not in resume[0]["link"]


def test_automation_hub_quick_action_respects_existing_entry_toggle(dashboard_db):
    bundle = dashboard_db["bundle"]
    with bundle["sync_session_factory"]() as session:
        team_id = session.query(Team.id).filter(Team.name == "Dashboard Team").scalar()
        session.add(
            SystemSetting(
                key=AUTOMATION_HUB_ENTRY_ENABLED_KEY,
                value="false",
            )
        )
        session.commit()
    app.dependency_overrides[dashboard_api.get_audit_access_boundary] = lambda: (
        _AuditBoundaryWithResumeRows(
            [
                SimpleNamespace(
                    id=1,
                    timestamp=datetime.utcnow(),
                    action_type="UPDATE",
                    resource_type="automation_script",
                    resource_id="script-1",
                    team_id=team_id,
                )
            ]
        )
    )

    with TestClient(app) as client:
        response = client.get("/api/dashboard")

    assert response.status_code == 200, response.text
    assert "/automation-hub" not in {
        action["href"] for action in response.json()["quick_actions"]
    }
    assert "automation_hub" not in {
        item["kind"] for item in response.json()["sections"]["resume"]["items"]
    }


def test_user_story_map_quick_action_resolves_to_existing_team_route(dashboard_db):
    bundle = dashboard_db["bundle"]
    with bundle["sync_session_factory"]() as session:
        team_id = session.query(Team.id).filter(Team.name == "Dashboard Team").scalar()

    with TestClient(app) as client:
        dashboard_response = client.get("/api/dashboard")
        route_template = next(
            action["href"]
            for action in dashboard_response.json()["quick_actions"]
            if action["key"] == "dashboard.quickAction.userStoryMap"
        )
        page_response = client.get(route_template.replace("{team_id}", str(team_id)))

    assert dashboard_response.status_code == 200, dashboard_response.text
    assert route_template == "/user-story-map/{team_id}"
    assert page_response.status_code == 200, page_response.text


def test_structured_lark_assignments_from_ui_appear_in_dashboard(dashboard_db):
    bundle = dashboard_db["bundle"]
    current = dashboard_db["user"]
    with bundle["sync_session_factory"]() as session:
        team = session.query(Team).filter(Team.name == "Dashboard Team").one()
        run = session.query(TestRunConfig).filter(TestRunConfig.name == "Active run").one()
        case_set = session.query(TestCaseSet).filter(TestCaseSet.team_id == team.id).one()
        session.add_all(
            [
                TestCaseLocal(
                    team_id=team.id,
                    test_case_set_id=case_set.id,
                    test_case_number="TC-DASH-UI-ASSIGN",
                    title="Assigned through the Test Run UI",
                ),
                TestCaseLocal(
                    team_id=team.id,
                    test_case_set_id=case_set.id,
                    test_case_number="TC-DASH-UI-BATCH",
                    title="Batch assigned through the Test Run UI",
                ),
            ]
        )
        item = TestRunItem(
            team_id=team.id,
            config_id=run.id,
            test_case_number="TC-DASH-UI-ASSIGN",
        )
        batch_item = TestRunItem(
            team_id=team.id,
            config_id=run.id,
            test_case_number="TC-DASH-UI-BATCH",
        )
        session.add_all([item, batch_item])
        session.commit()
        item_id = item.id
        batch_item_id = batch_item.id
        team_id = team.id
        run_id = run.id

    selected_lark_contact = {
        "id": current.lark_user_id,
        "name": current.full_name,
    }
    selected_lark_email_contact = {
        "name": current.full_name,
        "email": current.email,
    }
    with TestClient(app) as client:
        update = client.put(
            f"/api/teams/{team_id}/test-run-configs/{run_id}/items/{item_id}",
            json={"assignee": selected_lark_contact},
        )
        batch_update = client.post(
            f"/api/teams/{team_id}/test-run-configs/{run_id}/items/batch-update-results",
            json={
                "updates": [
                    {"id": batch_item_id, "assignee": selected_lark_email_contact},
                ]
            },
        )
        dashboard = client.get("/api/dashboard")

    assert update.status_code == 200, update.text
    assert update.json()["assignee_user_id"] == current.id
    assert batch_update.status_code == 200, batch_update.text
    assert batch_update.json()["success"] == 1
    assert dashboard.status_code == 200, dashboard.text
    assigned_by_run = {
        row["run"]["name"]: row
        for row in dashboard.json()["sections"]["assigned"]["items"]
    }
    assert assigned_by_run["Active run"]["item_count"] == 4


def test_assigned_run_count_is_exact_beyond_item_detail_limit(dashboard_db):
    bundle = dashboard_db["bundle"]
    current = dashboard_db["user"]
    with bundle["sync_session_factory"]() as session:
        team = session.query(Team).filter(Team.name == "Dashboard Team").one()
        run = session.query(TestRunConfig).filter(TestRunConfig.name == "Active run").one()
        session.add_all(
            [
                TestRunItem(
                    team_id=team.id,
                    config_id=run.id,
                    test_case_number=f"TC-DASH-COUNT-{index}",
                    assignee_user_id=current.id,
                    assignee_name=current.full_name,
                )
                for index in range(55)
            ]
        )
        session.commit()

    with TestClient(app) as client:
        response = client.get("/api/dashboard")

    assert response.status_code == 200, response.text
    assigned_by_run = {
        item["run"]["name"]: item
        for item in response.json()["sections"]["assigned"]["items"]
    }
    assert assigned_by_run["Active run"]["item_count"] == 57
    assert len(assigned_by_run["Active run"]["preview_items"]) == 5


def test_viewer_gets_assigned_read_only_without_resume(dashboard_db):
    dashboard_db["user"] = dashboard_db["viewer"]
    with TestClient(app) as client:
        response = client.get("/api/dashboard")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["sections"]["resume"]["items"] == []
    assert {item["action_mode"] for item in payload["sections"]["assigned"]["items"]} == {"view"}
    assert "dashboard.quickAction.appToken" not in {
        action["key"] for action in payload["quick_actions"]
    }


def test_queue_keeps_active_and_draft_runs_but_hides_inactive_team(dashboard_db):
    with TestClient(app) as client:
        initial = client.get("/api/dashboard")

    assert initial.status_code == 200, initial.text
    initial_payload = initial.json()
    assert [item["run"]["name"] for item in initial_payload["sections"]["resume"]["items"]] == [
        "Active run"
    ]
    assigned_by_run = {
        item["run"]["name"]: item for item in initial_payload["sections"]["assigned"]["items"]
    }
    assert assigned_by_run["Active run"]["item_count"] == 2
    assert assigned_by_run["Draft run"]["run"]["status"] == "draft"

    bundle = dashboard_db["bundle"]
    with bundle["sync_session_factory"]() as session:
        team = session.query(Team).filter(Team.name == "Dashboard Team").one()
        team.status = TeamStatus.INACTIVE
        session.commit()

    with TestClient(app) as client:
        inactive = client.get("/api/dashboard")

    assert inactive.status_code == 200, inactive.text
    inactive_payload = inactive.json()
    assert inactive_payload["sections"]["teams"]["items"] == []
    assert inactive_payload["sections"]["assigned"]["items"] == []
    assert inactive_payload["sections"]["resume"]["items"] == []


def test_admin_role_receives_personal_dashboard(dashboard_db):
    current = dashboard_db["user"]
    dashboard_db["user"] = SimpleNamespace(
        id=current.id,
        username=current.username,
        full_name=current.full_name,
        email=current.email,
        lark_user_id=current.lark_user_id,
        role=UserRole.ADMIN,
    )

    with TestClient(app) as client:
        response = client.get("/api/dashboard")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["dashboard_type"] == "personal"
    assert {
        "key": "dashboard.quickAction.appToken",
        "href": "#app-token",
        "icon": "fa-key",
    } in payload["quick_actions"]


def test_legacy_fallback_requires_a_unique_local_identity(dashboard_db):
    bundle = dashboard_db["bundle"]
    current = dashboard_db["user"]
    with bundle["sync_session_factory"]() as session:
        session.add(
            User(
                username="duplicate-dashboard-lark",
                email="duplicate-dashboard@example.com",
                lark_user_id=f" {current.lark_user_id} ",
                hashed_password="hashed",
                role=UserRole.VIEWER,
                is_active=True,
            )
        )
        session.commit()

    with TestClient(app) as client:
        response = client.get("/api/dashboard")

    assert response.status_code == 200, response.text
    assigned_by_run = {
        item["run"]["name"]: item
        for item in response.json()["sections"]["assigned"]["items"]
    }
    assert assigned_by_run["Active run"]["item_count"] == 1


def test_legacy_fallback_rejects_conflicting_machine_snapshots(dashboard_db):
    bundle = dashboard_db["bundle"]
    current = dashboard_db["user"]
    with bundle["sync_session_factory"]() as session:
        team = session.query(Team).filter(Team.name == "Dashboard Team").one()
        run = session.query(TestRunConfig).filter(TestRunConfig.name == "Active run").one()
        session.add(
            TestRunItem(
                team_id=team.id,
                config_id=run.id,
                test_case_number="TC-DASH-CONFLICT",
                assignee_id=current.lark_user_id,
                assignee_name="Conflicting legacy snapshot",
                assignee_email="different@example.com",
            )
        )
        session.commit()

    with TestClient(app) as client:
        response = client.get("/api/dashboard")

    assert response.status_code == 200, response.text
    assigned_by_run = {
        item["run"]["name"]: item
        for item in response.json()["sections"]["assigned"]["items"]
    }
    assert assigned_by_run["Active run"]["item_count"] == 2


def test_unknown_legacy_history_value_degrades_only_history_sections(dashboard_db):
    bundle = dashboard_db["bundle"]
    current = dashboard_db["user"]
    with bundle["sync_session_factory"]() as session:
        direct_item = (
            session.query(TestRunItem)
            .filter(TestRunItem.test_case_number == "TC-DASH-1")
            .one()
        )
        session.execute(
            text(
                "INSERT INTO test_run_item_result_history "
                "(team_id, config_id, item_id, prev_result, new_result, changed_by_id, changed_at) "
                "VALUES (:team_id, :config_id, :item_id, NULL, 'LegacyUnknown', :changed_by_id, CURRENT_TIMESTAMP)"
            ),
            {
                "team_id": direct_item.team_id,
                "config_id": direct_item.config_id,
                "item_id": direct_item.id,
                "changed_by_id": str(current.id),
            },
        )
        session.commit()

    with TestClient(app) as client:
        response = client.get("/api/dashboard")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["sections"]["assigned"]["state"] == "ready"
    assert payload["sections"]["activity"]["state"] == "partial"
    assert payload["sections"]["outcomes"]["state"] == "partial"
    assert payload["sections"]["resume"]["state"] == "partial"
    assert payload["sections"]["outcomes"]["counts"] == {"Passed": 1}
    assert payload["sections"]["resume"]["items"][0]["run"]["name"] == "Active run"
    assert set(payload["sections"]["resume"]["items"][0]) == {
        "kind",
        "team",
        "run",
        "last_activity_at",
        "link",
    }
    assert "LegacyUnknown" not in response.text


def test_dashboard_main_failure_is_generic_and_does_not_leak_storage_exception(dashboard_db):
    app.dependency_overrides[dashboard_api.get_main_access_boundary] = lambda: _UnavailableMainBoundary()
    try:
        with TestClient(app) as client:
            response = client.get("/api/dashboard")
    finally:
        app.dependency_overrides.pop(dashboard_api.get_main_access_boundary, None)

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "DASHBOARD_UNAVAILABLE"
    assert "secret diagnostic" not in response.text


@pytest.mark.asyncio
async def test_audit_fallback_serializes_only_allowlisted_action_resource_fields():
    service = DashboardService(
        main_boundary=_UnavailableMainBoundary(),
        audit_boundary=_AuditBoundaryWithSensitiveColumns(),
    )

    payload = await service._build_audit_fallback(user_id=1, visible_team_ids=[1])

    assert payload == {
        "state": "ready",
        "items": [
            {
                "timestamp": datetime(2026, 7, 28, 10, 0, 0),
                "action": "UPDATE",
                "resource": "test_run",
            }
        ],
        "resume_items": [],
    }


def test_resume_merges_safe_cross_feature_audit_work_and_honors_delete_tombstones(
    dashboard_db,
):
    bundle = dashboard_db["bundle"]
    now = datetime.utcnow() + timedelta(minutes=10)
    with bundle["sync_session_factory"]() as session:
        team = session.query(Team).filter(Team.name == "Dashboard Team").one()
        team_id = team.id

    rows = [
        SimpleNamespace(
            id=12,
            timestamp=now + timedelta(minutes=3),
            action_type="READ",
            resource_type="automation_script",
            resource_id="script-read",
            team_id=team_id,
        ),
        SimpleNamespace(
            id=11,
            timestamp=now + timedelta(minutes=2),
            action_type="READ",
            resource_type="user_story_map",
            resource_id="42",
            team_id=team_id,
        ),
        SimpleNamespace(
            id=10,
            timestamp=now + timedelta(minutes=1),
            action_type="READ",
            resource_type="test_case",
            resource_id="TC-DASH-1",
            team_id=team_id,
        ),
        SimpleNamespace(
            id=9,
            timestamp=now,
            action_type="UPDATE",
            resource_type="automation_script",
            resource_id="script-9",
            team_id=team_id,
        ),
        SimpleNamespace(
            id=8,
            timestamp=now - timedelta(minutes=1),
            action_type="UPDATE",
            resource_type="user_story_map",
            resource_id="42:node-abc",
            team_id=team_id,
        ),
        SimpleNamespace(
            id=7,
            timestamp=now - timedelta(minutes=2),
            action_type="UPDATE",
            resource_type="test_case",
            resource_id="TC-DASH-1",
            team_id=team_id,
        ),
        SimpleNamespace(
            id=6,
            timestamp=now - timedelta(minutes=3),
            action_type="DELETE",
            resource_type="test_case",
            resource_id="TC-DELETED",
            team_id=team_id,
        ),
        SimpleNamespace(
            id=5,
            timestamp=now - timedelta(minutes=4),
            action_type="UPDATE",
            resource_type="test_case",
            resource_id="TC-DELETED",
            team_id=team_id,
        ),
        SimpleNamespace(
            id=4,
            timestamp=now - timedelta(minutes=5),
            action_type="UPDATE",
            resource_type="test_case",
            resource_id="https://evil.example/redirect",
            team_id=team_id,
        ),
        SimpleNamespace(
            id=3,
            timestamp=now - timedelta(minutes=6),
            action_type="UPDATE",
            resource_type="test_case",
            resource_id="batch_4_items",
            team_id=team_id,
        ),
        SimpleNamespace(
            id=2,
            timestamp=now - timedelta(minutes=7),
            action_type="DELETE",
            resource_type="user_story_map",
            resource_id="43",
            team_id=team_id,
        ),
        SimpleNamespace(
            id=1,
            timestamp=now - timedelta(minutes=8),
            action_type="UPDATE",
            resource_type="user_story_map",
            resource_id="43:node-stale",
            team_id=team_id,
        ),
    ]
    app.dependency_overrides[dashboard_api.get_audit_access_boundary] = lambda: (
        _AuditBoundaryWithResumeRows(rows)
    )

    with TestClient(app) as client:
        response = client.get("/api/dashboard")

    assert response.status_code == 200, response.text
    payload = response.json()
    resume = payload["sections"]["resume"]
    assert resume["state"] == "ready"
    assert [item["kind"] for item in resume["items"][:5]] == [
        "automation_hub",
        "user_story_map",
        "test_case",
        "test_case",
        "test_run",
    ]
    automation_item = next(item for item in resume["items"] if item["kind"] == "automation_hub")
    map_items = [item for item in resume["items"] if item["kind"] == "user_story_map"]
    test_case_items = [item for item in resume["items"] if item["kind"] == "test_case"]
    assert automation_item["link"] == f"/automation-hub?team_id={team_id}"
    assert [item["link"] for item in map_items] == [f"/user-story-map/{team_id}/42"]
    assert test_case_items[0]["link"] == (
        f"/test-case-management?team_id={team_id}&tc=TC-DASH-1&mode=edit"
    )
    assert test_case_items[1]["link"] == f"/test-case-management?team_id={team_id}"
    assert test_case_items[1]["resource"] == {"id": ""}
    assert all(
        item.get("resource", {}).get("id") != "TC-DELETED"
        for item in resume["items"]
    )
    assert payload["sections"]["audit"]["items"][0] == {
        "timestamp": (now + timedelta(minutes=3)).isoformat(),
        "action": "READ",
        "resource": "automation_script",
    }
    assert "script-9" not in payload["sections"]["audit"]["items"][0].values()
    assert "evil.example" not in response.text


def test_system_dashboard_uses_safe_allowlisted_projection(dashboard_db):
    dashboard_db["user"] = dashboard_db["super_admin"]
    with TestClient(app) as client:
        response = client.get("/api/dashboard")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["dashboard_type"] == "system_administration"
    assert payload["sections"]["providers"] == {
        "state": "ready",
        "ci_configured": True,
        "result_configured": False,
    }
    assert {
        "key": "dashboard.quickAction.appToken",
        "href": "#app-token",
        "icon": "fa-key",
    } in payload["quick_actions"]
    serialized = response.text
    assert "secret-error-detail" not in serialized
    assert "secret-run-message" not in serialized
    assert "private-provider-name" not in serialized
    assert "private-provider-type" not in serialized
    assert "private.example" not in serialized
    assert "encrypted-secret" not in serialized


def test_system_dashboard_normalizes_scheduler_persistence_statuses(dashboard_db):
    completed_at = datetime(2026, 7, 29, 2, 5, 39)
    interrupted_at = datetime(2026, 7, 29, 3, 0, 40)
    with dashboard_db["bundle"]["sync_session_factory"]() as session:
        completed = (
            session.query(ScheduledService)
            .filter(ScheduledService.service_key == "safe-service")
            .one()
        )
        completed.last_run_status = "completed"
        completed.last_run_finished_at = completed_at
        session.add(
            ScheduledService(
                service_key="interrupted-service",
                display_name="Do not leak interrupted display text",
                enabled=True,
                is_running=False,
                last_run_status="interrupted",
                last_error="do-not-leak-interrupted-error",
                last_run_finished_at=interrupted_at,
            )
        )
        session.commit()

    dashboard_db["user"] = dashboard_db["super_admin"]
    with TestClient(app) as client:
        response = client.get("/api/dashboard")

    assert response.status_code == 200, response.text
    payload = response.json()
    services = {
        item["service_key"]: item
        for item in payload["sections"]["scheduled_services"]["items"]
    }
    assert services["safe-service"]["outcome"] == "success"
    assert services["safe-service"]["last_run_at"] == completed_at.isoformat()
    assert services["interrupted-service"]["outcome"] == "error"
    assert payload["sections"]["attention"] == {
        "state": "ready",
        "count": 1,
        "latest_at": interrupted_at.isoformat(),
    }
    assert "do-not-leak-interrupted-error" not in response.text
    assert "Do not leak interrupted display text" not in response.text
