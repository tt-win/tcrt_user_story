## Purpose

在 Ad-hoc Test Run 執行畫面的右鍵選單新增 Section 插入能力，讓使用者可直接在任一列上方或下方插入 section row，減少手動調整列位置的操作成本。  
Add section insertion actions to the Ad-hoc execution context menu so users can insert a section row above or below the selected row directly.

## Why

目前僅有工具列 `Add Section`，會固定插入在尾端，使用者若要在中間插入 section，需先新增後再搬移資料，流程不直覺且效率低。  
This improvement is needed to support faster in-place structuring during exploratory/ad-hoc execution editing.

## What Changes

- 在 Ad-hoc grid 右鍵選單新增兩個操作：`Insert section above`、`Insert section below`。
- 兩個操作分別在目前選取列上方/下方插入 section row。
- 新增的 section row 結構與既有工具列 `Add Section` 完全一致（`test_case_number=SECTION` 與預設欄位內容）。
- 在 read-only 狀態下不提供或不允許上述操作。
- 補齊 zh-TW/en-US/zh-CN 多語系文案。

## Requirements

### Requirement: Context menu section insertion actions

- **Given** 使用者在可編輯的 Ad-hoc execution grid 選取一列 / user selects a row in editable Ad-hoc grid
- **When** 使用者從右鍵選單點擊 `Insert section above` 或 `Insert section below` / user clicks `Insert section above` or `Insert section below` in context menu
- **Then** 系統 SHALL 在對應位置插入 section row / the system SHALL insert a section row at the requested relative position

### Requirement: Inserted section row format parity

- **Given** 使用者透過右鍵選單插入 section / user inserts section from context menu
- **When** 新列建立完成 / new row is created
- **Then** 系統 SHALL 使用與 `Add Section` 相同的 section 欄位預設值 / the system SHALL use the same section default payload as toolbar `Add Section`

### Requirement: Read-only protection for context menu insertion

- **Given** run 為 archived/completed 等唯讀狀態 / run is read-only (archived/completed)
- **When** 使用者開啟右鍵選單 / user opens context menu
- **Then** 系統 SHALL NOT 允許 section insertion actions / the system SHALL NOT allow section insertion actions

## Non-Functional Requirements

- 一致性 Consistency：右鍵插入後需維持既有 section 合併/渲染規則。
- 可用性 Usability：操作名稱需清楚區分上方/下方插入。
- 相容性 Compatibility：不變更後端 API 與 DB schema。

## Capabilities

### New Capabilities

- (none)

### Modified Capabilities

- `adhoc-test-run-execution-ui`: 擴充右鍵選單 section 插入行為與唯讀限制。

## Impact

- 主要影響：`app/static/js/adhoc_test_run.js`。
- 可能影響：`app/static/locales/zh-TW.json`、`app/static/locales/en-US.json`、`app/static/locales/zh-CN.json`。
- 測試影響：需覆蓋右鍵選單上/下插入與唯讀情境。
