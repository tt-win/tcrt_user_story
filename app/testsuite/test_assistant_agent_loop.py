"""assistant agent loop 測試（task 8.4；spec assistant-agent-loop）。

在 service 層（不經 HTTP/SSE）直接驅動 `run_agent_turn`/`_run_llm_loop`，以假 LLM
（`monkeypatch.setattr(AssistantLLMService, "call", ...)`）控制多輪 tool-call 腳本，
斷言 DB 內 turn/message/event 的最終狀態。跨 worker DB-tail 重連／disconnect 不取消
runner 屬 SSE/API 層行為，覆蓋於 test_assistant_conversations_api.py。
"""
from __future__ import annotations

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from types import SimpleNamespace

import pytest

from app.auth.dependencies import get_current_user
from app.auth.models import UserRole
from app.config import AssistantConfig
from app.database import get_db
from app.db_access.main import get_main_access_boundary
from app.main import app
from app.models.database_models import Team, TestCaseSet, TestCaseSection
from app.services.assistant import assistant_agent_service as agent_svc
from app.services.assistant import history_builder
from app.services.assistant.assistant_llm_service import (
    AssistantLLMContextLengthError,
    AssistantLLMError,
    AssistantLLMResult,
    AssistantLLMService,
    ParsedToolCall,
)
from app.services.assistant.conversation_service import ConversationService
from app.services.assistant.tool_executor import ToolExecutor
from app.services.assistant.tool_registry import get_tool_registry
from app.testsuite.db_test_helpers import (
    create_managed_test_database,
    dispose_managed_test_database,
    install_main_database_overrides,
)


class _ScriptedLLM:
    """依序回放腳本化結果；腳本用完後回傳純文字終止，避免測試因迴圈邏輯錯誤而真的無限跑。"""

    def __init__(self, script):
        self.script = list(script)
        self.calls = 0

    async def call(self, *, system_prompt, messages, tools):
        self.calls += 1
        if self.script:
            item = self.script.pop(0)
            if isinstance(item, Exception):
                raise item
            return item
        return AssistantLLMResult(content="(fallback) done", tool_calls=[])


@pytest.fixture
def agent_db(tmp_path, monkeypatch):
    bundle = create_managed_test_database(tmp_path / "assistant_agent_loop.db")
    install_main_database_overrides(
        monkeypatch=monkeypatch,
        app=app,
        get_db_dependency=get_db,
        async_engine=bundle["async_engine"],
        async_session_factory=bundle["async_session_factory"],
    )
    # 工具的 read/confirm 執行皆透過 ASGI loopback 打真實 endpoint，需要一個已認證身份
    # （比照 repo 既有測試慣例：override get_current_user，不走真 JWT）。
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=1, username="agent-loop-tester", role=UserRole.USER)

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

    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_current_user, None)
    dispose_managed_test_database(bundle)


def _make_services(cfg=None):
    cfg = cfg or AssistantConfig()
    boundary = get_main_access_boundary()
    registry = get_tool_registry()
    executor = ToolExecutor(app=app, main_boundary=boundary, config=cfg, registry=registry)
    conv_svc = ConversationService(boundary, cfg)
    return executor, conv_svc, registry, cfg


def _install_llm(monkeypatch, script):
    fake = _ScriptedLLM(script)

    async def _call(self, *, system_prompt, messages, tools):
        return await fake.call(system_prompt=system_prompt, messages=messages, tools=tools)

    monkeypatch.setattr(AssistantLLMService, "call", _call)
    return fake


async def _new_turn(conv_svc, *, team_id=1, text="hi", client_message_id="m1"):
    conv = await conv_svc.create_conversation(user_id=1, scope_type="team", team_id=team_id, title="t")
    result = await conv_svc.start_turn(conversation=conv, client_message_id=client_message_id, text=text, attachment_digests=[])
    return conv, result.turn


async def test_read_chain_then_write_creates_pending_and_stops(agent_db, monkeypatch):
    executor, conv_svc, registry, cfg = _make_services()
    llm = _install_llm(monkeypatch, [
        AssistantLLMResult(content=None, tool_calls=[ParsedToolCall(provider_tool_call_id="p1", name="list_test_cases", arguments={"limit": 5})]),
        AssistantLLMResult(content=None, tool_calls=[ParsedToolCall(
            provider_tool_call_id="p2", name="create_test_run_config",
            arguments={"name": "Agent Loop Run", "test_case_set_ids": [agent_db["set_id"]]},
        )]),
    ])
    conv, turn = await _new_turn(conv_svc)
    await agent_svc.run_agent_turn(
        conversation=conv, turn=turn, user_id=1, role=UserRole.USER, jwt="fake",
        conversation_service=conv_svc, executor=executor, llm_service=AssistantLLMService(), registry=registry, config=cfg,
    )
    assert llm.calls == 2, "read tool then write tool should each trigger one LLM call"
    turn_after = await conv_svc.get_turn_owned(user_id=1, conversation_id=conv.id, turn_key=turn.turn_key)
    assert turn_after.status == "completed"
    events = await conv_svc.get_events_after(turn_id=turn.id, after_seq=-1)
    event_types = [e.event_type for e in events]
    assert "confirmation_required" in event_types
    assert event_types[-1] == "done"


async def test_max_iterations_terminates_without_executing_further_tools(agent_db, monkeypatch):
    cfg = AssistantConfig(max_iterations=3)
    executor, conv_svc, registry, _ = _make_services(cfg)
    llm = _install_llm(monkeypatch, [
        AssistantLLMResult(content=None, tool_calls=[ParsedToolCall(provider_tool_call_id=f"p{i}", name="list_test_cases", arguments={"limit": 1})])
        for i in range(20)
    ])
    conv, turn = await _new_turn(conv_svc)
    await agent_svc.run_agent_turn(
        conversation=conv, turn=turn, user_id=1, role=UserRole.USER, jwt="fake",
        conversation_service=conv_svc, executor=executor, llm_service=AssistantLLMService(), registry=registry, config=cfg,
    )
    assert llm.calls == cfg.max_iterations, f"expected exactly {cfg.max_iterations} LLM calls, got {llm.calls}"
    turn_after = await conv_svc.get_turn_owned(user_id=1, conversation_id=conv.id, turn_key=turn.turn_key)
    assert turn_after.status == "completed", "hitting the cap is a graceful stop, not a failure"


async def test_unknown_tool_name_is_recoverable_not_fatal(agent_db, monkeypatch):
    executor, conv_svc, registry, cfg = _make_services()
    llm = _install_llm(monkeypatch, [
        AssistantLLMResult(content=None, tool_calls=[ParsedToolCall(provider_tool_call_id="p1", name="this_tool_does_not_exist", arguments={})]),
        AssistantLLMResult(content="sorry, cannot do that", tool_calls=[]),
    ])
    conv, turn = await _new_turn(conv_svc)
    await agent_svc.run_agent_turn(
        conversation=conv, turn=turn, user_id=1, role=UserRole.USER, jwt="fake",
        conversation_service=conv_svc, executor=executor, llm_service=AssistantLLMService(), registry=registry, config=cfg,
    )
    assert llm.calls == 2, "unknown-tool rejection must be fixable and let the loop continue"
    turn_after = await conv_svc.get_turn_owned(user_id=1, conversation_id=conv.id, turn_key=turn.turn_key)
    assert turn_after.status == "completed"
    history = await conv_svc.load_conversation_history_view(conversation_id=conv.id)
    tool_messages = [m for m in history if m["role"] == "tool"]
    assert any("unknown_tool" in (m["content"] or "") for m in tool_messages)


async def test_cancel_requested_before_first_llm_call_stops_immediately(agent_db, monkeypatch):
    executor, conv_svc, registry, cfg = _make_services()
    llm = _install_llm(monkeypatch, [AssistantLLMResult(content="should never run", tool_calls=[])])
    conv, turn = await _new_turn(conv_svc)
    await conv_svc.request_cancel(turn_id=turn.id)
    await agent_svc.run_agent_turn(
        conversation=conv, turn=turn, user_id=1, role=UserRole.USER, jwt="fake",
        conversation_service=conv_svc, executor=executor, llm_service=AssistantLLMService(), registry=registry, config=cfg,
    )
    assert llm.calls == 0, "cancelled before the loop starts must never call the LLM"
    turn_after = await conv_svc.get_turn_owned(user_id=1, conversation_id=conv.id, turn_key=turn.turn_key)
    assert turn_after.status == "cancelled"
    events = await conv_svc.get_events_after(turn_id=turn.id, after_seq=-1)
    assert [e.event_type for e in events] == ["cancelled"]


async def test_viewer_role_write_tool_filtered_from_catalog(agent_db, monkeypatch):
    """VIEWER 角色的工具目錄預過濾（design D2）：write 工具在迴圈層級就不在目錄內，
    LLM 呼叫它會被視為 unknown_tool（縱深防禦，非僅靠 executor 的 permission 檢查）。"""
    executor, conv_svc, registry, cfg = _make_services()
    llm = _install_llm(monkeypatch, [
        AssistantLLMResult(content=None, tool_calls=[ParsedToolCall(provider_tool_call_id="p1", name="create_test_run_config", arguments={"name": "x"})]),
        AssistantLLMResult(content="cannot write as viewer", tool_calls=[]),
    ])
    conv, turn = await _new_turn(conv_svc)
    await agent_svc.run_agent_turn(
        conversation=conv, turn=turn, user_id=1, role=UserRole.VIEWER, jwt="fake",
        conversation_service=conv_svc, executor=executor, llm_service=AssistantLLMService(), registry=registry, config=cfg,
    )
    turn_after = await conv_svc.get_turn_owned(user_id=1, conversation_id=conv.id, turn_key=turn.turn_key)
    assert turn_after.status == "completed"
    history = await conv_svc.load_conversation_history_view(conversation_id=conv.id)
    tool_messages = [m for m in history if m["role"] == "tool"]
    assert any("unknown_tool" in (m["content"] or "") for m in tool_messages), (
        "write tool must not even be reachable for VIEWER at the catalog level"
    )


async def test_stale_lease_owner_stops_loop_without_further_writes(agent_db, monkeypatch):
    """stale runner fencing：lease 被搶走（active_turn_key 換成別的 owner）後，
    `_renew_or_stop` 續租必失敗，迴圈須立即停止，不得繼續呼叫 LLM 或寫入下一步。"""
    from sqlalchemy import update
    from app.models.database_models import AssistantConversation

    executor, conv_svc, registry, cfg = _make_services()
    llm = _install_llm(monkeypatch, [
        AssistantLLMResult(content=None, tool_calls=[ParsedToolCall(provider_tool_call_id="p1", name="list_test_cases", arguments={"limit": 1})]),
    ])
    conv, turn = await _new_turn(conv_svc)

    async def _steal_lease(session):
        await session.execute(
            update(AssistantConversation).where(AssistantConversation.id == conv.id).values(active_turn_key="someone-else-turn-key")
        )

    boundary = get_main_access_boundary()
    await boundary.run_write(_steal_lease)

    await agent_svc.run_agent_turn(
        conversation=conv, turn=turn, user_id=1, role=UserRole.USER, jwt="fake",
        conversation_service=conv_svc, executor=executor, llm_service=AssistantLLMService(), registry=registry, config=cfg,
    )
    assert llm.calls == 0, "losing the lease before the first LLM call must stop the loop immediately"


async def test_context_length_error_retries_once_then_terminates(agent_db, monkeypatch):
    """provider context 過長只安全退讓一次（design D4）：第二次仍失敗即終止，不循環重試。"""
    executor, conv_svc, registry, cfg = _make_services()
    llm = _install_llm(monkeypatch, [
        AssistantLLMContextLengthError("too long"),
        AssistantLLMContextLengthError("still too long"),
    ])
    conv, turn = await _new_turn(conv_svc)
    await agent_svc.run_agent_turn(
        conversation=conv, turn=turn, user_id=1, role=UserRole.USER, jwt="fake",
        conversation_service=conv_svc, executor=executor, llm_service=AssistantLLMService(), registry=registry, config=cfg,
    )
    assert llm.calls == 2, "expected exactly one retry after the first context-length error"
    turn_after = await conv_svc.get_turn_owned(user_id=1, conversation_id=conv.id, turn_key=turn.turn_key)
    assert turn_after.status == "failed"
    events = await conv_svc.get_events_after(turn_id=turn.id, after_seq=-1)
    assert [e.event_type for e in events] == ["message_start", "error", "done"]


async def test_generic_llm_error_terminates_turn_as_failed(agent_db, monkeypatch):
    executor, conv_svc, registry, cfg = _make_services()
    llm = _install_llm(monkeypatch, [AssistantLLMError("provider exploded")])
    conv, turn = await _new_turn(conv_svc)
    await agent_svc.run_agent_turn(
        conversation=conv, turn=turn, user_id=1, role=UserRole.USER, jwt="fake",
        conversation_service=conv_svc, executor=executor, llm_service=AssistantLLMService(), registry=registry, config=cfg,
    )
    assert llm.calls == 1
    turn_after = await conv_svc.get_turn_owned(user_id=1, conversation_id=conv.id, turn_key=turn.turn_key)
    assert turn_after.status == "failed"


async def test_only_first_tool_call_processed_when_provider_returns_multiple(agent_db, monkeypatch):
    """design D4：一則 response 只處理第一個 tool call，其餘一律丟棄——即使 provider 違反
    parallel_tool_calls=false 回傳多個呼叫。"""
    executor, conv_svc, registry, cfg = _make_services()
    llm = _install_llm(monkeypatch, [
        AssistantLLMResult(content=None, tool_calls=[
            ParsedToolCall(provider_tool_call_id="dup", name="list_test_cases", arguments={"limit": 1}),
            ParsedToolCall(provider_tool_call_id="dup", name="list_test_cases", arguments={"limit": 2}),
            ParsedToolCall(provider_tool_call_id=None, name="list_test_cases", arguments={"limit": 3}),
        ]),
        AssistantLLMResult(content="done", tool_calls=[]),
    ])
    conv, turn = await _new_turn(conv_svc)
    await agent_svc.run_agent_turn(
        conversation=conv, turn=turn, user_id=1, role=UserRole.USER, jwt="fake",
        conversation_service=conv_svc, executor=executor, llm_service=AssistantLLMService(), registry=registry, config=cfg,
    )
    assert llm.calls == 2, "only the first tool call is processed; the response yields exactly one loop iteration for it"
    history = await conv_svc.load_conversation_history_view(conversation_id=conv.id)
    tool_call_messages = [m for m in history if m["role"] == "assistant" and m.get("tool_calls")]
    assert len(tool_call_messages) == 1, "the persisted history must not contain the discarded duplicate tool calls"


async def test_llm_tool_call_id_is_server_normalized_and_unique_even_with_missing_provider_ids(agent_db, monkeypatch):
    """provider 未回傳或重用 call id 時，llm_tool_call_id 仍須由伺服器正規化且對話內唯一。"""
    executor, conv_svc, registry, cfg = _make_services()
    llm = _install_llm(monkeypatch, [
        AssistantLLMResult(content=None, tool_calls=[ParsedToolCall(provider_tool_call_id=None, name="list_test_cases", arguments={"limit": 1})]),
        AssistantLLMResult(content=None, tool_calls=[ParsedToolCall(provider_tool_call_id=None, name="list_test_cases", arguments={"limit": 2})]),
        AssistantLLMResult(content="done", tool_calls=[]),
    ])
    conv, turn = await _new_turn(conv_svc)
    await agent_svc.run_agent_turn(
        conversation=conv, turn=turn, user_id=1, role=UserRole.USER, jwt="fake",
        conversation_service=conv_svc, executor=executor, llm_service=AssistantLLMService(), registry=registry, config=cfg,
    )
    history = await conv_svc.load_conversation_history_view(conversation_id=conv.id)
    call_ids = [m["llm_tool_call_id"] for m in history if m.get("llm_tool_call_id")]
    assert all(call_ids), "every tool call/result MUST have a non-empty server-normalized id"
    # 每個 assistant tool-call 訊息都要有恰好一個配對的 tool-result 訊息（同一 id 出現兩次）
    from collections import Counter
    counts = Counter(call_ids)
    assert all(c == 2 for c in counts.values()), f"expected each llm_tool_call_id paired exactly twice, got {counts}"
    assert len(set(call_ids)) == len(counts), "ids across different tool calls must be unique"


def test_exchange_group_trim_never_splits_a_tool_call_pair():
    class _Row:
        def __init__(self, role, content=None, tool_calls_json=None, llm_tool_call_id=None, tool_name=None, turn_id=None):
            self.role = role
            self.content = content
            self.tool_calls_json = tool_calls_json
            self.llm_tool_call_id = llm_tool_call_id
            self.tool_name = tool_name
            self.turn_id = turn_id

    import json as _json
    rows = [
        _Row("user", content="q1"),
        _Row("assistant", tool_calls_json=_json.dumps([{"id": "c1", "name": "list_test_cases", "arguments": {}}]), llm_tool_call_id="c1", tool_name="list_test_cases"),
        _Row("tool", content="[]", llm_tool_call_id="c1", tool_name="list_test_cases"),
        _Row("assistant", content="here is your answer"),
    ]
    groups = history_builder.build_exchange_groups(rows)
    assert len(groups) == 3
    assert len(groups[1]) == 2, "assistant tool-call + tool-result must be grouped as one atomic exchange"

    # budget 太小只能留最後一組時，仍不得拆散任何一組
    trimmed = history_builder.trim_by_exchange_groups(groups, max_chars=1)
    assert len(trimmed) >= 1
    roles = [m["role"] for m in trimmed]
    if "tool" in roles:
        assert "assistant" in roles, "tool result 存在時，配對的 assistant tool-call 訊息不得被獨立裁掉"


def test_build_llm_messages_surfaces_attachments_only_for_owning_turn():
    class _Row:
        def __init__(self, role, content=None, tool_calls_json=None, llm_tool_call_id=None, tool_name=None, turn_id=None):
            self.role = role
            self.content = content
            self.tool_calls_json = tool_calls_json
            self.llm_tool_call_id = llm_tool_call_id
            self.tool_name = tool_name
            self.turn_id = turn_id

    rows = [
        _Row("user", content="這是我的檔案", turn_id=1),
        _Row("assistant", content="收到", turn_id=1),
        _Row("user", content="還有別的嗎", turn_id=2),
    ]
    attachments_by_turn = {
        1: [{"attachment_index": 0, "original_name": "evidence.txt", "content_type": "text/plain"}],
    }

    messages = history_builder.build_llm_messages(rows, max_chars=100_000, attachments_by_turn=attachments_by_turn)
    user_msgs = [m for m in messages if m["role"] == "user"]
    assert len(user_msgs) == 2
    assert "file_ref=0" in user_msgs[0]["content"]
    assert "evidence.txt" in user_msgs[0]["content"]
    assert user_msgs[0]["content"].startswith("這是我的檔案"), "使用者原文必須保留在最前面,不得被附件附註取代"
    assert "file_ref" not in user_msgs[1]["content"], "沒有附件的 turn 不得被附加附件附註"


def test_build_llm_messages_without_attachments_by_turn_is_unaffected():
    class _Row:
        def __init__(self, role, content=None, tool_calls_json=None, llm_tool_call_id=None, tool_name=None, turn_id=None):
            self.role = role
            self.content = content
            self.tool_calls_json = tool_calls_json
            self.llm_tool_call_id = llm_tool_call_id
            self.tool_name = tool_name
            self.turn_id = turn_id

    rows = [_Row("user", content="hello", turn_id=1)]
    messages = history_builder.build_llm_messages(rows, max_chars=100_000)
    assert messages == [{"role": "user", "content": "hello"}]


def test_drop_oldest_group_removes_one_whole_group_not_a_partial_message():
    messages = [
        {"role": "user", "content": "q1"},
        {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "q2"},
        {"role": "assistant", "content": "a2"},
    ]
    result = history_builder.drop_oldest_group(messages)
    assert result == messages[1:], "should drop exactly the oldest single-message group"
