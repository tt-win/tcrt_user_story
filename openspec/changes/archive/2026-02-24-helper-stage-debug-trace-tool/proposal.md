## Why

目前 `AI Agent - Test Case Helper` 在部分票據仍會出現階段性失敗（尤其是 Requirement IR / Coverage JSON）。現行日志不足以在單次執行後完整回放每一階段的輸入、輸出與 LLM 原始回應，導致排障迭代成本高且難以穩定復現。

## What Changes

- 新增一個「統一 debug runner 工具」，可依序執行 Helper 六個階段並將每階段資料落檔。
- 每個階段提供獨立函式，可單獨執行、重跑、讀取上一步輸出檔案。
- 每個階段都保存完整 artifact（包含 prompt、LLM 原始回應、解析後 payload、錯誤堆疊、執行 metadata）。
- 新增格式化檢視功能，可將任一階段 artifact 以可閱讀格式完整呈現。
- 工具與輸出檔案皆放在 repo 忽略路徑，不納入 git 版本控管。

## Capabilities

### New Capabilities
- `helper-stage-debug-trace`: 提供可重播、可分階段執行的 Test Case Helper 調試管線與 artifact 落盤機制。

### Modified Capabilities
- `jira-ticket-to-test-case-poc`: 補充可觀測性與排障作業模式（不改動既有使用者流程與 API 契約）。

## Impact

- Affected code:
  - `app/services/jira_testcase_helper_service.py`
  - `app/services/jira_testcase_helper_llm_service.py`
  - `scripts/`（新增 debug runner）
  - `app/testsuite/`（新增工具層測試）
- Output storage (git ignored):
  - `.tmp/helper-debug-runs/<run-id>/stage-*.json`
  - `.tmp/helper-debug-runs/<run-id>/stage-*.md`
- External dependencies:
  - Jira client
  - OpenRouter model calls
  - Qdrant client（在 testcase/audit 階段）

## Purpose

- 中文：建立可追溯、可重播的階段診斷工具，快速定位哪一個階段與哪一段 LLM 回應造成失敗。
- English: Build a replayable stage-debug tool with full artifacts to localize failure causes across the helper pipeline.

## Requirements

- 系統 SHALL 提供六個獨立函式對應階段：Requirement IR、Analysis、Coverage、Test Case、Audit、Final Test Case。
- 系統 SHALL 允許每個階段從對應 artifact 檔案讀取上一步輸入，支援單獨重跑。
- 系統 SHALL 在每個階段儲存完整資料：輸入 payload、prompt、LLM raw response、parse result、錯誤資訊、時間戳與模型資訊。
- 系統 SHALL 提供格式化檢視輸出，能完整呈現指定 run 與指定 stage 的內容。
- 系統 SHALL 將工具及輸出資料放在 git ignore 路徑，不進版控。

Scenario (Given-When-Then):
- Given 一個會在 Requirement IR 或 Coverage 階段失敗的 TCG 單號
- When 工具逐階段執行並寫入 artifact
- Then 開發者可直接讀取對應 stage 檔案定位失敗原因，並可單獨重跑該 stage

## Non-Functional Requirements

- Reliability: 即使中途某 stage 失敗，也必須保留到失敗點前的所有 artifact。
- Observability: 每 stage 檔案需包含 request/response correlation 資訊與模型設定。
- Performance: 工具為除錯用途，不影響線上主流程；輸出落檔採本地檔案，避免阻塞主要 API。
- Maintainability: 每 stage 函式邊界清晰，可在單元測試中獨立驗證。
