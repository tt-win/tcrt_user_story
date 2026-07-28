"""全域對話的 turn context team（spec assistant-conversations「turn 的 context team 快照」、
assistant-tool-execution「in-process loopback 執行與 team_id 注入」、
assistant-action-confirmation「confirm 的有效 team 取自 turn 快照」）。

回歸目標：助手在全域對話（前端唯一會建立的類型）必須能對「前端工作區 team」執行 team-scoped
讀寫；沒有 context team 時 fail-closed；confirm 只認 turn 快照，不受之後工作區切換影響。
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace


import pytest
from fastapi.testclient import TestClient

from app.auth.dependencies import get_current_user
from app.auth.models import UserRole
from app.config import settings
from app.database import get_db
from app.db_access.main import get_main_access_boundary
from app.main import app
from app.models.database_models import (
    AssistantTurn,
    Team,
    TestCaseSet,
    TestCaseSection,
    User,
)
import app.services.assistant.assistant_llm_service as llm_mod
from app.services.assistant import conversation_service as conversation_service_module
from app.services.assistant.team_context import effective_team_id
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
        self.last_tools = None

    def is_configured(self):
        return True

    async def call(self, *, system_prompt, messages, tools):
        self.calls += 1
        self.last_tools = [t["function"]["name"] for t in tools]
        self.last_system_prompt = system_prompt
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
def team_ctx_db(tmp_path, monkeypatch):
    bundle = create_managed_test_database(tmp_path / "assistant_team_ctx.db")
    install_main_database_overrides(
        monkeypatch=monkeypatch,
        app=app,
        get_db_dependency=get_db,
        async_engine=bundle["async_engine"],
        async_session_factory=bundle["async_session_factory"],
    )
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=1, username="ctx-tester", role=UserRole.USER
    )
    monkeypatch.setattr(settings.ai.assistant, "enabled", True)
    monkeypatch.setattr(settings.openrouter, "api_key", "fake-key-for-test")

    fake_llm = _FakeLLM()
    monkeypatch.setattr(llm_mod, "_service_singleton", fake_llm)
    monkeypatch.setattr(conversation_service_module, "_fire_and_forget_title_generation", lambda *a, **k: None)

    with bundle["sync_session_factory"]() as session:
        # `get_user_accessible_teams` 需要真的 User row（依 role 決定可存取 team）。
        session.add(User(id=1, username="ctx-tester", email="ctx@example.com", hashed_password="x",
                         role=UserRole.USER, is_active=True, is_verified=True))
        session.add(Team(id=1, name="ART", description="", wiki_token="wt", test_case_table_id="tbl1"))
        session.add(Team(id=2, name="CID", description="", wiki_token="wt2", test_case_table_id="tbl2"))
        session.commit()
        art_set = TestCaseSet(team_id=1, name="Default", description="", is_default=True)
        cid_set = TestCaseSet(team_id=2, name="CID Default", description="", is_default=True)
        session.add_all([art_set, cid_set])
        session.flush()
        session.add(TestCaseSection(test_case_set_id=art_set.id, name="Unassigned", level=1, sort_order=0))
        session.add(TestCaseSection(test_case_set_id=cid_set.id, name="Unassigned", level=1, sort_order=0))
        session.commit()
        ids = {"art_set_id": art_set.id, "cid_set_id": cid_set.id}

    yield {"bundle": bundle, "llm": fake_llm, **ids}

    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_current_user, None)
    dispose_managed_test_database(bundle)


def _client():
    return TestClient(app)


def _global_conversation(client) -> int:
    r = client.post("/api/assistant/conversations", json={"scope_type": "global"}, headers=HEADERS)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _send(client, conv_id, *, text, message_id, context_team_id=None):
    data = {"text": text, "client_message_id": message_id}
    if context_team_id is not None:
        data["context_team_id"] = str(context_team_id)
    return client.post(f"/api/assistant/conversations/{conv_id}/messages", headers=HEADERS, data=data)


def _turns(bundle) -> list[AssistantTurn]:
    with bundle["sync_session_factory"]() as session:
        return list(session.query(AssistantTurn).order_by(AssistantTurn.id).all())


def _pending_action_id(client, conv_id) -> int:
    history = client.get(f"/api/assistant/conversations/{conv_id}/messages", headers=HEADERS).json()["messages"]
    pending = [m for m in history if m.get("pending_action") and m["pending_action"]["status"] == "pending"]
    assert len(pending) == 1, history
    return pending[0]["pending_action"]["action_id"]


def _pending_summary(client, conv_id) -> dict:
    history = client.get(f"/api/assistant/conversations/{conv_id}/messages", headers=HEADERS).json()["messages"]
    pending = [m for m in history if m.get("pending_action")]
    assert pending, history
    return pending[-1]["pending_action"]["confirmation_summary"]


# --------------------------------------------------------------------------- #
# effective_team_id（單一解析點）
# --------------------------------------------------------------------------- #


def test_effective_team_prefers_conversation_binding_then_turn_snapshot():
    team_conv = SimpleNamespace(scope_type="team", team_id=5)
    global_conv = SimpleNamespace(scope_type="global", team_id=None)
    turn = SimpleNamespace(context_team_id=9)

    assert effective_team_id(team_conv, turn) == 5, "team 對話必須忽略 turn 快照"
    assert effective_team_id(global_conv, turn) == 9
    assert effective_team_id(global_conv, SimpleNamespace(context_team_id=None)) is None
    assert effective_team_id(global_conv, None) is None


# --------------------------------------------------------------------------- #
# turn 快照
# --------------------------------------------------------------------------- #


def test_context_team_is_snapshotted_on_the_turn(team_ctx_db):
    client = _client()
    conv_id = _global_conversation(client)
    r = _send(client, conv_id, text="hi", message_id="m1", context_team_id=1)
    assert r.status_code == 200, r.text

    turns = _turns(team_ctx_db["bundle"])
    assert len(turns) == 1
    assert turns[0].context_team_id == 1


def test_inaccessible_context_team_is_rejected_without_creating_a_turn(team_ctx_db):
    client = _client()
    conv_id = _global_conversation(client)
    r = _send(client, conv_id, text="hi", message_id="m1", context_team_id=999)
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["code"] == "CONTEXT_TEAM_INVALID"
    assert _turns(team_ctx_db["bundle"]) == [], "驗證失敗不得留下 turn"


def test_missing_context_team_leaves_snapshot_null_and_only_discovery_tools(team_ctx_db):
    client = _client()
    conv_id = _global_conversation(client)
    r = _send(client, conv_id, text="hi", message_id="m1")
    assert r.status_code == 200, r.text

    turns = _turns(team_ctx_db["bundle"])
    assert len(turns) == 1 and turns[0].context_team_id is None

    tools = team_ctx_db["llm"].last_tools
    assert "create_test_case_set" not in tools, "無 context team 必須維持唯讀 discovery"
    assert "search_test_cases_global" in tools


def test_context_team_unlocks_team_scoped_tools(team_ctx_db):
    client = _client()
    conv_id = _global_conversation(client)
    r = _send(client, conv_id, text="hi", message_id="m1", context_team_id=1)
    assert r.status_code == 200, r.text

    tools = team_ctx_db["llm"].last_tools
    assert "create_test_case_set" in tools
    assert "list_test_cases" in tools
    prompt = team_ctx_db["llm"].last_system_prompt
    assert "本回合目標 team" in prompt and "ART" in prompt
    assert "目標 team 消歧" in prompt


# --------------------------------------------------------------------------- #
# 端對端：全域對話的寫入 + 確認
# --------------------------------------------------------------------------- #


def test_global_conversation_can_create_a_test_case_set_end_to_end(team_ctx_db):
    """本 change 的核心：全域對話 + 工作區 team → 寫入可提出、確認、執行成功。"""
    client = _client()
    conv_id = _global_conversation(client)
    fake = team_ctx_db["llm"]
    _push_tool_call(fake, "create_test_case_set", {"name": "Test12345", "description": ""})

    r = _send(client, conv_id, text="在 ART 建立一個 test case set Test12345", message_id="m1", context_team_id=1)
    assert r.status_code == 200, r.text
    assert "confirmation_required" in r.text, "全域對話必須能建立確認卡（過去會被 discovery 過濾擋掉）"

    summary = _pending_summary(client, conv_id)
    assert summary["team_id"] == 1
    assert summary["team_name"] == "ART", "確認卡必須標示目標 team，使用者才知道動到哪個 team"

    action_id = _pending_action_id(client, conv_id)
    _push_text(fake, "已在 ART 建立 test case set Test12345。")
    r2 = client.post(f"/api/assistant/conversations/{conv_id}/actions/{action_id}/confirm", headers=HEADERS)
    assert r2.status_code == 200, r2.text
    assert '"outcome": "succeeded"' in r2.text
    assert "Test12345" in r2.text

    with team_ctx_db["bundle"]["sync_session_factory"]() as session:
        created = session.query(TestCaseSet).filter(TestCaseSet.name == "Test12345").one()
        assert created.team_id == 1, "必須建立在 context team，而不是其他 team"


def test_write_without_context_team_is_rejected_before_any_pending(team_ctx_db):
    client = _client()
    conv_id = _global_conversation(client)
    fake = team_ctx_db["llm"]
    # 無 context team 時目錄不含寫入工具；即使模型硬要呼叫，executor 也 MUST 拒絕。
    _push_tool_call(fake, "create_test_case_set", {"name": "ShouldNotExist", "description": ""})
    _push_text(fake, "無法執行")

    r = _send(client, conv_id, text="建立一個 set", message_id="m1")
    assert r.status_code == 200, r.text
    assert "confirmation_required" not in r.text

    with team_ctx_db["bundle"]["sync_session_factory"]() as session:
        assert session.query(TestCaseSet).filter(TestCaseSet.name == "ShouldNotExist").first() is None


def test_confirm_uses_the_turn_snapshot_not_the_current_workspace(team_ctx_db):
    """確認卡出現後即使工作區切到 CID，動作仍必須落在建立當下的 ART。"""
    client = _client()
    conv_id = _global_conversation(client)
    fake = team_ctx_db["llm"]
    _push_tool_call(fake, "create_test_case_set", {"name": "SnapshotWins", "description": ""})

    r = _send(client, conv_id, text="建立 set", message_id="m1", context_team_id=1)
    assert r.status_code == 200, r.text
    action_id = _pending_action_id(client, conv_id)

    # confirm 端點不接受 team 參數；即便前端夾帶也不得影響目標 team。
    _push_text(fake, "done")
    r2 = client.post(
        f"/api/assistant/conversations/{conv_id}/actions/{action_id}/confirm",
        headers=HEADERS,
        params={"context_team_id": 2},
    )
    assert r2.status_code == 200, r2.text

    with team_ctx_db["bundle"]["sync_session_factory"]() as session:
        created = session.query(TestCaseSet).filter(TestCaseSet.name == "SnapshotWins").one()
        assert created.team_id == 1


def test_continuation_turn_inherits_the_context_team_snapshot(team_ctx_db):
    """pending.turn_id 會 rebind 到 continuation；快照沒繼承的話 confirm 後就解析不出 team。"""
    client = _client()
    conv_id = _global_conversation(client)
    fake = team_ctx_db["llm"]
    _push_tool_call(fake, "create_test_case_set", {"name": "Inherited", "description": ""})
    _send(client, conv_id, text="建立 set", message_id="m1", context_team_id=1)
    action_id = _pending_action_id(client, conv_id)
    _push_text(fake, "done")
    client.post(f"/api/assistant/conversations/{conv_id}/actions/{action_id}/confirm", headers=HEADERS)

    turns = _turns(team_ctx_db["bundle"])
    assert len(turns) == 2, "應有 source turn 與 continuation turn"
    assert all(turn.context_team_id == 1 for turn in turns)


def test_expired_when_snapshot_team_is_gone(team_ctx_db):
    """快照的 team 在 confirm 前被刪除（FK SET NULL）→ 無有效 team，MUST expire 而非誤執行。"""
    client = _client()
    conv_id = _global_conversation(client)
    fake = team_ctx_db["llm"]
    _push_tool_call(fake, "create_test_case_set", {"name": "GoneTeam", "description": ""})
    _send(client, conv_id, text="建立 set", message_id="m1", context_team_id=1)
    action_id = _pending_action_id(client, conv_id)

    with team_ctx_db["bundle"]["sync_session_factory"]() as session:
        turn = session.query(AssistantTurn).order_by(AssistantTurn.id).first()
        turn.context_team_id = None
        session.commit()

    r = client.post(f"/api/assistant/conversations/{conv_id}/actions/{action_id}/confirm", headers=HEADERS)
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["code"] == "SCOPE_INVALID"

    with team_ctx_db["bundle"]["sync_session_factory"]() as session:
        assert session.query(TestCaseSet).filter(TestCaseSet.name == "GoneTeam").first() is None


# --------------------------------------------------------------------------- #
# resolve 類工具的跨 team 行為
# --------------------------------------------------------------------------- #


def test_resolve_tool_may_target_another_accessible_team_with_team_label(team_ctx_db):
    """全域對話以 context team ART，但操作 CID 的 set：可存取即放行，且卡片標示 CID。"""
    client = _client()
    conv_id = _global_conversation(client)
    fake = team_ctx_db["llm"]
    _push_tool_call(
        fake, "create_test_case_section",
        {"set_id": team_ctx_db["cid_set_id"], "name": "From ART turn"},
    )

    r = _send(client, conv_id, text="在那個 set 下建 section", message_id="m1", context_team_id=1)
    assert r.status_code == 200, r.text
    assert "confirmation_required" in r.text, r.text

    summary = _pending_summary(client, conv_id)
    assert summary["team_id"] == 2 and summary["team_name"] == "CID", (
        "目標 team 必須是資源實際所屬的 team，否則使用者會誤判影響範圍"
    )


def test_resolve_tool_rejects_inaccessible_team(team_ctx_db, monkeypatch):
    """使用者無權存取的 team 資源 MUST 被拒（模擬 accessible teams 只有 ART）。"""
    from app.auth.permission_service import permission_service

    async def _only_art(user_id):
        return [1]

    monkeypatch.setattr(permission_service, "get_user_accessible_teams", _only_art)

    client = _client()
    conv_id = _global_conversation(client)
    fake = team_ctx_db["llm"]
    _push_tool_call(
        fake, "create_test_case_section",
        {"set_id": team_ctx_db["cid_set_id"], "name": "Should be rejected"},
    )
    _push_text(fake, "無法執行")

    r = _send(client, conv_id, text="在 CID 的 set 下建 section", message_id="m1", context_team_id=1)
    assert r.status_code == 200, r.text
    assert "confirmation_required" not in r.text


def test_team_bound_conversation_still_requires_exact_team_match(team_ctx_db):
    """team 對話的既有語意不變：跨 team 的 set_id 仍必須被拒。"""
    client = _client()
    r = client.post("/api/assistant/conversations", json={"scope_type": "team", "team_id": 1}, headers=HEADERS)
    conv_id = r.json()["id"]
    fake = team_ctx_db["llm"]
    _push_tool_call(
        fake, "create_test_case_section",
        {"set_id": team_ctx_db["cid_set_id"], "name": "Cross team"},
    )
    _push_text(fake, "無法執行")

    r2 = _send(client, conv_id, text="建 section", message_id="m1", context_team_id=2)
    assert r2.status_code == 200, r2.text
    assert "confirmation_required" not in r2.text, "team 對話不得因 context_team_id 而跨 team"

    turns = _turns(team_ctx_db["bundle"])
    assert turns[0].context_team_id is None, "team 對話不儲存 context team 快照"


# --------------------------------------------------------------------------- #
# 確認卡 fingerprint
# --------------------------------------------------------------------------- #


def test_target_team_is_part_of_the_confirmation_fingerprint(team_ctx_db):
    """team 進 summary 即進 fingerprint：同一動作在不同 team 的指紋必須不同。"""
    from app.config import AssistantConfig
    from app.services.assistant.tool_executor import ToolExecutor
    from app.services.assistant.tool_registry import get_tool_registry

    executor = ToolExecutor(
        app=app, main_boundary=get_main_access_boundary(), config=AssistantConfig(), registry=get_tool_registry()
    )
    tool = get_tool_registry().get("create_test_case_set")

    async def _fingerprints():
        art = await executor.build_confirmation_summary(
            tool, path_params={}, body_params={"name": "Same Name"}, team_id=1
        )
        cid = await executor.build_confirmation_summary(
            tool, path_params={}, body_params={"name": "Same Name"}, team_id=2
        )
        none_team = await executor.build_confirmation_summary(
            tool, path_params={}, body_params={"name": "Same Name"}
        )
        return art, cid, none_team

    art, cid, none_team = asyncio.run(_fingerprints())
    assert art[0]["team_name"] == "ART" and cid[0]["team_name"] == "CID"
    assert executor.compute_fingerprint(*art) != executor.compute_fingerprint(*cid)
    assert "team_id" not in none_team[0], "未指定 team 時 summary 不應憑空帶 team 欄位"
