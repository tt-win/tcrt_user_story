# ruff: noqa: E402
"""HTTP-level regression test for `POST /api/teams/{team_id}/automation-scripts/sync`.

Entering the Automation Hub before any storage provider is configured makes the
UI auto-fire a silent sync. The service raises ``ProviderNotConfiguredError``
(a ``ProviderRegistryError`` / ``ValueError`` — NOT an
``AutomationScriptServiceError``), so it slipped past the endpoint's existing
``except`` clauses and bubbled up as a 500 + traceback.

This pins the contract: an unconfigured storage slot is a precondition gap →
400 ``PROVIDER_NOT_CONFIGURED``, never a 500.
"""
from __future__ import annotations

from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.main import app
from app.auth.dependencies import get_current_user
from app.auth.models import UserRole
from app.database import get_db
from app.models.database_models import Team
from app.testsuite.db_test_helpers import (
    create_managed_test_database,
    dispose_managed_test_database,
    install_main_database_overrides,
)


@pytest.fixture
def sync_client(tmp_path, monkeypatch):
    bundle = create_managed_test_database(tmp_path / "automation_script_sync.db")

    import app.main as app_main
    import app.models.user_story_map_db as usm_db_module

    install_main_database_overrides(
        monkeypatch=monkeypatch,
        app=app,
        get_db_dependency=get_db,
        async_engine=bundle["async_engine"],
        async_session_factory=bundle["async_session_factory"],
    )

    async def _noop_async(*args, **kwargs):
        return None

    monkeypatch.setattr(app_main, "init_audit_database", _noop_async)
    monkeypatch.setattr(app_main, "cleanup_audit_database", _noop_async)
    monkeypatch.setattr(app_main.audit_service, "force_flush", _noop_async)
    monkeypatch.setattr(usm_db_module, "init_usm_db", _noop_async)

    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=42,
        username="pytest-runner",
        full_name="Pytest Runner",
        role=UserRole.SUPER_ADMIN,
    )

    with bundle["sync_session_factory"]() as session:
        # A team with NO storage provider — the unconfigured first-entry state.
        team = Team(name="Fresh Team", description="", wiki_token="w", test_case_table_id="tbl")
        session.add(team)
        session.commit()
        team_id = team.id

    client = TestClient(app)
    yield client, team_id

    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_current_user, None)
    dispose_managed_test_database(bundle)


def test_sync_without_storage_provider_returns_400_not_500(sync_client):
    client, team_id = sync_client

    resp = client.post(f"/api/teams/{team_id}/automation-scripts/sync", json={})

    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"]["code"] == "PROVIDER_NOT_CONFIGURED"
