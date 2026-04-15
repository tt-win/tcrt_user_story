## Why

目前團隊已經有 JIRA 轉 Test Case 的 PoC，但尚未整合到正式的 Test Case Set 管理流程，導致使用者仍需在多工具間切換並手動整理內容。現在需要把流程產品化，提供可編輯、可多輪確認、可直接入庫的 end-to-end 體驗，降低遺漏風險並提升產出一致性。

## What Changes

- 新增 Test Case Set 管理頁面的「AI Agent - Test Case Helper」入口，導入精靈式流程（wizard flow）。
- 新增從 JIRA TCG Ticket 載入需求、以 `gemini-3-flash-preview` 進行內容辨識統整與格式化，並以使用者 UI 語言呈現。
- 明確區分語言規則：需求整理階段以 UI 語言呈現供人工確認；Test Case 產出階段以使用者選定輸出語言（繁中/簡中/英文）生成。
- 新增需求編輯、分析/涵蓋率（Analysis/Coverage）確認、預產出 Test Case 確認、最終 Test Case 編輯與入庫流程。
- 新增語系輸出選擇（簡中、繁中、英文）並要求產出內容符合既有 Test Case model 與 section 建立規則。
- 新增分階段 LLM 模型策略與可設定機制：Analysis/Test Case/Audit 預設使用 Gemini 3 Flash Preview，Coverage 預設使用 GPT-5.2，且需可由 `config.yaml` 覆寫。
- 新增分階段 prompt 模板策略：Analysis/Coverage/Test Case/Audit 四階段 prompt 內建預設值（參考 PoC）且可由 `config.yaml` 覆寫。
- 新增 Test Case ID 規則：中間號與尾號皆採 10 號遞增（010, 020, 030...），並支援起始號設定。
- 明確規範本功能只使用主設定檔 `config.yaml`，不使用獨立 LLM 設定檔（如 `ai/llm_config.yaml`）作為來源。
- 明確規範模型呼叫統一走 OpenRouter 路徑，由 `config.yaml` 提供各階段 model id。
- 新增獨立 `Qdrant` async client（比照 jira/lark client 分層），集中管理連線池、重試、逾時與生命週期，並由 `config.yaml` 提供設定。
- 新增送出後自動導回目標 Test Case Set 並顯示新建 Test Case 的完成態行為。

## Capabilities

### New Capabilities
- `jira-ticket-to-test-case-helper`: 在 Web UI 內提供 JIRA Ticket 到 Test Case 的多階段 AI 協作流程（含需求整理、Analysis/Coverage、產生與入庫）。

### Modified Capabilities
- None（本次以新增 capability 為主，既有 capability 不直接改寫）。

## Impact

- Affected modules: `app/templates/`, `app/static/js/test-case-management/`, `app/api/`, `app/services/`（含 `qdrant_client.py`）, `app/models/`, `app/main.py`.
- Affected configuration: `config.yaml` / `config.yaml.example` / `app/config.py`（新增 helper 階段模型與 qdrant 連線設定鍵）。
- External dependencies: JIRA API、OpenRouter（Gemini 3 Flash Preview + GPT-5.2）、既有 AI/Agent 流程（參考 `/Users/hideman/code/test_case_agent_poc`）。
- Data impact: 需確保 Test Case/Section 建立符合現有 schema；無破壞性 migration 規劃。

## Purpose

- 中文：將「JIRA 需求 Ticket → 可落庫 Test Case」流程整合進既有管理介面，提供可審核、可編輯、可追蹤的協作體驗。
- English: Productize Jira-to-TestCase flow in existing Test Case Set UI with human-in-the-loop checkpoints.

## Requirements

### Requirement: Guided conversion workflow in Test Case Set UI
The system SHALL provide a guided workflow from ticket input to final test case persistence inside Test Case Set management.

#### Scenario: User completes full assisted flow
- **GIVEN** the user is on Test Case Set management page
- **WHEN** the user clicks AI helper, reviews/edits requirement, confirms analysis and generated test cases, then submits
- **THEN** the system stores test cases into the selected set and redirects to that set with created items visible

### Requirement: Locale-aware requirement normalization and test case output
The system SHALL support output language selection (`zh-CN`, `zh-TW`, `en`) and SHALL normalize multilingual ticket content before user editing.

#### Scenario: Mixed-language ticket with split review/output locale
- **GIVEN** a JIRA ticket contains mixed Chinese/English requirement text
- **WHEN** the UI locale is `zh-TW` and the user selects English output
- **THEN** normalized requirement content is shown in Traditional Chinese for review
- **AND** downstream generated test cases are shown in English

### Requirement: Separated language policy per stage
The system SHALL present normalized requirement content using current UI locale for human review, and SHALL generate final test cases using the user-selected output locale.

#### Scenario: Different UI locale and output locale
- **GIVEN** UI locale is `zh-TW` and output locale is set to `en`
- **WHEN** user runs helper flow
- **THEN** requirement review content is shown in Traditional Chinese and final generated test cases are in English

### Requirement: Test Case ID increment rule
The system SHALL generate IDs following `[TCG].[middle].[tail]` with 10-step increments (`010`,`020`,`030`...) for middle and tail numbers.

#### Scenario: Sequential numbering with initial middle number
- **GIVEN** initial middle number is `010`
- **WHEN** the system generates multiple criteria and cases
- **THEN** middle numbers and tail numbers increment by 10 for each next item

### Requirement: Config-driven stage model mapping in config.yaml
The system SHALL support per-stage model configuration in `config.yaml` and SHALL default to `gemini-3-flash-preview` for analysis/testcase/audit and `gpt-5.2` for coverage.

#### Scenario: Use default stage models from config
- **GIVEN** no custom override is provided for helper stage models
- **WHEN** the user runs the helper flow
- **THEN** analysis/testcase/audit use Gemini 3 Flash Preview and coverage uses GPT-5.2

## Non-Functional Requirements

- Security: API keys and credentials MUST remain server-side and MUST NOT be exposed to browser clients.
- Reliability: Each phase SHOULD support explicit error state and re-try without losing user-edited content.
- Usability: UI interactions MUST align with existing design system and provide markdown editing for requirement and test case review stages.
- Configuration Governance: The helper workflow MUST read model settings from `config.yaml` and MUST NOT depend on standalone LLM config files.
- Transactional Integrity: Commit to Test Case/Section data MUST be all-or-nothing with rollback on any persistence error.
- Performance Isolation: Long-running LLM calls SHOULD stay outside DB write transactions, and DB write transaction time SHOULD be minimized to reduce impact on concurrent users.
