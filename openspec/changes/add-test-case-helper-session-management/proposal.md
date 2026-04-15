## Why

目前 AI Agent - Test Case Helper 只能恢復「最近一次」session，當使用者同時處理多張 JIRA ticket 時，缺乏可視化 session 管理，容易誤刪進度或重工。We need a dedicated session management flow to browse, resume, and clean up sessions safely.

## What Changes

- 在 AI Helper modal 的「重新開始」右側新增「Session 管理」入口。
- 新增 Session 管理 modal：可瀏覽 session、顯示對應 JIRA ticket、回復到任一 session 進度。
- 新增批次選取刪除與一鍵清理（刪除該團隊可見的 helper sessions）。
- 調整 session 命名規則：由流水號改為 timestamp-based 命名。
- 定義 modal 切換生命週期：開啟 Session 管理時暫時收起 Helper；關閉 Session 管理時恢復 Helper 顯示；執行回復時自動切回 Helper 並載入指定 session。

## Capabilities

### New Capabilities

- `helper-session-management`: Session 管理介面的瀏覽、回復、批次刪除、一鍵清理與 modal 切換行為。

### Modified Capabilities

- `jira-ticket-to-test-case-poc`: 調整 helper session display naming 與 resume 相關要求（timestamp naming + resume target session）。

## Impact

- Frontend: `app/templates/_partials/ai_test_case_helper_modal.html`, new session manager partial/modal, `app/static/js/test-case-management/ai-helper.js`, helper modal CSS。
- Backend API: helper session listing/filtering、bulk delete、clear-all endpoints（沿用既有權限模型）。
- Data/Model: helper session display name 生成策略（timestamp）與刪除行為稽核。
- Tests: frontend interaction tests + API tests for resume/bulk delete/clear-all。

## Purpose

提供可控、可回復、可清理的 Helper Session 管理能力，降低多 ticket 並行作業時的上下文切換成本，並提升 session 生命周期可維護性。

## Requirements

### Requirement: Session Manager Entry and Modal Switching

- **GIVEN** 使用者正在 AI Agent - Test Case Helper modal
- **WHEN** 使用者點擊「Session 管理」
- **THEN** Helper modal 暫時隱藏並開啟 Session 管理 modal
- **AND** 關閉 Session 管理 modal 時，Helper modal MUST 回復顯示

### Requirement: Resume Any Session by Ticket-Aware List

- **GIVEN** Session 管理 modal 顯示 session 清單
- **WHEN** 使用者選擇任一 session 並執行回復
- **THEN** 系統 MUST 重新開啟 Helper modal 並接續該 session 階段與內容
- **AND** 左側清單 MUST 顯示該 session 對應的 JIRA ticket key

### Requirement: Batch Delete and One-Click Cleanup

- **GIVEN** Session 管理 modal
- **WHEN** 使用者勾選多筆 session 並刪除，或點擊一鍵清理
- **THEN** 系統 MUST 刪除指定 session（或全部可見 sessions）並更新清單

## Non-Functional Requirements

- Session 列表與操作回應應維持在可互動體驗（列表/刪除操作一般情境 < 2s，依現有資料量）。
- Session 命名格式需 deterministic 且可讀（timestamp-based），並可跨語系穩定顯示。
- 所有新文案需補齊 `zh-TW`、`zh-CN`、`en-US`。
