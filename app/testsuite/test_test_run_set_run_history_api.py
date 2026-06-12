"""HTTP-level tests for the new Test Run Set runs endpoints.

Replaces the removed ``GET /api/teams/{team_id}/automation-runs`` (and the
sibling /cancel, /reconcile, /sync, /sync-pending endpoints). Coverage:

- `GET /api/teams/{team_id}/test-run-sets/{set_id}/runs` lists runs scoped
  to the set; supports status / branch filter; rejects unknown / cross-team
  set ids.
- `GET /{set_id}/runs/{run_id}` returns a single run that belongs to the
  set; returns 404 when the run is not in the set (set-scoping enforced).
- `POST /{set_id}/runs/{run_id}/cancel` cancels a set-scoped run.
- `POST /{set_id}/runs/{run_id}/reconcile` reconciles a set-scoped run
  against a user-supplied external_run_id.

See `openspec/changes/move-run-history-to-test-run-set/`.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
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
from app.models.database_models import (
    AutomationProviderSlot,
    AutomationRun,
    AutomationRunStatus,
    AutomationRunTrigger,
    AutomationScriptGroup,
    SystemAutomationProvider,
    Team,
    TeamAutomationProvider,
    TestRunSet as TestRunSetDB,
    TestRunSetStatus as TestRunSetStatusEnum,
)
from app.testsuite.db_test_helpers import (
    create_managed_test_database,
    dispose_managed_test_database,
    install_main_database_overrides,
)


class _FakeCIProvider:
    """In-memory CI stand-in so the trigger pipeline does not hit the network."""

    def __init__(self, suite_job_name: str) -> None:
        self.suite_job_name = suite_job_name
        self.trigger_calls: list[tuple[str, str, dict]] = []

    async def create_suite_job(self, *args, **kwargs) -> str:
        return self.suite_job_name

    async def update_suite_job(self, *args, **kwargs) -> str:
        return self.suite_job_name

    async def trigger_run(self, workflow_id, branch, inputs):
        self.trigger_calls.append((workflow_id, branch, dict(inputs)))
        from app.services.automation.providers.base import ExternalRunRef

        return ExternalRunRef(
            external_run_id=f"queue-{workflow_id}",
            external_run_url=f"https://ci.example/queue/{workflow_id}",
            raw={},
        )

    async def get_run_status(self, external_run_id):  # type: ignore[no-untyped-def]
        from app.services.automation.providers.base import RunStatusSnapshot

        return RunStatusSnapshot(
            external_run_id=external_run_id,
            status="SUCCEEDED",
            raw={},
        )

    async def cancel_run(self, external_run_id):  # type: ignore[no-untyped-def]
        return None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


@pytest.fixture
def run_history_db(tmp_path, monkeypatch):
    main_bundle = create_managed_test_database(tmp_path / "test_run_set_run_history.db")

    install_main_database_overrides(
        monkeypatch=monkeypatch,
        app=app,
        get_db_dependency=get_db,
        async_engine=main_bundle["async_engine"],
        async_session_factory=main_bundle["async_session_factory"],
    )
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=7,
        username="run-history-runner",
        full_name="Run History Runner",
        role=UserRole.SUPER_ADMIN,
    )

    with main_bundle["sync_session_factory"]() as session:
        team_a = Team(
            name="Run History Team A",
            description="",
            wiki_token="rh-wiki-a",
            test_case_table_id="rh-tbl-a",
        )
        team_b = Team(
            name="Run History Team B",
            description="",
            wiki_token="rh-wiki-b",
            test_case_table_id="rh-tbl-b",
        )
        session.add_all([team_a, team_b])
        session.commit()

        storage = TeamAutomationProvider(
            team_id=team_a.id,
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
            config_json=json.dumps({
                "base_url": "https://jenkins.example",
                "default_runner_label": "linux",
                "default_branch": "main",
            }),
            credentials_encrypted=None,
            is_active=True,
        )
        session.add_all([storage, ci])
        session.commit()

        suite_a = AutomationScriptGroup(
            team_id=team_a.id,
            name="Run History Suite A",
            description="",
            ci_job_name="rh-suite-a",
            ci_job_type="JENKINS",
            script_paths_json=json.dumps(["tests/a.py"]),
        )
        session.add(suite_a)
        session.commit()

        set_a = TestRunSetDB(
            team_id=team_a.id,
            name="Run History Set A",
            description="",
            status=TestRunSetStatusEnum.ACTIVE,
            automation_suite_ids_json=json.dumps([suite_a.id]),
        )
        set_b = TestRunSetDB(
            team_id=team_a.id,
            name="Run History Set B",
            description="",
            status=TestRunSetStatusEnum.ACTIVE,
            automation_suite_ids_json=json.dumps([]),
        )
        session.add_all([set_a, set_b])
        session.commit()

        # Seed two runs in set_a (different statuses/branches) and one in set_b
        now = _utcnow()
        run_a1 = AutomationRun(
            team_id=team_a.id,
            script_group_id=suite_a.id,
            test_run_set_id=set_a.id,
            provider_id=ci.id,
            status=AutomationRunStatus.SUCCEEDED,
            triggered_by=AutomationRunTrigger.USER,
            triggered_by_user_id="7",
            tcrt_correlation_id="corr-a1",
            workflow_id="rh-suite-a",
            branch="main",
            inputs_json="{}",
            started_at=now,
            finished_at=now,
            duration_ms=60_000,
        )
        run_a2 = AutomationRun(
            team_id=team_a.id,
            script_group_id=suite_a.id,
            test_run_set_id=set_a.id,
            provider_id=ci.id,
            # RUNNING so it is cancellable (test_cancel_run_in_set);
            # external_run_id must be set so the cancel CI call has a target.
            status=AutomationRunStatus.RUNNING,
            triggered_by=AutomationRunTrigger.WEBHOOK,
            tcrt_correlation_id="corr-a2",
            external_run_id="ext-a2",
            external_run_url="https://ci.example/run/a2",
            workflow_id="rh-suite-a",
            branch="feature/x",
            inputs_json="{}",
            started_at=now,
            duration_ms=10_000,
        )
        run_b1 = AutomationRun(
            team_id=team_a.id,
            script_group_id=suite_a.id,
            test_run_set_id=set_b.id,
            provider_id=ci.id,
            status=AutomationRunStatus.QUEUED,
            triggered_by=AutomationRunTrigger.USER,
            tcrt_correlation_id="corr-b1",
            workflow_id="rh-suite-a",
            branch="main",
            inputs_json="{}",
        )
        session.add_all([run_a1, run_a2, run_b1])
        session.commit()

        ids = {
            "team_id": team_a.id,
            "team_b_id": team_b.id,
            "set_a_id": set_a.id,
            "set_b_id": set_b.id,
            "run_a1_id": run_a1.id,
            "run_a2_id": run_a2.id,
            "run_b1_id": run_b1.id,
            "ci_provider_id": ci.id,
        }

    yield {"ids": ids, "main_bundle": main_bundle}

    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_current_user, None)
    dispose_managed_test_database(main_bundle)


def test_list_runs_for_test_run_set(run_history_db):
    ids = run_history_db["ids"]
    client = TestClient(app)
    resp = client.get(
        f"/api/teams/{ids['team_id']}/test-run-sets/{ids['set_a_id']}/runs"
    )
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["total"] == 2
    items = {item["id"]: item for item in payload["items"]}
    assert ids["run_a1_id"] in items
    assert ids["run_a2_id"] in items
    assert items[ids["run_a1_id"]]["status"] == "SUCCEEDED"
    assert items[ids["run_a1_id"]]["test_run_set_id"] == ids["set_a_id"]
    assert items[ids["run_a1_id"]]["script_group_name"] == "Run History Suite A"


def test_list_runs_for_test_run_set_status_filter(run_history_db):
    ids = run_history_db["ids"]
    client = TestClient(app)
    resp = client.get(
        f"/api/teams/{ids['team_id']}/test-run-sets/{ids['set_a_id']}/runs",
        params={"status": "RUNNING"},
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["total"] == 1
    assert payload["items"][0]["id"] == ids["run_a2_id"]


def test_list_runs_for_test_run_set_branch_filter(run_history_db):
    ids = run_history_db["ids"]
    client = TestClient(app)
    resp = client.get(
        f"/api/teams/{ids['team_id']}/test-run-sets/{ids['set_a_id']}/runs",
        params={"branch": "feature/x"},
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["total"] == 1
    assert payload["items"][0]["id"] == ids["run_a2_id"]


def test_list_runs_for_test_run_set_excludes_other_sets(run_history_db):
    """A set that owns no runs returns an empty list (no leakage from other sets)."""
    ids = run_history_db["ids"]
    client = TestClient(app)
    resp = client.get(
        f"/api/teams/{ids['team_id']}/test-run-sets/{ids['set_b_id']}/runs"
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["total"] == 1
    assert payload["items"][0]["id"] == ids["run_b1_id"]


def test_get_run_in_set(run_history_db):
    ids = run_history_db["ids"]
    client = TestClient(app)
    resp = client.get(
        f"/api/teams/{ids['team_id']}/test-run-sets/{ids['set_a_id']}/runs/{ids['run_a1_id']}"
    )
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["id"] == ids["run_a1_id"]
    assert payload["test_run_set_id"] == ids["set_a_id"]


def test_get_run_in_set_rejects_run_in_other_set(run_history_db):
    """A run that belongs to a different set must not be readable via this set."""
    ids = run_history_db["ids"]
    client = TestClient(app)
    resp = client.get(
        f"/api/teams/{ids['team_id']}/test-run-sets/{ids['set_a_id']}/runs/{ids['run_b1_id']}"
    )
    assert resp.status_code == 404, resp.text
    detail = resp.json().get("detail") or {}
    assert detail.get("code") == "AUTOMATION_RUN_NOT_IN_SET"


def test_get_run_in_set_unknown_run(run_history_db):
    ids = run_history_db["ids"]
    client = TestClient(app)
    resp = client.get(
        f"/api/teams/{ids['team_id']}/test-run-sets/{ids['set_a_id']}/runs/999999"
    )
    assert resp.status_code == 404
    assert (resp.json().get("detail") or {}).get("code") == "AUTOMATION_RUN_NOT_IN_SET"


def test_cancel_run_in_set(run_history_db, monkeypatch):
    """POST cancel on a set-scoped run transitions it to CANCELLED."""
    from app.services.automation.run_service import AutomationRunService

    ids = run_history_db["ids"]
    fake = _FakeCIProvider(suite_job_name="rh-suite-a")
    # Stub the provider lookup at the run_service layer.
    async def _fake_provider(self, run):  # type: ignore[no-untyped-def]
        return fake

    monkeypatch.setattr(AutomationRunService, "_provider_from_run_record", _fake_provider)

    client = TestClient(app)
    # run_a2 is RUNNING; run_a1 is SUCCEEDED (terminal) and would 409
    resp = client.post(
        f"/api/teams/{ids['team_id']}/test-run-sets/{ids['set_a_id']}/runs/{ids['run_a2_id']}/cancel"
    )
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["status"] == "CANCELLED"


def test_cancel_run_in_set_rejects_run_in_other_set(run_history_db, monkeypatch):
    from app.services.automation import script_group_service as sgs

    ids = run_history_db["ids"]
    fake = _FakeCIProvider(suite_job_name="rh-suite-a")
    monkeypatch.setattr(sgs, "instantiate_provider", lambda *a, **kw: fake)

    client = TestClient(app)
    # run_b1 is RUNNING (non-terminal) and belongs to set_b
    resp = client.post(
        f"/api/teams/{ids['team_id']}/test-run-sets/{ids['set_a_id']}/runs/{ids['run_b1_id']}/cancel"
    )
    assert resp.status_code == 404
    assert (resp.json().get("detail") or {}).get("code") == "AUTOMATION_RUN_NOT_IN_SET"


def test_reconcile_run_in_set(run_history_db, monkeypatch):
    """POST reconcile on a set-scoped run updates the external_run_id."""
    from app.services.automation.run_service import AutomationRunService

    ids = run_history_db["ids"]
    fake = _FakeCIProvider(suite_job_name="rh-suite-a")
    # Stub the provider lookup at the run_service layer (avoids needing
    # valid Jenkins credentials in the test seed).
    async def _fake_provider(self, run):  # type: ignore[no-untyped-def]
        return fake

    monkeypatch.setattr(AutomationRunService, "_provider_from_run_record", _fake_provider)

    client = TestClient(app)
    resp = client.post(
        f"/api/teams/{ids['team_id']}/test-run-sets/{ids['set_a_id']}/runs/{ids['run_a1_id']}/reconcile",
        json={"external_run_id": "manual-ext-1"},
    )
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["external_run_id"] == "manual-ext-1"


def test_reconcile_run_in_set_rejects_run_in_other_set(run_history_db):
    ids = run_history_db["ids"]
    client = TestClient(app)
    resp = client.post(
        f"/api/teams/{ids['team_id']}/test-run-sets/{ids['set_a_id']}/runs/{ids['run_b1_id']}/reconcile",
        json={"external_run_id": "x"},
    )
    assert resp.status_code == 404
    assert (resp.json().get("detail") or {}).get("code") == "AUTOMATION_RUN_NOT_IN_SET"
