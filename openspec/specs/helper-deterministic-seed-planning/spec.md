# helper-deterministic-seed-planning Specification

## Purpose
定義 QA AI Agent 在 screen 3 的 deterministic requirement planning 與 verification item 結構。

## Requirements
### Requirement: Section planning MUST run locally without LLM dependency
系統 SHALL 在 screen 3 以本地邏輯建立 section / requirement plan，不依賴 LLM。

#### Scenario: Local planning payload is produced from parser output
- **WHEN** ticket 結構化完成
- **THEN** 系統可直接產出 section planning payload

### Requirement: Acceptance Criteria MUST drive section allocation
section 配置 SHALL 由 Acceptance Criteria 驅動，並支援使用者調整起始 section number。

#### Scenario: User edits the starting section number
- **WHEN** 使用者修改起始 section number
- **THEN** 後續 section 編號依規則重新配置

### Requirement: Verification items MUST use one of four categories
每個 verification item SHALL 使用既定類別之一，例如 API / UI / Functional / Other。

#### Scenario: API verification item stores endpoint detail
- **WHEN** verification item 類型為 API
- **THEN** 系統保留 endpoint 等細節

### Requirement: Each verification item MUST contain one or more check conditions
verification item SHALL 至少包含一個可驗證的 check condition。

#### Scenario: Check condition cannot be saved without coverage
- **WHEN** verification item 沒有有效 check condition
- **THEN** 系統不允許存檔或鎖定

### Requirement: Requirement-plan editing MUST autosave every five seconds
screen 3 編輯中的 requirement plan SHALL 週期性自動儲存。

#### Scenario: Autosave persists current section edits
- **WHEN** 使用者在 screen 3 編輯內容
- **THEN** 系統約每五秒自動保存目前變更

### Requirement: Requirement plan MUST support explicit lock and unlock
系統 SHALL 提供明確 lock / unlock 機制控制後續 seed generation。

#### Scenario: Locked requirement plan enables seed generation
- **WHEN** requirement plan 被鎖定
- **THEN** 使用者可進入 seed generation

#### Scenario: Unlock disables seed generation
- **WHEN** 使用者解鎖 plan
- **THEN** 需重新確認後才能進入下一階段
