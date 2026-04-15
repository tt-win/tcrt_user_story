# Capability: Helper Structured Requirement Schema

## Purpose

定義 QA AI Agent 將 Jira ticket 正規化為結構化需求 payload 的契約，供 guided intake、section planning 與 testcase generation 使用。

## Requirements

### Requirement: Structured requirement MUST follow the preclean-compatible schema
系統 SHALL 將 ticket 正規化為與既有 preclean 流程相容的 schema，包含 `ticket_markdown`、`structured_requirement.user_story_narrative`、`criteria`、`technical_specifications` 與 `acceptance_criteria[]`。

#### Scenario: Parser preserves canonical section names
- **WHEN** parser 正規化有效 ticket
- **THEN** 輸出維持 canonical section names，不改寫成 helper-specific aliases

### Requirement: User Story Narrative Field Extraction
系統 SHALL 將 `As a`、`I want`、`So that` 拆成獨立欄位並保留原意。

#### Scenario: Extract As a / I want / So that fields
- **WHEN** narrative 區塊含有對應內容
- **THEN** 系統將其映射到結構化欄位

### Requirement: Acceptance Criteria MUST become ordered scenario objects
系統 SHALL 將 Acceptance Criteria 轉成保序的 scenario objects，包含 `scenario_title`、`given[]`、`when[]`、`then[]` 與必要的 `and[]`。

#### Scenario: Scenario order is preserved
- **WHEN** ticket 含有多個 Acceptance Criteria scenarios
- **THEN** parser 保留原始順序供 section numbering 與畫面顯示使用

### Requirement: Section display metadata MUST be derived from Acceptance Criteria
screen 3 的 section title 與 identifier SHALL 由 Acceptance Criteria 衍生。

#### Scenario: Scenario title becomes the section title
- **WHEN** parser 產出 scenario title
- **THEN** screen 3 使用其作為對應 section 的預設標題

### Requirement: Criteria and Technical Specifications MUST remain readable reference panes
系統 SHALL 保留 `Criteria` 與 `Technical Specifications` 為唯讀參考區，而不是強制轉成可編輯 verification items。

#### Scenario: Supporting sections stay visible during verification editing
- **WHEN** 使用者在 screen 3 編輯 section
- **THEN** 仍可同時查看 criteria 與 technical specs 參考內容

### Requirement: Requirement-rich planning context MUST be attached to each section
每個 section SHALL 帶有 `section_id`、`section_title`、scenario clauses 與對應 requirement references，供後續 planning / generation 使用。

#### Scenario: Section context retains requirement references
- **WHEN** 使用者打開某個 section
- **THEN** UI 可直接顯示 scenario 摘要與 requirement references，不需重新 parse raw ticket
