## Why

Test Data（`test_data_json` / `TestDataItem`）已支援單筆 Test Case CRUD、QA AI Helper、MCP 讀取與 Set CSV 匯出欄位，但 **Bulk Create 與 Bulk Clone 路徑完全忽略 test_data**，導致批次建案後仍需逐筆補資料，Clone 也會靜默遺失。同時 Bulk Create 的 CSV 契約與 Set CSV Export 欄序不一致，使用者無法可靠地「匯出 → 再批次建回」時理解 test_data 欄位語意。現在補齊 bulk create / export 契約 / clone，可讓 test_data 在日常批次工作流中端到端可用。

## What Changes

- **Bulk Create（JWT UI + API）**
  - `BulkTestCaseItem` 新增可選 `test_data: List[TestDataItem]`。
  - `POST .../testcases/bulk_create` 採兩階段：schema 通過後，先對整批完成 `normalize_test_data_items()` 與衝突檢查，**全部成功後才** `add` 任何列並寫入 `test_data_json`（避免 `run_sync_write` 半成功 commit）。
  - 驗證分層：**缺 value / 非 string id 等 → HTTP 422**；**編號衝突 → `success=false` + `duplicates`（維持既有 UI）**；**normalize 失敗 → `success=false` + `errors`**；皆 DB 零寫入，欄位不可混用。
  - Bulk Create 文字模式 CSV **向後相容**：既有 2–7 欄格式不變；新增可選第 8 欄為 test_data JSON 陣列字串（形狀與 Set Export **非空** `test_data` cell 一致）。
  - 預覽 UI 顯示 test_data 摘要（name / category）；`credential` value 在預覽遮罩。
  - Audit details **不得**寫入 credential 明文（使用 `redact_credential_test_data` 或僅記 count/names）。
- **Bulk Clone（JWT + 共用 `run_bulk_clone_sync` / app-token）**
  - 複製來源 case 的 `test_data_json` 至新 case（內容等價；缺 test_data 則維持 null/空）。
  - 不改變「不複製 TCG / 附件 / 執行結果」等既有 clone 邊界（TCG 仍依現況；本 change 只補 test_data）。
- **Test Case Set CSV Export**
  - 將 export 的 `test_data` 欄位提升為正式契約：僅通過「共用可 round-trip 判定」（schema + **完整 normalize 穩定性**）的非空陣列輸出 compact JSON；會被 normalize 拒/改寫或型別非法者空字串。
  - 補齊／強化測試：duplicate 相容、422 / errors 分層、export normalize 邊界（重複 name、>100、超長、清洗、null byte）、原子性與 audit 不含 credential 明文。
  - 文件說明：Export 整列 **不可** 直接貼回 Bulk Create（欄序不同）；僅 **test_data 儲存格 JSON 形狀** 與 Bulk Create 第 8 欄對齊，便於人工搬移。
- **文件 / i18n / sample**
  - 更新 Bulk Create help、placeholder、sample CSV、manual；說明 credential 匯入風險。
- **非目標**
  - 不做 DB migration（`test_data_json` 已存在）。
  - 不做「整份 Export CSV 一鍵 re-import」新 UI/parser（欄序對齊屬未來 change）。
  - 不做 Bulk Edit test_data、不做 MCP mutate、不改 Lark sync。
  - 不發明第二套 test_data CSV DSL（非 JSON）。
- **相容性**：Bulk Create 省略第 8 欄時行為與今日相同；export 欄位名稱與順序維持 `TEST_CASE_SET_CSV_COLUMNS`，不標 **BREAKING**。

## Capabilities

### New Capabilities
- `test-data-bulk-transfer`：定義 test_data 在 Bulk Create 匯入、Test Case Set CSV Export、Bulk Clone 三條轉移路徑上的契約、驗證、安全（audit/預覽 redact）與向後相容行為。

### Modified Capabilities
- `test-case-management`：補上 bulk create / bulk clone 對本地 test case 內容欄位（含 test_data）的行為要求。
- `test-case-management-ui`：Bulk Create Mode 文字輸入、預覽、說明與 sample 支援 test_data 欄位。

## Impact

- **API / Backend**：`app/api/test_cases.py`（`BulkTestCaseItem`、`bulk_create_test_cases`、`run_bulk_clone_sync`）；`app/api/test_case_sets.py`（export 契約與測試對齊，邏輯可能僅需小改或文件化）。重用 `normalize_test_data_items`、`redact_credential_test_data`（`app/models/test_case.py`）。
- **Frontend**：`app/static/js/test-case-management/bulk.js`、`app/templates/test_case_management.html`、三語系 locale、`app/static/samples/bulk_test_cases_sample.csv`。
- **Docs**：`manual/03_Test_Case_Management.md`、`docs/user_manual.md`（若仍描述 Bulk Create 格式）。
- **Tests**：bulk_create 含/不含 test_data、normalize 失敗整批拒絕、bulk_clone 複製 test_data、export CSV test_data 形狀與 credential 保真、前端 parse 回歸（若有既有 JS 測試則補；否則以後端為主）。
- **Migration / Rollback**：無 schema 變更。Rollback = 還原 API/前端契約與文件；已寫入的 `test_data_json` 保留無害。
- **風險**：CSV 內嵌 JSON 對 Excel 不友善；credential 明文可能經 clipboard/export 外洩——以預覽/audit 遮罩與文件警告緩解，DB 與 export 保真以支援可攜。
