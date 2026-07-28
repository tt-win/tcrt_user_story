## Why

`assistant-widget-ui` 目前要求「所有已登入頁面」都注入右下角 FAB，因此由 `window.open` 開啟的兩個彈出視窗也會出現 AI 助手入口：

- `/test-case-reference`（參考測試案例彈窗，`test-case-management/reference-test-case.js`、`test-run-execution/render.js` 開啟）
- `/test-case-management?...&minimal=1&mode=edit`（Test Case 編輯器彈窗，`test-run-execution/render.js` 開啟）

這兩個彈窗是為單一任務開的窄視窗（1200×800 / 1400×900，且 `minimal-mode` 已隱藏 header/footer），助手屬於主視窗的全域入口，在彈窗中只會遮住內容、也沒有跨頁續聊的價值。使用者要求彈窗中不需要出現 AI Assistant。

## What Changes

- widget 啟動時新增「彈出視窗不注入」判斷：`assistant-widget.js` 的 `init()` 在呼叫 availability API 之前先檢查視圖旗標，命中即完全不注入 DOM（不發 availability 請求）。
- 權威旗標由伺服器渲染：`base.html` 在 `hide_assistant_widget` 為真時輸出 `<body data-assistant-widget="off">`；`test_case_reference.html` 以 `{% set hide_assistant_widget = true %}` 標記（沿用既有 `page_title_i18n_key` 的慣例），`app/main.py` 的 `/test-case-management` route 把既有的 `minimal_flag` 傳入 context。
- 前端另容錯 `minimal=1` / `editor=1` query（與 `test-case-management/cache.js` 既有 minimal 判斷同一組條件），避免只靠 server context 的單點失誤。
- 主視窗、其餘所有已登入頁面行為完全不變；不動 availability API、權限模型、i18n 文案（無新增使用者可見文字）。

## Capabilities

### Modified Capabilities
- `assistant-widget-ui`: 「全頁懸浮入口與可見性 gating」requirement 增列例外——以 `window.open` 開啟的單一任務彈出視窗 MUST NOT 注入 widget。

## Impact

- **前端 JS**：`app/static/js/assistant-widget.js` 新增純函式 `assistantWidgetDisabledForView()` 與 `init()` 早退。
- **前端 template**：`app/templates/base.html`（body 屬性）、`app/templates/test_case_reference.html`（旗標）。
- **後端**：`app/main.py` `/test-case-management` route 多傳一個 template context 值；無 API contract、無 schema、無 migration 變更。
- **測試**：`app/testsuite/js/assistant-widget.test.mjs` 新增純函式測試。
- **i18n**：無變更。
