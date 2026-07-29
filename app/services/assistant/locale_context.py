"""回合回覆語言（reply language；跟隨前端 UI 語系）。

送往 LLM 的 system prompt 是跨使用者共用的快取內容，且整份模板以繁體中文撰寫，唯一的語言規則
是「跟隨使用者訊息的語言」——實務上模型因此不論 UI 切到哪個語系都以繁體中文回覆。本模組把
「本回合的介面語系」組成可 append 的權威語言指示（MUST NOT 進入 prompt 快取，與
`capability_context` 同一理由），並提供對話標題摘要用的單行指示。

語系值由前端提供（`ui_locale`），MUST 先經 `normalize_ui_locale` 映射到支援清單才使用：
prompt 內只出現映射後的常數字串，client 原字串不得插入 prompt。無法映射時回傳 `None`，
呼叫端一律略過語言指示（退回 prompt 內的「跟隨使用者訊息語言」預設），不得因此拒絕請求。
"""

from __future__ import annotations

from typing import Optional

# 與前端 `app/static/js/i18n.js` 的 `supportedLanguages` 對齊（en-US / zh-CN / zh-TW 三語系）。
SUPPORTED_UI_LOCALES: tuple[str, ...] = ("en-US", "zh-CN", "zh-TW")

# 語言指示刻意以該語系本身撰寫：整份 system prompt 為繁體中文，用目標語言下達指令才是最強訊號。
_REPLY_LANGUAGE_BLOCKS: dict[str, str] = {
    "en-US": (
        "## Response language (authoritative for this turn)\n"
        "\n"
        "- The user's interface language is `en-US`. Reply in English only, even when the user's\n"
        "  message is written in another language.\n"
        "- Keep identifiers verbatim: test case numbers (e.g. `TCG-1234`), team names, set / section /\n"
        "  test run titles, tool names and API field values are data, so never translate them.\n"
        "- This rule overrides any other language guidance in this prompt.\n"
    ),
    "zh-CN": (
        "## 回复语言（本回合权威）\n"
        "\n"
        "- 用户的界面语言是 `zh-CN`。无论用户用哪种语言提问，一律使用简体中文回复。\n"
        "- 标识符保持原文：测试案例编号（例如 `TCG-1234`）、team 名称、set／section／test run 名称、\n"
        "  工具名与 API 字段取值都是资料，不要翻译。\n"
        "- 本规则优先于本 prompt 中其他任何语言指示。\n"
    ),
    "zh-TW": (
        "## 回覆語言（本回合權威）\n"
        "\n"
        "- 使用者的介面語言是 `zh-TW`。無論使用者以哪種語言提問，一律使用繁體中文回覆。\n"
        "- 識別碼保持原文：測試案例編號（例如 `TCG-1234`）、team 名稱、set／section／test run 名稱、\n"
        "  工具名與 API 欄位取值都是資料，不要翻譯。\n"
        "- 本規則優先於本 prompt 中其他任何語言指示。\n"
    ),
}

# 對話標題摘要（`title_service`）用的單行指示；同樣以目標語系撰寫。
_TITLE_LANGUAGE_LINES: dict[str, str] = {
    "en-US": "- Write the title in English, regardless of the language used in the conversation.",
    "zh-CN": "- 无论对话使用哪种语言，标题一律使用简体中文。",
    "zh-TW": "- 無論對話使用哪種語言，標題一律使用繁體中文。",
}


def normalize_ui_locale(raw: Optional[str]) -> Optional[str]:
    """把 client 送來的語系字串映射到 `SUPPORTED_UI_LOCALES`；無法映射回傳 `None`。

    映射規則鏡射前端 `i18n.js` 的 `normalizeSupportedLanguage`（含 Safari 的 `zh-Hant-TW` /
    `zh-Hans-CN` 形式與 `zh` 預設簡體），避免前後端對同一字串得出不同語系。
    """
    if not raw:
        return None
    text = str(raw).strip()
    if not text:
        return None
    lowered = text.lower().replace("_", "-")

    for locale in SUPPORTED_UI_LOCALES:
        if lowered == locale.lower():
            return locale
    if lowered.startswith("zh-hant") or lowered in {"zh-tw", "zh-hk", "zh-mo"}:
        return "zh-TW"
    if lowered.startswith("zh-hans") or lowered in {"zh-cn", "zh-sg"}:
        return "zh-CN"

    primary = lowered.split("-")[0]
    if primary == "zh":
        return "zh-CN"
    for locale in SUPPORTED_UI_LOCALES:
        if locale.lower().startswith(f"{primary}-"):
            return locale
    return None


def build_reply_language_context(ui_locale: str) -> str:
    """回傳該語系的語言指示區塊；未支援的語系視為 `zh-TW`（呼叫端已先 normalize）。"""
    return _REPLY_LANGUAGE_BLOCKS.get(ui_locale, _REPLY_LANGUAGE_BLOCKS["zh-TW"])


def append_reply_language_context(system_prompt: str, ui_locale: Optional[str]) -> str:
    """把語言指示接在組裝後的 system prompt 之後（含 capability context 之後）。

    MUST 以 append 實作、MUST NOT 依賴模板 token：DB 內的 system prompt 可由管理員任意編輯，
    token 一被刪掉就會靜默退回「永遠繁體中文」的錯誤行為（同 `capability_context` 的理由）。
    `ui_locale` 為 `None`（未帶或無法映射）時原樣回傳，由 prompt 內的預設規則處理。
    """
    normalized = normalize_ui_locale(ui_locale)
    if normalized is None:
        return system_prompt
    return f"{system_prompt.rstrip()}\n\n{build_reply_language_context(normalized)}"


def append_title_language_line(title_prompt: str, ui_locale: Optional[str]) -> str:
    """把標題語言指示接在標題 prompt 之後；`ui_locale` 為 `None` 時原樣回傳。"""
    normalized = normalize_ui_locale(ui_locale)
    if normalized is None:
        return title_prompt
    return f"{title_prompt.rstrip()}\n{_TITLE_LANGUAGE_LINES[normalized]}\n"
