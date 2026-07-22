"""assistant 對話 API 測試（task 8.6；spec assistant-conversations）。

聚焦尚未被 test_assistant_confirmation_flow.py／既有 smoke test 覆蓋的項目：team tombstone
唯讀、刪除 409（有進行中 turn）、同 ID 不同 fingerprint 409、turn_seq→message_seq 排序、
附檔 relative_path 安全性、per-worker slot 耗盡 503、sub-resource 跨 team 拒絕。
"""
from __future__ import annotations

from pathlib import Path
import sys
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import asyncio

import pytest
from fastapi.testclient import TestClient

from app.auth.dependencies import get_current_user
from app.auth.models import UserRole
from app.config import settings
from app.database import get_db
from app.db_access.main import get_main_access_boundary
from app.main import app
from app.models.database_models import (
    AssistantUploadedFile,
    Team,
    TestCaseSet,
    TestCaseSection,
)
import app.services.assistant.assistant_llm_service as llm_mod
from app.services.assistant import conversation_service as conversation_service_module
from app.services.assistant.attachment_storage import resolve_stored_path
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
        self.last_messages = None

    def is_configured(self):
        return True

    async def call(self, *, system_prompt, messages, tools):
        self.calls += 1
        self.last_messages = messages
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
def conv_db(tmp_path, monkeypatch):
    bundle = create_managed_test_database(tmp_path / "assistant_conversations.db")
    install_main_database_overrides(
        monkeypatch=monkeypatch,
        app=app,
        get_db_dependency=get_db,
        async_engine=bundle["async_engine"],
        async_session_factory=bundle["async_session_factory"],
    )
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=1, username="conv-tester", role=UserRole.USER)
    monkeypatch.setattr(settings.ai.assistant, "enabled", True)
    monkeypatch.setattr(settings.openrouter, "api_key", "fake-key-for-test")

    fake_llm = _FakeLLM()
    monkeypatch.setattr(llm_mod, "_service_singleton", fake_llm)

    with bundle["sync_session_factory"]() as session:
        session.add(Team(id=1, name="ART", description="", wiki_token="wt", test_case_table_id="tbl1"))
        session.add(Team(id=2, name="Other Team", description="", wiki_token="wt2", test_case_table_id="tbl2"))
        session.commit()
        tcs = TestCaseSet(team_id=1, name="Default", description="", is_default=True)
        tcs_other = TestCaseSet(team_id=2, name="Other Default", description="", is_default=True)
        session.add_all([tcs, tcs_other])
        session.flush()
        session.add(TestCaseSection(test_case_set_id=tcs.id, name="Unassigned", level=1, sort_order=0))
        session.commit()
        set_id, other_team_set_id = tcs.id, tcs_other.id

    yield {"bundle": bundle, "set_id": set_id, "other_team_set_id": other_team_set_id, "llm": fake_llm}

    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_current_user, None)
    dispose_managed_test_database(bundle)


def _client():
    return TestClient(app)


def test_cross_user_isolation_returns_404_not_403(conv_db):
    client = _client()
    r = client.post("/api/assistant/conversations", json={"scope_type": "team", "team_id": 1}, headers=HEADERS)
    conv_id = r.json()["id"]

    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=2, username="other-user", role=UserRole.USER)
    try:
        r2 = client.get(f"/api/assistant/conversations/{conv_id}/messages", headers=HEADERS)
        assert r2.status_code == 404, "must not leak existence of another user's conversation via a different status code"
    finally:
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=1, username="conv-tester", role=UserRole.USER)


def test_team_deleted_conversation_becomes_read_only_tombstone(conv_db):
    """team 被刪除時 FK ondelete=SET NULL 會把 team_id 轉為 NULL；此對話 MUST 轉為唯讀，
    不得再建立新 turn（scope_type 仍為 team，不會被誤認為 global）。直接把 team_id 設為
    NULL（而非真的刪除 Team row 依賴 SQLite FK cascade——測試用的 sync session 未必啟用
    `PRAGMA foreign_keys=ON`，直接賦值可精準且可靠地重現「team 已刪除」後的狀態）。"""
    client = _client()
    r = client.post("/api/assistant/conversations", json={"scope_type": "team", "team_id": 1}, headers=HEADERS)
    conv_id = r.json()["id"]
    assert r.json()["scope_type"] == "team"

    from app.models.database_models import AssistantConversation

    with conv_db["bundle"]["sync_session_factory"]() as session:
        conv_row = session.get(AssistantConversation, conv_id)
        conv_row.team_id = None
        session.commit()

    r2 = client.post(
        f"/api/assistant/conversations/{conv_id}/messages", headers=HEADERS,
        data={"text": "hi", "client_message_id": "m1"},
    )
    assert r2.status_code == 409, r2.text
    assert r2.json()["detail"]["code"] == "SCOPE_INVALID"

    r3 = client.get(f"/api/assistant/conversations/{conv_id}/messages", headers=HEADERS)
    assert r3.status_code == 200, "history should still be readable after the team is gone"

    r4 = client.get("/api/assistant/conversations", headers=HEADERS)
    conv_after = next(c for c in r4.json() if c["id"] == conv_id)
    assert conv_after["scope_type"] == "team", "scope_type must remain 'team' (tombstone), not silently become 'global'"
    assert conv_after["team_id"] is None
    assert conv_after["source_team_id"] == 1, "source_team_id preserves which team this conversation originally belonged to"


def test_delete_conversation_with_active_turn_returns_409(conv_db, monkeypatch):
    """有進行中 turn 時刪除須被拒絕（需先 stop）。以較長的假 LLM 延遲製造「仍在 running」的窗口。"""
    import asyncio as _asyncio

    client = _client()
    r = client.post("/api/assistant/conversations", json={"scope_type": "team", "team_id": 1}, headers=HEADERS)
    conv_id = r.json()["id"]
    fake = conv_db["llm"]

    async def _slow_call(self, *, system_prompt, messages, tools):
        fake.calls += 1
        await _asyncio.sleep(0.3)
        return llm_mod.AssistantLLMResult(content="slow done", tool_calls=[])

    monkeypatch.setattr(fake, "call", _slow_call.__get__(fake))

    import threading
    holder = {}

    def _send():
        holder["resp"] = client.post(
            f"/api/assistant/conversations/{conv_id}/messages", headers=HEADERS,
            data={"text": "slow", "client_message_id": "m1"},
        )

    thread = threading.Thread(target=_send)
    thread.start()

    turn_key = None
    for _ in range(50):
        import time
        time.sleep(0.02)
        hist = client.get(f"/api/assistant/conversations/{conv_id}/messages", headers=HEADERS).json()["messages"]
        if hist:
            turn_key = hist[0]["turn_key"]
            break
    assert turn_key is not None, "expected the user message row to be visible before the slow turn finishes"

    r_delete = client.delete(f"/api/assistant/conversations/{conv_id}", headers=HEADERS)
    assert r_delete.status_code == 409, r_delete.text
    assert r_delete.json()["detail"]["code"] == "CONVERSATION_HAS_ACTIVE_TURN"

    thread.join(timeout=5)


def test_same_client_message_id_different_content_returns_409(conv_db):
    client = _client()
    r = client.post("/api/assistant/conversations", json={"scope_type": "team", "team_id": 1}, headers=HEADERS)
    conv_id = r.json()["id"]
    fake = conv_db["llm"]
    _push_text(fake, "first reply")
    r1 = client.post(
        f"/api/assistant/conversations/{conv_id}/messages", headers=HEADERS,
        data={"text": "hello world", "client_message_id": "dup-1"},
    )
    assert r1.status_code == 200

    r2 = client.post(
        f"/api/assistant/conversations/{conv_id}/messages", headers=HEADERS,
        data={"text": "a totally different message", "client_message_id": "dup-1"},
    )
    assert r2.status_code == 409, r2.text
    assert r2.json()["detail"]["code"] == "IDEMPOTENCY_KEY_REUSED"


def test_history_ordered_by_turn_seq_then_message_seq(conv_db):
    client = _client()
    r = client.post("/api/assistant/conversations", json={"scope_type": "team", "team_id": 1}, headers=HEADERS)
    conv_id = r.json()["id"]
    fake = conv_db["llm"]
    for i in range(3):
        _push_text(fake, f"reply {i}")
        resp = client.post(
            f"/api/assistant/conversations/{conv_id}/messages", headers=HEADERS,
            data={"text": f"message {i}", "client_message_id": f"seq-{i}"},
        )
        assert resp.status_code == 200

    history = client.get(f"/api/assistant/conversations/{conv_id}/messages", headers=HEADERS).json()["messages"]
    turn_seqs = [m["turn_seq"] for m in history]
    assert turn_seqs == sorted(turn_seqs), "history MUST be ordered by turn_seq"
    by_turn = {}
    for m in history:
        by_turn.setdefault(m["turn_seq"], []).append(m["message_seq"])
    for seqs in by_turn.values():
        assert seqs == sorted(seqs), "within a turn, message_seq MUST be monotonically ordered"
    assert sorted(set(turn_seqs)) == [0, 1, 2]


def test_uploaded_attachment_relative_path_is_safe_and_resolvable(conv_db):
    client = _client()
    r = client.post("/api/assistant/conversations", json={"scope_type": "team", "team_id": 1}, headers=HEADERS)
    conv_id = r.json()["id"]
    fake = conv_db["llm"]
    _push_text(fake, "got your file")
    resp = client.post(
        f"/api/assistant/conversations/{conv_id}/messages", headers=HEADERS,
        data={"text": "here is a file", "client_message_id": "m1"},
        files={"attachments": ("evidence.txt", b"file content", "text/plain")},
    )
    assert resp.status_code == 200, resp.text

    async def _get_upload(session):
        from sqlalchemy import select
        return (await session.execute(select(AssistantUploadedFile))).scalars().all()

    boundary = get_main_access_boundary()
    uploads = asyncio.run(boundary.run_read(_get_upload))
    assert len(uploads) == 1
    upload = uploads[0]
    assert upload.original_name == "evidence.txt"
    assert not upload.relative_path.startswith("/"), "relative_path MUST be relative, not an absolute machine path"
    assert ".." not in upload.relative_path.split("/"), "relative_path MUST NOT contain path traversal segments"
    assert upload.relative_path != "evidence.txt", "stored name MUST be server-random, not the original filename"
    resolved = resolve_stored_path(upload.relative_path)
    assert resolved.is_file()
    assert resolved.read_bytes() == b"file content"


def test_uploaded_attachment_is_surfaced_to_llm_but_not_persisted_or_leaked_to_next_turn(conv_db, monkeypatch):
    """紅隊發現的核心 bug：附件上傳成功後,LLM 從未被告知有哪些 file_ref 可用,導致助手實際上
    用不到使用者上傳的檔案。驗證：(1) LLM 收到的 user 訊息內容含 file_ref/檔名,(2) 前端歷史畫面
    仍只顯示使用者原始輸入（附件清單不寫回持久化內容),(3) 下一個 turn 不會再看到這份附件清單。

    首輪（turn_seq==0）結束後會背景觸發標題自動摘要，其 LLM 呼叫共用同一個 fake（`conv_db`
    monkeypatch 的 `_service_singleton`），會覆寫 `fake.last_messages`／多算 `fake.calls`，
    與本測試要驗證的「agent loop 呼叫」互相干擾，故關閉標題背景生成，只保留本測試關注的行為。"""
    monkeypatch.setattr(conversation_service_module, "_fire_and_forget_title_generation", lambda *a, **k: None)
    client = _client()
    r = client.post("/api/assistant/conversations", json={"scope_type": "team", "team_id": 1}, headers=HEADERS)
    conv_id = r.json()["id"]
    fake = conv_db["llm"]

    _push_text(fake, "got your file")
    resp = client.post(
        f"/api/assistant/conversations/{conv_id}/messages", headers=HEADERS,
        data={"text": "here is a file", "client_message_id": "m1"},
        files={"attachments": ("evidence.txt", b"file content", "text/plain")},
    )
    assert resp.status_code == 200, resp.text

    assert fake.last_messages is not None
    user_msgs = [m for m in fake.last_messages if m["role"] == "user"]
    assert len(user_msgs) == 1
    assert "file_ref=0" in user_msgs[0]["content"], "LLM 必須被告知本回合可用的 file_ref,否則無從正確引用附件"
    assert "evidence.txt" in user_msgs[0]["content"]

    history = client.get(f"/api/assistant/conversations/{conv_id}/messages", headers=HEADERS).json()
    history_user_msgs = [m for m in history["messages"] if m["role"] == "user"]
    assert len(history_user_msgs) == 1
    assert history_user_msgs[0]["content"] == "here is a file", (
        "系統附加的附件清單不得寫回持久化內容,前端歷史畫面應只顯示使用者原始輸入"
    )

    # 下一個 turn（無新附件）：不應該再看到第一輪的 file_ref 附註洩漏過來
    _push_text(fake, "no file this time")
    resp2 = client.post(
        f"/api/assistant/conversations/{conv_id}/messages", headers=HEADERS,
        data={"text": "anything else?", "client_message_id": "m2"},
    )
    assert resp2.status_code == 200, resp2.text
    assert fake.calls == 2
    contents_in_second_call = [m.get("content") or "" for m in fake.last_messages]
    assert not any("file_ref=0" in c for c in contents_in_second_call), (
        "file_ref 只能在上傳當下的同一 turn 內有效,不得洩漏到後續 turn 的 LLM context"
    )


def test_attachments_saved_event_emitted_and_history_carries_attachments_field(conv_db, monkeypatch):
    """紅隊發現的另一半 bug：使用者送出附件後,對話裡看不到任何圖示/上傳成功訊號。驗證：
    (1) SSE 串流含 `attachments_saved` 事件，(2) 歷史重載的 user 訊息項目帶 `attachments` 欄位。"""
    monkeypatch.setattr(conversation_service_module, "_fire_and_forget_title_generation", lambda *a, **k: None)
    client = _client()
    r = client.post("/api/assistant/conversations", json={"scope_type": "team", "team_id": 1}, headers=HEADERS)
    conv_id = r.json()["id"]
    fake = conv_db["llm"]
    _push_text(fake, "got your file")
    resp = client.post(
        f"/api/assistant/conversations/{conv_id}/messages", headers=HEADERS,
        data={"text": "here is a file", "client_message_id": "m1"},
        files={"attachments": ("evidence.txt", b"file content", "text/plain")},
    )
    assert resp.status_code == 200, resp.text
    assert "event: attachments_saved" in resp.text
    assert '"original_name": "evidence.txt"' in resp.text
    assert '"attachment_index": 0' in resp.text

    history = client.get(f"/api/assistant/conversations/{conv_id}/messages", headers=HEADERS).json()
    user_item = next(m for m in history["messages"] if m["role"] == "user")
    assert user_item["attachments"] == [
        {"attachment_index": 0, "original_name": "evidence.txt", "content_type": "text/plain", "size_bytes": 12}
    ]


def test_download_attachment_endpoint_streams_file_and_enforces_ownership(conv_db, monkeypatch):
    monkeypatch.setattr(conversation_service_module, "_fire_and_forget_title_generation", lambda *a, **k: None)
    client = _client()
    r = client.post("/api/assistant/conversations", json={"scope_type": "team", "team_id": 1}, headers=HEADERS)
    conv_id = r.json()["id"]
    fake = conv_db["llm"]
    _push_text(fake, "got your file")
    client.post(
        f"/api/assistant/conversations/{conv_id}/messages", headers=HEADERS,
        data={"text": "here is a file", "client_message_id": "m1"},
        files={"attachments": ("evidence.txt", b"file content", "text/plain")},
    )
    history = client.get(f"/api/assistant/conversations/{conv_id}/messages", headers=HEADERS).json()
    turn_key = next(m for m in history["messages"] if m["role"] == "user")["turn_key"]

    ok = client.get(
        f"/api/assistant/conversations/{conv_id}/turns/{turn_key}/attachments/0", headers=HEADERS
    )
    assert ok.status_code == 200, ok.text
    assert ok.content == b"file content"
    assert 'filename="evidence.txt"' in ok.headers["content-disposition"]
    assert ok.headers["content-disposition"].startswith("attachment;")

    missing_index = client.get(
        f"/api/assistant/conversations/{conv_id}/turns/{turn_key}/attachments/99", headers=HEADERS
    )
    assert missing_index.status_code == 404

    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=999, username="someone-else", role=UserRole.USER
    )
    try:
        other_user = client.get(
            f"/api/assistant/conversations/{conv_id}/turns/{turn_key}/attachments/0", headers=HEADERS
        )
        assert other_user.status_code == 404, "另一個使用者不得下載他人對話的附件"
    finally:
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
            id=1, username="conv-tester", role=UserRole.USER
        )


def test_attachment_only_message_with_empty_text_succeeds(conv_db, monkeypatch):
    """紅隊發現：`text` 表單欄位原本宣告為 `Form(...)`（必填)。前端「只傳附件、不輸入文字」時
    會送出 `text=""`,但 multipart 請求中空字串欄位會被 python-multipart 解析為缺失,導致
    422 Field required,使用者無法單獨傳附件。驗證空字串 `text` 加檔案可成功送出。"""
    monkeypatch.setattr(conversation_service_module, "_fire_and_forget_title_generation", lambda *a, **k: None)
    client = _client()
    r = client.post("/api/assistant/conversations", json={"scope_type": "team", "team_id": 1}, headers=HEADERS)
    conv_id = r.json()["id"]
    fake = conv_db["llm"]
    _push_text(fake, "got your file, thanks!")
    resp = client.post(
        f"/api/assistant/conversations/{conv_id}/messages", headers=HEADERS,
        data={"text": "", "client_message_id": "m1"},
        files={"attachments": ("evidence.txt", b"file content", "text/plain")},
    )
    assert resp.status_code == 200, resp.text
    assert "event: attachments_saved" in resp.text


def test_per_worker_slot_exhaustion_returns_503(conv_db):
    """本機 runner slot 耗盡（`max_active_turns_per_worker` 相當於 0）時 MUST 回 503
    ADMISSION_DENIED，且不得建立 turn（無界排隊）。以 FastAPI 的 `dependency_overrides`
    換掉 `_get_runner_supervisor`，因為它是路由簽名中 `Depends(...)` 已綁定的函式物件，
    monkeypatch 模組屬性無法影響已綁定的 Depends。"""
    import app.api.assistant as assistant_api
    from app.services.assistant.runner_supervisor import RunnerSupervisor

    zero_capacity_supervisor = RunnerSupervisor(0)
    app.dependency_overrides[assistant_api._get_runner_supervisor] = lambda: zero_capacity_supervisor
    try:
        client = _client()
        r = client.post("/api/assistant/conversations", json={"scope_type": "team", "team_id": 1}, headers=HEADERS)
        conv_id = r.json()["id"]
        resp = client.post(
            f"/api/assistant/conversations/{conv_id}/messages", headers=HEADERS,
            data={"text": "hi", "client_message_id": "m1"},
        )
        assert resp.status_code == 503, resp.text
        assert resp.json()["detail"]["code"] == "ADMISSION_DENIED"
    finally:
        app.dependency_overrides.pop(assistant_api._get_runner_supervisor, None)


def test_write_tool_rejects_sub_resource_from_another_team(conv_db):
    """create_test_case 指定屬於別 team 的 test_case_set_id 時，team_mismatch 拒絕（非 fixable），
    不建立 pending。"""
    client = _client()
    r = client.post("/api/assistant/conversations", json={"scope_type": "team", "team_id": 1}, headers=HEADERS)
    conv_id = r.json()["id"]
    fake = conv_db["llm"]
    _push_tool_call(fake, "create_test_case", {
        "test_case_number": "TC-CROSS-001", "title": "cross team", "test_case_set_id": conv_db["other_team_set_id"],
    })
    _push_text(fake, "sorry, could not create it")
    resp = client.post(
        f"/api/assistant/conversations/{conv_id}/messages", headers=HEADERS,
        data={"text": "create a case in the wrong team's set", "client_message_id": "m1"},
    )
    assert resp.status_code == 200, resp.text
    assert "confirmation_required" not in resp.text, "cross-team sub-resource must be rejected before any pending is created"

    from sqlalchemy import select
    from app.models.database_models import TestCaseLocal

    async def _get_cases(session):
        return (await session.execute(select(TestCaseLocal).where(TestCaseLocal.test_case_number == "TC-CROSS-001"))).scalars().all()

    boundary = get_main_access_boundary()
    cases = asyncio.run(boundary.run_read(_get_cases))
    assert len(cases) == 0
