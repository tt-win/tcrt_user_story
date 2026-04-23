# test-data-management Specification

## Purpose
定義 Test Data 的生命週期管理，包含其依附於 Test Case 的儲存方式、整批 CRUD 行為，以及在 Test Run Item 中的即時讀取機制。

## Requirements

### Requirement: Test Data 以 JSON 陣列儲存於 Test Case
系統 SHALL 將 Test Data 以 JSON 字串形式儲存於 `test_case_local.test_data_json` 欄位。每筆 Test Data 為 `{id, name, value}` 物件。當 Test Case 被刪除時，其 Test Data 隨同移除。

#### Scenario: Test Case 刪除時連帶移除 Test Data
- **WHEN** 使用者刪除一個含有 Test Data 的 Test Case
- **THEN** 該 Test Case 的 Test Data 隨同從資料庫移除

### Requirement: Test Data 支援整批 CRUD
系統 SHALL 允許具備權限的使用者透過 Test Case 的更新 API 對 Test Data 執行整批建立、讀取、更新、刪除。每一筆 Test Data SHALL 包含顯示名稱（name）與內容值（value），且同一 Test Case 可擁有多筆 Test Data。

#### Scenario: 建立 Test Data
- **WHEN** 使用者為特定 Test Case 新增一筆 Test Data（name = "valid_email", value = "qa@example.com"）並儲存 Test Case
- **THEN** 系統將包含該筆資料的 JSON 陣列儲存至 `test_data_json`

#### Scenario: 讀取 Test Data 列表
- **WHEN** 使用者開啟 Test Case Detail 頁面
- **THEN** 系統回傳該 Test Case 的 Test Data 陣列，按陣列索引順序呈現

#### Scenario: 更新 Test Data
- **WHEN** 使用者修改既有 Test Data 的 name 或 value 並儲存 Test Case
- **THEN** 系統將更新後的 JSON 陣列寫入 `test_data_json`

#### Scenario: 刪除 Test Data
- **WHEN** 使用者刪除一筆 Test Data 並儲存 Test Case
- **THEN** 系統將移除該筆資料後的 JSON 陣列寫入 `test_data_json`

### Requirement: Test Data 欄位約束
Test Data 的 name SHALL 為必填且長度不得為零；value 為必填但允許空字串。

#### Scenario: 儲存 Test Case 時 name 為空
- **WHEN** 使用者嘗試儲存含有 name 為空字串的 Test Data 的 Test Case
- **THEN** 系統回傳 422 驗證錯誤，拒絕儲存

#### Scenario: 儲存 Test Case 時 value 為空字串
- **WHEN** 使用者儲存含有 value 為空字串但 name 有效的 Test Data 的 Test Case
- **THEN** 系統允許儲存

### Requirement: Test Run Item 即時讀取 Test Case 的 Test Data
Test Run Item SHALL 透過與 Test Case 的即時關聯讀取當前 Test Data，而非儲存 snapshot。Test Case 的 Test Data 更新後，所有引用該 Test Case 的 Test Run Item 即時反映變更。

#### Scenario: Test Run Item 顯示當前 Test Data
- **WHEN** 使用者開啟 Test Run Item Detail 頁面
- **THEN** 頁面顯示該 Test Case 當前的所有 Test Data

#### Scenario: 修改 Test Case Test Data 影響 Test Run Item
- **WHEN** 使用者修改 Test Case 的 Test Data 並儲存
- **THEN** 重新載入 Test Run Item Detail 後，顯示更新後的 Test Data

### Requirement: Test Data 複製功能
系統 SHALL 在 Test Run Item Detail 頁面為每一筆 Test Data 提供一鍵複製功能，將 value 複製至使用者剪貼簿。

#### Scenario: QA 複製 Test Data
- **WHEN** QA 在 Test Run Item Detail 點擊 Test Data 的複製按鈕
- **THEN** 該筆 Test Data 的 value 被寫入系統剪貼簿
