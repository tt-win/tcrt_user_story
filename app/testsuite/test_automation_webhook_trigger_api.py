# ruff: noqa: E402
"""End-to-end HTTP tests for the public suite-trigger webhook endpoint.

These prove the exact request shape the UI's "trigger curl example" produces
(empty JSON body + HMAC-SHA256 signature over the raw body) is accepted by the
live route — i.e. the copied curl is runnable with no edits.
"""

from __future__ import annotations

import hashlib
import hmac
import json
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
    AutomationScript,
    AutomationScriptFormat,
    AutomationScriptGroup,
    AutomationScriptGroupJobType,
    AutomationWebhook,
    AutomationWebhookDirection,
    SystemAutomationProvider,
    Team,
    TeamAutomationProvider,
)
from app.services.automation import script_group_service as group_service_module
from app.services.automation.providers.base import ExternalRunRef
from app.testsuite.db_test_helpers import (
    create_managed_test_database,
    dispose_managed_test_database,
    install_main_database_overrides,
)


_SECRET = "trigger-secret-abc"
_TOKEN = "trigger-token-xyz"


class _FakeCIProvider:
    async def create_suite_job(self, suite_id, suite_name, test_paths, default_runner_label, **kwargs) -> str:
        return f"tcrt-suite-{suite_id}"

    async def update_suite_job(self, suite_id, suite_name, test_paths, default_runner_label, **kwargs) -> str:
        return f"tcrt-suite-{suite_id}"

    async def trigger_run(self, workflow_id, branch, inputs) -> ExternalRunRef:
        return ExternalRunRef(
            external_run_id="queue:555",
            external_run_url="https://jenkins.example/queue/item/555/",
            raw={"job_name": workflow_id},
        )


@pytest.fixture
def trigger_client(tmp_path, monkeypatch):
    bundle = create_managed_test_database(tmp_path / "test_case_repo.db")
    SyncSessionLocal = bundle["sync_session_factory"]

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

    # Keep CI provider resolution off the network.
    monkeypatch.setattr(
        group_service_module, "instantiate_provider", lambda *a, **k: _FakeCIProvider()
    )

    with SyncSessionLocal() as session:
        team = Team(name="QA", description="", wiki_token="w", test_case_table_id="tbl")
        session.add(team)
        session.commit()

        storage = TeamAutomationProvider(
            team_id=team.id,
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
            config_json=json.dumps({"default_runner_label": "any", "default_branch": "main"}),
            credentials_encrypted=None,
            is_active=True,
        )
        session.add_all([storage, ci])
        session.commit()

        script = AutomationScript(
            team_id=team.id,
            provider_id=storage.id,
            name="test_login.py",
            script_format=AutomationScriptFormat.PYTEST,
            ref_path="tests/test_login.py",
            ref_branch="main",
            tags_json="[]",
        )
        session.add(script)
        session.commit()

        group = AutomationScriptGroup(
            team_id=team.id,
            name="Login Regression",
            description=None,
            script_paths_json=json.dumps(["tests/test_login.py"]),
            ci_job_name="tcrt-suite-pre",
            ci_job_type=AutomationScriptGroupJobType.JENKINS,
        )
        session.add(group)
        session.commit()

        bound = AutomationWebhook(
            team_id=team.id,
            direction=AutomationWebhookDirection.INBOUND,
            name="Trigger Hook",
            token=_TOKEN,
            secret=_SECRET,
            script_group_id=group.id,
            events_json="[]",
            is_active=True,
        )
        unbound = AutomationWebhook(
            team_id=team.id,
            direction=AutomationWebhookDirection.INBOUND,
            name="Unbound Hook",
            token=_TOKEN + "-u",
            secret=_SECRET,
            script_group_id=None,
            events_json="[]",
            is_active=True,
        )
        session.add_all([bound, unbound])
        session.commit()

    from app.api import automation_webhooks_public

    automation_webhooks_public._rate_limit_buckets.clear()
    client = TestClient(app)
    yield client

    app.dependency_overrides.pop(get_db, None)
    dispose_managed_test_database(bundle)


def _sign(body: bytes) -> str:
    return "sha256=" + hmac.new(_SECRET.encode("utf-8"), body, hashlib.sha256).hexdigest()


def test_trigger_with_signed_empty_body_succeeds(trigger_client):
    body = b"{}"
    resp = trigger_client.post(
        f"/api/v1/webhooks/ci/{_TOKEN}/trigger",
        content=body,
        headers={"Content-Type": "application/json", "X-TCRT-Signature": _sign(body)},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["run_id"] > 0
    assert data["status"] == "QUEUED"
    assert data["external_run_id"] == "queue:555"
    assert data["tcrt_correlation_id"]


def test_trigger_bad_signature_rejected(trigger_client):
    resp = trigger_client.post(
        f"/api/v1/webhooks/ci/{_TOKEN}/trigger",
        content=b"{}",
        headers={"Content-Type": "application/json", "X-TCRT-Signature": "sha256=deadbeef"},
    )
    assert resp.status_code == 401
    assert resp.json()["detail"]["code"] == "WEBHOOK_SIGNATURE_INVALID"


def test_trigger_unbound_webhook_conflict(trigger_client):
    body = b"{}"
    resp = trigger_client.post(
        f"/api/v1/webhooks/ci/{_TOKEN}-u/trigger",
        content=body,
        headers={"Content-Type": "application/json", "X-TCRT-Signature": _sign(body)},
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "WEBHOOK_NO_SUITE_BOUND"
