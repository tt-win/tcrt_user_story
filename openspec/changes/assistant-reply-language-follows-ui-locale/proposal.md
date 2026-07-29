## Why

AI Assistant 不論 UI 切到 `en-US`、`zh-CN` 或 `zh-TW`，回覆一律是繁體中文。根因不是模型偏好，而是助手**完全不知道介面語系**：

- 前端 `assistant-widget.js` 送訊息（`POST /api/assistant/.../messages`）與確認（`.../confirm`）時都沒有帶語系，後端也沒有任何語系參數。
- `prompts/assistant/system.md` 唯一的語言規則是「使用使用者訊息所使用的語言回覆」；而整份模板（含 capability context）都是繁體中文，實務上模型就一路以繁體中文回覆，連英文提問也常被回中文。
- `prompts/assistant/title.md` 更直接寫死「繁體中文短標題」，因此「近期對話」清單的自動標題永遠是繁體中文。

`assistant-widget-ui` 已要求 widget 介面文案三語系跟隨 UI，但助手**產出**的語言不在任何 spec 內，形成缺口：介面是英文、回答卻是中文。

## What Changes

- 新增 `app/services/assistant/locale_context.py`：語系正規化（鏡射前端 `i18n.js` 的 `normalizeSupportedLanguage`，含 `zh-Hant-*` / `zh-Hans-*`）與「回覆語言」指示區塊；區塊以目標語系本身撰寫，並宣告為本回合權威、優先於 prompt 內其他語言敘述。
- 回合組裝：`_run_llm_loop` 在 capability context 之後 append 語言指示。與 capability context 同一約束——MUST 在 assemble 之後 append、MUST NOT 依賴模板 token（DB prompt 可被管理員改寫）、MUST NOT 進入跨使用者的 system prompt 快取。
- API contract（皆為 optional，未帶即維持原行為）：`POST /api/assistant/conversations/{id}/messages` 新增 form 欄位 `ui_locale`；`POST /api/assistant/conversations/{id}/actions/{action_id}/confirm` 新增 query 參數 `ui_locale`。無法映射到支援語系一律視為未提供，不得因此拒絕請求。
- 前端：`assistant-widget.js` 新增純函式 `assistantUiLocaleFrom()`（i18n 現行語系 → `localStorage.language` → `<html lang>`），送訊息與確認時帶上 `ui_locale`。
- 對話標題：`title.md` 移除寫死的「繁體中文」，改為「預設跟隨使用者訊息語言、prompt 結尾另有語言指示時以其為準」；`ConversationService.set_reply_locale()` 把本 request 的語系交給背景標題摘要使用（orphan recovery 等無 request 情境維持 None → 走預設規則）。
- 無新增使用者可見文案，`app/static/locales/*.json` 不變；無 schema／migration 變更。

## Non-goals

- 不新增「助手回覆語言」的獨立使用者設定；語言一律跟隨介面語系（單一來源，避免第二個開關）。
- 不改變 confirm 的有效 team 來源（仍取 turn 快照）；`ui_locale` 只影響本次 continuation 產生的文字。
- 不翻譯系統控制路徑的固定文案（如達迭代上限的收尾訊息、`error_message`）——那些是既有的後端固定字串，不在本次範圍。
- 不改 QA AI Helper 的 `output_locale` 流程（既有機制，另有 session 級設定）。

## Capabilities

### Modified Capabilities
- `assistant-agent-loop`: 新增 requirement「回覆語言跟隨介面語系」——回合 system prompt MUST append 依 UI 語系決定的權威語言指示。
- `assistant-conversations`: 「對話標題自動摘要」requirement 增列標題語言規則（跟隨該回合 UI 語系，無語系時跟隨使用者訊息語言，MUST NOT 寫死單一語系）。

## Impact

- **後端服務**：新檔 `app/services/assistant/locale_context.py`；`assistant_agent_service.py`（`_run_llm_loop` / `run_agent_turn` / `run_confirm_turn` 多一個 `ui_locale`）；`conversation_service.py`（`set_reply_locale` + 傳入標題摘要）；`title_service.py`（`generate_title(ui_locale=...)`）。
- **API**：`app/api/assistant.py` 兩個端點各多一個 optional 參數；既有 client 未帶時行為不變（向後相容）。
- **Prompt 檔**：`prompts/assistant/system.md`「語言」段落、`prompts/assistant/title.md` 標題語言規則。DB 內已被管理員覆寫的 system prompt 也能生效（語言指示以 append 注入，不依賴模板 token）。
- **前端**：`app/static/js/assistant-widget.js`（純函式 + 送出／確認帶語系）。
- **測試**：新增 `app/testsuite/test_assistant_reply_language.py`；`app/testsuite/test_assistant_conversation_title.py` 補 `ui_locale` 轉遞；`app/testsuite/js/assistant-widget.test.mjs` 補純函式測試。
- **i18n / schema / migration**：無變更。
- **風險**：語言指示是 prompt 層行為，模型仍有極小機率不遵循；斷言對象因此是「送往 LLM 的 system prompt 內容」而非模型輸出。若前端送出未支援語系（例如未來新增語系但後端未同步），行為退回原本的「跟隨使用者訊息語言」，不會壞掉整個回合。
