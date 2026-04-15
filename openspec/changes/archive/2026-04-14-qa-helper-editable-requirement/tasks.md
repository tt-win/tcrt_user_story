## 1. 後端 Reparse API

- [x] 1.1 在 `app/models/qa_ai_helper.py` 新增 `QAAIHelperTicketReparseRequest` Pydantic model（含 `raw_ticket_markdown: str` 欄位）
- [x] 1.2 在 `app/services/qa_ai_helper_service.py` 新增 `reparse_ticket()` 方法：接收 markdown → 執行 deterministic parser → 驗證 → 更新既有 ticket_snapshot 的 `raw_ticket_markdown`、`structured_requirement`、`validation_summary` → 回傳 workspace
- [x] 1.3 在 `app/api/qa_ai_helper.py` 新增 `POST /sessions/{session_id}/ticket/reparse` 端點，委派至 service 的 `reparse_ticket()`

## 2. 前端 HTML 模板

- [x] 2.1 在 `qa_ai_helper.html` 的 screen 2 Markdown 預覽區域上方新增工具列：「編輯」按鈕、「重新載入需求單」按鈕
- [x] 2.2 新增 textarea 元素（預設 hidden）與編輯模式工具列（「重新解析」按鈕、「取消編輯」按鈕）

## 3. 前端 JavaScript 邏輯

- [x] 3.1 新增 `enterEditMode()` 函數：隱藏 Markdown 預覽、顯示 textarea 並填入 raw markdown
- [x] 3.2 新增 `exitEditMode()` 函數：隱藏 textarea、恢復 Markdown 預覽、清除 dirty state
- [x] 3.3 新增前端 dirty state 追蹤（`state.ticketMarkdownDirty`），textarea 內容變更時設為 true
- [x] 3.4 新增 `reparseTicketMarkdown()` 函數：收集 textarea 內容，呼叫 `POST /sessions/{session_id}/ticket/reparse`，更新 state 並重新渲染
- [x] 3.5 新增 `reloadTicketFromJira()` 函數：若 dirty 則顯示 confirm dialog，確認後呼叫既有 `POST /sessions/{session_id}/ticket`
- [x] 3.6 更新 `renderTicketConfirmation()` 函數：reparse 成功後退出 edit mode、重新渲染 preview 與 validation summary
- [x] 3.7 綁定新按鈕的 click 事件至對應函數

## 4. 前端樣式

- [x] 4.1 在 `qa-ai-helper.css` 新增 edit mode textarea 樣式與 edit toolbar 樣式

## 5. i18n 文案

- [x] 5.1 在 `app/static/locales/` 的 zh-TW 與 en 語系檔新增：編輯、取消編輯、重新解析、重新載入需求單、確認覆蓋 dialog 等文案

## 6. 驗證

- [ ] 6.1 手動驗證：編輯 → 重新解析 → validation 更新正確
- [ ] 6.2 手動驗證：dirty state 下重新載入 → confirm dialog → JIRA 內容覆蓋
- [ ] 6.3 確認既有流程不受影響：不編輯直接 proceed 仍正常運作
