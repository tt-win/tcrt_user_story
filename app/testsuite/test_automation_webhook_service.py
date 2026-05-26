import hashlib
import hmac
import json

import pytest

from app.api import automation_webhooks_public
from app.services.automation import webhook_service as webhook_service_module
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
    AutomationWebhookOutboundOnlyError,
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
async def test_dispatch_event_fanout_only_matching_subscriptions(webhook_db, monkeypatch):
    """OUTBOUND webhooks subscribed (or wildcard) to an event get a POST; others are skipped."""
    ids = webhook_db["ids"]
    calls: list[dict] = []

    class _FakeResponse:
        def __init__(self, status_code=204):
            self.status_code = status_code
            self.text = ""
            self.reason_phrase = "No Content"

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, *, content, headers):
            calls.append({"url": url, "event": headers.get("X-TCRT-Event")})
            return _FakeResponse(204)

    monkeypatch.setattr(webhook_service_module.httpx, "AsyncClient", _FakeClient)

    async with webhook_db["async_sessionmaker"]() as session:
        service = AutomationWebhookService(session)
        # subscriber: only "run.completed"
        sub_completed, _t, _s = await service.create_webhook(
            team_id=ids["team_id"],
            direction=AutomationWebhookDirection.OUTBOUND,
            name="completed-only",
            target_url="https://hook.example/completed",
            events=["run.completed"],
            is_active=True,
            actor="1",
        )
        # subscriber: wildcard (empty events)
        sub_wildcard, _t2, _s2 = await service.create_webhook(
            team_id=ids["team_id"],
            direction=AutomationWebhookDirection.OUTBOUND,
            name="wildcard",
            target_url="https://hook.example/all",
            events=[],
            is_active=True,
            actor="1",
        )
        # inactive
        inactive, _t3, _s3 = await service.create_webhook(
            team_id=ids["team_id"],
            direction=AutomationWebhookDirection.OUTBOUND,
            name="inactive",
            target_url="https://hook.example/off",
            events=[],
            is_active=False,
            actor="1",
        )

        deliveries = await service.dispatch_event(
            team_id=ids["team_id"],
            event="run.triggered",
            data={"run_id": 1},
        )

    # wildcard hit, completed-only skipped, inactive skipped
    assert len(deliveries) == 1
    assert deliveries[0]["webhook_id"] == sub_wildcard.id
    assert deliveries[0]["status"] == "OK"
    assert {c["url"] for c in calls} == {"https://hook.example/all"}


@pytest.mark.asyncio
async def test_dispatch_event_records_failure_status(webhook_db, monkeypatch):
    """Non-2xx response should mark webhook last_status with FAILED."""
    ids = webhook_db["ids"]

    class _FakeResponse:
        def __init__(self):
            self.status_code = 500
            self.text = "boom"
            self.reason_phrase = "Internal Server Error"

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, *, content, headers):
            return _FakeResponse()

    monkeypatch.setattr(webhook_service_module.httpx, "AsyncClient", _FakeClient)

    async with webhook_db["async_sessionmaker"]() as session:
        service = AutomationWebhookService(session)
        webhook, _t, _s = await service.create_webhook(
            team_id=ids["team_id"],
            direction=AutomationWebhookDirection.OUTBOUND,
            name="broken",
            target_url="https://broken.example",
            events=[],
            is_active=True,
            actor="1",
        )
        deliveries = await service.dispatch_event(
            team_id=ids["team_id"],
            event="run.completed",
            data={"run_id": 7},
        )
        assert len(deliveries) == 1
        assert deliveries[0]["status"] == "FAILED"
        assert deliveries[0]["status_code"] == 500
        assert webhook.last_status.startswith("RUN.COMPLETED_FAILED")
        rows = await service.list_deliveries(team_id=ids["team_id"], webhook_id=webhook.id)
        assert len(rows) == 1
        assert rows[0].delivery_id == deliveries[0]["delivery_id"]
        assert rows[0].status == "FAILED"
        assert rows[0].status_code == 500
        assert rows[0].response_body == "boom"
        assert json.loads(rows[0].request_body)["event"] == "run.completed"


@pytest.mark.asyncio
async def test_replay_delivery_resends_recorded_payload(webhook_db, monkeypatch):
    ids = webhook_db["ids"]
    calls: list[dict] = []

    class _FakeResponse:
        status_code = 204
        text = ""
        reason_phrase = "No Content"

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, *, content, headers):
            calls.append({"url": url, "payload": json.loads(content), "event": headers.get("X-TCRT-Event")})
            return _FakeResponse()

    monkeypatch.setattr(webhook_service_module.httpx, "AsyncClient", _FakeClient)

    async with webhook_db["async_sessionmaker"]() as session:
        service = AutomationWebhookService(session)
        webhook, _t, _s = await service.create_webhook(
            team_id=ids["team_id"],
            direction=AutomationWebhookDirection.OUTBOUND,
            name="replayable",
            target_url="https://hook.example/replay",
            events=[],
            is_active=True,
            actor="1",
        )
        await service.dispatch_event(
            team_id=ids["team_id"],
            event="run.completed",
            data={"run_id": 7},
        )
        original = (await service.list_deliveries(team_id=ids["team_id"], webhook_id=webhook.id))[0]
        replayed = await service.replay_delivery(team_id=ids["team_id"], delivery_id=original.id)

    assert len(calls) == 2
    assert calls[0]["payload"]["data"] == {"run_id": 7}
    assert calls[1]["payload"]["data"] == {"run_id": 7}
    assert replayed.id != original.id
    assert replayed.status == "OK"
    assert replayed.event == "run.completed"


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


@pytest.mark.asyncio
async def test_send_test_ping_posts_signed_payload_and_updates_status(webhook_db, monkeypatch):
    captured = {}

    class FakeResponse:
        status_code = 202
        text = "accepted"
        reason_phrase = "Accepted"

    class FakeAsyncClient:
        def __init__(self, **kwargs):
            captured["client_kwargs"] = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, *, content, headers):
            captured["url"] = url
            captured["content"] = content
            captured["headers"] = headers
            return FakeResponse()

    monkeypatch.setattr(webhook_service_module.httpx, "AsyncClient", FakeAsyncClient)
    ids = webhook_db["ids"]

    async with webhook_db["async_sessionmaker"]() as session:
        service = AutomationWebhookService(session)
        webhook, _token, secret = await service.create_webhook(
            team_id=ids["team_id"],
            direction=AutomationWebhookDirection.OUTBOUND,
            name="Outbound",
            target_url="https://hooks.example/test",
            events=["run.completed"],
            is_active=True,
            actor="1",
        )
        result = await service.send_test_ping(team_id=ids["team_id"], webhook_id=webhook.id)

    assert result["status"] == "OK"
    assert result["status_code"] == 202
    assert captured["url"] == "https://hooks.example/test"
    assert captured["headers"]["X-TCRT-Event"] == "test"
    assert captured["headers"]["X-TCRT-Signature"] == f"sha256={_sign(captured['content'], secret)}"
    assert webhook.last_status == "TEST_OK 202"
    assert webhook.last_triggered_at is not None


@pytest.mark.asyncio
async def test_send_test_ping_rejects_inbound_webhook(webhook_db):
    ids = webhook_db["ids"]
    async with webhook_db["async_sessionmaker"]() as session:
        service = AutomationWebhookService(session)
        webhook, _token, _secret = await service.create_webhook(
            team_id=ids["team_id"],
            direction=AutomationWebhookDirection.INBOUND,
            name="Inbound",
            target_url=None,
            events=[],
            is_active=True,
            actor="1",
        )
        with pytest.raises(AutomationWebhookOutboundOnlyError):
            await service.send_test_ping(team_id=ids["team_id"], webhook_id=webhook.id)
