"""Regression tests for red-team findings RT-001 … RT-008 (add-global-ai-assistant)."""
from __future__ import annotations

import asyncio
import base64
import json
import os
import sys
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import select, update

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.auth.models import UserRole
from app.config import AssistantConfig
from app.database import get_db
from app.db_access.main import get_main_access_boundary
from app.main import app
from app.models.database_models import (
    AssistantPendingAction,
    AssistantRuntimeCounter,
    AssistantTurn,
    Team,
    TestCaseSection,
    TestCaseSet,
)
from app.services.assistant import ids
from app.services.assistant.conversation_service import (
    GLOBAL_ADMISSION_SCOPE_KEY,
    ConversationService,
    user_admission_scope_key,
)
from app.services.assistant.projection import apply_projection, project_and_redact
from app.services.assistant.tool_executor import PendingCreationRequest, ToolExecutor
from app.services.assistant.tool_registry import get_tool_registry
from app.testsuite.db_test_helpers import (
    create_managed_test_database,
    dispose_managed_test_database,
    install_main_database_overrides,
)


@pytest.fixture
def rt_db(tmp_path, monkeypatch):
    bundle = create_managed_test_database(tmp_path / "assistant_rt.db")
    install_main_database_overrides(
        monkeypatch=monkeypatch,
        app=app,
        get_db_dependency=get_db,
        async_engine=bundle["async_engine"],
        async_session_factory=bundle["async_session_factory"],
    )
    with bundle["sync_session_factory"]() as session:
        session.add(Team(id=1, name="ART", description="", wiki_token="wt", test_case_table_id="tbl1"))
        session.commit()
        tcs = TestCaseSet(team_id=1, name="Default", description="", is_default=True)
        session.add(tcs)
        session.flush()
        session.add(TestCaseSection(test_case_set_id=tcs.id, name="Unassigned", level=1, sort_order=0))
        session.commit()
        set_id = tcs.id

    yield {"bundle": bundle, "set_id": set_id}
    dispose_managed_test_database(bundle)


def _svc(cfg=None):
    cfg = cfg or AssistantConfig()
    return ConversationService(get_main_access_boundary(), cfg)


async def _seed_pending(conv_svc: ConversationService, *, user_id: int = 1, team_id: int = 1):
    conv = await conv_svc.create_conversation(user_id=user_id, scope_type="team", team_id=team_id, title="rt")
    turn_result = await conv_svc.start_turn(
        conversation=conv, client_message_id="m-source", text="propose write", attachment_digests=[]
    )
    source_turn = turn_result.turn
    execution_key = ids.generate_execution_key()
    payload = {
        "path_params": {},
        "query_params": {},
        "body_params": {"name": "RT Run", "test_case_set_ids": [1]},
    }
    pending = await conv_svc.create_pending_action_and_complete_turn(
        conversation_id=conv.id,
        turn_id=source_turn.id,
        turn_key=source_turn.turn_key,
        user_id=user_id,
        tool_name="create_test_run_config",
        arguments_redacted_json=json.dumps(payload["body_params"]),
        arguments_for_history=payload["body_params"],
        execution_payload_json=json.dumps(payload),
        execution_payload_encrypted=False,
        confirmation_summary={"action": "create", "target_label": "RT Run"},
        confirmation_fingerprint="fp-stable-001",
        pending_ttl_seconds=600,
        execution_key=execution_key,
    )
    # Re-load conversation (lease/admission released by pending create)
    conv = await conv_svc.get_conversation_owned(user_id=user_id, conversation_id=conv.id)
    return conv, source_turn, pending


async def _counter(session, scope_key: str) -> int:
    row = (
        await session.execute(
            select(AssistantRuntimeCounter.active_count).where(AssistantRuntimeCounter.scope_key == scope_key)
        )
    ).scalar_one_or_none()
    return int(row or 0)


# ---------------------------------------------------------------------------
# RT-001 / RT-002 / RT-003
# ---------------------------------------------------------------------------


def test_claim_increments_admission_and_complete_decrements_to_baseline(rt_db):
    """RT-001: claim Tx A reserves global+user admission; complete releases back to baseline."""
    conv_svc = _svc()

    async def _run():
        conv, _source, pending = await _seed_pending(conv_svc)
        boundary = get_main_access_boundary()

        async def _read_counts(session):
            return (
                await _counter(session, GLOBAL_ADMISSION_SCOPE_KEY),
                await _counter(session, user_admission_scope_key(1)),
            )

        baseline = await boundary.run_read(_read_counts)

        continuation = await conv_svc.claim_pending_for_confirm(
            conversation=conv,
            action=pending,
            recomputed_fingerprint="fp-stable-001",
            tool_timeout_seconds=30,
        )
        after_claim = await boundary.run_read(_read_counts)
        assert after_claim[0] == baseline[0] + 1
        assert after_claim[1] == baseline[1] + 1

        await conv_svc.finalize_confirm_outcome(
            conversation_id=conv.id,
            turn=continuation,
            action_id=pending.id,
            user_id=1,
            outcome_status="succeeded",
            tool_result_payload={"ok": True},
            http_status=201,
        )
        await conv_svc.complete_continuation_turn(
            conversation_id=conv.id,
            turn_id=continuation.id,
            turn_key=continuation.turn_key,
            user_id=1,
            status="completed",
        )
        after_complete = await boundary.run_read(_read_counts)
        assert after_complete == baseline

    asyncio.run(_run())


def test_claim_rebinds_turn_id_clears_payload_and_recovery_marks_unknown(rt_db):
    """RT-002 + RT-003: claim rebinds pending.turn_id, clears payload; orphan recovery → unknown."""
    conv_svc = _svc()

    async def _run():
        conv, source_turn, pending = await _seed_pending(conv_svc)
        source_turn_id = source_turn.id
        assert pending.turn_id == source_turn_id
        assert pending.execution_payload_json is not None

        continuation = await conv_svc.claim_pending_for_confirm(
            conversation=conv,
            action=pending,
            recomputed_fingerprint="fp-stable-001",
            tool_timeout_seconds=30,
        )

        boundary = get_main_access_boundary()

        async def _get_pending(session):
            return await session.get(AssistantPendingAction, pending.id)

        action_after = await boundary.run_read(_get_pending)
        assert action_after.turn_id == continuation.id, "claim must rebind pending.turn_id to continuation"
        assert action_after.turn_id != source_turn_id
        assert action_after.status == "executing"
        assert action_after.execution_payload_json is None, "claim must clear execution_payload_json"
        history = await conv_svc.load_conversation_history_view(conversation_id=conv.id)
        assert not any(row["turn_key"] == continuation.turn_key for row in history)
        assert await conv_svc.get_active_turn_view(conversation_id=conv.id) == {
            "turn_key": continuation.turn_key,
            "status": "running",
        }

        # Force lease + execution deadline into the past so recovery can fence.
        from app.models.database_models import AssistantConversation
        from app.services.assistant.conversation_service import _db_now as db_now_fn

        async def _age(session):
            db_now = await db_now_fn(session)
            past = db_now - timedelta(seconds=120)
            await session.execute(
                update(AssistantPendingAction)
                .where(AssistantPendingAction.id == pending.id)
                .values(execution_deadline=past)
            )
            await session.execute(
                update(AssistantConversation)
                .where(AssistantConversation.id == conv.id)
                .values(turn_lease_expires_at=past)
            )

        await boundary.run_write(_age)

        recovered = await conv_svc.recover_orphan_executing_pending()
        assert recovered == 1

        action_final = await boundary.run_read(_get_pending)
        assert action_final.status == "unknown"
        assert action_final.execution_payload_json is None

        async def _get_turn(session):
            return await session.get(AssistantTurn, continuation.id)

        turn_final = await boundary.run_read(_get_turn)
        assert turn_final.status == "failed"

        events = await conv_svc.get_events_after(turn_id=continuation.id, after_seq=-1)
        assert [event.event_type for event in events] == ["tool_finished", "done"]
        payload = json.loads(events[0].payload_json)
        assert payload["tool_name"] == "create_test_run_config"
        assert payload["outcome"] == "unknown"
        assert payload["result"] == {"status": "unknown", "code": "execution_orphaned"}

    asyncio.run(_run())


def test_recover_orphan_turn_writes_error_and_terminal_done(rt_db):
    """Lease recovery must terminate DB-tail SSE instead of leaving subscribers on keepalive forever."""
    conv_svc = _svc()

    async def _run():
        conv = await conv_svc.create_conversation(user_id=1, scope_type="team", team_id=1, title="orphan")
        turn = (await conv_svc.start_turn(
            conversation=conv, client_message_id="orphan-turn", text="hello", attachment_digests=[]
        )).turn
        boundary = get_main_access_boundary()
        from app.models.database_models import AssistantConversation
        from app.services.assistant.conversation_service import _db_now as db_now_fn

        async def _age(session):
            now = await db_now_fn(session)
            await session.execute(
                update(AssistantConversation)
                .where(AssistantConversation.id == conv.id)
                .values(turn_lease_expires_at=now - timedelta(seconds=120))
            )

        await boundary.run_write(_age)
        assert await conv_svc.recover_orphan_turns() == 1
        events = await conv_svc.get_events_after(turn_id=turn.id, after_seq=-1)
        assert [event.event_type for event in events] == ["error", "done"]
        assert json.loads(events[0].payload_json) == {
            "code": "turn_orphaned",
            "message": "The assistant turn expired before it could finish.",
        }
        assert await conv_svc.is_turn_terminal(turn_id=turn.id) is True

    asyncio.run(_run())


def test_terminal_probe_waits_for_terminal_event_commit(rt_db):
    """A completed row alone must not close DB-tail during the commit gap before `done`."""
    conv_svc = _svc()

    async def _run():
        conv = await conv_svc.create_conversation(user_id=1, scope_type="team", team_id=1, title="terminal gap")
        started = await conv_svc.start_turn(
            conversation=conv, client_message_id="terminal-gap", text="hello", attachment_digests=[]
        )
        await conv_svc.complete_turn_release_lease(
            conversation_id=conv.id,
            turn_id=started.turn.id,
            turn_key=started.turn.turn_key,
            user_id=1,
            status="completed",
        )
        assert await conv_svc.renew_lease(
            conversation_id=conv.id, turn_key=started.turn.turn_key, ttl_seconds=30
        ) is False
        assert await conv_svc.is_turn_terminal(turn_id=started.turn.id) is False
        await conv_svc.append_event(turn_id=started.turn.id, event_type="done", payload=None)
        assert await conv_svc.is_turn_terminal(turn_id=started.turn.id) is True

    asyncio.run(_run())


def test_recover_orphan_turns_skips_executing_pending_continuation(rt_db):
    """RT-002: recover_orphan_turns must not close a turn that still has executing pending."""
    conv_svc = _svc()

    async def _run():
        conv, _source, pending = await _seed_pending(conv_svc)
        continuation = await conv_svc.claim_pending_for_confirm(
            conversation=conv,
            action=pending,
            recomputed_fingerprint="fp-stable-001",
            tool_timeout_seconds=30,
        )
        boundary = get_main_access_boundary()
        from app.models.database_models import AssistantConversation
        from app.services.assistant.conversation_service import _db_now as db_now_fn

        async def _age_lease_only(session):
            db_now = await db_now_fn(session)
            past = db_now - timedelta(seconds=120)
            await session.execute(
                update(AssistantConversation)
                .where(AssistantConversation.id == conv.id)
                .values(turn_lease_expires_at=past)
            )
            # Keep execution_deadline in the future so only recover_orphan_turns would match
            # if it incorrectly included this turn.

        await boundary.run_write(_age_lease_only)

        n = await conv_svc.recover_orphan_turns()
        assert n == 0

        async def _get_pending(session):
            return await session.get(AssistantPendingAction, pending.id)

        action = await boundary.run_read(_get_pending)
        assert action.status == "executing"

        async def _get_turn(session):
            return await session.get(AssistantTurn, continuation.id)

        turn = await boundary.run_read(_get_turn)
        assert turn.status == "running"

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# RT-004
# ---------------------------------------------------------------------------


def test_start_turn_expires_open_pending_with_synthetic_result(rt_db):
    """RT-004: starting a new user message expires existing pending + pairs synthetic tool result."""
    conv_svc = _svc()

    async def _run():
        conv, source_turn, pending = await _seed_pending(conv_svc)
        # New message must supersede pending
        result = await conv_svc.start_turn(
            conversation=conv, client_message_id="m-new", text="never mind, do something else", attachment_digests=[]
        )
        assert result.is_replay is False

        boundary = get_main_access_boundary()

        async def _get_pending(session):
            return await session.get(AssistantPendingAction, pending.id)

        action = await boundary.run_read(_get_pending)
        assert action.status == "expired"
        assert action.execution_payload_json is None

        from app.models.database_models import AssistantMessage

        async def _tool_msgs(session):
            return (
                await session.execute(
                    select(AssistantMessage).where(
                        AssistantMessage.turn_id == source_turn.id,
                        AssistantMessage.role == "tool",
                    )
                )
            ).scalars().all()

        tool_msgs = await boundary.run_read(_tool_msgs)
        assert len(tool_msgs) >= 1
        contents = [json.loads(m.content) for m in tool_msgs if m.content]
        assert any(c.get("status") == "expired" for c in contents)

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# RT-005
# ---------------------------------------------------------------------------


def test_list_projection_filters_fields_on_list_and_items_envelope():
    """RT-005: apply_projection must filter list-of-dicts and {items: [...]} shapes."""
    allowlist = ("record_id", "title", "priority")
    rows = [
        {"record_id": 1, "title": "a", "priority": "P0", "secret": "nope", "internal": True},
        {"record_id": 2, "title": "b", "priority": "P1", "secret": "nope2"},
    ]
    projected = apply_projection(rows, allowlist)
    assert projected == [
        {"record_id": 1, "title": "a", "priority": "P0"},
        {"record_id": 2, "title": "b", "priority": "P1"},
    ]
    assert "secret" not in json.dumps(projected)

    envelope = {"items": rows, "total": 2, "skip": 0, "limit": 10, "extra": "x"}
    projected_env = apply_projection(envelope, allowlist + ("total", "skip", "limit"))
    assert projected_env["total"] == 2
    assert "extra" not in projected_env
    assert projected_env["items"] == projected

    # project_and_redact path used by executor
    result = project_and_redact(rows, allowlist, max_chars=100_000)
    assert all("secret" not in item for item in result)


# ---------------------------------------------------------------------------
# RT-006
# ---------------------------------------------------------------------------


def test_bulk_clone_schema_fields_match_api_model():
    """RT-006: bulk_clone_test_cases body schema uses BulkCloneItem field names."""
    tool = get_tool_registry().get("bulk_clone_test_cases")
    assert tool is not None
    item_props = tool.body_schema["properties"]["items"]["items"]["properties"]
    assert "source_record_id" in item_props
    assert "test_case_number" in item_props
    assert "source_test_case_number" not in item_props
    assert "new_test_case_number" not in item_props
    required = set(tool.body_schema["properties"]["items"]["items"]["required"])
    assert required == {"source_record_id", "test_case_number"}
    assert "created_count" in tool.projection
    assert "cloned" not in tool.projection
    assert "duplicates" in tool.projection


# ---------------------------------------------------------------------------
# RT-007
# ---------------------------------------------------------------------------


def test_sensitive_execution_payload_encrypt_decrypt_roundtrip(rt_db):
    """RT-007: encrypted payload stores raw envelope string; decrypt returns original dict."""
    raw_key = base64.b64encode(os.urandom(32)).decode("ascii")
    cfg = AssistantConfig(payload_encryption_key=raw_key)
    executor = ToolExecutor(
        app=app, main_boundary=get_main_access_boundary(), config=cfg, registry=get_tool_registry()
    )
    tool = get_tool_registry().get("create_test_case")
    sensitive_tool = replace(tool, sensitive_input_paths=("body_params.title",))
    execution_key = "e" * 32

    class _FakeConversation:
        id = 1
        team_id = 1
        scope_type = "team"

    async def _run():
        prepared = await executor.prepare_write_tool(
            sensitive_tool,
            {
                "test_case_number": "TC-ENC-RT",
                "title": "sensitive-title",
                "test_case_set_id": rt_db["set_id"],
            },
            conversation=_FakeConversation(),
            user_id=1,
            role=UserRole.USER,
            execution_key=execution_key,
        )
        assert isinstance(prepared, PendingCreationRequest)
        assert prepared.execution_payload_encrypted is True
        # Must be envelope JSON, not {"_raw": ...}
        envelope = json.loads(prepared.execution_payload_json)
        assert "ciphertext" in envelope
        assert "_raw" not in envelope

        decrypted = executor.decrypt_execution_payload(
            sensitive_tool,
            execution_key=execution_key,
            execution_payload_json=prepared.execution_payload_json,
            encrypted=True,
        )
        assert decrypted["body_params"]["title"] == "sensitive-title"
        assert decrypted["body_params"]["test_case_number"] == "TC-ENC-RT"

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# RT-008
# ---------------------------------------------------------------------------


def test_claim_rejects_when_live_fingerprint_recheck_differs(rt_db):
    """RT-008 / P2-1: live recheck raises ConfirmationStaleError with new card data;
    claim Tx A rolls back (pending stays pending). Caller CAS-updates summary from error."""
    from app.services.assistant.errors import ConfirmationStaleError

    conv_svc = _svc()
    live_summary = {"action": "create", "target_label": "RT Run LIVE"}

    async def _run():
        conv, _source, pending = await _seed_pending(conv_svc)
        old_fp = pending.confirmation_fingerprint

        async def _recheck():
            return "fp-different-live", live_summary

        with pytest.raises(ConfirmationStaleError) as ei:
            await conv_svc.claim_pending_for_confirm(
                conversation=conv,
                action=pending,
                recomputed_fingerprint="fp-stable-001",
                tool_timeout_seconds=30,
                live_fingerprint_recheck=_recheck,
            )

        assert ei.value.new_fingerprint == "fp-different-live"
        assert ei.value.new_summary == live_summary

        boundary = get_main_access_boundary()

        async def _get_pending(session):
            return await session.get(AssistantPendingAction, pending.id)

        action = await boundary.run_read(_get_pending)
        assert action.status == "pending"
        assert action.execution_payload_json is not None
        assert action.confirmation_fingerprint == old_fp, "claim Tx A must roll back without mutating card"

        # API-layer path: CAS update card from error payload (same as pre-claim STALE).
        updated = await conv_svc.update_pending_summary_cas(
            action_id=pending.id,
            old_fingerprint=old_fp,
            new_summary=ei.value.new_summary,
            new_fingerprint=ei.value.new_fingerprint,
        )
        assert updated is True
        action2 = await boundary.run_read(_get_pending)
        assert action2.status == "pending"
        assert action2.confirmation_fingerprint == "fp-different-live"
        assert json.loads(action2.confirmation_summary_json) == live_summary

    asyncio.run(_run())


def test_finalize_confirm_emits_single_tool_finished(rt_db):
    """P2-2: finalize_confirm_outcome is the sole tool_finished emitter for confirm path."""
    from app.models.database_models import AssistantEvent

    conv_svc = _svc()

    async def _run():
        conv, _source, pending = await _seed_pending(conv_svc)
        continuation = await conv_svc.claim_pending_for_confirm(
            conversation=conv,
            action=pending,
            recomputed_fingerprint="fp-stable-001",
            tool_timeout_seconds=30,
        )
        await conv_svc.finalize_confirm_outcome(
            conversation_id=conv.id,
            turn=continuation,
            action_id=pending.id,
            user_id=1,
            outcome_status="succeeded",
            tool_result_payload={"ok": True},
            http_status=201,
        )

        boundary = get_main_access_boundary()

        async def _events(session):
            return (
                await session.execute(
                    select(AssistantEvent)
                    .where(AssistantEvent.turn_id == continuation.id)
                    .order_by(AssistantEvent.seq)
                )
            ).scalars().all()

        events = await boundary.run_read(_events)
        finished = [e for e in events if e.event_type == "tool_finished"]
        assert len(finished) == 1
        payload = json.loads(finished[0].payload_json)
        assert payload["tool_name"] == "create_test_run_config"
        assert payload["outcome"] == "succeeded"
        assert payload["status"] == "succeeded"
        assert payload["http_status"] == 201
        assert payload["result"] == {"ok": True}

    asyncio.run(_run())


def test_confirm_decrypt_failure_expires_pending(rt_db, monkeypatch):
    """P2-3: corrupt execution_payload on confirm fail-closes with expire + 409, not bare 500."""
    from types import SimpleNamespace

    from fastapi.testclient import TestClient

    from app.auth.dependencies import get_current_user
    from app.config import settings
    from app.main import app
    import app.services.assistant.assistant_llm_service as llm_mod

    class _CfgLLM:
        def is_configured(self):
            return True

    conv_svc = _svc()
    conv, _source, pending = asyncio.run(_seed_pending(conv_svc))
    boundary = get_main_access_boundary()

    async def _corrupt(session):
        row = await session.get(AssistantPendingAction, pending.id)
        row.execution_payload_json = "not-valid-json{{{"
        row.execution_payload_encrypted = False

    asyncio.run(boundary.run_write(_corrupt))

    monkeypatch.setattr(settings.ai.assistant, "enabled", True)
    monkeypatch.setattr(llm_mod, "_service_singleton", _CfgLLM())
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=1, username="rt-tester", role=UserRole.USER
    )
    try:
        client = TestClient(app)
        r = client.post(
            f"/api/assistant/conversations/{conv.id}/actions/{pending.id}/confirm",
            headers={"Authorization": "Bearer dummy"},
        )
        assert r.status_code == 409, r.text
        assert r.json()["detail"]["code"] == "EXECUTION_PAYLOAD_DECRYPT_FAILED"

        async def _get_pending(session):
            return await session.get(AssistantPendingAction, pending.id)

        action = asyncio.run(boundary.run_read(_get_pending))
        assert action.status == "expired"
        assert action.execution_payload_json is None
    finally:
        app.dependency_overrides.pop(get_current_user, None)
