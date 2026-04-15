## Why

目前 QA AI Agent - Test Case Helper 對 requirement 缺少固定輸入契約，導致需求抽取依賴自由文字與模型推論，拆解精度與一致性不穩定。  
Current helper decomposition is driven by loosely structured text, which causes unstable requirement parsing and downstream testcase quality.

## What Changes

- 新增「格式化 requirement schema」：以 `Menu / User Story Narrative / Criteria / Technical Specifications / Acceptance Criteria / API路徑` 為標準段落，支援 Jira wiki 樣式（`h1/h2/h3`、`As a/I want/So that`、`Given/When/Then`）。
- 新增 requirement parser + validator：先做 deterministic 結構化解析，再交由 IR/analysis 使用。
- 新增前進警告機制：當 requirement 格式不完整時，使用者點下一步必須先看到警告與缺漏段落清單；使用者可選擇返回修正或仍要繼續。
- 更新 analysis/coverage 輸入契約：優先使用格式化 requirement 結果，降低 fallback 對自由文字的依賴。
- 調整分析流程為「單次 LLM 呼叫合併輸出 analysis + coverage」；移除獨立 coverage 初次生成呼叫。
- 合併輸出若缺少 coverage 或 coverage 不完整，直接視為 analysis 失敗並報錯；僅保留 LLM 呼叫層補救（重試/JSON repair）。
- 更正 analysis 階段 pre-testcase 呈現：每條目需直接顯示對應 requirement 內容與規格驗證要求，不再以 analysis/coverage 參考條目代號作為主要資訊。
- 強化 testcase 產生契約：嚴格要求 preconditions/steps/expected result 完整且可觀測，並禁止 pre/s/exp 出現占位詞（REF/同上/略/TBD/N/A）。
- 調整 generate 容錯：當 testcase 校驗失敗（如占位詞命中）時，系統改採 deterministic 修補與降級校驗，避免流程中斷。
- 最大程度保留既有 Test Case Helper UI 建設成果（既有三步驟 modal、互動流程、元件），僅在新流程需要時做必要最小修改。
- 建立 requirement traceability 契約：以穩定 requirement key 連結 requirement -> pre-testcase -> testcase，避免後續開發階段失去需求依據。
- 簡化架構邊界：統一 prompt 設定來源與 pretestcase payload envelope，降低多處規則分岔。
- 補齊範例驅動測試：以真實需求範例驗證 section 抽取、Gherkin 場景拆解、平台分支與 warning 行為。

## Capabilities

### New Capabilities
- `helper-structured-requirement-schema`: 定義並驗證 Test Case Helper 的標準 requirement 格式與欄位契約。
- `helper-requirement-completeness-warning`: 在格式不符時提供「前進警告 + 缺漏提示 + 使用者確認」流程。

### Modified Capabilities
- `jira-ticket-to-test-case-poc`: 將需求拆解輸入由自由描述調整為「格式化 requirement 優先」策略，提升可追蹤性與穩定度。

## Impact

- Affected code: `app/services/jira_testcase_helper_service.py`, `app/static/js/test-case-management/ai-helper.js`, `app/models/test_case_helper.py`, `app/api/test_case_helper.py`, `app/testsuite/test_jira_testcase_helper_service.py`, `app/testsuite/test_jira_testcase_helper_frontend.py`.
- API/UI behavior: analyze 前增加 requirement completeness 檢查與 warning 互動。
- Data compatibility: 不做破壞性 DB schema 變更；以既有 draft payload 擴充為主。

## Purpose

- 中文：建立可機器驗證的 requirement 格式，讓 helper 的需求拆解精準、可追蹤且可預期。
- English: Establish a machine-valid requirement contract to improve decomposition accuracy, traceability, and consistency.

## Requirements

### Requirement: Structured Requirement Contract
The system SHALL parse and validate requirement documents against the standardized section schema before decomposition.

#### Scenario: Parse standardized Jira wiki requirement
- **GIVEN** 一份包含 `Menu / User Story Narrative / Criteria / Technical Specifications / Acceptance Criteria` 的需求文件
- **WHEN** 使用者啟動 helper analysis
- **THEN** 系統將內容解析為結構化欄位（含 `As a/I want/So that` 與 `Given/When/Then`）
- **AND** analysis/coverage 必須使用該結構化結果作為主要輸入

### Requirement: Incomplete Format Warning on Next Step
The system SHALL warn users when requirement format is incomplete before moving to the next step.

#### Scenario: User chooses to proceed with incomplete requirement
- **GIVEN** requirement 缺少必要段落或 Gherkin 結構不完整
- **WHEN** 使用者點擊下一步
- **THEN** 系統顯示「requirement 不完整」警告與缺漏項目清單
- **AND** 使用者可選擇「返回修正」或「仍要繼續」
- **AND** 若使用者選擇繼續，流程可前進且保留警告紀錄

### Requirement: Requirement-Rich Pre-Testcase Presentation
The system SHALL present requirement content and specification verification points directly in pre-testcase entries during analysis stage.

#### Scenario: Pre-testcase keeps requirement and verification context for testcase authoring
- **GIVEN** analysis/coverage 已完成且存在可用 pre-testcase 條目
- **WHEN** 使用者在 analysis 階段檢視 pre-testcase
- **THEN** 每個條目需直接呈現該需求的規格內容與驗證要求（包含檢核項與預期）
- **AND** 介面不應以 analysis/coverage 參考代號列表作為主要呈現內容
- **AND** 後續 testcase 產生與人工編修可直接使用這些需求與驗證資訊

### Requirement: Single-Prompt Analysis/Coverage Generation
The system SHALL generate analysis and coverage in one prompt call during analyze stage.

#### Scenario: Analyze stage emits merged payload and avoids separate coverage generation
- **GIVEN** requirement IR 已建立完成
- **WHEN** 使用者觸發 analyze
- **THEN** 系統以單一次 LLM prompt 回傳 `analysis` 與 `coverage`
- **AND** 不執行獨立 coverage 初次生成呼叫
- **AND** 若 coverage 缺漏或不完整，系統直接回報錯誤（不走額外 coverage 補全流程）

### Requirement: Stable Requirement Traceability
The system SHALL keep stable requirement identifiers and carry them through downstream artifacts.

#### Scenario: Requirement context remains available in testcase authoring
- **GIVEN** 一條需求已被解析並進入 pre-testcase
- **WHEN** 使用者進入 testcase 生成與人工編修
- **THEN** 系統仍可追溯到原始 requirement key、規格條件與驗證要求
- **AND** 不因 analysis/coverage 重新排序而失去需求對應

## Non-Functional Requirements

- Reliability: 格式檢查結果必須可重現，對同一輸入得到一致缺漏判定。
- Usability: 警告文案需清楚指出缺漏段落，且不破壞既有三步驟操作體驗。
- Compatibility: 保持現有 helper API 與 draft 流程相容，採漸進式導入。
- Observability: 記錄 warning 觸發次數、缺漏類型與使用者是否選擇繼續。
- Maintainability: 降低 prompt 與 payload 規格分散，避免跨模組規則漂移。
- UI Continuity: 優先重用既有 Helper UI 元件與交互；若需修改，必須遵循 TCRT UI 風格與設計系統。
