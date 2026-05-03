# test-case-management Specification

## Purpose
定義 TCRT 中測試案例的本地管理邊界，確保測試案例建立、編輯、刪除與後續維護皆以本地系統資料為唯一來源，不再依賴外部同步回寫。

## ADDED Requirements

### Requirement: Test Case 資料模型支援 Test Data 關聯
系統 SHALL 在 Test Case 的資料模型與 API 回應中納入 `test_data` 欄位，使取用方能一併取得 Test Case 及其 Test Data 列表。

#### Scenario: 取得 Test Case 時包含 Test Data
- **WHEN** 使用者透過 API 或 UI 取得單一 Test Case 詳情
- **THEN** 回應中包含該 Test Case 的所有 Test Data（id, name, value），按陣列索引順序排列

#### Scenario: 更新 Test Case 時整批更新 Test Data
- **WHEN** 使用者透過 API 更新 Test Case 並提供 `test_data` 陣列
- **THEN** 系統將 `test_data` 序列化為 JSON 儲存至 `test_data_json`，取代原有內容

## MODIFIED Requirements

### Requirement: 測試案例的本地化管理
系統 SHALL 將測試案例的所有建立、編輯、刪除操作保留在本地系統內，不再嘗試從外部資料源（如 Lark）同步或覆寫本地資料。刪除測試案例時，其 Test Data 隨同移除。

#### Scenario: 編輯測試案例
- **WHEN** 使用者在 TCRT 系統中編輯一個現有的測試案例
- **THEN** 變更會直接儲存至本地資料庫，並且不會觸發任何外部的同步 API，也不會被外部資料覆寫。

#### Scenario: 建立測試案例
- **WHEN** 使用者透過 UI 手動建立新的測試案例
- **THEN** 測試案例成為本地管理的唯一資源，不再需要包含任何 Lark record_id 才能運作。
