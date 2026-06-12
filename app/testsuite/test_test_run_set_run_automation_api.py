"""HTTP-level tests for `POST /api/teams/{team_id}/test-run-sets/{set_id}/run-automation`.

This endpoint is the new single trigger entry point that replaces the
removed `POST /automation-scripts/{id}/runs` and
`POST /automation-script-groups/{id}/runs` public endpoints. Coverage:

- Happy path: set with 1 / multiple suites triggers runs and writes
  `automation_runs.test_run_set_id`.
- Error path: empty set → 400 NO_AUTOMATION_SUITES.
- Error path: cross-team suite id → 400 AUTOMATION_SUITE_INVALID.
- Error path: suite id that does not exist → 400 AUTOMATION_SUITE_INVALID.
- Error path: unknown set id → 404 TEST_RUN_SET_NOT_FOUND.

The CI provider is replaced with `_FakeCIProvider` so no network call happens.

See `openspec/changes/move-automation-execution-to-test-run-set/`.
"""
from __future__ import annotations

import json
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
    """In-memory CI stand-in used so the trigger pipeline does not hit the network."""

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


class _FailingCIProvider(_FakeCIProvider):
    async def update_suite_job(self, *args, **kwargs) -> str:
        from app.services.automation.script_group_service import AutomationScriptGroupCIApiError

        raise AutomationScriptGroupCIApiError(
            "Failed to ensure suite job on CI: credentials rejected"
        )


def _seed_automation_assets(session, team_id: int, suite_count: int) -> list[int]:
    """Create one storage + one CI provider and N suites for the given team."""
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

    suite_ids: list[int] = []
    for i in range(suite_count):
        suite = AutomationScriptGroup(
            team_id=team_id,
            name=f"Suite {i}",
            description="",
            ci_job_name=f"suite-job-{i}",
            ci_job_type="JENKINS",
            script_paths_json=json.dumps([f"tests/test_{i}.py"]),
        )
        session.add(suite)
        session.flush()
        suite_ids.append(suite.id)
    session.commit()
    return suite_ids


@pytest.fixture
def run_automation_db(tmp_path, monkeypatch):
    main_bundle = create_managed_test_database(tmp_path / "test_run_set_run_automation.db")
    audit_bundle = create_managed_test_database(
        tmp_path / "test_run_set_run_automation_audit.db",
        target_name="audit",
    )

    install_main_database_overrides(
        monkeypatch=monkeypatch,
        app=app,
        get_db_dependency=get_db,
        async_engine=main_bundle["async_engine"],
        async_session_factory=main_bundle["async_session_factory"],
    )

    with audit_bundle["sync_session_factory"]() as session:
        pass

    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=42,
        username="pytest-runner",
        full_name="Pytest Runner",
        role=UserRole.SUPER_ADMIN,
    )

    with main_bundle["sync_session_factory"]() as session:
        team = Team(
            name="Run Auto Team",
            description="",
            wiki_token="run-auto-wiki",
            test_case_table_id="run-auto-tbl",
        )
        session.add(team)
        session.commit()

        suite_ids = _seed_automation_assets(session, team.id, suite_count=2)

        set_one = TestRunSetDB(
            team_id=team.id,
            name="Set with 1 suite",
            description="",
            status=TestRunSetStatusEnum.ACTIVE,
            automation_suite_ids_json=json.dumps([suite_ids[0]]),
        )
        set_many = TestRunSetDB(
            team_id=team.id,
            name="Set with 2 suites",
            description="",
            status=TestRunSetStatusEnum.ACTIVE,
            automation_suite_ids_json=json.dumps(suite_ids),
        )
        set_empty = TestRunSetDB(
            team_id=team.id,
            name="Set empty",
            description="",
            status=TestRunSetStatusEnum.ACTIVE,
            automation_suite_ids_json=json.dumps([]),
        )
        session.add_all([set_one, set_many, set_empty])
        session.commit()

        ids = {
            "team_id": team.id,
            "suite_ids": suite_ids,
            "set_one_id": set_one.id,
            "set_many_id": set_many.id,
            "set_empty_id": set_empty.id,
        }

    yield {
        "ids": ids,
        "main_bundle": main_bundle,
    }

    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_current_user, None)
    dispose_managed_test_database(audit_bundle)
    dispose_managed_test_database(main_bundle)


def _patch_fake_ci(monkeypatch, suite_job_name: str) -> _FakeCIProvider:
    from app.services.automation import script_group_service as sgs

    fake = _FakeCIProvider(suite_job_name=suite_job_name)
    monkeypatch.setattr(sgs, "instantiate_provider", lambda *a, **kw: fake)
    return fake


def _patch_failing_ci(monkeypatch) -> _FailingCIProvider:
    from app.services.automation import script_group_service as sgs

    fake = _FailingCIProvider(suite_job_name="unused")
    monkeypatch.setattr(sgs, "instantiate_provider", lambda *a, **kw: fake)
    return fake


def test_run_automation_endpoint_triggers_single_suite(run_automation_db, monkeypatch):
    ids = run_automation_db["ids"]
    _patch_fake_ci(monkeypatch, suite_job_name=f"suite-job-{ids['suite_ids'][0]}")

    client = TestClient(app)
    resp = client.post(
        f"/api/teams/{ids['team_id']}/test-run-sets/{ids['set_one_id']}/run-automation"
    )
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["triggered_suite_ids"] == [ids["suite_ids"][0]]
    assert len(payload["run_ids"]) == 1


def test_run_automation_endpoint_triggers_multiple_suites(run_automation_db, monkeypatch):
    ids = run_automation_db["ids"]
    _patch_fake_ci(monkeypatch, suite_job_name="placeholder")

    client = TestClient(app)
    resp = client.post(
        f"/api/teams/{ids['team_id']}/test-run-sets/{ids['set_many_id']}/run-automation"
    )
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["triggered_suite_ids"] == ids["suite_ids"]
    assert len(payload["run_ids"]) == 2


def test_run_automation_endpoint_triggers_requested_suite(run_automation_db, monkeypatch):
    ids = run_automation_db["ids"]
    _patch_fake_ci(monkeypatch, suite_job_name="placeholder")

    client = TestClient(app)
    resp = client.post(
        f"/api/teams/{ids['team_id']}/test-run-sets/{ids['set_many_id']}/run-automation",
        json={"suite_id": ids["suite_ids"][1]},
    )
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["triggered_suite_ids"] == [ids["suite_ids"][1]]
    assert len(payload["run_ids"]) == 1


def test_run_automation_endpoint_rejects_suite_not_in_set(run_automation_db, monkeypatch):
    ids = run_automation_db["ids"]
    _patch_fake_ci(monkeypatch, suite_job_name="placeholder")

    client = TestClient(app)
    resp = client.post(
        f"/api/teams/{ids['team_id']}/test-run-sets/{ids['set_one_id']}/run-automation",
        json={"suite_id": ids["suite_ids"][1]},
    )
    assert resp.status_code == 400, resp.text
    detail = resp.json().get("detail") or {}
    assert detail.get("code") == "AUTOMATION_SUITE_NOT_IN_SET"


def test_run_automation_endpoint_empty_set_returns_400(run_automation_db):
    ids = run_automation_db["ids"]
    client = TestClient(app)
    resp = client.post(
        f"/api/teams/{ids['team_id']}/test-run-sets/{ids['set_empty_id']}/run-automation"
    )
    assert resp.status_code == 400, resp.text
    detail = resp.json().get("detail") or {}
    assert detail.get("code") == "NO_AUTOMATION_SUITES"


def test_run_automation_endpoint_unknown_set_returns_404(run_automation_db, monkeypatch):
    ids = run_automation_db["ids"]
    _patch_fake_ci(monkeypatch, suite_job_name="placeholder")

    client = TestClient(app)
    resp = client.post(
        f"/api/teams/{ids['team_id']}/test-run-sets/999999/run-automation"
    )
    assert resp.status_code == 404, resp.text
    detail = resp.json().get("detail") or {}
    assert detail.get("code") == "TEST_RUN_SET_NOT_FOUND"


def test_run_automation_endpoint_cross_team_suite_returns_400(run_automation_db, monkeypatch):
    """A set that points to another team's suite must be rejected with HTTP 400."""
    from app.models.database_models import Team as TeamModel

    ids = run_automation_db["ids"]
    main_bundle = run_automation_db["main_bundle"]

    _patch_fake_ci(monkeypatch, suite_job_name="placeholder")

    with main_bundle["sync_session_factory"]() as session:
        other_team = TeamModel(
            name="Other Team",
            description="",
            wiki_token="other-wiki",
            test_case_table_id="other-tbl",
        )
        session.add(other_team)
        session.flush()
        other_suite = AutomationScriptGroup(
            team_id=other_team.id,
            name="Other Suite",
            description="",
            ci_job_name="other-suite-job",
            ci_job_type="JENKINS",
            script_paths_json=json.dumps(["tests/other.py"]),
        )
        session.add(other_suite)
        session.flush()
        other_suite_id = other_suite.id

        set_db = (
            session.query(TestRunSetDB).filter(TestRunSetDB.id == ids["set_one_id"]).one()
        )
        set_db.automation_suite_ids_json = json.dumps([other_suite_id])
        session.commit()

    client = TestClient(app)
    resp = client.post(
        f"/api/teams/{ids['team_id']}/test-run-sets/{ids['set_one_id']}/run-automation"
    )
    assert resp.status_code == 400, resp.text
    detail = resp.json().get("detail") or {}
    assert detail.get("code") == "AUTOMATION_SUITE_INVALID"


def test_run_automation_endpoint_missing_suite_returns_400(run_automation_db, monkeypatch):
    """A set pointing to a suite id that no longer exists must be rejected."""
    ids = run_automation_db["ids"]
    main_bundle = run_automation_db["main_bundle"]

    _patch_fake_ci(monkeypatch, suite_job_name="placeholder")

    with main_bundle["sync_session_factory"]() as session:
        set_db = (
            session.query(TestRunSetDB).filter(TestRunSetDB.id == ids["set_one_id"]).one()
        )
        set_db.automation_suite_ids_json = json.dumps([9999999])
        session.commit()

    client = TestClient(app)
    resp = client.post(
        f"/api/teams/{ids['team_id']}/test-run-sets/{ids['set_one_id']}/run-automation"
    )
    assert resp.status_code == 400, resp.text
    detail = resp.json().get("detail") or {}
    assert detail.get("code") == "AUTOMATION_SUITE_INVALID"


def test_run_automation_endpoint_ci_api_error_returns_502(run_automation_db, monkeypatch):
    ids = run_automation_db["ids"]
    _patch_failing_ci(monkeypatch)

    client = TestClient(app)
    resp = client.post(
        f"/api/teams/{ids['team_id']}/test-run-sets/{ids['set_one_id']}/run-automation"
    )

    assert resp.status_code == 502, resp.text
    detail = resp.json().get("detail") or {}
    assert detail.get("code") == "AUTOMATION_RUN_CI_API_FAILED"
    assert "credentials rejected" in detail.get("message", "")
