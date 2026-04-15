## Why

創建一個概念驗證（PoC）腳本，讓 QA 工程師能夠透過 JIRA Ticket 單號快速生成相關的 Test Cases。目前的 Test Case 創建流程需要人工分析 JIRA Ticket 內容並手動撰寫 Test Cases，這個過程耗時且容易遺漏測試情境。透過這個 PoC 工具，可以自動化地從 JIRA 取得 Ticket 資訊，查詢歷史相似的 Test Cases 作為參考，並利用 LLM 生成完整的 Test Cases，大幅提升測試準備效率。

## What Changes

- **新增** `ai/jira_to_test_case_poc.py` - TUI 互動式腳本，提供以下功能：
  - 輸入 JIRA Ticket 單號（如 PROJ-123）
  - 自動從 JIRA API 取得 Ticket 資訊（description, component, labels 等）
  - 自動判斷所屬 component
  - 從 Qdrant 向量資料庫查詢相關的 Test Cases
  - 使用 OpenRouter (openrouter/free) LLM 生成符合格式的 Test Cases
  - TUI 格式化顯示生成的 Test Cases
- **新增** OpenSpec 變更追蹤記錄

## Capabilities

### New Capabilities
- `jira-ticket-to-test-case-poc`: TUI 工具，將 JIRA Ticket 轉換為 Test Cases 的概念驗證實作

### Modified Capabilities
- None (this is a new PoC tool, not modifying existing capabilities)

## Impact

**新增檔案:**
- `ai/jira_to_test_case_poc.py` - 主要的 TUI 腳本

**依賴項目:**
- `textual` - 用於建立 TUI 介面
- `app.services.jira_client` - 與 JIRA API 互動
- `app.services.qdrant_client` 或直接使用 `qdrant_client` - 查詢向量資料庫
- OpenRouter API (openrouter/free) - LLM 推論

**現有系統影響:**
- 不影響現有資料庫結構
- 不修改現有 API
- 純粹是獨立執行的 PoC 工具
- 需要 Qdrant 向量資料庫中已有 Test Cases 資料
