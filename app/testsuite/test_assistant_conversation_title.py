"""Regression tests for automatic conversation title generation (add-global-ai-assistant, tasks.md §15)."""
from __future__ import annotations

import asyncio
import sys
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import select, update

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import AssistantConfig
from app.database import get_db
from app.db_access.main import get_main_access_boundary
from app.main import app
from app.models.database_models import AssistantConversation, AssistantTurn
from app.services.assistant import conversation_service as conversation_service_module
from app.services.assistant.conversation_service import ConversationService
from app.testsuite.db_test_helpers import (
    create_managed_test_database,
    dispose_managed_test_database,
    install_main_database_overrides,
)


@pytest.fixture
def title_db(tmp_path, monkeypatch):
    bundle = create_managed_test_database(tmp_path / "assistant_title.db")
    install_main_database_overrides(
        monkeypatch=monkeypatch,
        app=app,
        get_db_dependency=get_db,
        async_engine=bundle["async_engine"],
        async_session_factory=bundle["async_session_factory"],
    )
    yield bundle
    dispose_managed_test_database(bundle)


def _svc(cfg=None):
    cfg = cfg or AssistantConfig()
    return ConversationService(get_main_access_boundary(), cfg)


async def _get_conversation(conversation_id: int):
    boundary = get_main_access_boundary()

    async def _get(session):
        return await session.get(AssistantConversation, conversation_id)

    return await boundary.run_read(_get)


# ---------------------------------------------------------------------------
# maybe_generate_title / set_title_if_absent 單元行為
# ---------------------------------------------------------------------------


def test_maybe_generate_title_uses_llm_summary_of_first_exchange(title_db, monkeypatch):
    conv_svc = _svc()

    async def _fake_generate_title(*, user_text, assistant_text, max_chars):
        assert user_text == "幫我查一下登入模組的失敗案例"
        assert assistant_text == "已找到 3 筆登入模組的失敗案例。"
        return "查詢登入模組失敗案例"

    monkeypatch.setattr(
        conversation_service_module.title_service, "generate_title", _fake_generate_title
    )

    async def _run():
        conv = await conv_svc.create_conversation(user_id=1, scope_type="global", team_id=None)
        assert conv.title is None
        turn = (
            await conv_svc.start_turn(
                conversation=conv,
                client_message_id="m1",
                text="幫我查一下登入模組的失敗案例",
                attachment_digests=[],
            )
        ).turn
        await conv_svc.append_message(
            turn_id=turn.id, role="assistant", content="已找到 3 筆登入模組的失敗案例。"
        )

        await conv_svc.maybe_generate_title(conv.conversation_key)

        reloaded = await _get_conversation(conv.id)
        assert reloaded.title == "查詢登入模組失敗案例"

    asyncio.run(_run())


def test_maybe_generate_title_falls_back_when_llm_unavailable(title_db, monkeypatch):
    conv_svc = _svc(AssistantConfig(title_max_chars=10))

    async def _fake_generate_title(**kwargs):
        return None  # 模擬未設定 OpenRouter key 或呼叫失敗

    monkeypatch.setattr(
        conversation_service_module.title_service, "generate_title", _fake_generate_title
    )

    async def _run():
        conv = await conv_svc.create_conversation(user_id=1, scope_type="global", team_id=None)
        turn = (
            await conv_svc.start_turn(
                conversation=conv,
                client_message_id="m1",
                text="這是一段很長的使用者輸入文字用來測試截斷邏輯是否正確運作",
                attachment_digests=[],
            )
        ).turn
        await conv_svc.append_message(turn_id=turn.id, role="assistant", content="好的，我來處理。")

        await conv_svc.maybe_generate_title(conv.conversation_key)

        reloaded = await _get_conversation(conv.id)
        assert reloaded.title is not None
        assert reloaded.title == "這是一段很長的使用者…"  # 10 字截斷 + 刪節號
        assert len(reloaded.title) == 11

    asyncio.run(_run())


def test_maybe_generate_title_does_not_overwrite_existing_title(title_db, monkeypatch):
    conv_svc = _svc()

    def _fail_if_called(**kwargs):
        raise AssertionError("title 已存在時不應呼叫 LLM 摘要")

    monkeypatch.setattr(conversation_service_module.title_service, "generate_title", _fail_if_called)

    async def _run():
        conv = await conv_svc.create_conversation(
            user_id=1, scope_type="global", team_id=None, title="使用者自訂標題"
        )
        turn = (
            await conv_svc.start_turn(
                conversation=conv, client_message_id="m1", text="hello", attachment_digests=[]
            )
        ).turn
        await conv_svc.append_message(turn_id=turn.id, role="assistant", content="hi there")

        await conv_svc.maybe_generate_title(conv.conversation_key)

        reloaded = await _get_conversation(conv.id)
        assert reloaded.title == "使用者自訂標題"

    asyncio.run(_run())


def test_maybe_generate_title_skips_llm_when_only_tool_call_placeholder_exists(title_db, monkeypatch):
    """write-first turn：唯一的 assistant 訊息是 tool-call 佔位列（content=None），不得被誤用為摘要輸入。"""
    conv_svc = _svc()

    def _fail_if_called(**kwargs):
        raise AssertionError("assistant 尚無純文字回覆時不應呼叫 LLM 摘要")

    monkeypatch.setattr(conversation_service_module.title_service, "generate_title", _fail_if_called)

    async def _run():
        conv = await conv_svc.create_conversation(user_id=1, scope_type="global", team_id=None)
        turn = (
            await conv_svc.start_turn(
                conversation=conv, client_message_id="m1", text="幫我建立一個 test run", attachment_digests=[]
            )
        ).turn
        await conv_svc.append_message(
            turn_id=turn.id,
            role="assistant",
            content=None,
            tool_calls_json='[{"id": "call_1", "name": "create_test_run_config", "arguments": {}}]',
            llm_tool_call_id="call_1",
            tool_name="create_test_run_config",
        )

        await conv_svc.maybe_generate_title(conv.conversation_key)

        reloaded = await _get_conversation(conv.id)
        assert reloaded.title is not None
        assert reloaded.title.startswith("幫我建立一個 test run")

    asyncio.run(_run())


def test_set_title_if_absent_is_cas_by_conversation_key(title_db):
    conv_svc = _svc()

    async def _run():
        conv = await conv_svc.create_conversation(user_id=1, scope_type="global", team_id=None)
        first = await conv_svc.set_title_if_absent(conv.conversation_key, "第一次寫入")
        assert first is True
        second = await conv_svc.set_title_if_absent(conv.conversation_key, "第二次寫入")
        assert second is False

        reloaded = await _get_conversation(conv.id)
        assert reloaded.title == "第一次寫入"

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# 5 個終結 turn 的路徑：只在 turn_seq==0 觸發、且維持既有回傳契約
# ---------------------------------------------------------------------------


def _capture_fired_keys(monkeypatch):
    fired: list[str] = []

    def _record(service, conversation_key):
        fired.append(conversation_key)

    monkeypatch.setattr(
        conversation_service_module, "_fire_and_forget_title_generation", _record
    )
    return fired


def test_complete_turn_release_lease_fires_only_for_first_turn(title_db, monkeypatch):
    fired = _capture_fired_keys(monkeypatch)
    conv_svc = _svc()

    async def _run():
        conv = await conv_svc.create_conversation(user_id=1, scope_type="global", team_id=None)
        first_turn = (
            await conv_svc.start_turn(
                conversation=conv, client_message_id="m1", text="hello", attachment_digests=[]
            )
        ).turn
        await conv_svc.complete_turn_release_lease(
            conversation_id=conv.id,
            turn_id=first_turn.id,
            turn_key=first_turn.turn_key,
            user_id=1,
            status="completed",
        )
        assert fired == [conv.conversation_key]

        conv = await conv_svc.get_conversation_owned(user_id=1, conversation_id=conv.id)
        second_turn = (
            await conv_svc.start_turn(
                conversation=conv, client_message_id="m2", text="hello again", attachment_digests=[]
            )
        ).turn
        await conv_svc.complete_turn_release_lease(
            conversation_id=conv.id,
            turn_id=second_turn.id,
            turn_key=second_turn.turn_key,
            user_id=1,
            status="completed",
        )
        assert fired == [conv.conversation_key]  # 第二輪不再觸發

    asyncio.run(_run())


def test_create_pending_action_and_complete_turn_preserves_return_contract_and_fires_title(
    title_db, monkeypatch
):
    fired = _capture_fired_keys(monkeypatch)
    conv_svc = _svc()

    async def _run():
        conv = await conv_svc.create_conversation(user_id=1, scope_type="global", team_id=None)
        turn = (
            await conv_svc.start_turn(
                conversation=conv, client_message_id="m1", text="建立一個 test run", attachment_digests=[]
            )
        ).turn
        from app.services.assistant import ids

        execution_key = ids.generate_execution_key()
        pending = await conv_svc.create_pending_action_and_complete_turn(
            conversation_id=conv.id,
            turn_id=turn.id,
            turn_key=turn.turn_key,
            user_id=1,
            tool_name="create_test_run_config",
            arguments_redacted_json="{}",
            arguments_for_history={},
            execution_payload_json=None,
            execution_payload_encrypted=False,
            confirmation_summary={"action": "create", "target_label": "Run"},
            confirmation_fingerprint="fp-1",
            pending_ttl_seconds=600,
            execution_key=execution_key,
        )

        # 對外回傳契約不變：仍是 AssistantPendingAction，既有呼叫端／測試依賴 pending.id 不受影響。
        assert pending.id is not None
        assert pending.tool_name == "create_test_run_config"
        assert fired == [conv.conversation_key]

    asyncio.run(_run())


def test_recover_orphan_turns_preserves_int_return_and_fires_title_for_first_turn(title_db, monkeypatch):
    fired = _capture_fired_keys(monkeypatch)
    conv_svc = _svc()

    async def _run():
        conv = await conv_svc.create_conversation(user_id=1, scope_type="global", team_id=None)
        turn = (
            await conv_svc.start_turn(
                conversation=conv, client_message_id="m1", text="hello", attachment_digests=[]
            )
        ).turn

        boundary = get_main_access_boundary()
        from app.services.assistant.conversation_service import _db_now as db_now_fn

        async def _age(session):
            db_now = await db_now_fn(session)
            past = db_now - timedelta(seconds=120)
            await session.execute(
                update(AssistantConversation)
                .where(AssistantConversation.id == conv.id)
                .values(turn_lease_expires_at=past)
            )

        await boundary.run_write(_age)

        recovered = await conv_svc.recover_orphan_turns()

        # 對外回傳契約不變：retention.py 用 %d 格式化、既有測試斷言 int，不能變成 list。
        assert recovered == 1
        assert isinstance(recovered, int)
        assert fired == [conv.conversation_key]

        async def _get_turn(session):
            return await session.get(AssistantTurn, turn.id)

        turn_final = await boundary.run_read(_get_turn)
        assert turn_final.status == "failed"

    asyncio.run(_run())


def test_reject_write_before_pending_fires_title_only_when_terminate_turn_true(title_db, monkeypatch):
    fired = _capture_fired_keys(monkeypatch)
    conv_svc = _svc()

    async def _reject(conv, terminate_turn: bool):
        turn = (
            await conv_svc.start_turn(
                conversation=conv,
                client_message_id=f"m-{terminate_turn}",
                text="幫我刪除所有 test case",
                attachment_digests=[],
            )
        ).turn
        await conv_svc.reject_write_before_pending(
            conversation_id=conv.id,
            turn_id=turn.id,
            turn_key=turn.turn_key,
            user_id=1,
            llm_tool_call_id="call-1",
            tool_name="delete_test_case",
            arguments_for_history={},
            synthetic_result={"status": "rejected", "code": "schema_invalid"},
            terminate_turn=terminate_turn,
        )

    async def _run():
        conv_true = await conv_svc.create_conversation(user_id=1, scope_type="global", team_id=None)
        await _reject(conv_true, True)
        assert fired == [conv_true.conversation_key]

        conv_false = await conv_svc.create_conversation(user_id=1, scope_type="global", team_id=None)
        await _reject(conv_false, False)
        # terminate_turn=False：turn 未終結（不可修復性尚未確定），不得觸發標題生成。
        assert fired == [conv_true.conversation_key]

    asyncio.run(_run())


def test_recover_orphan_executing_pending_does_not_refire_for_rebound_continuation_turn(
    title_db, monkeypatch
):
    """執行中 pending 對應的 turn 一定是 claim 時重新綁定的 continuation turn（turn_seq>=1）：
    來源 turn_seq==0 的標題觸發早在 create_pending_action_and_complete_turn 當下就已發生過。"""
    fired = _capture_fired_keys(monkeypatch)
    conv_svc = _svc()

    async def _run():
        from app.services.assistant import ids
        from app.services.assistant.conversation_service import _db_now as db_now_fn

        conv = await conv_svc.create_conversation(user_id=1, scope_type="global", team_id=None)
        source_turn = (
            await conv_svc.start_turn(
                conversation=conv, client_message_id="m1", text="建立一個 test run", attachment_digests=[]
            )
        ).turn
        pending = await conv_svc.create_pending_action_and_complete_turn(
            conversation_id=conv.id,
            turn_id=source_turn.id,
            turn_key=source_turn.turn_key,
            user_id=1,
            tool_name="create_test_run_config",
            arguments_redacted_json="{}",
            arguments_for_history={},
            execution_payload_json=None,
            execution_payload_encrypted=False,
            confirmation_summary={"action": "create", "target_label": "Run"},
            confirmation_fingerprint="fp-1",
            pending_ttl_seconds=600,
            execution_key=ids.generate_execution_key(),
        )
        # 首輪已觸發一次（見 test_create_pending_action_and_complete_turn_* ）。
        assert fired == [conv.conversation_key]

        conv = await conv_svc.get_conversation_owned(user_id=1, conversation_id=conv.id)
        continuation = await conv_svc.claim_pending_for_confirm(
            conversation=conv, action=pending, recomputed_fingerprint="fp-1", tool_timeout_seconds=30
        )
        assert continuation.turn_seq >= 1

        boundary = get_main_access_boundary()

        async def _age(session):
            db_now = await db_now_fn(session)
            past = db_now - timedelta(seconds=120)
            await session.execute(
                update(AssistantConversation)
                .where(AssistantConversation.id == conv.id)
                .values(turn_lease_expires_at=past)
            )
            from app.models.database_models import AssistantPendingAction

            await session.execute(
                update(AssistantPendingAction)
                .where(AssistantPendingAction.id == pending.id)
                .values(execution_deadline=past)
            )

        await boundary.run_write(_age)

        recovered = await conv_svc.recover_orphan_executing_pending()

        assert recovered == 1
        assert isinstance(recovered, int)
        # 沒有第二次觸發：continuation turn 的 turn_seq >= 1，被 guard 正確擋下。
        assert fired == [conv.conversation_key]

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# title_service：LLM 呼叫失敗必須 fallback，不得讓例外外洩（曾發現的 P0）
# ---------------------------------------------------------------------------


def test_generate_title_returns_none_on_unexpected_llm_exception(monkeypatch):
    from app.services.assistant import title_service

    class _BrokenLLMService:
        async def call(self, *, system_prompt, messages, tools):
            raise RuntimeError("connection reset by peer")  # 模擬連線層例外，非 AssistantLLMError 子類

    monkeypatch.setattr(title_service, "get_assistant_llm_service", lambda: _BrokenLLMService())

    async def _run():
        result = await title_service.generate_title(
            user_text="hello", assistant_text="hi there", max_chars=40
        )
        assert result is None

    asyncio.run(_run())
