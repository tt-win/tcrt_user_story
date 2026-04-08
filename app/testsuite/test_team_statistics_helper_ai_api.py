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


@pytest.fixture
def team_statistics_db(tmp_path, monkeypatch):
    db_path = tmp_path / "team_statistics_retired_helper.db"
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


def test_helper_ai_analytics_returns_gone_for_admin(team_statistics_db, monkeypatch):
    async def _allow_admin(_user_id, _required_role):
        return True

    monkeypatch.setattr(permission_service, "check_user_role", _allow_admin)
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=1,
        username="stats-admin",
        role=UserRole.SUPER_ADMIN,
    )

    client = TestClient(app)
    response = client.get("/api/admin/team_statistics/helper_ai_analytics?days=30")

    assert response.status_code == 410, response.text
    payload = response.json()
    assert payload["detail"]["error"] == "legacy_helper_statistics_retired"
    assert "V3 rollout" in payload["detail"]["message"]


def test_helper_ai_analytics_still_requires_admin(team_statistics_db, monkeypatch):
    async def _deny_admin(_user_id, _required_role):
        return False

    monkeypatch.setattr(permission_service, "check_user_role", _deny_admin)
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=2,
        username="stats-viewer",
        role=UserRole.USER,
    )

    client = TestClient(app)
    response = client.get("/api/admin/team_statistics/helper_ai_analytics?days=30")

    assert response.status_code == 403, response.text
