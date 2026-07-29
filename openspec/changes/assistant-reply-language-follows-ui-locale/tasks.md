## 1. 語系正規化與語言指示

- [x] 1.1 新增 `app/services/assistant/locale_context.py`：`normalize_ui_locale()` 鏡射前端 `i18n.js` 的 `normalizeSupportedLanguage`（三語系、`zh-Hant-*`/`zh-Hans-*`/`zh-HK`/`zh-SG`、裸 `zh` → `zh-CN`），無法映射回傳 `None`
- [x] 1.2 同檔提供 `build_reply_language_context()` / `append_reply_language_context()`：指示區塊以目標語系本身撰寫、宣告為本回合權威、要求識別碼保持原文；prompt 內只出現映射後的常數字串（不插入 client 原字串）
- [x] 1.3 同檔提供 `append_title_language_line()` 供對話標題摘要使用

## 2. 回合組裝

- [x] 2.1 `assistant_agent_service._run_llm_loop` 新增 `ui_locale` 參數，於 `append_capability_context` 之後 append 語言指示（不寫回 assemble 快取、不依賴模板 token）
- [x] 2.2 `run_agent_turn` / `run_confirm_turn` 傳遞 `ui_locale`（含 confirm continuation 的內層迴圈）

## 3. API contract

- [x] 3.1 `POST /api/assistant/conversations/{id}/messages` 新增 optional form 欄位 `ui_locale`，normalize 後傳入 runner；無法映射視為未提供，不回 4xx
- [x] 3.2 `POST /api/assistant/conversations/{id}/actions/{action_id}/confirm` 新增 optional query 參數 `ui_locale`（語言取 confirm 當下語系，有效 team 仍取 turn 快照）

## 4. 對話標題語言

- [x] 4.1 `ConversationService.set_reply_locale()` 保存本 request／turn 語系，`maybe_generate_title` 傳入 `title_service.generate_title(ui_locale=...)`
- [x] 4.2 `title_service.generate_title` 接受 `ui_locale` 並以 append 方式補語言指示；`prompts/assistant/title.md` 移除寫死的「繁體中文」並改為預設跟隨使用者訊息語言

## 5. Prompt 與前端

- [x] 5.1 `prompts/assistant/system.md`「語言」段落改為以回合語言指示為權威、無指示時才跟隨使用者訊息語言，並要求識別碼不翻譯
- [x] 5.2 `app/static/js/assistant-widget.js` 新增檔案頂層純函式 `assistantUiLocaleFrom(i18nApi, storage, documentLang)`（i18n → `localStorage.language` → `<html lang>`，取不到回傳 null）
- [x] 5.3 送訊息的 FormData 與確認的 URL 帶上 `ui_locale`（`encodeURIComponent`）

## 6. 測試與 spec

- [x] 6.1 新增 `app/testsuite/test_assistant_reply_language.py`：語系正規化參數化、append 行為（不改動／無法映射即略過／排在最後）、端到端三語系進入 system prompt、切換語系不污染共用快取、標題 prompt 語言
- [x] 6.2 `app/testsuite/test_assistant_conversation_title.py` 補 `ui_locale` 轉遞測試並更新既有 stub 簽名
- [x] 6.3 `app/testsuite/js/assistant-widget.test.mjs` 補 `assistantUiLocaleFrom` 測試
- [x] 6.4 `openspec/changes/assistant-reply-language-follows-ui-locale/specs/` 記錄 `assistant-agent-loop`（ADDED）與 `assistant-conversations`（MODIFIED）requirement delta
