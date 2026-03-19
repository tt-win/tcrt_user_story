from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.main import app
from app.audit.database import AuditLogTable
from app.audit.models import ActionType, AuditSeverity, ResourceType
from app.auth.dependencies import get_current_user
from app.auth.models import UserRole
from app.database import get_db
from app.models.database_models import (
    LarkDepartment,
    LarkUser,
    Team,
    TestCaseLocal,
    TestCaseSet,
    TestRunConfig,
    TestRunItem,
    TestRunItemResultHistory,
    User,
)
from app.models.lark_types import TestResultStatus
from app.testsuite.db_test_helpers import (
    create_managed_test_database,
    dispose_managed_test_database,
    install_audit_database_overrides,
    install_main_database_overrides,
)


@pytest.fixture
def reporting_stats_db(tmp_path, monkeypatch):
    main_bundle = create_managed_test_database(tmp_path / "reporting_stats_main.db")
    audit_bundle = create_managed_test_database(
        tmp_path / "reporting_stats_audit.db",
        target_name="audit",
    )

    now = datetime.utcnow()

    with main_bundle["sync_session_factory"]() as session:
        team = Team(
            name="Reporting Team",
            description="",
            wiki_token="wiki-reporting",
            test_case_table_id="tbl-reporting",
        )
        session.add(team)
        session.commit()

        admin_user = User(
            username="reporting-admin",
            email="reporting-admin@example.com",
            hashed_password="hashed-password",
            role=UserRole.SUPER_ADMIN,
            is_active=True,
            is_verified=True,
        )
        session.add(admin_user)
        session.commit()

        test_case_set = TestCaseSet(
            team_id=team.id,
            name=f"Reporting Set {team.id}",
            description="",
            is_default=True,
        )
        session.add(test_case_set)
        session.commit()

        session.add_all(
            [
                TestCaseLocal(
                    team_id=team.id,
                    test_case_set_id=test_case_set.id,
                    test_case_number="TC-1001",
                    title="Reporting Case 1",
                    created_at=now - timedelta(days=2),
                    updated_at=now - timedelta(days=1),
                ),
                TestCaseLocal(
                    team_id=team.id,
                    test_case_set_id=test_case_set.id,
                    test_case_number="TC-1002",
                    title="Reporting Case 2",
                    created_at=now - timedelta(days=1),
                    updated_at=now - timedelta(days=1),
                ),
            ]
        )
        session.commit()

        run_config = TestRunConfig(
            team_id=team.id,
            name="Reporting Regression",
            created_at=now - timedelta(days=3),
            updated_at=now - timedelta(days=1),
        )
        session.add(run_config)
        session.commit()

        session.add_all(
            [
                TestRunItem(
                    team_id=team.id,
                    config_id=run_config.id,
                    test_case_number="TC-1001",
                    created_at=now - timedelta(days=2),
                    updated_at=now - timedelta(days=2),
                ),
                TestRunItem(
                    team_id=team.id,
                    config_id=run_config.id,
                    test_case_number="TC-1002",
                    created_at=now - timedelta(days=1),
                    updated_at=now - timedelta(days=1),
                ),
            ]
        )
        session.commit()

        item_rows = (
            session.query(TestRunItem)
            .order_by(TestRunItem.created_at.asc(), TestRunItem.id.asc())
            .all()
        )
        session.add_all(
            [
                TestRunItemResultHistory(
                    team_id=team.id,
                    config_id=run_config.id,
                    item_id=item_rows[0].id,
                    new_result=TestResultStatus.PASSED,
                    changed_at=now - timedelta(days=2),
                    change_source="api",
                ),
                TestRunItemResultHistory(
                    team_id=team.id,
                    config_id=run_config.id,
                    item_id=item_rows[1].id,
                    new_result=TestResultStatus.FAILED,
                    changed_at=now - timedelta(days=1),
                    change_source="api",
                ),
            ]
        )

        session.add(
            LarkDepartment(
                department_id="od-reporting",
                path="0/Engineering/QA",
                direct_user_count=1,
                total_user_count=1,
                status="active",
            )
        )
        session.add(
            LarkUser(
                user_id="ou-reporting-admin",
                name="Reporting Admin",
                primary_department_id="od-reporting",
                department_ids_json=json.dumps(["od-reporting"]),
                is_activated=True,
                is_exited=False,
            )
        )
        session.commit()

        team_id = team.id
        admin_user_id = admin_user.id

    with audit_bundle["sync_session_factory"]() as session:
        session.add_all(
            [
                AuditLogTable(
                    timestamp=now - timedelta(hours=12),
                    user_id=admin_user_id,
                    username="reporting-admin",
                    role="SUPER_ADMIN",
                    action_type=ActionType.CREATE,
                    resource_type=ResourceType.TEST_CASE,
                    resource_id="TC-1001",
                    team_id=team_id,
                    details=json.dumps({"count": 1}),
                    action_brief="建立測試案例",
                    severity=AuditSeverity.INFO,
                ),
                AuditLogTable(
                    timestamp=now - timedelta(hours=6),
                    user_id=admin_user_id,
                    username="reporting-admin",
                    role="SUPER_ADMIN",
                    action_type=ActionType.DELETE,
                    resource_type=ResourceType.USER_STORY_MAP,
                    resource_id="usm-42",
                    team_id=team_id,
                    details=json.dumps({"count": 1}),
                    action_brief="刪除使用者故事地圖",
                    severity=AuditSeverity.CRITICAL,
                ),
            ]
        )
        session.commit()

    install_main_database_overrides(
        monkeypatch=monkeypatch,
        app=app,
        get_db_dependency=get_db,
        async_engine=main_bundle["async_engine"],
        async_session_factory=main_bundle["async_session_factory"],
    )
    install_audit_database_overrides(
        monkeypatch=monkeypatch,
        async_session_factory=audit_bundle["async_session_factory"],
    )
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=admin_user_id,
        username="reporting-admin",
        role=UserRole.SUPER_ADMIN,
    )

    yield {
        "team_id": team_id,
        "admin_user_id": admin_user_id,
    }

    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_current_user, None)
    dispose_managed_test_database(audit_bundle)
    dispose_managed_test_database(main_bundle)


def test_admin_daily_statistics_endpoints(reporting_stats_db):
    client = TestClient(app)

    run_resp = client.get("/api/admin/stats/test_run_actions_daily?days=30")
    assert run_resp.status_code == 200, run_resp.text
    run_payload = run_resp.json()
    assert sum(run_payload["counts"]) == 2
    assert len(run_payload["dates"]) == 2

    case_resp = client.get("/api/admin/stats/test_cases_created_daily?days=30")
    assert case_resp.status_code == 200, case_resp.text
    case_payload = case_resp.json()
    assert sum(case_payload["counts"]) == 2
    assert len(case_payload["dates"]) == 2


def test_team_statistics_overview_case_trends_and_run_metrics(reporting_stats_db):
    client = TestClient(app)

    overview_resp = client.get("/api/admin/team_statistics/overview?days=30")
    assert overview_resp.status_code == 200, overview_resp.text
    overview_payload = overview_resp.json()
    assert overview_payload["team_count"] == 1
    assert overview_payload["user_count"] == 1
    assert overview_payload["test_case_total"] == 2
    assert overview_payload["test_run_total"] == 1
    assert len(overview_payload["recent_activity"]) == 2

    trends_resp = client.get("/api/admin/team_statistics/test_case_trends?days=30")
    assert trends_resp.status_code == 200, trends_resp.text
    trends_payload = trends_resp.json()
    assert trends_payload["overall"]["total_created"] == 2
    assert trends_payload["overall"]["total_updated"] == 1
    assert trends_payload["per_team_daily"][0]["team_id"] == reporting_stats_db["team_id"]

    metrics_resp = client.get("/api/admin/team_statistics/test_run_metrics?days=30")
    assert metrics_resp.status_code == 200, metrics_resp.text
    metrics_payload = metrics_resp.json()
    assert metrics_payload["by_status"]["PASSED"] == 1
    assert metrics_payload["by_status"]["FAILED"] == 1
    assert metrics_payload["by_team"][0]["team_id"] == reporting_stats_db["team_id"]
    assert metrics_payload["by_team"][0]["count"] == 2
    assert metrics_payload["per_team_pass_rate"][0]["overall_pass_rate"] == 50.0


def test_team_statistics_audit_analysis_and_department_stats(reporting_stats_db):
    client = TestClient(app)

    audit_resp = client.get("/api/admin/team_statistics/audit_analysis?days=30")
    assert audit_resp.status_code == 200, audit_resp.text
    audit_payload = audit_resp.json()
    assert audit_payload["by_resource_type"]["TEST_CASE"] == 1
    assert audit_payload["by_resource_type"]["USER_STORY_MAP"] == 1
    assert audit_payload["by_severity"]["CRITICAL"] == 1
    assert audit_payload["critical_actions"][0]["resource_type"] == "USER_STORY_MAP"

    department_resp = client.get("/api/admin/team_statistics/department_stats?days=30")
    assert department_resp.status_code == 200, department_resp.text
    department_payload = department_resp.json()
    assert department_payload["user_distribution"]["SUPER_ADMIN"] == 1
    assert department_payload["department_list"][0]["dept_id"] == "od-reporting"
    assert department_payload["by_department_users"][0]["username"] == "reporting-admin"
    assert department_payload["by_department_users"][0]["action_count"] == 2
