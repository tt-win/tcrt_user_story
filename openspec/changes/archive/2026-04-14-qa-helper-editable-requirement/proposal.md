## Why

QA AI Helper 的「需求單內容確認」畫面（screen 2）目前以唯讀方式呈現從 JIRA 載入的需求內容。當需求單內容不完整或有誤時，QA 人員無法直接在 Helper 流程中修正，只能回到 JIRA 修改後重新操作，中斷了 AI 輔助產生 Test Case 的連續流程。開放使用者在確認畫面直接編修需求，並提供重新載入功能讓編修後的內容即時生效，可大幅降低來回切換的時間成本。

## What Changes

- 將 screen 2 的需求 Markdown 預覽區域從唯讀改為可編輯，使用者可直接修改 `raw_ticket_markdown` 內容
- 提供「重新解析」按鈕，讓編修後的需求重新經過 deterministic parser 與格式驗證，更新 `structured_requirement` 與 `validation_summary`
- 提供「重新載入需求單」按鈕，讓使用者可從 JIRA 重新抓取最新的需求單內容（覆蓋目前編輯），適用於需求單已在 JIRA 端更新的場景
- 前端需記錄是否有手動編修（dirty state），在重新載入前給予確認提示，避免使用者意外覆蓋已編輯的內容

## Capabilities

### New Capabilities
- `helper-requirement-editing`: 定義 screen 2 需求內容的可編輯行為，包含編輯模式切換、重新解析、dirty state 管理與重新載入確認互動

### Modified Capabilities
- `helper-guided-intake`: 原 spec 要求 screen 2 以唯讀呈現 ticket markdown（Requirement: "Screen 2 MUST render read-only ticket markdown"），此變更將解除唯讀限制，改為可編輯模式

## Impact

- **前端**：`app/templates/qa_ai_helper.html`（screen 2 卡片結構）、`app/static/js/qa-ai-helper/main.js`（renderTicketConfirmation、新增編輯/重新解析/重新載入邏輯）、`app/static/css/qa-ai-helper.css`（編輯模式樣式）
- **後端 API**：`app/api/qa_ai_helper.py` — 需新增或調整端點支援接收使用者編修後的 markdown 並觸發重新解析
- **服務層**：`app/services/qa_ai_helper_service.py` — 需新增接受自訂 markdown 的解析路徑（reparse），與既有 `fetch_ticket()` 重新載入路徑並存
- **i18n**：`app/static/locales/` 需新增編輯相關按鈕與確認提示文案
- **資料庫**：不新增欄位，reparse 直接更新既有 ticket_snapshot 的 `raw_ticket_markdown`、`structured_requirement`、`validation_summary`
- **Rollback 考量**：無 schema 變更，前端降級時回復唯讀行為即可
