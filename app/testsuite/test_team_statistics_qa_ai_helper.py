"""
QA AI Helper 團隊數據統計 API 測試

測試 7 個端點的基本存取權限與回傳結構。
"""

from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.main import app
from app.database import get_db
from app.auth.dependencies import get_current_user
from app.auth.models import UserRole
from app.auth.permission_service import permission_service
from app.testsuite.db_test_helpers import (
    create_managed_test_database,
    dispose_managed_test_database,
    install_main_database_overrides,
)


BASE_URL = "/api/admin/team_statistics/qa-ai-helper"
ENDPOINTS = [
    "overview",
    "adoption",
    "generation",
    "funnel",
    "telemetry",
    "user-engagement",
    "ai-ratio",
]


@pytest.fixture
def helper_stats_db(tmp_path, monkeypatch):
    db_path = tmp_path / "helper_stats_test.db"
    database_bundle = create_managed_test_database(db_path)

    install_main_database_overrides(
        monkeypatch=monkeypatch,
        app=app,
        get_db_dependency=get_db,
        async_engine=database_bundle["async_engine"],
        async_session_factory=database_bundle["async_session_factory"],
    )

    yield database_bundle

    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_current_user, None)
    dispose_managed_test_database(database_bundle)


def _setup_admin(monkeypatch):
    """設定 Admin 身分。"""

    async def _allow_admin(_user_id, _required_role):
        return True

    monkeypatch.setattr(permission_service, "check_user_role", _allow_admin)
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=1,
        username="stats-admin",
        role=UserRole.SUPER_ADMIN,
    )


def _setup_normal_user(monkeypatch):
    """設定一般使用者身分。"""

    async def _deny_admin(_user_id, _required_role):
        return False

    monkeypatch.setattr(permission_service, "check_user_role", _deny_admin)
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=2,
        username="normal-user",
        role=UserRole.USER,
    )


# ===========================================================================
# 權限測試：Admin 可以存取所有端點
# ===========================================================================


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_admin_can_access_all_endpoints(helper_stats_db, monkeypatch, endpoint):
    _setup_admin(monkeypatch)
    client = TestClient(app)
    response = client.get(f"{BASE_URL}/{endpoint}?days=7")
    assert response.status_code == 200, f"{endpoint}: {response.text}"
    payload = response.json()
    assert "date_range" in payload, f"{endpoint}: missing date_range"


# ===========================================================================
# 權限測試：一般使用者不可存取
# ===========================================================================


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_normal_user_forbidden(helper_stats_db, monkeypatch, endpoint):
    _setup_normal_user(monkeypatch)
    client = TestClient(app)
    response = client.get(f"{BASE_URL}/{endpoint}?days=7")
    assert response.status_code == 403, f"{endpoint}: expected 403, got {response.status_code}"


# ===========================================================================
# 回傳結構驗證（空資料庫）
# ===========================================================================


def test_overview_response_structure(helper_stats_db, monkeypatch):
    _setup_admin(monkeypatch)
    client = TestClient(app)
    data = client.get(f"{BASE_URL}/overview?days=7").json()

    assert "kpi" in data
    kpi = data["kpi"]
    assert "total_sessions" in kpi
    assert "completed_sessions" in kpi
    assert "completion_rate" in kpi
    assert "total_tcs_generated" in kpi
    assert "total_tcs_committed" in kpi
    assert "overall_seed_adoption_rate" in kpi
    assert "overall_tc_adoption_rate" in kpi

    assert "team_ranking" in data
    assert isinstance(data["team_ranking"], list)


def test_adoption_response_structure(helper_stats_db, monkeypatch):
    _setup_admin(monkeypatch)
    client = TestClient(app)
    data = client.get(f"{BASE_URL}/adoption?days=7").json()

    assert "overall" in data
    overall = data["overall"]
    assert "seed_adoption_rate" in overall
    assert "tc_adoption_rate" in overall
    assert "user_edit_rate" in overall
    assert "ai_generated_ratio" in overall

    assert "overall_trend" in data
    assert "dates" in data["overall_trend"]


def test_generation_response_structure(helper_stats_db, monkeypatch):
    _setup_admin(monkeypatch)
    client = TestClient(app)
    data = client.get(f"{BASE_URL}/generation?days=7").json()

    assert "overall_trend" in data
    assert "overall_summary" in data
    assert "team_ranking" in data
    assert "user_ranking" in data


def test_funnel_response_structure(helper_stats_db, monkeypatch):
    _setup_admin(monkeypatch)
    client = TestClient(app)
    data = client.get(f"{BASE_URL}/funnel?days=7").json()

    assert "funnel" in data
    assert "status_distribution" in data
    assert "by_team" in data


def test_telemetry_response_structure(helper_stats_db, monkeypatch):
    _setup_admin(monkeypatch)
    client = TestClient(app)
    data = client.get(f"{BASE_URL}/telemetry?days=7").json()

    assert "overall" in data
    overall = data["overall"]
    assert "total_calls" in overall
    assert "total_tokens" in overall
    assert "avg_duration_ms" in overall

    assert "token_trend" in data
    assert "team_ranking" in data


def test_user_engagement_response_structure(helper_stats_db, monkeypatch):
    _setup_admin(monkeypatch)
    client = TestClient(app)
    data = client.get(f"{BASE_URL}/user-engagement?days=7").json()

    assert "team_ranking" in data
    assert "user_ranking" in data
    assert "dau_trend" in data
    assert "dates" in data["dau_trend"]


def test_ai_ratio_response_structure(helper_stats_db, monkeypatch):
    _setup_admin(monkeypatch)
    client = TestClient(app)
    data = client.get(f"{BASE_URL}/ai-ratio?days=7").json()

    assert "overall" in data
    overall = data["overall"]
    assert "total_created" in overall
    assert "ai_committed" in overall
    assert "manual_created" in overall
    assert "ai_ratio" in overall
    assert overall["manual_created"] == overall["total_created"] - overall["ai_committed"]

    assert "overall_trend" in data
    trend = data["overall_trend"]
    assert "dates" in trend
    assert "total_created" in trend
    assert "ai_committed" in trend
    assert "manual_created" in trend
    assert "ai_ratio" in trend

    assert "team_ranking" in data
    assert isinstance(data["team_ranking"], list)

    assert "by_team_trend" in data
    assert isinstance(data["by_team_trend"], list)


# ===========================================================================
# 參數驗證
# ===========================================================================


def test_custom_date_range(helper_stats_db, monkeypatch):
    _setup_admin(monkeypatch)
    client = TestClient(app)
    response = client.get(f"{BASE_URL}/overview?start_date=2026-04-01&end_date=2026-04-07")
    assert response.status_code == 200
    data = response.json()
    assert data["date_range"]["start"] == "2026-04-01"
    assert data["date_range"]["end"] == "2026-04-07"
    assert data["date_range"]["days"] == 7


def test_invalid_date_range_missing_end(helper_stats_db, monkeypatch):
    _setup_admin(monkeypatch)
    client = TestClient(app)
    response = client.get(f"{BASE_URL}/overview?start_date=2026-04-01")
    assert response.status_code == 400


def test_date_range_exceeds_max(helper_stats_db, monkeypatch):
    _setup_admin(monkeypatch)
    client = TestClient(app)
    response = client.get(f"{BASE_URL}/overview?start_date=2026-01-01&end_date=2026-06-01")
    assert response.status_code == 400


def test_team_ids_filter(helper_stats_db, monkeypatch):
    _setup_admin(monkeypatch)
    client = TestClient(app)
    response = client.get(f"{BASE_URL}/overview?days=7&team_ids=1,2,3")
    assert response.status_code == 200


# ===========================================================================
# 快取測試
# ===========================================================================


def test_cache_returns_consistent_results(helper_stats_db, monkeypatch):
    """連續兩次呼叫應回傳相同結果（第二次應命中快取）。"""
    _setup_admin(monkeypatch)
    client = TestClient(app)

    r1 = client.get(f"{BASE_URL}/overview?days=7")
    r2 = client.get(f"{BASE_URL}/overview?days=7")

    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.json() == r2.json()
