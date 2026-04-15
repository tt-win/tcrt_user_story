## Purpose

將 ad-hoc test run 的 `Add Row` 從「一次新增 1 列」改為可一次輸入並新增多列，降低大量資料建檔時的重複操作成本。  
Improve ad-hoc execution authoring efficiency by allowing users to add multiple rows in one action.

## Why

目前使用者在 ad-hoc 測試情境下需要反覆點擊 `Add Row` 才能建立大量空白測試列，操作成本高且容易中斷編輯節奏。  
This change is needed now because the current single-row flow slows down bulk test case drafting during ad-hoc runs.

## What Changes

- 調整 ad-hoc execution toolbar 的 `Add Row` 互動，先讓使用者輸入要新增的列數。
- 系統依輸入數量一次插入多列空白資料，並維持既有 `handleChange`/autosave 流程。
- 新增輸入驗證與錯誤提示（僅接受正整數，並限制最大可新增數量）。
- 補齊相關 i18n 文案（繁中/英文，必要時含簡中）。

## Requirements

### Requirement: Batch row creation from Add Row action

- **Given** 使用者位於可編輯的 ad-hoc execution 頁面 / user is on editable ad-hoc execution page
- **When** 使用者點擊 `Add Row` 並輸入合法列數（例如 5） / user clicks `Add Row` and submits a valid count (e.g., 5)
- **Then** 系統 SHALL 一次新增對應數量的空白列 / the system SHALL insert the requested number of blank rows in one action

### Requirement: Input validation for row count

- **Given** 使用者輸入非數字、0、負數或超過上限的數值 / user enters non-numeric, zero, negative, or over-limit value
- **When** 系統驗證輸入 / system validates the input
- **Then** 系統 SHALL 顯示可理解的驗證訊息且 SHALL NOT 插入任何新列 / the system SHALL show validation feedback and SHALL NOT insert any rows

### Requirement: Read-only protection remains enforced

- **Given** 該 ad-hoc run 為 archived 或唯讀狀態 / the ad-hoc run is archived or read-only
- **When** 使用者觸發 `Add Row` / user triggers `Add Row`
- **Then** 系統 SHALL 維持既有唯讀阻擋行為且 SHALL NOT 新增資料列 / the system SHALL preserve read-only guard behavior and SHALL NOT add rows

## Non-Functional Requirements

- 可用性 Usability：在不改變主要版面結構下完成批次新增，避免干擾既有編輯流程。
- 效能 Performance：一般使用情境（例如一次新增 50 列）應維持可接受的前端互動回應。
- 相容性 Compatibility：不變更後端 API 契約與資料表 schema。

## Capabilities

### New Capabilities

- `adhoc-test-run-execution-ui`: 定義 ad-hoc execution 頁面的批次新增列互動、驗證與唯讀保護行為。

### Modified Capabilities

- (none)

## Impact

- 主要影響：`app/static/js/adhoc_test_run.js`、`app/templates/adhoc_test_run_execution.html`。
- 可能影響：`app/static/locales/zh-TW.json`、`app/static/locales/en-US.json`、`app/static/locales/zh-CN.json`。
- 測試影響：需補充批次新增列的前端互動驗證（含唯讀與錯誤輸入情境）。
