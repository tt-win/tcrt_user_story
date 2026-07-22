"""assistant confirm/cancel 流程測試（task 8.5；spec assistant-action-confirmation）。

透過 HTTP 層（`TestClient`，仿 repo 既有慣例：`get_current_user` override + dummy Bearer
header，不走真 JWT）驅動 `/api/assistant/conversations/{id}/messages` 與
`/actions/{id}/confirm|cancel`，驗證 confirm 判斷順序、CONFIRMATION_STALE 重新確認、
併發 CAS 只有一方勝出、execution_payload 於終態清除、非擁有者 404、以及 unknown outcome
的 synthetic pairing。
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.auth.dependencies import get_current_user
from app.auth.models import UserRole
from app.config import settings
from app.database import get_db
from app.db_access.main import get_main_access_boundary
from app.main import app
from app.models.database_models import (
    AssistantPendingAction,
    AssistantToolExecution,
    Team,
    TestCaseSet,
    TestCaseSection,
)
import app.services.assistant.assistant_llm_service as llm_mod
from app.testsuite.db_test_helpers import (
    create_managed_test_database,
    dispose_managed_test_database,
    install_main_database_overrides,
)

HEADERS = {"Authorization": "Bearer dummy"}


class _FakeLLM:
    def __init__(self):
        self.script = []
        self.calls = 0

    def is_configured(self):
        return True

    async def call(self, *, system_prompt, messages, tools):
        self.calls += 1
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
def confirm_db(tmp_path, monkeypatch):
    bundle = create_managed_test_database(tmp_path / "assistant_confirm.db")
    install_main_database_overrides(
        monkeypatch=monkeypatch,
        app=app,
        get_db_dependency=get_db,
        async_engine=bundle["async_engine"],
        async_session_factory=bundle["async_session_factory"],
    )
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=1, username="confirm-tester", role=UserRole.USER)
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


def _create_conversation(client):
    r = client.post("/api/assistant/conversations", json={"scope_type": "team", "team_id": 1}, headers=HEADERS)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _find_pending_action_id(client, conv_id):
    history = client.get(f"/api/assistant/conversations/{conv_id}/messages", headers=HEADERS).json()["messages"]
    pending = [m for m in history if m.get("pending_action") and m["pending_action"]["status"] == "pending"]
    assert len(pending) == 1, history
    return pending[0]["pending_action"]["action_id"]


def test_confirm_executes_the_write_exactly_once_and_clears_execution_payload(confirm_db):
    client = _client()
    conv_id = _create_conversation(client)
    fake = confirm_db["llm"]
    _push_tool_call(fake, "create_test_run_config", {"name": "Confirm Flow Run", "test_case_set_ids": [confirm_db["set_id"]]})
    r = client.post(
        f"/api/assistant/conversations/{conv_id}/messages", headers=HEADERS,
        data={"text": "create a run", "client_message_id": "m1"},
    )
    assert r.status_code == 200, r.text
    assert "confirmation_required" in r.text

    action_id = _find_pending_action_id(client, conv_id)
    _push_text(fake, "done")
    r2 = client.post(f"/api/assistant/conversations/{conv_id}/actions/{action_id}/confirm", headers=HEADERS)
    assert r2.status_code == 200, r2.text
    assert "tool_started" in r2.text
    assert '"display_mode": "status_only"' in r2.text
    assert f'"action_id": {action_id}' in r2.text
    assert '"outcome": "succeeded"' in r2.text
    assert r2.text.index("tool_started") < r2.text.index("tool_finished")
    assert '"name": "Confirm Flow Run"' in r2.text
    assert '"content": "done"' not in r2.text
    assert "text_delta" not in r2.text, "confirmed result must not be followed by terminal LLM prose"

    history = client.get(f"/api/assistant/conversations/{conv_id}/messages", headers=HEADERS).json()["messages"]
    tool_messages = [m for m in history if m["role"] == "tool" and m["tool_name"] == "create_test_run_config"]
    assert len(tool_messages) == 1
    assert tool_messages[0]["tool_result"]["name"] == "Confirm Flow Run"
    assert tool_messages[0]["tool_outcome"] == "succeeded"
    assert not any(m["role"] == "assistant" and m.get("content") == "done" for m in history)

    async def _get_action(session):
        return await session.get(AssistantPendingAction, action_id)

    boundary = get_main_access_boundary()
    import asyncio
    action = asyncio.run(boundary.run_read(_get_action))
    assert action.status == "confirmed"
    assert action.execution_payload_json is None, "execution_payload MUST be cleared after resolution"


def test_successful_write_stays_successful_when_follow_up_llm_crashes(confirm_db, monkeypatch):
    client = _client()
    conv_id = _create_conversation(client)
    fake = confirm_db["llm"]
    _push_tool_call(fake, "create_test_run_config", {"name": "Committed Run", "test_case_set_ids": [confirm_db["set_id"]]})
    client.post(
        f"/api/assistant/conversations/{conv_id}/messages", headers=HEADERS,
        data={"text": "create a run", "client_message_id": "m1"},
    )
    action_id = _find_pending_action_id(client, conv_id)

    async def _boom_after_commit(*, system_prompt, messages, tools):
        raise RuntimeError("follow-up planning crashed")

    monkeypatch.setattr(fake, "call", _boom_after_commit)
    response = client.post(f"/api/assistant/conversations/{conv_id}/actions/{action_id}/confirm", headers=HEADERS)

    assert response.status_code == 200, response.text
    assert '"outcome": "succeeded"' in response.text
    assert "event: error" not in response.text
    assert "text_delta" not in response.text

    history = client.get(f"/api/assistant/conversations/{conv_id}/messages", headers=HEADERS).json()["messages"]
    resolved = [m["pending_action"] for m in history if m.get("pending_action")]
    assert any(action["action_id"] == action_id and action["status"] == "confirmed" for action in resolved)


def test_batch_execute_actions_uses_one_confirmation_for_all_independent_writes(confirm_db):
    client = _client()
    conv_id = _create_conversation(client)
    fake = confirm_db["llm"]
    _push_tool_call(fake, "batch_execute_actions", {"actions": [
        {"tool_name": "create_test_case_set", "arguments": {"name": "Batch Set A"}},
        {"tool_name": "create_test_case_set", "arguments": {"name": "Batch Set B"}},
    ]})
    proposed = client.post(
        f"/api/assistant/conversations/{conv_id}/messages", headers=HEADERS,
        data={"text": "create both sets", "client_message_id": "batch-actions-create"},
    )
    assert proposed.status_code == 200, proposed.text
    assert proposed.text.count("confirmation_required") == 1
    action_id = _find_pending_action_id(client, conv_id)

    _push_text(fake, "both done")
    confirmed = client.post(
        f"/api/assistant/conversations/{conv_id}/actions/{action_id}/confirm", headers=HEADERS
    )
    assert confirmed.status_code == 200, confirmed.text
    assert '"succeeded_count": 2' in confirmed.text
    assert "both done" not in confirmed.text
    assert "text_delta" not in confirmed.text

    with confirm_db["bundle"]["sync_session_factory"]() as session:
        names = {row[0] for row in session.query(TestCaseSet.name).filter(TestCaseSet.name.in_(["Batch Set A", "Batch Set B"])).all()}
    assert names == {"Batch Set A", "Batch Set B"}


def test_confirm_continuation_can_still_create_a_new_pending_without_terminal_text(confirm_db):
    client = _client()
    conv_id = _create_conversation(client)
    fake = confirm_db["llm"]
    _push_tool_call(fake, "create_test_case_set", {"name": "Dependent Parent"})
    proposed = client.post(
        f"/api/assistant/conversations/{conv_id}/messages",
        headers=HEADERS,
        data={"text": "create a set then a section", "client_message_id": "dependent-create"},
    )
    assert proposed.status_code == 200, proposed.text
    first_action_id = _find_pending_action_id(client, conv_id)

    # Fresh fixture 的 default set 是 1，因此第一個 create 會產生 set id 2；continuation 的新
    # tool call 必須照常建立第二張確認卡，而不是被 terminal-text suppression 吃掉。
    fake.script.append(llm_mod.AssistantLLMResult(
        content="我已經準備好建立 section，請確認",
        tool_calls=[llm_mod.ParsedToolCall(
            provider_tool_call_id="p-next",
            name="create_test_case_section",
            arguments={"set_id": 2, "name": "Dependent Child"},
        )],
    ))
    continued = client.post(
        f"/api/assistant/conversations/{conv_id}/actions/{first_action_id}/confirm",
        headers=HEADERS,
    )

    assert continued.status_code == 200, continued.text
    assert '"outcome": "succeeded"' in continued.text
    assert "confirmation_required" in continued.text
    assert "我已經準備好" not in continued.text
    assert "text_delta" not in continued.text
    second_action_id = _find_pending_action_id(client, conv_id)
    assert second_action_id != first_action_id


@pytest.mark.parametrize("outcome", ["failed", "unknown"])
def test_finalized_non_success_outcome_does_not_emit_follow_up_error(confirm_db, monkeypatch, outcome):
    client = _client()
    conv_id = _create_conversation(client)
    fake = confirm_db["llm"]
    _push_tool_call(fake, "create_test_run_config", {
        "name": f"Finalized {outcome}",
        "test_case_set_ids": [confirm_db["set_id"]],
    })
    client.post(
        f"/api/assistant/conversations/{conv_id}/messages", headers=HEADERS,
        data={"text": "create a run", "client_message_id": f"finalized-{outcome}"},
    )
    action_id = _find_pending_action_id(client, conv_id)

    from app.services.assistant.conversation_service import ConversationService
    from app.services.assistant.tool_executor import ConfirmExecutionResult, ToolExecutor

    async def _finalized_result(self, tool, **kwargs):
        return ConfirmExecutionResult(outcome, {"status": outcome}, 409 if outcome == "failed" else None)

    async def _cleanup_boom(self, **kwargs):
        raise RuntimeError("cleanup after authoritative outcome failed")

    monkeypatch.setattr(ToolExecutor, "execute_confirmed_write", _finalized_result)
    monkeypatch.setattr(ConversationService, "complete_continuation_turn", _cleanup_boom)

    response = client.post(f"/api/assistant/conversations/{conv_id}/actions/{action_id}/confirm", headers=HEADERS)

    assert response.status_code == 200, response.text
    assert f'"outcome": "{outcome}"' in response.text
    assert "event: error" not in response.text
    assert "text_delta" not in response.text

    history = client.get(f"/api/assistant/conversations/{conv_id}/messages", headers=HEADERS).json()["messages"]
    resolved = [m["pending_action"] for m in history if m.get("pending_action")]
    expected_status = "failed" if outcome == "failed" else "unknown"
    assert any(action["action_id"] == action_id and action["status"] == expected_status for action in resolved)


@pytest.mark.parametrize(
    ("tool_name", "arguments", "client_message_id"),
    [
        ("create_test_case_set", {"name": "Reported Case Set"}, "report-set"),
        ("create_test_run_config", {"name": "Reported Test Run"}, "report-run"),
        ("create_test_run_set", {"name": "Reported Run Set"}, "report-run-set"),
    ],
)
def test_create_tools_report_authoritative_id_and_name(
    confirm_db, tool_name, arguments, client_message_id
):
    client = _client()
    conv_id = _create_conversation(client)
    fake = confirm_db["llm"]
    if tool_name == "create_test_run_config":
        arguments["test_case_set_ids"] = [confirm_db["set_id"]]
    _push_tool_call(fake, tool_name, arguments)
    proposed = client.post(
        f"/api/assistant/conversations/{conv_id}/messages",
        headers=HEADERS,
        data={"text": f"run {tool_name}", "client_message_id": client_message_id},
    )
    assert proposed.status_code == 200, proposed.text
    action_id = _find_pending_action_id(client, conv_id)
    _push_text(fake, "done")
    confirmed = client.post(
        f"/api/assistant/conversations/{conv_id}/actions/{action_id}/confirm", headers=HEADERS
    )
    assert confirmed.status_code == 200, confirmed.text
    assert '"outcome": "succeeded"' in confirmed.text
    assert f'"name": "{arguments["name"]}"' in confirmed.text
    assert '"id":' in confirmed.text

    history = client.get(
        f"/api/assistant/conversations/{conv_id}/messages", headers=HEADERS
    ).json()["messages"]
    result = next(item for item in history if item["role"] == "tool" and item["tool_name"] == tool_name)
    assert result["tool_outcome"] == "succeeded"
    assert result["tool_result"]["name"] == arguments["name"]
    assert result["tool_result"]["id"] is not None


def test_repeat_confirm_replays_without_reexecuting(confirm_db):
    client = _client()
    conv_id = _create_conversation(client)
    fake = confirm_db["llm"]
    _push_tool_call(fake, "create_test_run_config", {"name": "Replay Run", "test_case_set_ids": [confirm_db["set_id"]]})
    client.post(
        f"/api/assistant/conversations/{conv_id}/messages", headers=HEADERS,
        data={"text": "create a run", "client_message_id": "m1"},
    )
    action_id = _find_pending_action_id(client, conv_id)
    _push_text(fake, "done")
    r1 = client.post(f"/api/assistant/conversations/{conv_id}/actions/{action_id}/confirm", headers=HEADERS)
    assert r1.status_code == 200

    calls_before = fake.calls
    r2 = client.post(f"/api/assistant/conversations/{conv_id}/actions/{action_id}/confirm", headers=HEADERS)
    assert r2.status_code == 200
    assert fake.calls == calls_before, "repeat confirm must replay the existing continuation, not re-run the LLM/tool"
    assert r2.text == r1.text or "succeeded" in r2.text


def test_cancel_prevents_execution_and_marks_resolved(confirm_db):
    client = _client()
    conv_id = _create_conversation(client)
    fake = confirm_db["llm"]
    _push_tool_call(fake, "create_test_run_config", {"name": "Cancelled Run", "test_case_set_ids": [confirm_db["set_id"]]})
    client.post(
        f"/api/assistant/conversations/{conv_id}/messages", headers=HEADERS,
        data={"text": "create a run", "client_message_id": "m1"},
    )
    action_id = _find_pending_action_id(client, conv_id)
    r = client.post(f"/api/assistant/conversations/{conv_id}/actions/{action_id}/cancel", headers=HEADERS)
    assert r.status_code == 200
    assert r.json()["status"] == "cancelled"

    from sqlalchemy import select
    from app.models.database_models import TestRunConfig

    async def _get_runs(session):
        return (await session.execute(select(TestRunConfig).where(TestRunConfig.name == "Cancelled Run"))).scalars().all()

    import asyncio
    boundary = get_main_access_boundary()
    runs = asyncio.run(boundary.run_read(_get_runs))
    assert len(runs) == 0, "cancelled action must never execute the write"

    r2 = client.post(f"/api/assistant/conversations/{conv_id}/actions/{action_id}/cancel", headers=HEADERS)
    assert r2.status_code == 409, "cancel is CAS-protected: cancelling twice must not silently succeed"


def test_confirmation_stale_when_target_changes_before_confirm(confirm_db):
    """等待確認期間影響範圍改變（spec）：confirm 重算 fingerprint 不同時回 409 CONFIRMATION_STALE，
    不執行工具；卡片摘要同時更新為最新值。"""
    with confirm_db["bundle"]["sync_session_factory"]() as session:
        from app.models.database_models import TestCaseLocal
        case = TestCaseLocal(team_id=1, test_case_set_id=confirm_db["set_id"], test_case_number="TC-STALE-001", title="original title")
        session.add(case)
        session.commit()
        case_id = case.id

    client = _client()
    conv_id = _create_conversation(client)
    fake = confirm_db["llm"]
    _push_tool_call(fake, "update_test_case", {"record_id": case_id, "title": "new title"})
    client.post(
        f"/api/assistant/conversations/{conv_id}/messages", headers=HEADERS,
        data={"text": "rename it", "client_message_id": "m1"},
    )
    action_id = _find_pending_action_id(client, conv_id)

    # 使用者按確認前，該 test_case_number（confirmation summary 的 target_label 來源）被改變
    with confirm_db["bundle"]["sync_session_factory"]() as session:
        from app.models.database_models import TestCaseLocal as TCL
        row = session.get(TCL, case_id)
        row.test_case_number = "TC-STALE-001-RENAMED"
        session.commit()

    r = client.post(f"/api/assistant/conversations/{conv_id}/actions/{action_id}/confirm", headers=HEADERS)
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["code"] == "CONFIRMATION_STALE"

    from sqlalchemy import select
    from app.models.database_models import TestCaseLocal as TCL2

    async def _get_case(session):
        return (await session.execute(select(TCL2).where(TCL2.id == case_id))).scalar_one()

    import asyncio
    boundary = get_main_access_boundary()
    case_after = asyncio.run(boundary.run_read(_get_case))
    assert case_after.title == "original title", "stale confirm must not execute the write"


def test_non_owner_cannot_confirm_or_cancel(confirm_db):
    client = _client()
    conv_id = _create_conversation(client)
    fake = confirm_db["llm"]
    _push_tool_call(fake, "create_test_run_config", {"name": "Owned Run", "test_case_set_ids": [confirm_db["set_id"]]})
    client.post(
        f"/api/assistant/conversations/{conv_id}/messages", headers=HEADERS,
        data={"text": "create a run", "client_message_id": "m1"},
    )
    action_id = _find_pending_action_id(client, conv_id)

    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=999, username="someone-else", role=UserRole.USER)
    try:
        r = client.post(f"/api/assistant/conversations/{conv_id}/actions/{action_id}/confirm", headers=HEADERS)
        assert r.status_code == 404
        r2 = client.post(f"/api/assistant/conversations/{conv_id}/actions/{action_id}/cancel", headers=HEADERS)
        assert r2.status_code == 404
    finally:
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=1, username="confirm-tester", role=UserRole.USER)


def test_concurrent_confirms_execute_the_write_exactly_once(confirm_db):
    """CAS 認領只有一方勝出：5 個併發 confirm 只實際執行一次工具（port of scratch smoke_confirm_race.py）。"""
    client = _client()
    conv_id = _create_conversation(client)
    fake = confirm_db["llm"]
    _push_tool_call(fake, "create_test_run_config", {"name": "Race Run", "test_case_set_ids": [confirm_db["set_id"]]})
    client.post(
        f"/api/assistant/conversations/{conv_id}/messages", headers=HEADERS,
        data={"text": "create a run", "client_message_id": "m1"},
    )
    action_id = _find_pending_action_id(client, conv_id)
    _push_text(fake, "done")

    def _confirm():
        return client.post(f"/api/assistant/conversations/{conv_id}/actions/{action_id}/confirm", headers=HEADERS)

    with ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(lambda _: _confirm(), range(5)))

    for r in results:
        assert r.status_code == 200, r.text

    from sqlalchemy import select
    from app.models.database_models import TestRunConfig

    async def _get_runs(session):
        return (await session.execute(select(TestRunConfig).where(TestRunConfig.name == "Race Run"))).scalars().all()

    import asyncio
    boundary = get_main_access_boundary()
    runs = asyncio.run(boundary.run_read(_get_runs))
    assert len(runs) == 1, f"expected the write to execute exactly once despite 5 concurrent confirms, got {len(runs)}"


def test_concurrent_same_client_message_id_converges_on_one_turn(confirm_db):
    """port of scratch smoke_race.py：同一 client_message_id 併發送出只建立一個 turn，quota 不重複扣。"""
    client = _client()
    conv_id = _create_conversation(client)
    fake = confirm_db["llm"]
    _push_text(fake, "hello")

    def _send():
        return client.post(
            f"/api/assistant/conversations/{conv_id}/messages", headers=HEADERS,
            data={"text": "same message", "client_message_id": "race-m1"},
        )

    with ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(lambda _: _send(), range(5)))

    for r in results:
        assert r.status_code == 200, r.text

    from sqlalchemy import select
    from app.models.database_models import AssistantRateLimitBucket, AssistantTurn, AssistantConversation

    async def _check(session):
        turns = (
            await session.execute(
                select(AssistantTurn)
                .join(AssistantConversation, AssistantConversation.id == AssistantTurn.conversation_id)
                .where(AssistantTurn.client_message_id == "race-m1")
            )
        ).scalars().all()
        buckets = (await session.execute(select(AssistantRateLimitBucket).where(AssistantRateLimitBucket.user_id == 1))).scalars().all()
        return turns, buckets

    import asyncio
    boundary = get_main_access_boundary()
    turns, buckets = asyncio.run(boundary.run_read(_check))
    assert len({t.id for t in turns}) == 1, f"expected exactly one turn for the shared client_message_id, got {len(turns)}"
    assert len(buckets) == 1 and buckets[0].used_count == 1, "quota must be charged exactly once despite 5 concurrent requests"


def test_unknown_outcome_when_loopback_raises_after_claim(confirm_db, monkeypatch):
    """mutation loopback 發生無法證明未執行的錯誤時進入 unknown，MUST NOT 宣稱剛好一次；
    payload 仍須清除並寫入 synthetic 結果。"""
    client = _client()
    conv_id = _create_conversation(client)
    fake = confirm_db["llm"]
    _push_tool_call(fake, "create_test_run_config", {"name": "Unknown Outcome Run", "test_case_set_ids": [confirm_db["set_id"]]})
    client.post(
        f"/api/assistant/conversations/{conv_id}/messages", headers=HEADERS,
        data={"text": "create a run", "client_message_id": "m1"},
    )
    action_id = _find_pending_action_id(client, conv_id)

    from app.services.assistant.tool_executor import ToolExecutor

    secret_marker = "secret-like-token-should-never-leak"

    async def _boom(self, tool, *, team_id, path_params, query_params, body_params, jwt, conversation_key, files=None):
        raise RuntimeError(secret_marker)

    # patch 底層 _loopback（execute_confirmed_write 自身已有 try/except 把 loopback 例外轉為
    # unknown outcome）；不要整個換掉 execute_confirmed_write，否則會繞過那段既有的錯誤分類邏輯。
    monkeypatch.setattr(ToolExecutor, "_loopback", _boom)

    r = client.post(f"/api/assistant/conversations/{conv_id}/actions/{action_id}/confirm", headers=HEADERS)
    assert r.status_code == 200, r.text
    assert "tool_started" in r.text
    assert '"outcome": "unknown"' in r.text
    assert secret_marker not in r.text

    history_response = client.get(f"/api/assistant/conversations/{conv_id}/messages", headers=HEADERS)
    assert history_response.status_code == 200
    assert secret_marker not in history_response.text

    async def _get_action(session):
        action = await session.get(AssistantPendingAction, action_id)
        journal = (
            await session.execute(
                select(AssistantToolExecution).where(AssistantToolExecution.execution_key == action.execution_key)
            )
        ).scalar_one()
        return action, journal

    import asyncio
    boundary = get_main_access_boundary()
    action, journal = asyncio.run(boundary.run_read(_get_action))
    assert action.status == "unknown"
    assert action.execution_payload_json is None
    assert secret_marker not in str(journal.error_message or "")
