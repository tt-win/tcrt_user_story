## Context

TCRT 目前以 `TestCaseLocal`（本地 SQLite）作為 test case 唯一來源，`TestRunItem` 在建立 Test Run 時以 JSON snapshot 方式保存部分 test case 欄位（如 `attachments_json`、`execution_results_json`），但核心內容欄位（`title`, `precondition`, `steps`, `expected_result`, `priority`）是透過 SQLAlchemy `viewonly` relationship 從 `TestCaseLocal` **即時讀取**。Test Data 作為輔助執行資料，行為應與核心內容欄位一致。

## Goals / Non-Goals

**Goals:**
- 支援一對多 Test Data 掛載在 Test Case 上（CRUD）。
- Test Case Detail UI 可即時編輯 Test Data。
- Test Run Item Detail UI 可顯示當前 Test Case 的 Test Data，並提供一鍵複製。
- 資料庫變更需為非破壞性升級，且不新增獨立資料表、不修改 `test_run_items`。

**Non-Goals:**
- 不在 Test Data 中支援檔案附件（僅純文字 name/value）。
- 不與 Lark 同步 Test Data。
- 不在 Test Run 執行期間反向修改來源 Test Case 的 Test Data。
- 不為 Test Data 建立獨立資料表或修改 `test_run_items`。

## Decisions

### 1. 資料欄位設計：JSON 欄位於 test_case_local（對齊既有架構）
- **Rationale**：TCRT 現有資料模型已大量使用 JSON 欄位儲存多值資料。使用 JSON 欄位可最小化 schema 變更，且 Test Data 量小、純文字，整批讀寫效能無虞。
- **Schema 變更**：
  - `test_case_local` 新增 `test_data_json`（Column(Text, nullable=True)）：儲存 Test Data 陣列 JSON，每筆元素為 `{id, name, value}`。此處 `Text` 為專案內 `MediumText` 別名，SQLite/PostgreSQL 下為一般 Text，MySQL 下自動對應 `MEDIUMTEXT`（16MB），與既有 `attachments_json`、`tcg_json` 等欄位採用相同跨資料庫策略。
  - `test_run_items` **不變更**（無需新增欄位）。
- **Alternatives considered**：
  - 獨立 `test_data` 表 → 拒絕，因使用者要求最小化架構變動。
  - `test_run_items` 新增 `test_data_json` snapshot → 拒絕，因 Test Run Item 已透過 `test_case` relationship 即時讀取 Test Case 內容，snapshot 會導致與 Test Case 不一致。

### 2. Test Data 結構
- 每筆 Test Data 為 `{id: str, name: str, value: str}` 物件。
- `id` 由前端生成（`crypto.randomUUID` 或後端於儲存時補上），用於前端列表中的 key 與 diff 識別。
- `name` 為必填，長度 > 0；`value` 允許空字串。
- 順序以陣列索引為準，無需額外排序欄位。

### 3. API 設計：整批更新於 Test Case PUT
- **Rationale**：Test Data 依附於 Test Case，無需獨立路由。整批更新可避免多次 API round trip。
- **設計**：
  - `TestCaseUpdate` 與 `TestCaseCreate` 新增 `test_data: Optional[List[TestDataItem]]`。
  - 後端接收時將 `test_data` 序列化為 JSON 字串寫入 `test_case_local.test_data_json`。
  - `TestCaseResponse` 於輸出時反序列化 `test_data_json` 為 `test_data: List[TestDataItem]`。
- **權限**：沿用 Test Case 的編輯權限（Casbin RBAC），無額外權限顆粒度。

### 4. Test Run Item：即時讀取 Test Case 的 Test Data
- **Rationale**：對齊現有 `title`, `steps`, `precondition` 等核心欄位的讀取模式。`TestRunItem` 已透過 `test_case`（`viewonly=True`）relationship 即時 JOIN `TestCaseLocal`。Test Data 作為輔助資料，無需 snapshot。
- **設計**：
  - Test Run Item API (`_db_to_response`) 從 `item.test_case` 即時讀取 `test_data_json`，反序列化後回傳。
  - Test Run 建立時**不處理** Test Data 複製邏輯。
  - Test Case 的 Test Data 更新後，所有引用該 Test Case 的 Test Run Item 即時反映變更。

### 5. 前端互動：inline 編輯 + 一鍵複製
- **Test Case Detail**：在 Steps 區塊下方新增「Test Data」摺疊/展開區塊，使用動態表單列（name + value + 刪除 + 新增列）。儲存時隨同 Test Case 其他欄位一併 PUT。
- **Test Run Item Detail**：在預期結果區塊旁新增「Test Data」唯讀卡片列表，每筆提供「複製到剪貼簿」按鈕（`navigator.clipboard.writeText`）。資料來源為 `test_case.test_data`（即時讀取）。

### 6. Pydantic 模型
- 新增 `TestDataItem`（`id: str`, `name: str`, `value: str`）。
- `TestCaseCreate`、`TestCaseUpdate`、`TestCaseResponse` 擴展 `test_data: Optional[List[TestDataItem]]`。
- `TestRunItemResponse` 擴展 `test_data: Optional[List[TestDataItem]]`（來自即時讀取的 `test_case.test_data_json`）。

## Risks / Trade-offs

| Risk | Mitigation |
|------|------------|
| 單筆 Test Data 更新需整批覆寫 JSON 欄位 | 純文字資料量小，race condition 風險低；如未來頻繁並發編輯，可改用樂觀鎖 |
| JSON 欄位難以對單筆 test data 做 DB 層級驗證 | 由 Pydantic 模型於 API 層驗證（name 必填、value 允許空字串） |
| DB bootstrap 腳本未執行導致欄位缺失 | `database_init.py` 需以 `add_column_if_not_exists` 確保 `test_data_json` 欄位存在 |
| Test Case 被刪除後 Test Run Item 無法讀取 Test Data | 與現有 `title`, `steps` 等欄位行為一致；若 Test Case 被刪除，Test Run Item 的 Test Data 顯示為空 |

## Migration Plan

1. **Bootstrap**：在 `database_init.py` 以 `add_column_if_not_exists` 模式：
   - `ALTER TABLE test_cases ADD COLUMN test_data_json TEXT`
2. **現有資料**：無需回填，Test Data 為全新功能。
3. **Rollback**：
   - 移除 `test_cases.test_data_json` 欄位。
   - 回滾 Pydantic 模型與前端模板/JS 修改。

## Open Questions

- `test_data` 的 `id` 應由前端生成（UUID）還是後端於儲存時補上？建議前端生成，以避免 diff 與重新渲染問題。
- Test Data 的 `value` 是否需支援多行文字（textarea）？建議第一版先支援單行輸入，但 JSON 與 DB 欄位保留彈性。
- 是否需要 Test Data 的批次匯入/匯出？建議第一版不實作，待使用者回饋。
