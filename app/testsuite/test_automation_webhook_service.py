import hashlib
import hmac
import json

import pytest

from app.api import automation_webhooks_public
from app.models.database_models import (
    AutomationProviderSlot,
    AutomationRun,
    AutomationRunStatus,
    AutomationRunTrigger,
    AutomationWebhookDirection,
    SystemAutomationProvider,
    Team,
)
from app.services.automation.webhook_service import (
    AutomationRunForWebhookNotFoundError,
    AutomationWebhookInactiveError,
    AutomationWebhookInboundOnlyError,
    AutomationWebhookNameConflictError,
    AutomationWebhookNotFoundError,
    AutomationWebhookService,
    AutomationWebhookSignatureError,
)
from app.testsuite.db_test_helpers import create_managed_test_database, dispose_managed_test_database


@pytest.fixture
def webhook_db(tmp_path):
    bundle = create_managed_test_database(tmp_path / "test_case_repo.db")
    SyncSessionLocal = bundle["sync_session_factory"]
    AsyncSessionLocal = bundle["async_session_factory"]

    with SyncSessionLocal() as session:
        team = Team(name="QA Team", description="", wiki_token="t", test_case_table_id="tbl")
        session.add(team)
        session.commit()

        # CI providers are org-scoped — live in system_automation_providers.
        provider = SystemAutomationProvider(
            provider_slot=AutomationProviderSlot.CI,
            provider_type="ci:jenkins",
            name="Jenkins",
            config_json=json.dumps({}),
            credentials_encrypted=None,
            is_active=True,
        )
        session.add(provider)
        session.commit()

        run = AutomationRun(
            team_id=team.id,
            automation_script_id=None,
            provider_id=provider.id,
            status=AutomationRunStatus.QUEUED,
            triggered_by=AutomationRunTrigger.USER,
            tcrt_correlation_id="corr-aaa",
            external_run_id="queue:1",
            workflow_id="job-a",
            branch="main",
            inputs_json="{}",
        )
        session.add(run)
        session.commit()

        ids = {"team_id": team.id, "provider_id": provider.id, "run_id": run.id, "correlation": run.tcrt_correlation_id}

    yield {"ids": ids, "async_sessionmaker": AsyncSessionLocal}
    dispose_managed_test_database(bundle)


def _sign(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


@pytest.mark.asyncio
async def test_ensure_default_inbound_webhook_is_idempotent(webhook_db):
    """The auto-managed inbound webhook is looked up by sentinel name so a
    second call returns the same row instead of conflict-erroring."""
    ids = webhook_db["ids"]
    async with webhook_db["async_sessionmaker"]() as session:
        service = AutomationWebhookService(session)
        first = await service.ensure_default_inbound_webhook(team_id=ids["team_id"])
        second = await service.ensure_default_inbound_webhook(team_id=ids["team_id"])
        assert first.id == second.id
        assert first.token == second.token
        assert AutomationWebhookDirection(first.direction) == AutomationWebhookDirection.INBOUND
        assert first.name == "TCRT default (auto)"


@pytest.mark.asyncio
async def test_list_webhooks_excludes_auto_managed_receiver(webhook_db):
    """The system-managed run-status receiver is hidden from the user-facing
    list — it's an internal sink, not a webhook the team created."""
    ids = webhook_db["ids"]
    async with webhook_db["async_sessionmaker"]() as session:
        service = AutomationWebhookService(session)
        auto = await service.ensure_default_inbound_webhook(team_id=ids["team_id"])
        outbound, _t, _s = await service.create_webhook(
            team_id=ids["team_id"],
            direction=AutomationWebhookDirection.OUTBOUND,
            name="My Hook",
            target_url="https://example.test/hook",
            events=["run.completed"],
            is_active=True,
            actor="1",
        )

        listed = await service.list_webhooks(team_id=ids["team_id"])

    listed_ids = {w.id for w in listed}
    assert auto.id not in listed_ids
    assert outbound.id in listed_ids


def test_build_inbound_webhook_url_empty_when_public_base_url_unset(monkeypatch):
    """When public_base_url isn't configured, the helper returns "" so the
    Jenkins job XML's <defaultValue> stays empty and the post-stage gracefully
    skips the callback."""
    from app.services.automation.webhook_service import build_inbound_webhook_url
    import app.config as cfg_mod

    fake = type("F", (), {"token": "abc123"})()
    monkeypatch.setattr(cfg_mod.get_settings().app, "public_base_url", "")
    assert build_inbound_webhook_url(fake) == ""


def test_build_inbound_webhook_url_composes_run_status_path(monkeypatch):
    from app.services.automation.webhook_service import build_inbound_webhook_url
    import app.config as cfg_mod

    fake = type("F", (), {"token": "tok-xyz"})()
    monkeypatch.setattr(
        cfg_mod.get_settings().app, "public_base_url", "http://tcrt.local:9999/"
    )
    assert (
        build_inbound_webhook_url(fake)
        == "http://tcrt.local:9999/api/v1/webhooks/ci/tok-xyz/run-status"
    )


def test_inbound_webhook_rate_limit_is_per_token():
    automation_webhooks_public._rate_limit_buckets.clear()
    token = "token-a"

    for _ in range(automation_webhooks_public._RATE_LIMIT_CAPACITY):
        assert automation_webhooks_public._consume_rate_limit(token) is None

    assert automation_webhooks_public._consume_rate_limit(token) is not None
    assert automation_webhooks_public._consume_rate_limit("token-b") is None


@pytest.mark.asyncio
async def test_create_webhook_returns_token_and_secret(webhook_db):
    ids = webhook_db["ids"]
    async with webhook_db["async_sessionmaker"]() as session:
        service = AutomationWebhookService(session)
        webhook, token, secret = await service.create_webhook(
            team_id=ids["team_id"],
            direction=AutomationWebhookDirection.INBOUND,
            name="CI",
            target_url=None,
            events=[],
            is_active=True,
            actor="1",
        )
    assert webhook.id > 0
    assert webhook.token == token
    assert webhook.secret == secret
    assert len(token) >= 32
    assert len(secret) >= 32


@pytest.mark.asyncio
async def test_create_webhook_name_conflict_within_direction(webhook_db):
    ids = webhook_db["ids"]
    async with webhook_db["async_sessionmaker"]() as session:
        service = AutomationWebhookService(session)
        await service.create_webhook(
            team_id=ids["team_id"],
            direction=AutomationWebhookDirection.INBOUND,
            name="CI",
            target_url=None,
            events=[],
            is_active=True,
            actor="1",
        )
        with pytest.raises(AutomationWebhookNameConflictError):
            await service.create_webhook(
                team_id=ids["team_id"],
                direction=AutomationWebhookDirection.INBOUND,
                name="CI",
                target_url=None,
                events=[],
                is_active=True,
                actor="1",
            )


@pytest.mark.asyncio
async def test_load_inbound_rejects_outbound_and_inactive(webhook_db):
    ids = webhook_db["ids"]
    async with webhook_db["async_sessionmaker"]() as session:
        service = AutomationWebhookService(session)
        outbound, _t, _s = await service.create_webhook(
            team_id=ids["team_id"],
            direction=AutomationWebhookDirection.OUTBOUND,
            name="Out",
            target_url="https://example/",
            events=[],
            is_active=True,
            actor="1",
        )
        inbound, _t2, _s2 = await service.create_webhook(
            team_id=ids["team_id"],
            direction=AutomationWebhookDirection.INBOUND,
            name="In",
            target_url=None,
            events=[],
            is_active=False,
            actor="1",
        )
        with pytest.raises(AutomationWebhookInboundOnlyError):
            await service.load_inbound_webhook(token=outbound.token)
        with pytest.raises(AutomationWebhookInactiveError):
            await service.load_inbound_webhook(token=inbound.token)
        with pytest.raises(AutomationWebhookNotFoundError):
            await service.load_inbound_webhook(token="nope")


@pytest.mark.asyncio
async def test_verify_signature_match_and_mismatch(webhook_db):
    ids = webhook_db["ids"]
    async with webhook_db["async_sessionmaker"]() as session:
        service = AutomationWebhookService(session)
        webhook, _t, secret = await service.create_webhook(
            team_id=ids["team_id"],
            direction=AutomationWebhookDirection.INBOUND,
            name="In",
            target_url=None,
            events=[],
            is_active=True,
            actor="1",
        )
        body = b'{"tcrt_run_id":"corr-aaa","status":"SUCCEEDED"}'

        # exact match
        service.verify_signature(webhook=webhook, body=body, signature=_sign(body, secret))
        # accept sha256= prefix
        service.verify_signature(webhook=webhook, body=body, signature=f"sha256={_sign(body, secret)}")

        with pytest.raises(AutomationWebhookSignatureError):
            service.verify_signature(webhook=webhook, body=body, signature="deadbeef")
        with pytest.raises(AutomationWebhookSignatureError):
            service.verify_signature(webhook=webhook, body=body, signature=None)


@pytest.mark.asyncio
async def test_apply_run_status_matches_by_correlation_and_advances(webhook_db):
    ids = webhook_db["ids"]
    async with webhook_db["async_sessionmaker"]() as session:
        service = AutomationWebhookService(session)
        webhook, _t, _s = await service.create_webhook(
            team_id=ids["team_id"],
            direction=AutomationWebhookDirection.INBOUND,
            name="In",
            target_url=None,
            events=[],
            is_active=True,
            actor="1",
        )
        payload = {
            "tcrt_run_id": ids["correlation"],
            "status": "SUCCEEDED",
            "external_run_url": "https://ci.example/run/77",
            "started_at": "2026-01-01T00:00:00Z",
            "finished_at": "2026-01-01T00:01:30Z",
            "duration_ms": 90000,
            "report_url": "https://allure.example/77",
        }
        run = await service.apply_run_status(webhook=webhook, payload=payload)

    assert run.status == AutomationRunStatus.SUCCEEDED
    assert run.external_run_url == "https://ci.example/run/77"
    assert run.report_url == "https://allure.example/77"
    assert run.duration_ms == 90000
    assert run.finished_at is not None
    assert run.last_synced_at is not None
    assert webhook.last_triggered_at is not None


@pytest.mark.asyncio
async def test_apply_run_status_matches_by_external_id_fallback(webhook_db):
    ids = webhook_db["ids"]
    async with webhook_db["async_sessionmaker"]() as session:
        service = AutomationWebhookService(session)
        webhook, _t, _s = await service.create_webhook(
            team_id=ids["team_id"],
            direction=AutomationWebhookDirection.INBOUND,
            name="In",
            target_url=None,
            events=[],
            is_active=True,
            actor="1",
        )
        run = await service.apply_run_status(
            webhook=webhook,
            payload={"external_run_id": "queue:1", "status": "FAILED"},
        )
    assert run.status == AutomationRunStatus.FAILED


@pytest.mark.asyncio
async def test_apply_run_status_no_match_raises(webhook_db):
    ids = webhook_db["ids"]
    async with webhook_db["async_sessionmaker"]() as session:
        service = AutomationWebhookService(session)
        webhook, _t, _s = await service.create_webhook(
            team_id=ids["team_id"],
            direction=AutomationWebhookDirection.INBOUND,
            name="In",
            target_url=None,
            events=[],
            is_active=True,
            actor="1",
        )
        with pytest.raises(AutomationRunForWebhookNotFoundError):
            await service.apply_run_status(
                webhook=webhook,
                payload={"tcrt_run_id": "nonexistent", "status": "FAILED"},
            )
        with pytest.raises(AutomationRunForWebhookNotFoundError):
            await service.apply_run_status(
                webhook=webhook,
                payload={"status": "FAILED"},
            )


@pytest.mark.asyncio
async def test_apply_run_status_terminal_run_does_not_revert(webhook_db):
    ids = webhook_db["ids"]
    async with webhook_db["async_sessionmaker"]() as session:
        service = AutomationWebhookService(session)
        webhook, _t, _s = await service.create_webhook(
            team_id=ids["team_id"],
            direction=AutomationWebhookDirection.INBOUND,
            name="In",
            target_url=None,
            events=[],
            is_active=True,
            actor="1",
        )
        # First mark as SUCCEEDED
        await service.apply_run_status(
            webhook=webhook,
            payload={"tcrt_run_id": ids["correlation"], "status": "SUCCEEDED"},
        )
        # Then send a stale RUNNING payload — should keep SUCCEEDED
        run = await service.apply_run_status(
            webhook=webhook,
            payload={"tcrt_run_id": ids["correlation"], "status": "RUNNING"},
        )
    assert run.status == AutomationRunStatus.SUCCEEDED


@pytest.mark.asyncio
async def test_regenerate_secret_replaces_secret_only(webhook_db):
    ids = webhook_db["ids"]
    async with webhook_db["async_sessionmaker"]() as session:
        service = AutomationWebhookService(session)
        webhook, token, original_secret = await service.create_webhook(
            team_id=ids["team_id"],
            direction=AutomationWebhookDirection.INBOUND,
            name="In",
            target_url=None,
            events=[],
            is_active=True,
            actor="1",
        )
        rotated, new_secret = await service.regenerate_secret(
            team_id=ids["team_id"],
            webhook_id=webhook.id,
            actor="1",
        )

    assert rotated.token == token
    assert rotated.secret == new_secret
    assert new_secret != original_secret

