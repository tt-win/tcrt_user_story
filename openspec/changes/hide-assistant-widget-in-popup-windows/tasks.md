## 1. 前端 widget 判斷

- [x] 1.1 `app/static/js/assistant-widget.js` 新增檔案頂層純函式 `assistantWidgetDisabledForView(bodyDataset, search)`：`data-assistant-widget="off"` 或 `minimal=1|true` / `editor=1|true` query 即回傳 true（不使用 `URLSearchParams`，維持 node:test vm context 可測）
- [x] 1.2 `init()` 在 `checkAvailability()` 之前呼叫該判斷並早退，命中時不注入任何 DOM、不發 availability 請求

## 2. 伺服器端旗標

- [x] 2.1 `app/templates/base.html`：`hide_assistant_widget` 為真時於 `<body>` 輸出 `data-assistant-widget="off"`
- [x] 2.2 `app/templates/test_case_reference.html`：`{% set hide_assistant_widget = true %}`
- [x] 2.3 `app/main.py` `/test-case-management` route：把既有 `minimal_flag` 以 `hide_assistant_widget` 傳入 template context

## 3. 測試與 spec

- [x] 3.1 `app/testsuite/js/assistant-widget.test.mjs` 新增 `assistantWidgetDisabledForView` 測試（server 旗標、minimal/editor query、一般頁面、近似值不誤判）
- [x] 3.2 `openspec/changes/hide-assistant-widget-in-popup-windows/specs/assistant-widget-ui/spec.md` 記錄 requirement delta
