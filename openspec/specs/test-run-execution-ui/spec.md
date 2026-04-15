# test-run-execution-ui Specification

## Purpose
Refactor Test Run Execution page to use external static assets while preserving all existing functionality including filter panel, multi-set section hydration, and execution filtering.

## Requirements
### Requirement: Execution Filter Panel Toggle
系統 SHALL 在使用者啟用 executionFilterToggle 時顯示 Test Run Execution 的 filter panel，並提供狀態、案例編號、標題、優先級與執行者的篩選輸入。

#### Scenario: Toggle filter panel via click or keyboard
- **WHEN** 使用者點擊 executionFilterToggle 或按下 Enter/Space
- **THEN** filter panel 會顯示並可被操作

#### Scenario: Close filter panel
- **WHEN** 使用者點擊關閉按鈕、按下 Escape，或點擊 panel 外部
- **THEN** filter panel 會關閉且 toggle 狀態回到收合

### Requirement: Multi-set section hydration for execution page
The system SHALL load section trees from all Test Case Sets configured on a Test Run and merge them for execution filtering/grouping.

#### Scenario: Execution page loads sections from multiple sets
- **WHEN** a Test Run configuration contains multiple Test Case Set IDs
- **THEN** the execution page fetches sections for each configured set
- **AND** merged section filters are available before item rendering completes

### Requirement: Execution filtering remains stable with multi-set items
The system SHALL preserve existing execution filter behaviors when Test Run items span multiple Test Case Sets.

#### Scenario: Filter and group multi-set execution items
- **WHEN** execution items belong to different Test Case Sets
- **THEN** section grouping, section checkbox filters, and existing non-section filters continue to work without runtime errors

#### Scenario: Reflect backend cleanup results
- **WHEN** backend cleanup removes out-of-scope Test Run items
- **THEN** execution page reload shows the updated item list without deleted items
- **AND** section/filter rendering remains consistent
