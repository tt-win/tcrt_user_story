## 1. Database & Migration

- [x] 1.1 在 `test_case_local`（資料表名 `test_cases`）新增 `test_data_json` 欄位（`Column(Text, nullable=True)`）於 `app/models/database_models.py`。此處 `Text` 為專案內 `MediumText` 別名（`from ..db_types import MediumText as Text`），MySQL 下自動對應 `MEDIUMTEXT`，與既有 JSON 欄位策略一致。
- [x] 1.2 更新 `database_init.py`，以 `add_column_if_not_exists` 模式新增 `test_data_json` 至 `test_cases`
- [x] 1.3 執行本地啟動驗證，確認 bootstrap 無誤：`./start.sh` 可正常啟動且無 schema 錯誤

## 2. Backend Models & Schemas

- [x] 2.1 新增 `TestDataItem` Pydantic 模型（`id: str`, `name: str`, `value: str`）於 `app/models/test_case.py`
- [x] 2.2 擴展 `TestCaseCreate`、`TestCaseUpdate`、`TestCaseResponse` 以包含 `test_data: Optional[List[TestDataItem]]`
- [x] 2.3 更新 `TestCase`/`TestCaseLocal` 序列化邏輯，使 `test_data_json` ↔ `test_data` 自動轉換
- [x] 2.4 擴展 `TestRunItemResponse` 以包含 `test_data: Optional[List[TestDataItem]]`（來自即時讀取的 `test_case.test_data_json`）

## 3. Backend API

- [x] 3.1 更新 `app/api/test_cases.py` 的 `create_test_case` 與 `update_test_case`，將 `test_data` 序列化為 JSON 寫入 DB
- [x] 3.2 更新 `app/api/test_cases.py` 的 `get_test_case`，將 `test_data_json` 反序列化後回傳
- [x] 3.3 更新 `app/api/test_run_items.py` 的 `_db_to_response`，從 `item.test_case` 即時讀取 `test_data_json` 並反序列化後回傳

## 4. Frontend - Test Case Detail

- [x] 4.1 在 Test Case Detail 模板/JS 新增 Test Data 區塊（Steps 下方）
- [x] 4.2 實作 Test Data inline 編輯 UI：動態表單列（name + value + 刪除 + 新增列）
- [x] 4.3 儲存 Test Case 時將 Test Data 陣列一併隨同 PUT 送出
- [x] 4.4 無編輯權限時，Test Data 區塊以唯讀模式呈現

## 5. Frontend - Test Run Item Detail

- [x] 5.1 在 Test Run Item Detail 模板/JS 新增 Test Data 顯示區塊
- [x] 5.2 從 `test_case.test_data`（即時讀取）渲染 Test Data 列表（name + value）
- [x] 5.3 為每筆 Test Data 加入「複製」按鈕，使用 `navigator.clipboard.writeText` 複製 value
- [x] 5.4 無 Test Data 時顯示「無 Test Data」提示

## 6. i18n

- [x] 6.1 在 `app/static/locales/` 的繁體中文與英文語系檔中補充 Test Data 相關文案（標題、新增、刪除、複製、無資料提示）（另補 zh-CN）

## 7. Testing

- [x] 7.1 Test Data 整批更新驗證：新增/修改/刪除隨同 Test Case PUT（已由 owner 手動驗證完成）
- [x] 7.2 Test Run Item API 回應包含 Test Data 的驗證（已由 owner 手動驗證完成）
- [x] 7.3 後端回歸驗證（已由 owner 手動驗證完成）

## 8. Documentation & Cleanup

- [x] 8.1 確認 `openspec/changes/add-test-data-crud/` 下所有文件對齊即時讀取設計
- [x] 8.2 確認 `README.md` 或相關文件無需更新（本次變更為功能增補，非架構調整）
