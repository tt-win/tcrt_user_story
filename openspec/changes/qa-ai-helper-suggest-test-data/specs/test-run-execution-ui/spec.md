# test-run-execution-ui Specification

## Purpose
定義 Test Run 執行頁面的顯示與互動契約。

## ADDED Requirements

### Requirement: Test Run item detail MUST warn on empty test_data value
Test Run item detail 顯示 test_data 時，若某筆 value 為空字串，SHALL 顯示 warning icon 提示使用者於執行前補齊。該提示 SHALL NOT 阻擋 run item 狀態變更或 step 勾選。

#### Scenario: Empty value shows warning icon
- **WHEN** Test Run item 所引用的 test case 其 test_data 某筆 value 為空字串
- **THEN** 該列在 test_data 區塊顯示警示 icon 與提示文字（i18n key：`testRun.testDataValueMissing`）

#### Scenario: Warning does not block execution
- **WHEN** 存在 warning 的 test_data 時使用者操作 run item
- **THEN** 使用者仍可勾選 steps、修改結果、提交狀態
