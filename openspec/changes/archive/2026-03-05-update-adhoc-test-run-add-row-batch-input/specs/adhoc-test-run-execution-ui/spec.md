# adhoc-test-run-execution-ui Specification

## Purpose

定義 Ad-hoc Test Run Execution 頁面中 `Add Row` 的批次新增行為、輸入驗證與唯讀保護。  
Define batch row insertion behavior, input validation, and read-only guard for `Add Row` in Ad-hoc Test Run Execution UI.

## ADDED Requirements

### Requirement: Add Row SHALL support user-defined batch count

The system SHALL allow users to input a row count when triggering `Add Row`, and SHALL insert that number of blank rows in one action.

#### Scenario: Insert multiple rows with one confirmation
- **WHEN** 使用者在可編輯頁面點擊 `Add Row` 並提交合法數值 `N` / user clicks `Add Row` on editable page and submits valid count `N`
- **THEN** 系統一次新增 `N` 列空白資料 / the system inserts `N` blank rows in a single operation
- **AND** 系統維持既有資料欄位預設值映射 / the system keeps existing default row field mapping

#### Scenario: Cancel batch insert
- **WHEN** 使用者開啟列數輸入後取消操作 / user opens row-count input then cancels
- **THEN** 系統 SHALL NOT 新增任何資料列 / the system SHALL NOT insert any rows

### Requirement: Row count input SHALL be validated before insertion

The system SHALL validate row count as a bounded positive integer before mutating table data.

#### Scenario: Reject invalid row count
- **WHEN** 使用者輸入非數字、0、負數或超過上限 / user enters non-number, zero, negative, or over-limit value
- **THEN** 系統顯示驗證訊息並 SHALL NOT 修改表格資料 / the system shows validation feedback and SHALL NOT mutate table rows

#### Scenario: Accept boundary values
- **WHEN** 使用者輸入邊界合法值（`1` 或最大上限） / user enters boundary valid value (`1` or configured max)
- **THEN** 系統依輸入值新增對應列數 / the system inserts rows exactly by the provided count

### Requirement: Read-only mode SHALL block batch row insertion

The system SHALL preserve current read-only protection for archived or locked ad-hoc runs.

#### Scenario: Archived run blocks Add Row batch flow
- **WHEN** archived/read-only run 的使用者觸發 `Add Row` / user triggers `Add Row` in archived/read-only run
- **THEN** 系統顯示唯讀提示且 SHALL NOT 開始批次新增 / the system shows read-only notice and SHALL NOT start batch insertion

### Requirement: Batch Add Row UI text SHALL be localized

The system SHALL provide i18n-backed labels/messages for row-count prompt, validation feedback, confirm, and cancel actions.

#### Scenario: Localized prompt and validation shown in selected locale
- **WHEN** 使用者以繁中或英文語系使用 `Add Row` 批次功能 / user uses batch `Add Row` under zh-TW or en-US locale
- **THEN** 輸入提示與錯誤訊息使用對應語系文案 / prompt and validation messages are shown in the active locale
