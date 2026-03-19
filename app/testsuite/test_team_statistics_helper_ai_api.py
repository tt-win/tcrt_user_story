from pathlib import Path
import sys
import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.main import app
from app.database import get_db
from app.auth.dependencies import get_current_user
from app.auth.models import UserRole
from app.api.team_statistics import _estimate_helper_ai_cost
from app.models.database_models import (
    AITestCaseHelperSession,
    AITestCaseHelperStageMetric,
    Team,
    TestCaseSet,
    User,
)
from app.testsuite.db_test_helpers import (
    create_managed_test_database,
    dispose_managed_test_database,
    install_main_database_overrides,
)


@pytest.fixture
def helper_stats_db(tmp_path, monkeypatch):
    db_path = tmp_path / "helper_team_statistics.db"
    database_bundle = create_managed_test_database(db_path)
    TestingSessionLocal = database_bundle["sync_session_factory"]
    AsyncTestingSessionLocal = database_bundle["async_session_factory"]

    now = datetime.utcnow()
    with TestingSessionLocal() as session:
        team_a = Team(
            name="Helper Team A",
            description="",
            wiki_token="wiki-helper-a",
            test_case_table_id="tbl-helper-a",
        )
        team_b = Team(
            name="Helper Team B",
            description="",
            wiki_token="wiki-helper-b",
            test_case_table_id="tbl-helper-b",
        )
        session.add_all([team_a, team_b])
        session.commit()

        admin_user = User(
            username="helper-stats-admin",
            email="helper-stats-admin@example.com",
            hashed_password="hashed-password",
            role=UserRole.SUPER_ADMIN,
            is_active=True,
            is_verified=True,
        )
        viewer_user = User(
            username="helper-stats-viewer",
            email="helper-stats-viewer@example.com",
            hashed_password="hashed-password",
            role=UserRole.USER,
            is_active=True,
            is_verified=True,
        )
        session.add_all([admin_user, viewer_user])
        session.commit()

        set_a = TestCaseSet(
            team_id=team_a.id,
            name=f"Helper Stats Set A-{team_a.id}",
            description="",
            is_default=True,
        )
        set_b = TestCaseSet(
            team_id=team_b.id,
            name=f"Helper Stats Set B-{team_b.id}",
            description="",
            is_default=True,
        )
        session.add_all([set_a, set_b])
        session.commit()

        session_a = AITestCaseHelperSession(
            team_id=team_a.id,
            created_by_user_id=admin_user.id,
            target_test_case_set_id=set_a.id,
            ticket_key="TCG-10001",
            review_locale="zh-TW",
            output_locale="zh-TW",
            initial_middle="010",
            current_phase="testcase",
            phase_status="waiting_confirm",
            status="active",
            created_at=now - timedelta(days=2),
            updated_at=now - timedelta(hours=6),
        )
        session_b = AITestCaseHelperSession(
            team_id=team_b.id,
            created_by_user_id=admin_user.id,
            target_test_case_set_id=set_b.id,
            ticket_key="TCG-20002",
            review_locale="zh-TW",
            output_locale="zh-TW",
            initial_middle="010",
            current_phase="analysis",
            phase_status="failed",
            status="failed",
            created_at=now - timedelta(days=3),
            updated_at=now - timedelta(hours=12),
        )
        session.add_all([session_a, session_b])
        session.commit()

        metrics = [
            AITestCaseHelperStageMetric(
                session_id=session_a.id,
                team_id=team_a.id,
                user_id=admin_user.id,
                ticket_key="TCG-10001",
                phase="analysis",
                status="success",
                started_at=now - timedelta(hours=10),
                ended_at=now - timedelta(hours=10, seconds=-4),
                duration_ms=4000,
                input_tokens=100000,
                output_tokens=50000,
                cache_read_tokens=10000,
                cache_write_tokens=0,
                input_audio_tokens=0,
                input_audio_cache_tokens=0,
                pretestcase_count=6,
                testcase_count=0,
                model_name="analysis-model",
                usage_json='{"prompt_tokens":100000,"completion_tokens":50000}',
                created_at=now - timedelta(hours=10),
            ),
            AITestCaseHelperStageMetric(
                session_id=session_a.id,
                team_id=team_a.id,
                user_id=admin_user.id,
                ticket_key="TCG-10001",
                phase="testcase",
                status="success",
                started_at=now - timedelta(hours=8),
                ended_at=now - timedelta(hours=8, seconds=-9),
                duration_ms=9000,
                input_tokens=250000,
                output_tokens=300000,
                cache_read_tokens=50000,
                cache_write_tokens=20000,
                input_audio_tokens=0,
                input_audio_cache_tokens=0,
                pretestcase_count=0,
                testcase_count=8,
                model_name="testcase-model",
                usage_json='{"prompt_tokens":250000,"completion_tokens":300000}',
                created_at=now - timedelta(hours=8),
            ),
            AITestCaseHelperStageMetric(
                session_id=session_b.id,
                team_id=team_b.id,
                user_id=admin_user.id,
                ticket_key="TCG-20002",
                phase="analysis",
                status="failed",
                started_at=now - timedelta(hours=7),
                ended_at=now - timedelta(hours=7, seconds=-3),
                duration_ms=3000,
                input_tokens=50000,
                output_tokens=10000,
                cache_read_tokens=0,
                cache_write_tokens=0,
                input_audio_tokens=0,
                input_audio_cache_tokens=0,
                pretestcase_count=0,
                testcase_count=0,
                model_name="analysis-model",
                usage_json='{"prompt_tokens":50000,"completion_tokens":10000}',
                error_message="analysis failed",
                created_at=now - timedelta(hours=7),
            ),
        ]
        session.add_all(metrics)
        session.commit()

        team_a_id = team_a.id
        team_b_id = team_b.id
        admin_user_id = admin_user.id
        viewer_user_id = viewer_user.id

    install_main_database_overrides(
        monkeypatch=monkeypatch,
        app=app,
        get_db_dependency=get_db,
        async_engine=database_bundle["async_engine"],
        async_session_factory=AsyncTestingSessionLocal,
    )
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=admin_user_id,
        username="helper-stats-admin",
        role=UserRole.SUPER_ADMIN,
    )

    yield {
        "db_path": str(db_path),
        "team_a_id": team_a_id,
        "team_b_id": team_b_id,
        "admin_user_id": admin_user_id,
        "viewer_user_id": viewer_user_id,
    }

    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_current_user, None)
    dispose_managed_test_database(database_bundle)


def test_helper_ai_analytics_returns_progress_stage_metrics_and_cost(helper_stats_db):
    client = TestClient(app)
    resp = client.get("/api/admin/team_statistics/helper_ai_analytics?days=30")
    assert resp.status_code == 200, resp.text
    payload = resp.json()

    assert len(payload["progress_records"]) == 2
    assert payload["progress_summary"]["total_sessions"] == 2
    assert payload["token_usage"]["input_tokens"] == 400000
    assert payload["token_usage"]["output_tokens"] == 360000
    assert payload["token_usage"]["cache_read_tokens"] == 60000
    assert payload["token_usage"]["cache_write_tokens"] == 20000

    team_usage = payload["team_usage"]
    assert len(team_usage) == 2
    team_a_usage = next(
        item for item in team_usage if item["team_id"] == helper_stats_db["team_a_id"]
    )
    team_b_usage = next(
        item for item in team_usage if item["team_id"] == helper_stats_db["team_b_id"]
    )
    assert team_a_usage["session_count"] == 1
    assert team_a_usage["distinct_users"] == 1
    assert team_a_usage["distinct_tickets"] == 1
    assert team_a_usage["active_sessions"] == 1
    assert team_a_usage["completed_sessions"] == 0
    assert team_a_usage["failed_sessions"] == 0
    assert team_a_usage["telemetry_runs"] == 2
    assert team_a_usage["total_tokens"] == 780000
    assert team_a_usage["estimated_cost_usd"] == pytest.approx(7.7195, abs=1e-6)
    assert team_b_usage["failed_sessions"] == 1
    assert team_b_usage["telemetry_runs"] == 1
    assert team_b_usage["total_tokens"] == 60000
    assert team_b_usage["estimated_cost_usd"] == pytest.approx(0.22, abs=1e-6)

    analysis_metric = next(item for item in payload["stage_metrics"] if item["phase"] == "analysis")
    assert analysis_metric["total_runs"] == 2
    assert analysis_metric["success_runs"] == 1
    assert analysis_metric["failed_runs"] == 1
    assert analysis_metric["pretestcase_count_total"] == 6
    assert analysis_metric["avg_duration_ms"] == 3500
    assert analysis_metric["p95_duration_ms"] == 4000

    testcase_metric = next(item for item in payload["stage_metrics"] if item["phase"] == "testcase")
    assert testcase_metric["total_runs"] == 1
    assert testcase_metric["testcase_count_total"] == 8

    total_cost = payload["cost_estimate"]["total_estimated_cost_usd"]
    assert total_cost == pytest.approx(8.0995, abs=1e-6)
    assert payload["cost_estimate"]["pricing_profile_version"] == "google-vertex-baseline-v1"

    coverage = payload["data_coverage"]
    assert coverage["session_count"] == 2
    assert coverage["telemetry_session_count"] == 2
    assert coverage["is_partial"] is False


def test_helper_ai_analytics_supports_team_filter(helper_stats_db):
    team_a_id = helper_stats_db["team_a_id"]
    client = TestClient(app)
    resp = client.get(
        f"/api/admin/team_statistics/helper_ai_analytics?days=30&team_ids={team_a_id}"
    )
    assert resp.status_code == 200, resp.text
    payload = resp.json()

    assert payload["applied_filters"]["team_ids"] == [team_a_id]
    assert len(payload["progress_records"]) == 1
    assert all(item["team_id"] == team_a_id for item in payload["progress_records"])
    assert len(payload["team_usage"]) == 1
    assert payload["team_usage"][0]["team_id"] == team_a_id
    assert payload["team_usage"][0]["session_count"] == 1
    assert payload["team_usage"][0]["total_tokens"] == 780000
    assert payload["team_usage"][0]["estimated_cost_usd"] == pytest.approx(7.7195, abs=1e-6)
    assert payload["token_usage"]["input_tokens"] == 350000
    assert payload["token_usage"]["output_tokens"] == 350000
    assert payload["cost_estimate"]["total_estimated_cost_usd"] == pytest.approx(7.7195, abs=1e-6)


def test_helper_ai_analytics_reuses_date_range_guard(helper_stats_db):
    client = TestClient(app)
    resp = client.get(
        "/api/admin/team_statistics/helper_ai_analytics?start_date=2025-01-01&end_date=2025-05-01"
    )
    assert resp.status_code == 400
    body = resp.json()
    assert "日期區間不可超過" in body["detail"]["error"]


def test_helper_ai_analytics_gracefully_handles_missing_telemetry_table(helper_stats_db):
    db_path = helper_stats_db["db_path"]
    temp_engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False, "timeout": 30},
        pool_pre_ping=True,
    )
    with temp_engine.begin() as conn:
        conn.exec_driver_sql("DROP TABLE IF EXISTS ai_tc_helper_stage_metrics")
    temp_engine.dispose()

    client = TestClient(app)
    resp = client.get("/api/admin/team_statistics/helper_ai_analytics?days=30")
    assert resp.status_code == 200, resp.text
    payload = resp.json()

    assert len(payload["progress_records"]) == 2
    assert len(payload["team_usage"]) == 2
    assert all(item["total_tokens"] == 0 for item in payload["team_usage"])
    assert payload["stage_metrics"] == []
    assert payload["token_usage"]["total_tokens"] == 0
    assert payload["data_coverage"]["telemetry_available"] is False
    assert payload["data_coverage"]["telemetry_record_count"] == 0
    assert "no such table" in str(payload["data_coverage"]["telemetry_error"]).lower()


def test_helper_ai_analytics_requires_admin_role(helper_stats_db):
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=helper_stats_db["viewer_user_id"],
        username="helper-stats-viewer",
        role=UserRole.USER,
    )
    client = TestClient(app)
    resp = client.get("/api/admin/team_statistics/helper_ai_analytics?days=30")
    assert resp.status_code == 403

    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=helper_stats_db["admin_user_id"],
        username="helper-stats-admin",
        role=UserRole.SUPER_ADMIN,
    )


def test_estimate_helper_ai_cost_uses_200k_tier_threshold():
    result_at_threshold = _estimate_helper_ai_cost(
        {
            "input_tokens": 200000,
            "output_tokens": 200000,
            "cache_read_tokens": 200000,
            "cache_write_tokens": 200000,
            "input_audio_tokens": 200000,
            "input_audio_cache_tokens": 200000,
        }
    )
    breakdown_threshold = result_at_threshold["breakdown"]
    assert breakdown_threshold["input"]["rate_per_1m_usd"] == 2.0
    assert breakdown_threshold["output"]["rate_per_1m_usd"] == 12.0
    assert breakdown_threshold["cache_read"]["rate_per_1m_usd"] == 0.2
    assert breakdown_threshold["cache_write"]["rate_per_1m_usd"] == 0.375

    result_over_threshold = _estimate_helper_ai_cost(
        {
            "input_tokens": 200001,
            "output_tokens": 200001,
            "cache_read_tokens": 200001,
            "cache_write_tokens": 1,
            "input_audio_tokens": 200001,
            "input_audio_cache_tokens": 200001,
        }
    )
    breakdown_over = result_over_threshold["breakdown"]
    assert breakdown_over["input"]["rate_per_1m_usd"] == 4.0
    assert breakdown_over["output"]["rate_per_1m_usd"] == 18.0
    assert breakdown_over["cache_read"]["rate_per_1m_usd"] == 0.4
    assert breakdown_over["input_audio"]["rate_per_1m_usd"] == 4.0
    assert breakdown_over["input_audio_cache"]["rate_per_1m_usd"] == 0.4
    assert breakdown_over["cache_write"]["rate_per_1m_usd"] == 0.375
