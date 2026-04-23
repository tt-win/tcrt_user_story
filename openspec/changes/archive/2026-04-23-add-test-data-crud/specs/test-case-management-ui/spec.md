# test-case-management-ui Specification

## Purpose
定義 Test Case Management UI 的主要行為，包括資產分離、預設 Set 顯示與切換、共享過濾連結、impact warning 與 section navigation 穩定性。

## ADDED Requirements

### Requirement: Test Case Detail 提供 Test Data 編輯區塊
系統 SHALL 在 Test Case Detail 頁面新增 Test Data 管理區塊，允許使用者檢視、新增、修改與刪除該 Test Case 的 Test Data。Test Data 的變更隨同 Test Case 一併儲存。

#### Scenario: 顯示 Test Data 列表
- **WHEN** 使用者開啟 Test Case Detail 頁面
- **THEN** 頁面顯示該 Test Case 的所有 Test Data，每筆包含 name 與 value

#### Scenario: 新增 Test Data
- **WHEN** 使用者在 Test Data 區塊點擊新增按鈕
- **THEN** 出現可編輯的空白列，輸入 name 與 value

#### Scenario: 修改 Test Data
- **WHEN** 使用者編輯既有 Test Data 的 name 或 value
- **THEN** 變更在儲存 Test Case 後反映於頁面與資料庫

#### Scenario: 刪除 Test Data
- **WHEN** 使用者點擊 Test Data 列的刪除按鈕
- **THEN** 該筆 Test Data 從前端列表移除，並在儲存 Test Case 時同步至資料庫

#### Scenario: 儲存 Test Case 連帶儲存 Test Data
- **WHEN** 使用者儲存 Test Case
- **THEN** Test Data 的增刪改隨同 Test Case 一併整批寫入 `test_data_json`

#### Scenario: 無權限使用者無法編輯 Test Data
- **WHEN** 無編輯權限的使用者查看 Test Case Detail
- **THEN** Test Data 區塊以唯讀模式呈現，不顯示新增/修改/刪除控制項
