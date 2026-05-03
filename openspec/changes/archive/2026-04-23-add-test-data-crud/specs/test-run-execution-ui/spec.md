# test-run-execution-ui Specification

## Purpose
定義 Ad-hoc Test Run 執行頁在可編輯模式下的表格操作行為，包含批次新增空白列、區段列插入、唯讀保護與對應 i18n 體驗。

## ADDED Requirements

### Requirement: Test Run Item Detail 顯示 Test Data
系統 SHALL 在 Test Run Item Detail 頁面顯示該項目所對應 Test Case 當前的 Test Data，並提供一鍵複製 value 的功能。

#### Scenario: 顯示 Test Data
- **WHEN** 使用者開啟 Test Run Item Detail 頁面
- **THEN** 頁面透過即時關聯顯示該 Test Case 當前所有的 Test Data（name 與 value）

#### Scenario: 複製 Test Data value
- **WHEN** 使用者點擊 Test Data 列的複製按鈕
- **THEN** 該筆 Test Data 的 value 被寫入系統剪貼簿，並顯示複製成功提示

#### Scenario: Test Case 無 Test Data
- **WHEN** 使用者開啟一個對應 Test Case 無 Test Data 的 Test Run Item Detail
- **THEN** 頁面顯示「無 Test Data」提示，不報錯也不顯示空白區塊

#### Scenario: Test Case 被刪除後無法顯示 Test Data
- **WHEN** 使用者開啟一個對應 Test Case 已被刪除的 Test Run Item Detail
- **THEN** Test Data 區塊顯示為空或「無 Test Data」，不報錯
