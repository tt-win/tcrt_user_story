# Capability: Helper Requirement Completeness Warning

## Purpose

定義 QA AI Agent 在 screen 2 對 ticket 結構完整性的檢查規則，並以 blocking gate 取代舊的 override continuation 流程。

## Requirements

### Requirement: Format validation MUST gate transition from screen 2 to screen 3
系統 SHALL 在使用者進入 screen 3 前驗證 ticket 結構，至少要求 `User Story Narrative`、`Criteria` 與 `Acceptance Criteria` 存在且可解析。

#### Scenario: Missing required sections block progression
- **WHEN** 缺少必要 sections
- **THEN** screen 2 顯示缺漏項並阻止進入 screen 3

#### Scenario: Missing user-story narrative fields block progression
- **WHEN** `As a`、`I want`、`So that` 任一欄位為空
- **THEN** 系統回報缺漏並阻止流程前進

#### Scenario: Unnamed acceptance scenario blocks progression
- **WHEN** parser 產出 `Unnamed Scenario`
- **THEN** 系統將其視為錯誤並阻止進入 screen 3

#### Scenario: Incomplete gherkin clauses block progression
- **WHEN** 任一 acceptance scenario 缺少 `Given`、`When` 或 `Then`
- **THEN** 系統回報缺漏 clause 並阻止前進

#### Scenario: Missing technical specifications do not block progression
- **WHEN** `Technical Specifications` 為空
- **THEN** 系統保留空白參考區，但若其他必要項完整仍可前進

#### Scenario: Parser errors are surfaced to the user
- **WHEN** parser 無法正規化必要 sections
- **THEN** 系統將 parser error 與缺漏原因回傳給使用者
