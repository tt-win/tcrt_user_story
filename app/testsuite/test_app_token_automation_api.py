"""Tests for app token automation trigger/cancel/reconcile API."""

from __future__ import annotations

from datetime import datetime, timedelta
import json
from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.auth.app_token_dependencies import generate_app_token
from app.database import get_db
from app.main import app
from app.models.database_models import (
    AutomationProviderSlot,
    AutomationScriptGroup,
    SystemAutomationProvider,
    Team,
    TeamAppToken,
    TeamAppTokenStatus,
    TeamAutomationProvider,
    TestRunSet as TestRunSetDB,
    TestRunSetStatus as TestRunSetStatusEnum,
    User,
)
from app.testsuite.db_test_helpers import (
    create_managed_test_database,
    dispose_managed_test_database,
    install_main_database_overrides,
)


class _FakeCIProvider:
    """In-memory CI stand-in covering trigger + cancel + status sync."""

    def __init__(self, suite_job_name: str) -> None:
        self.suite_job_name = suite_job_name
        self.cancelled: list[str] = []

    async def create_suite_job(self, *args, **kwargs) -> str:
        return self.suite_job_name

    async def update_suite_job(self, *args, **kwargs) -> str:
        return self.suite_job_name

    async def trigger_run(self, workflow_id, branch, inputs):
        from app.services.automation.providers.base import ExternalRunRef

        return ExternalRunRef(
            external_run_id=f"queue-{workflow_id}",
            external_run_url=f"https://ci.example/queue/{workflow_id}",
            raw={},
        )

    async def cancel_run(self, external_run_id: str) -> None:
        self.cancelled.append(external_run_id)

    async def get_run_status(self, external_run_id: str):
        from app.services.automation.providers.base import RunStatusSnapshot

        return RunStatusSnapshot(
            status="SUCCEEDED",
            external_run_id=external_run_id,
            external_run_url=f"https://ci.example/run/{external_run_id}",
        )


def _seed_automation_assets(session, team_id: int, with_provider: bool = True) -> int:
    if with_provider:
        storage = TeamAutomationProvider(
            team_id=team_id,
            provider_slot=AutomationProviderSlot.STORAGE,
            provider_type="storage:github",
            name="GitHub",
            config_json=json.dumps({"owner": "ex", "repo": "auto", "default_branch": "main"}),
            credentials_encrypted=None,
            is_active=True,
        )
        ci = SystemAutomationProvider(
            provider_slot=AutomationProviderSlot.CI,
            provider_type="ci:jenkins",
            name="Jenkins",
            config_json=json.dumps({"default_runner_label": "linux", "default_branch": "main"}),
            credentials_encrypted=None,
            is_active=True,
        )
        session.add_all([storage, ci])
        session.commit()

    suite = AutomationScriptGroup(
        team_id=team_id,
        name="Suite",
        description="",
        ci_job_name="suite-job",
        ci_job_type="JENKINS",
        script_paths_json=json.dumps(["tests/test_1.py"]),
    )
    session.add(suite)
    session.commit()
    return suite.id


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    database_bundle = create_managed_test_database(tmp_path / "test_app_token_automation.db")
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

    yield database_bundle["sync_session_factory"]

    app.dependency_overrides.pop(get_db, None)
    dispose_managed_test_database(database_bundle)


def _seed_data(session, with_provider=True, scopes=None):
    if scopes is None:
        scopes = ["automation:execute", "test_run:read"]

    team = Team(name="Auto Team", description="", wiki_token="auto-wiki", test_case_table_id="auto-tbl")
    session.add(team)
    session.commit()

    user = User(username="auto_creator", email="auto@e.com", full_name="Auto", role="admin", is_active=True, hashed_password="d")
    session.add(user)
    session.commit()

    raw, h, p = generate_app_token()
    session.add(TeamAppToken(
        name="auto-token", owner_team_id=team.id, token_hash=h, token_prefix=p,
        status=TeamAppTokenStatus.ACTIVE, scopes_json=json.dumps(scopes),
        expires_at=datetime.utcnow() + timedelta(days=90), created_by_user_id=user.id,
    ))

    read_raw, read_h, read_p = generate_app_token()
    session.add(TeamAppToken(
        name="auto-read-token", owner_team_id=team.id, token_hash=read_h, token_prefix=read_p,
        status=TeamAppTokenStatus.ACTIVE, scopes_json=json.dumps(["test_run:read"]),
        expires_at=datetime.utcnow() + timedelta(days=90), created_by_user_id=user.id,
    ))
    session.commit()

    suite_id = _seed_automation_assets(session, team.id, with_provider=with_provider)

    test_run_set = TestRunSetDB(
        team_id=team.id,
        name="Set",
        description="",
        status=TestRunSetStatusEnum.ACTIVE,
        automation_suite_ids_json=json.dumps([suite_id]),
    )
    session.add(test_run_set)
    session.commit()

    return {
        "team_id": team.id,
        "set_id": test_run_set.id,
        "suite_id": suite_id,
        "execute_token": raw,
        "read_token": read_raw,
    }


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _patch_ci(monkeypatch, suite_job_name: str = "suite-job") -> _FakeCIProvider:
    from app.services.automation import script_group_service as sgs
    from app.services.automation import run_service as rs

    fake = _FakeCIProvider(suite_job_name=suite_job_name)
    monkeypatch.setattr(sgs, "instantiate_provider", lambda *a, **kw: fake)
    monkeypatch.setattr(rs, "instantiate_provider", lambda *a, **kw: fake)
    return fake


class TestAutomationTrigger:
    def test_trigger_requires_scope(self, temp_db, monkeypatch):
        with temp_db() as session:
            seeded = _seed_data(session)
        _patch_ci(monkeypatch)
        with TestClient(app) as client:
            resp = client.post(
                f"/api/app/teams/{seeded['team_id']}/test-run-sets/{seeded['set_id']}/run-automation",
                headers=_bearer(seeded["read_token"]),
            )
            assert resp.status_code == 403
            assert resp.json()["detail"]["code"] == "APP_TOKEN_SCOPE_DENIED"

    def test_trigger_success(self, temp_db, monkeypatch):
        with temp_db() as session:
            seeded = _seed_data(session)
        _patch_ci(monkeypatch)
        with TestClient(app) as client:
            resp = client.post(
                f"/api/app/teams/{seeded['team_id']}/test-run-sets/{seeded['set_id']}/run-automation",
                headers=_bearer(seeded["execute_token"]),
            )
            assert resp.status_code == 200, resp.text
            data = resp.json()
            assert data["triggered_suite_ids"] == [seeded["suite_id"]]
            assert len(data["run_ids"]) == 1

    def test_trigger_cross_team_path_denied(self, temp_db, monkeypatch):
        """Calling another team's path is denied before any automation logic runs."""
        with temp_db() as session:
            seeded = _seed_data(session)
            other_team = Team(name="Other", description="", wiki_token="other-w", test_case_table_id="other-t")
            session.add(other_team)
            session.commit()
            other_set = TestRunSetDB(team_id=other_team.id, name="Other Set", status=TestRunSetStatusEnum.ACTIVE)
            session.add(other_set)
            session.commit()
            other_team_id = other_team.id
            other_set_id = other_set.id
        _patch_ci(monkeypatch)
        with TestClient(app) as client:
            resp = client.post(
                f"/api/app/teams/{other_team_id}/test-run-sets/{other_set_id}/run-automation",
                headers=_bearer(seeded["execute_token"]),
            )
            assert resp.status_code == 403
            assert resp.json()["detail"]["code"] == "APP_TOKEN_TEAM_SCOPE_DENIED"

    def test_trigger_set_from_another_team_not_found(self, temp_db, monkeypatch):
        """Referencing another team's set id under your own team path 404s (no cross-team leak)."""
        with temp_db() as session:
            seeded = _seed_data(session)
            other_team = Team(name="Other", description="", wiki_token="other-w", test_case_table_id="other-t")
            session.add(other_team)
            session.commit()
            other_set = TestRunSetDB(team_id=other_team.id, name="Other Set", status=TestRunSetStatusEnum.ACTIVE)
            session.add(other_set)
            session.commit()
            other_set_id = other_set.id
        _patch_ci(monkeypatch)
        with TestClient(app) as client:
            resp = client.post(
                f"/api/app/teams/{seeded['team_id']}/test-run-sets/{other_set_id}/run-automation",
                headers=_bearer(seeded["execute_token"]),
            )
            assert resp.status_code == 404, resp.text
            assert resp.json()["detail"]["code"] == "TEST_RUN_SET_NOT_FOUND"

    def test_trigger_missing_provider_returns_400(self, temp_db):
        with temp_db() as session:
            seeded = _seed_data(session, with_provider=False)
        with TestClient(app) as client:
            resp = client.post(
                f"/api/app/teams/{seeded['team_id']}/test-run-sets/{seeded['set_id']}/run-automation",
                headers=_bearer(seeded["execute_token"]),
            )
            assert resp.status_code == 400, resp.text
            assert resp.json()["detail"]["code"] == "AUTOMATION_PROVIDER_NOT_CONFIGURED"


class TestAutomationCancelReconcile:
    def _trigger_run(self, client, seeded):
        resp = client.post(
            f"/api/app/teams/{seeded['team_id']}/test-run-sets/{seeded['set_id']}/run-automation",
            headers=_bearer(seeded["execute_token"]),
        )
        assert resp.status_code == 200, resp.text
        return resp.json()["run_ids"][0]

    def test_cancel_requires_scope(self, temp_db, monkeypatch):
        with temp_db() as session:
            seeded = _seed_data(session)
        _patch_ci(monkeypatch)
        with TestClient(app) as client:
            run_id = self._trigger_run(client, seeded)
            resp = client.post(
                f"/api/app/teams/{seeded['team_id']}/test-run-sets/{seeded['set_id']}/runs/{run_id}/cancel",
                headers=_bearer(seeded["read_token"]),
            )
            assert resp.status_code == 403

    def test_cancel_success_then_already_terminal(self, temp_db, monkeypatch):
        with temp_db() as session:
            seeded = _seed_data(session)
        fake = _patch_ci(monkeypatch)
        with TestClient(app) as client:
            run_id = self._trigger_run(client, seeded)
            resp = client.post(
                f"/api/app/teams/{seeded['team_id']}/test-run-sets/{seeded['set_id']}/runs/{run_id}/cancel",
                headers=_bearer(seeded["execute_token"]),
            )
            assert resp.status_code == 200, resp.text
            assert resp.json()["status"] == "CANCELLED"
            assert fake.cancelled

            resp2 = client.post(
                f"/api/app/teams/{seeded['team_id']}/test-run-sets/{seeded['set_id']}/runs/{run_id}/cancel",
                headers=_bearer(seeded["execute_token"]),
            )
            assert resp2.status_code == 409, resp2.text
            assert resp2.json()["detail"]["code"] == "AUTOMATION_RUN_ALREADY_TERMINAL"

    def test_cancel_run_not_in_set_returns_404(self, temp_db, monkeypatch):
        with temp_db() as session:
            seeded = _seed_data(session)
        _patch_ci(monkeypatch)
        with TestClient(app) as client:
            run_id = self._trigger_run(client, seeded)
            resp = client.post(
                f"/api/app/teams/{seeded['team_id']}/test-run-sets/999999/runs/{run_id}/cancel",
                headers=_bearer(seeded["execute_token"]),
            )
            assert resp.status_code == 404

    def test_reconcile_success(self, temp_db, monkeypatch):
        with temp_db() as session:
            seeded = _seed_data(session)
        _patch_ci(monkeypatch)
        with TestClient(app) as client:
            run_id = self._trigger_run(client, seeded)
            resp = client.post(
                f"/api/app/teams/{seeded['team_id']}/test-run-sets/{seeded['set_id']}/runs/{run_id}/reconcile",
                headers=_bearer(seeded["execute_token"]),
                json={},
            )
            assert resp.status_code == 200, resp.text
            assert resp.json()["status"] == "SUCCEEDED"


class TestAutomationHubEndpointsRemainRemoved:
    def test_hub_script_run_endpoint_returns_404(self, temp_db, monkeypatch):
        with temp_db() as session:
            seeded = _seed_data(session)
        _patch_ci(monkeypatch)
        with TestClient(app) as client:
            resp = client.post(
                f"/api/teams/{seeded['team_id']}/automation-scripts/1/runs",
                headers=_bearer(seeded["execute_token"]),
            )
            assert resp.status_code in (404, 405)

    def test_hub_suite_run_endpoint_returns_404(self, temp_db, monkeypatch):
        with temp_db() as session:
            seeded = _seed_data(session)
        _patch_ci(monkeypatch)
        with TestClient(app) as client:
            resp = client.post(
                f"/api/teams/{seeded['team_id']}/automation-script-groups/{seeded['suite_id']}/runs",
                headers=_bearer(seeded["execute_token"]),
            )
            assert resp.status_code in (404, 405)
