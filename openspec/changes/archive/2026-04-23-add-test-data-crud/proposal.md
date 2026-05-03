## Why

目前 QA 在執行測試時，test data 資訊散落在測試步驟描述中，難以快速複製與重複使用。為提升測試執行效率，系統應提供獨立的 test data 欄位，讓 QA 能在 Test Case Detail 與 Test Run Item Detail 中直接查看、複製並管理測試資料，且同一測試案例可維護多筆 test data。

## What Changes

- 新增 `test_data` 資料表，支援一對多關聯至 test case（非 test case steps）。
- 新增後端 API：Test Data 的 CRUD（掛在 test case 下），含權限控管。
- Test Case Detail 頁面（UI）新增 Test Data 區塊，可增刪改查。
- Test Run Item Detail 頁面（UI）新增 Test Data 唯讀/複製區塊（run 建立時 snapshot test data）。
- 資料庫 bootstrap / migration 腳本需支援非破壞性升級。

## Capabilities

### New Capabilities
- `test-data-management`: 定義 Test Data 的生命週期管理（CRUD）與其與 Test Case、Test Run Item 的關聯行為。

### Modified Capabilities
- `test-case-management`: Test Case 資料模型與 API 需擴展以支援多筆 Test Data 的關聯與讀取。
- `test-case-management-ui`: Test Case Detail 頁面需新增 Test Data 編輯互動區塊。
- `test-run-execution-ui`: Test Run Item Detail 頁面需新增 Test Data 顯示與複製互動區塊。

## Impact

- **Database**: 新增 `test_data` 資料表（含欄位 `id`, `test_case_id`, `name`, `value`, `created_at`, `updated_at`）；`test_run_items` 關聯 snapshot。
- **Backend API**: 新增 `POST/GET/PUT/DELETE /api/test-cases/{id}/test-data` 端點；修改 test case 與 test run item 序列化邏輯。
- **Frontend**: `app/templates/test_case_detail.html`、`app/templates/test_run_item_detail.html`（或對應 JS 模組）需新增 Test Data 區塊。
- **i18n**: `app/static/locales/` 需補充 Test Data 相關文案。
- **Migration**: `database_init.py` 或對應 migration script 需確保現有資料不受影響。
