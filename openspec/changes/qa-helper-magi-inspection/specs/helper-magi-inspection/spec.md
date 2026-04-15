## ADDED Requirements

### Requirement: Inspection flow MUST execute in two sequential phases
MAGI inspection 流程 SHALL 分為 Phase 1（multi-model extraction）與 Phase 2（consolidation）兩個循序階段。Phase 1 完成後方可進入 Phase 2。

#### Scenario: Phase 1 completes before Phase 2 begins
- **WHEN** 系統啟動 MAGI inspection 流程
- **THEN** 所有 Phase 1 extraction 呼叫完成後，系統才啟動 Phase 2 consolidation

#### Scenario: Phase 1 partial failure does not block Phase 2
- **WHEN** Phase 1 中部分模型呼叫失敗但至少一個模型成功
- **THEN** Phase 2 仍以可用的 extraction 結果進行統合，並在統合結果中標註缺少的角色面向

### Requirement: Phase 1 MUST invoke one extraction call per AC Scenario per role model
Phase 1 SHALL 為每個 Acceptance Criteria Scenario 與每個角色模型建立獨立呼叫（3 models x N scenarios = 3N 呼叫），所有呼叫 SHALL 並行執行。

#### Scenario: Two AC Scenarios produce six parallel extraction calls
- **WHEN** ticket 包含 2 個 AC Scenarios
- **THEN** 系統發出 6 個並行 extraction 呼叫（2 scenarios x 3 models）

#### Scenario: Each extraction call receives only its assigned Scenario
- **WHEN** 系統建構 extraction prompt
- **THEN** prompt 僅包含該呼叫對應的單一 AC Scenario，不混入其他 Scenario

### Requirement: Three extraction role models MUST have distinct focus areas
三個低階角色模型 SHALL 各有專屬且互補的角色焦點，覆蓋六大面向。

#### Scenario: Role A focuses on Happy Path and basic Permission
- **WHEN** 系統建構 Role A 的 extraction prompt
- **THEN** role_focus 注入 Happy Path 與基本 Permission 的角色描述

#### Scenario: Role B focuses on Edge Cases and Performance
- **WHEN** 系統建構 Role B 的 extraction prompt
- **THEN** role_focus 注入 Edge Cases 與 Performance 的角色描述

#### Scenario: Role C focuses on Error Handling, advanced Permission, and Abuse
- **WHEN** 系統建構 Role C 的 extraction prompt
- **THEN** role_focus 注入 Error Handling、進階 Permission 與 Abuse 的角色描述

### Requirement: Phase 2 consolidation model MUST produce structured output
Phase 2 高階模型 SHALL 統合所有 Phase 1 extraction 結果，產出可直接 parse 為 PlanSection / VerificationItem / CheckCondition 的結構化格式（JSON object），不得使用 markdown 或自由文字格式。

#### Scenario: Consolidation output is valid JSON matching expected schema
- **WHEN** Phase 2 完成統合
- **THEN** 輸出為合法 JSON，每個 PlanSection 對應一個 AC Scenario，每個 VerificationItem 含 category、summary、detail，每個 CheckCondition 含 condition_text 與 coverage_tag

#### Scenario: Coverage tags are limited to defined values
- **WHEN** consolidation 產出 CheckCondition
- **THEN** coverage_tag 僅限 Happy Path / Error Handling / Edge Test Case / Permission 四種值

#### Scenario: Verification categories are limited to defined values
- **WHEN** consolidation 產出 VerificationItem
- **THEN** category 僅限 API / UI / 功能驗證 / 其他 四種值

### Requirement: Consolidation result MUST auto-populate VERIFICATION_PLANNING data structure
統合結果 SHALL 自動填充進 VERIFICATION_PLANNING 畫面的 PlanSection / VerificationItem / CheckCondition 資料結構。使用者保留完整的增刪修改能力。

#### Scenario: AI-generated sections appear in VERIFICATION_PLANNING screen
- **WHEN** inspection 流程成功完成
- **THEN** VERIFICATION_PLANNING 畫面自動載入 AI 產生的 sections、items 與 conditions

#### Scenario: User can modify AI-populated verification items
- **WHEN** AI 填充完成後
- **THEN** 使用者可自由新增、刪除或修改任何 verification item 與 check condition

### Requirement: Extraction intermediate data MUST use compressed format
Phase 1 extraction 輸出 SHALL 使用壓縮格式（pipe-delimited `title|coverage|condition`），不做易讀排版，以降低 Phase 2 統合輸入的 token 消耗。

#### Scenario: Extraction output uses pipe-delimited format
- **WHEN** 低階模型完成 extraction
- **THEN** 輸出格式為 pipe-delimited 壓縮格式，非 markdown 或 JSON

### Requirement: All inspection model IDs MUST be configurable
三個低階模型 ID 與高階統合模型 ID SHALL 可透過 `config.yaml` 設定，並支援環境變數覆蓋。

#### Scenario: Config defines four inspection model slots
- **WHEN** 系統載入 inspection 模型設定
- **THEN** 從 `config.yaml` 讀取 `inspection_extraction_a`、`inspection_extraction_b`、`inspection_extraction_c` 與 `inspection_consolidation` 四個模型設定

#### Scenario: Environment variable overrides config model ID
- **WHEN** 環境變數指定某 inspection model ID
- **THEN** 該環境變數值取代 `config.yaml` 中的預設值

#### Scenario: Missing model config falls back to sensible defaults
- **WHEN** 某 inspection model slot 未設定
- **THEN** 系統使用預設模型 ID（extraction 預設為各自的低階模型，consolidation 預設為高階模型）

### Requirement: Inspection prompt templates MUST reside in prompt directory
Inspection 的 extraction 與 consolidation prompt 模板 SHALL 放置於 `prompts/jira_testcase_helper/` 目錄，使用 `.md` 格式與 `{placeholder}` 字串替換。

#### Scenario: Extraction prompt template is loaded from file
- **WHEN** 系統準備 extraction prompt
- **THEN** 從 `prompts/jira_testcase_helper/inspection_extraction.md` 載入模板

#### Scenario: Consolidation prompt template is loaded from file
- **WHEN** 系統準備 consolidation prompt
- **THEN** 從 `prompts/jira_testcase_helper/inspection_consolidation.md` 載入模板

### Requirement: Inspection failure MUST allow manual fallback
當 inspection 流程完全失敗（Phase 1 所有模型皆失敗或 Phase 2 失敗）時，系統 SHALL 允許使用者 fallback 到手動填寫 VERIFICATION_PLANNING，並顯示適當錯誤訊息。

#### Scenario: All extraction models fail
- **WHEN** Phase 1 所有三個模型呼叫皆失敗
- **THEN** 系統顯示錯誤訊息並導引使用者手動填寫 verification items

#### Scenario: Consolidation fails after successful extraction
- **WHEN** Phase 1 成功但 Phase 2 consolidation 失敗
- **THEN** 系統顯示錯誤訊息並導引使用者手動填寫 verification items
