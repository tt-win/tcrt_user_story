"""助手回覆語言跟隨介面語系（spec assistant-agent-loop「回覆語言跟隨介面語系」、
assistant-conversations「對話標題自動摘要」）。

回歸目標：UI 切到 en-US／zh-CN 時，送往 LLM 的 system prompt 必須帶該語系的權威語言指示，
而不是只靠一份繁體中文模板讓模型一律回繁體中文。LLM 輸出無法確定性斷言，因此斷言對象是
（a）送進 LLM 的 system prompt 內容、（b）語系正規化與 append 的純函式行為。
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
from app.main import app
from app.models.database_models import User
import app.services.assistant.assistant_llm_service as llm_mod
from app.services.assistant import conversation_service as conversation_service_module
from app.services.assistant import title_service
from app.services.assistant.locale_context import (
    SUPPORTED_UI_LOCALES,
    append_reply_language_context,
    append_title_language_line,
    build_reply_language_context,
    normalize_ui_locale,
)
from app.testsuite.db_test_helpers import (
    create_managed_test_database,
    dispose_managed_test_database,
    install_main_database_overrides,
)

HEADERS = {"Authorization": "Bearer dummy"}

_LOCALE_MARKERS = {
    "en-US": "Reply in English only",
    "zh-CN": "一律使用简体中文回复",
    "zh-TW": "一律使用繁體中文回覆",
}


# --------------------------------------------------------------------------- #
# 語系正規化（與前端 i18n.js 的 normalizeSupportedLanguage 對齊）
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("en-US", "en-US"),
        ("zh-CN", "zh-CN"),
        ("zh-TW", "zh-TW"),
        ("en-us", "en-US"),
        ("zh_TW", "zh-TW"),
        ("  zh-TW  ", "zh-TW"),
        ("zh-Hant-TW", "zh-TW"),
        ("zh-Hans-CN", "zh-CN"),
        ("zh-HK", "zh-TW"),
        ("zh-SG", "zh-CN"),
        ("zh", "zh-CN"),
        ("en-GB", "en-US"),
        (None, None),
        ("", None),
        ("   ", None),
        ("ja-JP", None),
        ("klingon", None),
    ],
)
def test_normalize_ui_locale(raw, expected):
    assert normalize_ui_locale(raw) == expected


def test_every_supported_locale_has_a_directive():
    for locale in SUPPORTED_UI_LOCALES:
        block = build_reply_language_context(locale)
        assert _LOCALE_MARKERS[locale] in block
        assert f"`{locale}`" in block, "語言指示必須標明本回合語系"


# --------------------------------------------------------------------------- #
# append 行為（不依賴模板 token、無語系即不改動）
# --------------------------------------------------------------------------- #


def test_append_reply_language_context_appends_to_the_end():
    base = "admin 自訂的 system prompt（不含任何語言 token）\n\n## 本回合能力事實\n- ...\n"

    result = append_reply_language_context(base, "en-US")

    assert result.startswith("admin 自訂的 system prompt")
    assert "## 本回合能力事實" in result, "既有 capability context 不得被覆寫"
    assert _LOCALE_MARKERS["en-US"] in result
    assert result.index("## 本回合能力事實") < result.index("Reply in English only"), (
        "語言指示必須排在最後（最靠近使用者訊息，優先於前面的一般性描述）"
    )


def test_append_reply_language_context_normalizes_and_skips_unknown_locale():
    base = "prompt"

    assert _LOCALE_MARKERS["zh-CN"] in append_reply_language_context(base, "zh-Hans-CN")
    assert append_reply_language_context(base, None) == base
    assert append_reply_language_context(base, "ja-JP") == base, "無法映射時退回 prompt 預設規則"


def test_append_title_language_line():
    base = "標題 prompt\n- 既有規則\n"

    assert "标题一律使用简体中文" in append_title_language_line(base, "zh-CN")
    assert "Write the title in English" in append_title_language_line(base, "en-us")
    assert append_title_language_line(base, None) == base
    assert append_title_language_line(base, "ja-JP") == base


# --------------------------------------------------------------------------- #
# 端到端：POST /messages 的 ui_locale 進到送往 LLM 的 system prompt
# --------------------------------------------------------------------------- #


class _FakeLLM:
    """記錄每次呼叫的 system prompt（跨回合快取污染的斷言對象）。"""

    def __init__(self):
        self.system_prompts: list[str] = []

    def is_configured(self):
        return True

    async def call(self, *, system_prompt, messages, tools):
        self.system_prompts.append(system_prompt)
        return llm_mod.AssistantLLMResult(content="done", tool_calls=[])


@pytest.fixture
def locale_db(tmp_path, monkeypatch):
    bundle = create_managed_test_database(tmp_path / "assistant_reply_language.db")
    install_main_database_overrides(
        monkeypatch=monkeypatch,
        app=app,
        get_db_dependency=get_db,
        async_engine=bundle["async_engine"],
        async_session_factory=bundle["async_session_factory"],
    )
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=1, username="locale-tester", role=UserRole.USER
    )
    monkeypatch.setattr(settings.ai.assistant, "enabled", True)
    monkeypatch.setattr(settings.openrouter, "api_key", "fake-key-for-test")

    fake_llm = _FakeLLM()
    monkeypatch.setattr(llm_mod, "_service_singleton", fake_llm)
    # 標題摘要另以單元測試涵蓋；此處不讓背景 task 干擾 system prompt 記錄。
    monkeypatch.setattr(conversation_service_module, "_fire_and_forget_title_generation", lambda *a, **k: None)

    with bundle["sync_session_factory"]() as session:
        session.add(User(id=1, username="locale-tester", email="locale@example.com", hashed_password="x",
                         role=UserRole.USER, is_active=True, is_verified=True))
        session.commit()

    yield {"bundle": bundle, "llm": fake_llm}

    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_current_user, None)
    dispose_managed_test_database(bundle)


def _conversation(client) -> int:
    r = client.post("/api/assistant/conversations", json={"scope_type": "global"}, headers=HEADERS)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _send(client, conv_id, *, message_id, ui_locale=None, text="hi"):
    data = {"text": text, "client_message_id": message_id}
    if ui_locale is not None:
        data["ui_locale"] = ui_locale
    return client.post(f"/api/assistant/conversations/{conv_id}/messages", headers=HEADERS, data=data)


@pytest.mark.parametrize("ui_locale", ["en-US", "zh-CN", "zh-TW"])
def test_ui_locale_reaches_the_system_prompt(locale_db, ui_locale):
    client = TestClient(app)
    conv_id = _conversation(client)

    r = _send(client, conv_id, message_id="m1", ui_locale=ui_locale)
    assert r.status_code == 200, r.text

    prompts = locale_db["llm"].system_prompts
    assert len(prompts) == 1
    assert _LOCALE_MARKERS[ui_locale] in prompts[0]
    other_markers = [m for loc, m in _LOCALE_MARKERS.items() if loc != ui_locale]
    assert not [m for m in other_markers if m in prompts[0]], "同一回合不得出現其他語系的指示"


def test_unmappable_or_missing_locale_is_ignored_without_rejecting_the_turn(locale_db):
    client = TestClient(app)
    conv_id = _conversation(client)

    assert _send(client, conv_id, message_id="m1", ui_locale="ja-JP").status_code == 200
    assert _send(client, conv_id, message_id="m2").status_code == 200

    for prompt in locale_db["llm"].system_prompts:
        assert not [m for m in _LOCALE_MARKERS.values() if m in prompt], (
            "無可用語系時不得附加語言指示（退回 prompt 內的預設規則）"
        )


def test_switching_ui_language_switches_the_next_turn_without_polluting_the_cache(locale_db):
    """同一 process／同一對話先後兩個語系：assemble 的共用快取不得殘留上一回合的語言指示。"""
    client = TestClient(app)
    conv_id = _conversation(client)

    assert _send(client, conv_id, message_id="m1", ui_locale="zh-TW").status_code == 200
    assert _send(client, conv_id, message_id="m2", ui_locale="en-US").status_code == 200

    first, second = locale_db["llm"].system_prompts
    assert _LOCALE_MARKERS["zh-TW"] in first and _LOCALE_MARKERS["en-US"] not in first
    assert _LOCALE_MARKERS["en-US"] in second and _LOCALE_MARKERS["zh-TW"] not in second


# --------------------------------------------------------------------------- #
# 標題摘要語言
# --------------------------------------------------------------------------- #


def test_title_prompt_carries_the_requested_language(monkeypatch):
    captured: dict[str, str] = {}

    class _TitleLLM:
        def is_configured(self):
            return True

        async def call(self, *, system_prompt, messages, tools):
            captured["system_prompt"] = system_prompt
            return llm_mod.AssistantLLMResult(content="Find failing login cases", tool_calls=[])

    monkeypatch.setattr(title_service, "get_assistant_llm_service", lambda: _TitleLLM())

    title = asyncio.run(title_service.generate_title(
        user_text="list failing cases", assistant_text="here they are", max_chars=40, ui_locale="en-US"
    ))
    assert title == "Find failing login cases"
    assert "Write the title in English" in captured["system_prompt"]

    asyncio.run(title_service.generate_title(
        user_text="list failing cases", assistant_text="here they are", max_chars=40
    ))
    assert "繁體中文" not in captured["system_prompt"], "未帶語系時不得寫死繁體中文"
    assert "Write the title in English" not in captured["system_prompt"]
