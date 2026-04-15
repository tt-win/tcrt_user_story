## ADDED Requirements

### Requirement: Context menu SHALL provide section insertion above and below selected row

The system SHALL provide two context menu actions in Ad-hoc execution grid: `Insert section above` and `Insert section below`.

#### Scenario: Insert section above selected row
- **WHEN** 使用者在可編輯 Ad-hoc grid 選取一列並執行 `Insert section above` / user selects a row and runs `Insert section above` in editable Ad-hoc grid
- **THEN** 系統 SHALL 在該列上方插入一列 section row / the system SHALL insert one section row above the selected row

#### Scenario: Insert section below selected row
- **WHEN** 使用者在可編輯 Ad-hoc grid 選取一列並執行 `Insert section below` / user selects a row and runs `Insert section below` in editable Ad-hoc grid
- **THEN** 系統 SHALL 在該列下方插入一列 section row / the system SHALL insert one section row below the selected row

### Requirement: Context menu inserted section SHALL match toolbar Add Section payload

The system SHALL use the same section default payload for context-menu insertion and toolbar `Add Section`.

#### Scenario: Section row fields are consistent across entry points
- **WHEN** 使用者透過右鍵選單插入 section / user inserts a section from context menu
- **THEN** 新增列的 `test_case_number` SHALL 為 `SECTION` / inserted row `test_case_number` SHALL be `SECTION`
- **AND** 其他預設欄位值 SHALL 與工具列 `Add Section` 一致 / remaining default field values SHALL match toolbar `Add Section`

### Requirement: Read-only mode SHALL block context-menu section insertion actions

The system SHALL NOT allow section insertion actions from context menu when Ad-hoc run is read-only.

#### Scenario: Read-only context menu excludes insertion actions
- **WHEN** run 狀態為 archived/completed 等唯讀情境且使用者開啟右鍵選單 / run is read-only (archived/completed) and user opens context menu
- **THEN** 右鍵選單 SHALL NOT 顯示或可執行 section insertion actions / context menu SHALL NOT expose executable section insertion actions

### Requirement: Section insertion action labels SHALL be localized

The system SHALL provide i18n labels for `Insert section above` and `Insert section below` in supported locales.

#### Scenario: Context menu labels follow active locale
- **WHEN** 使用者切換語系後開啟右鍵選單 / user opens context menu after changing locale
- **THEN** section insertion actions 顯示對應語系文案 / section insertion actions display locale-specific labels
