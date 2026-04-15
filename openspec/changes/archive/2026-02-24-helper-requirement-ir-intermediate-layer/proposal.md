## Why

目前 `requirement -> analysis` 直接餵原始 Jira 長文（含雙語與複雜表格），導致 coverage 階段常出現 JSON 修復後語意遺漏，進而讓 pre-testcase 與最終 testcase 品質不穩定。現在需要把需求先轉為 machine-readable 中介資料，確保後續分析與覆蓋可驗證、可補全。

## What Changes

- 新增隱藏中介階段 `requirement_ir`，將 Jira/requirement 轉為結構化 JSON（非人類編輯格式）。
- Analysis 階段改為以 `requirement_ir` 為主要輸入，不再直接依賴原始長文本。
- Coverage 階段新增完整覆蓋規則與伺服器端 gate（缺漏 `analysis.id` 或 section 必須補全後才能進 pre-testcase）。
- 新增表格需求正規化規則（欄位屬性、格式規則、跨頁參數、edited 註記保留）到 IR schema。
- 新增失敗回復策略：coverage parse 失敗時先完整重生，再做 JSON repair；避免只修語法不補內容。

## Capabilities

### New Capabilities
- `jira-requirement-ir-pipeline`: 定義 Jira requirement 到 machine-readable IR 的標準資料契約與流轉行為。

### Modified Capabilities
- `jira-ticket-to-test-case-poc`: 將 analysis/coverage 的輸入與覆蓋驗證改為 IR-first 流程，並調整失敗重試策略。

## Impact

- Affected code:
  - `app/services/jira_testcase_helper_service.py`
  - `app/services/jira_testcase_helper_prompt_service.py`
  - `app/services/jira_testcase_helper_llm_service.py`
  - `app/models/test_case_helper.py`
  - `app/api/test_case_helper.py`
  - `config.yaml` / `config.yaml.example` / `app/config.py`
- Affected data:
  - helper drafts 新增/調整 `requirement_ir` payload 儲存（無破壞性 schema 變更優先）。
- External dependencies:
  - OpenRouter LLM calls（analysis/coverage prompt 調整）
  - Jira ticket content parsing

## Purpose

- 中文：在不改變使用者操作路徑下，建立 IR 中介層以穩定 pre-testcase 品質與 testcase 產出一致性。
- English: Introduce an IR-first pipeline between requirement and analysis to improve determinism and coverage completeness.

## Requirements

- 系統 SHALL 在 helper 流程中產生 machine-readable `requirement_ir`，並以其驅動 analysis。
- 系統 SHALL 對 coverage 結果執行完整覆蓋檢查（analysis item 與 section 不得遺漏）。
- 系統 SHALL 針對表格型需求保留可追蹤欄位語義（sortable/fixed/format/style/edit-note）。
- 系統 SHALL 在 coverage 失敗重試時優先重生完整內容，而非僅修補 JSON 語法。

Scenario (Given-When-Then):
- Given `TCG-93178` 含複雜 Reference 表格
- When helper 執行 requirement -> analysis -> coverage
- Then pre-testcase 應覆蓋全部 analysis 條目，且格式/樣式/互動規則不遺漏

## Non-Functional Requirements

- Reliability: Coverage completeness gate 必須可程式化驗證並可重試補全。
- Performance: 新增 IR 不得顯著增加整體延遲（目標增加 <= 20%）。
- Compatibility: 維持既有 UI/stepper 與 commit model，不引入破壞性 API 變更。
- Observability: 需記錄每階段 item 覆蓋率與補全次數，便於追蹤品質。
