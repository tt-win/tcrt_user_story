"""assistant 執行日誌（journal）稽核測試（task 8.7）。

`assistant_tool_executions` 是 at-most-once 與稽核的權威記錄；FK `conversation_id` 為
`ondelete=SET NULL`，但 `source_conversation_key`（不可重用權威鍵）／`source_conversation_id`／
`source_turn_key` 為不可變副本，即使對話被刪除、甚至 SQLite rowid 被重用，仍須可正確追查、
不混淆。
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sys
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import asyncio
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.auth.dependencies import get_current_user
from app.auth.models import UserRole
from app.config import AssistantConfig, settings
from app.database import get_db
from app.db_access.main import get_main_access_boundary
from app.main import app
from app.models.database_models import AssistantToolExecution, Team, TestCaseSet, TestCaseSection
import app.services.assistant.assistant_llm_service as llm_mod
from app.services.assistant.conversation_service import ConversationService
from app.services.assistant.tool_executor import RejectionResult, ToolExecutor
from app.services.assistant.tool_registry import get_tool_registry
from app.testsuite.db_test_helpers import (
    create_managed_test_database,
    dispose_managed_test_database,
    install_main_database_overrides,
)

HEADERS = {"Authorization": "Bearer dummy"}


class _FakeLLM:
    def __init__(self):
        self.script = []

    def is_configured(self):
        return True

    async def call(self, *, system_prompt, messages, tools):
        if self.script:
            return self.script.pop(0)
        return llm_mod.AssistantLLMResult(content="(fallback) done", tool_calls=[])


def _push_tool_call(fake, name, arguments):
    fake.script.append(llm_mod.AssistantLLMResult(
        content=None, tool_calls=[llm_mod.ParsedToolCall(provider_tool_call_id="p", name=name, arguments=arguments)]
    ))


def _push_text(fake, content):
    fake.script.append(llm_mod.AssistantLLMResult(content=content, tool_calls=[]))


@pytest.fixture
def journal_db(tmp_path, monkeypatch):
    bundle = create_managed_test_database(tmp_path / "assistant_journal.db")
    install_main_database_overrides(
        monkeypatch=monkeypatch,
        app=app,
        get_db_dependency=get_db,
        async_engine=bundle["async_engine"],
        async_session_factory=bundle["async_session_factory"],
    )
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=1, username="journal-tester", role=UserRole.USER)
    monkeypatch.setattr(settings.ai.assistant, "enabled", True)
    monkeypatch.setattr(settings.openrouter, "api_key", "fake-key-for-test")

    fake_llm = _FakeLLM()
    monkeypatch.setattr(llm_mod, "_service_singleton", fake_llm)

    with bundle["sync_session_factory"]() as session:
        session.add(Team(id=1, name="ART", description="", wiki_token="wt", test_case_table_id="tbl1"))
        session.commit()
        tcs = TestCaseSet(team_id=1, name="Default", description="", is_default=True)
        session.add(tcs)
        session.flush()
        session.add(TestCaseSection(test_case_set_id=tcs.id, name="Unassigned", level=1, sort_order=0))
        session.commit()
        set_id = tcs.id

    yield {"bundle": bundle, "set_id": set_id, "llm": fake_llm}

    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_current_user, None)
    dispose_managed_test_database(bundle)


def _client():
    return TestClient(app)


async def _journal_rows_by_source_key(source_conversation_key):
    boundary = get_main_access_boundary()

    async def _query(session):
        return (
            await session.execute(
                select(AssistantToolExecution).where(AssistantToolExecution.source_conversation_key == source_conversation_key)
            )
        ).scalars().all()

    return await boundary.run_read(_query)


def test_journal_queryable_by_source_key_after_conversation_deleted(journal_db):
    client = _client()
    r = client.post("/api/assistant/conversations", json={"scope_type": "team", "team_id": 1}, headers=HEADERS)
    conv_id = r.json()["id"]
    conversation_key = r.json()["conversation_key"]
    fake = journal_db["llm"]

    # read tool 也會寫 journal（started/succeeded）
    _push_text(fake, "querying now")
    client.post(
        f"/api/assistant/conversations/{conv_id}/messages", headers=HEADERS,
        data={"text": "just chat", "client_message_id": "m0"},
    )

    _push_tool_call(fake, "create_test_run_config", {"name": "Journal Run", "test_case_set_ids": [journal_db["set_id"]]})
    client.post(
        f"/api/assistant/conversations/{conv_id}/messages", headers=HEADERS,
        data={"text": "create a run", "client_message_id": "m1"},
    )
    history = client.get(f"/api/assistant/conversations/{conv_id}/messages", headers=HEADERS).json()["messages"]
    action_id = next(m["pending_action"]["action_id"] for m in history if m.get("pending_action"))
    _push_text(fake, "done")
    r_confirm = client.post(f"/api/assistant/conversations/{conv_id}/actions/{action_id}/confirm", headers=HEADERS)
    assert r_confirm.status_code == 200

    rows_before = asyncio.run(_journal_rows_by_source_key(conversation_key))
    assert len(rows_before) >= 1, "expected at least the confirmed mutation's journal row"
    assert any(row.status == "succeeded" for row in rows_before)

    r_delete = client.delete(f"/api/assistant/conversations/{conv_id}", headers=HEADERS)
    assert r_delete.status_code == 204, r_delete.text

    rows_after = asyncio.run(_journal_rows_by_source_key(conversation_key))
    assert len(rows_after) == len(rows_before), "journal rows MUST survive conversation deletion, queryable by source_conversation_key"
    for row in rows_after:
        assert row.conversation_id is None, "FK conversation_id is SET NULL after delete"
        assert row.source_conversation_key == conversation_key
        assert row.source_conversation_id is not None
        assert row.source_turn_key


def test_sqlite_id_reuse_does_not_confuse_journal_lookup(journal_db):
    """conversation A 建立→刪除→conversation B 建立，即使 SQLite 將 A 的整數 PK 重用給 B，
    source_conversation_key（每個對話各自唯一的 32-hex）仍須正確區分兩者的 journal。"""
    client = _client()
    fake = journal_db["llm"]

    r_a = client.post("/api/assistant/conversations", json={"scope_type": "team", "team_id": 1}, headers=HEADERS)
    conv_a_id, key_a = r_a.json()["id"], r_a.json()["conversation_key"]
    _push_text(fake, "a")
    client.post(f"/api/assistant/conversations/{conv_a_id}/messages", headers=HEADERS, data={"text": "hi a", "client_message_id": "m1"})
    client.delete(f"/api/assistant/conversations/{conv_a_id}", headers=HEADERS)

    r_b = client.post("/api/assistant/conversations", json={"scope_type": "team", "team_id": 1}, headers=HEADERS)
    conv_b_id, key_b = r_b.json()["id"], r_b.json()["conversation_key"]
    assert key_a != key_b, "conversation_key MUST be globally unique even across delete+recreate"

    _push_tool_call(fake, "create_test_run_config", {"name": "B Run", "test_case_set_ids": [journal_db["set_id"]]})
    client.post(f"/api/assistant/conversations/{conv_b_id}/messages", headers=HEADERS, data={"text": "create run for b", "client_message_id": "m1"})
    history = client.get(f"/api/assistant/conversations/{conv_b_id}/messages", headers=HEADERS).json()["messages"]
    action_id = next(m["pending_action"]["action_id"] for m in history if m.get("pending_action"))
    _push_text(fake, "done")
    client.post(f"/api/assistant/conversations/{conv_b_id}/actions/{action_id}/confirm", headers=HEADERS)

    rows_a = asyncio.run(_journal_rows_by_source_key(key_a))
    rows_b = asyncio.run(_journal_rows_by_source_key(key_b))
    assert len(rows_b) >= 1
    assert all(row.source_conversation_key == key_b for row in rows_b)
    assert all(row.source_conversation_key == key_a for row in rows_a)
    b_ids = {row.id for row in rows_b}
    a_ids = {row.id for row in rows_a}
    assert not (a_ids & b_ids), "journal rows for A and B must never be conflated even if the integer PK were reused"


def test_journal_arguments_are_masked_not_raw_credential(journal_db):
    conv_svc = ConversationService(get_main_access_boundary(), AssistantConfig())

    async def _run():
        conv = await conv_svc.create_conversation(user_id=1, scope_type="team", team_id=1, title="t")
        turn_result = await conv_svc.start_turn(conversation=conv, client_message_id="m1", text="hi", attachment_digests=[])
        turn = turn_result.turn
        tool = get_tool_registry().get("list_test_cases")
        journal_id = await conv_svc.start_read_tool_journal(
            conversation=conv, turn=turn, user_id=1, team_id=1, llm_tool_call_id="call1", tool_name=tool.name,
            risk_level=tool.risk_level,
            arguments_json=json.dumps({"limit": 5, "test_data": [{"category": "credential", "value": "should-not-appear"}]}),
        )
        return journal_id

    journal_id = asyncio.run(_run())

    async def _get(session):
        return await session.get(AssistantToolExecution, journal_id)

    boundary = get_main_access_boundary()
    row = asyncio.run(boundary.run_read(_get))
    assert "should-not-appear" not in (row.arguments_json or ""), (
        "journal arguments_json 應已是呼叫端遮罩後的內容（此處直接測 start_read_tool_journal 的參數"
        "即為呼叫端責任；本測試以此驗證：只要遮罩後才傳入，journal 就不含明文）"
    )


def test_sensitive_payload_encryption_unavailable_fails_closed(journal_db, monkeypatch):
    """目前 64 個工具皆無 sensitive_input_paths（credential 寫入已在更早階段被拒），此為
    縱深防禦路徑的專屬測試：若某工具標記為需要加密而金鑰未設定，MUST fail-closed 拒絕建立
    pending，不得明文落 DB。"""
    executor = ToolExecutor(app=app, main_boundary=get_main_access_boundary(), config=AssistantConfig(payload_encryption_key=""), registry=get_tool_registry())
    tool = get_tool_registry().get("create_test_case")
    sensitive_tool = replace(tool, sensitive_input_paths=("body_params.test_data",))

    async def _run():
        class _FakeConversation:
            id = 1
            team_id = 1
            scope_type = "team"

        return await executor.prepare_write_tool(
            sensitive_tool, {"test_case_number": "TC-ENC-001", "title": "x", "test_case_set_id": journal_db["set_id"]},
            conversation=_FakeConversation(), user_id=1, role=UserRole.USER, execution_key="e" * 32,
        )

    result = asyncio.run(_run())
    assert isinstance(result, RejectionResult)
    assert result.code == "sensitive_payload_encryption_unavailable"
    assert result.fixable is False
