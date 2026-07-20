## 1. Backend — Bulk Create

- [x] 1.1 擴充 `BulkTestCaseItem` 增加可選 `test_data: Optional[List[TestDataItem]]`
- [x] 1.2 實作兩階段 bulk_create（schema 通過後）：A1 編號衝突 → `success=false, duplicates=[...], errors=[]`；A2 每筆 `normalize_test_data_items` 暫存，失敗 → `success=false, errors=[...], duplicates=[]`；兩階段皆**不得** `session.add`；禁止把 duplicate 塞進 `errors` 或把 normalize 塞進 `duplicates`
- [x] 1.3 Phase B 僅在 A1+A2 全數成功後，才建立 `TestCaseLocalDB` 並寫入已 normalize 的 `test_data_json`；省略/空 test_data 則 null
- [x] 1.4 bulk_create audit `details` 排除 credential 明文（redact 或僅記 count/names）

## 2. Backend — Bulk Clone

- [x] 2.1 在 `run_bulk_clone_sync` 建立新列時複製 `src.test_data_json`
- [x] 2.2 確認 JWT `bulk_clone` 與 app-token bulk-clone 皆走同一 sync 函式而無需重複邏輯

## 3. Backend — Set CSV Export 契約

- [x] 3.1 調整 test_data 匯出 helper：依 design 映射表；**共用可 round-trip 判定**＝schema 型別 + 完整 normalize 穩定性（≤100、name/value 清洗後不變、name 唯一、長度上限、無 null byte 等）；未通過 → 整格空字串（建議試跑 `normalize_test_data_items` 並比對 name/value 字面）
- [x] 3.2 確認 `TEST_CASE_SET_CSV_COLUMNS` 欄名順序不變；通過判定的非空陣列 credential value 保真
## 4. Frontend — Bulk Create 文字模式

- [x] 4.1 更新 `parseBulkText`：最多 8 欄；第 8 欄可選。非空時須為 JSON 陣列且通過與 export **相同**的可 round-trip 判定（含 ≤100、穩定 name/value、唯一 name、長度、null byte）；未通過 → 行級錯誤
- [x] 4.2 `confirmBulkTextCreate` payload 帶上解析後的 `test_data`；勿對 JSON value 套用正文用的 `\\n` 轉換；失敗時仍依 `data.duplicates` 標記 Conflict、依 `data.errors` 顯示錯誤（不混用）
- [x] 4.3 預覽表新增 Test Data 摘要欄；`credential` value 遮罩
- [x] 4.4 更新 modal help/placeholder 相關 i18n（en-US / zh-CN / zh-TW），含敏感資料與「Export 整列不可直接貼回」提示
- [x] 4.5 更新 `app/static/samples/bulk_test_cases_sample.csv` 至少一列示範第 8 欄
- [x] 4.6 預覽表頭模板（`test_case_management.html`）補 Test Data 欄位

## 5. Docs

- [x] 5.1 更新 `manual/03_Test_Case_Management.md` Bulk Create 格式說明
- [x] 5.2 若 `docs/user_manual.md` 仍描述 Bulk Create 格式，同步更新

## 6. Tests

- [x] 6.1 bulk_create：含 test_data 成功寫入；省略 test_data 相容
- [x] 6.2 bulk_create 原子性（normalize → `errors`）：第 1 筆合法、第 2 筆同 case 重複 name 或僅空白字元 name → `success=false`、`errors` 非空、`duplicates` 為空、DB **0 筆**
- [x] 6.3 bulk_create schema 422：缺 value、或 `id` 為 number → **HTTP 422**、DB 0 筆（非 envelope）
- [x] 6.4 bulk_create duplicate 相容（兩情境皆測）：(a) DB 已存在相同 `test_case_number`；(b) **同一 request 內兩筆相同編號** → 皆 `success=false`、`duplicates` 含該編號、`errors` 為空、DB 0 筆
- [x] 6.5 bulk_create category 正規化：省略 / `null` / `""` → 寫入後 `text`；`EMAIL`（或混用大小寫）→ 寫入後 canonical `email`
- [x] 6.6 bulk_create audit：成功建立含唯一 credential 秘密字串後，audit details **不含**該明文
- [x] 6.7 bulk_clone：來源有/無 test_data 的複製行為
- [x] 6.8 export-csv：通過判定的非空陣列與 credential 保真；`null`/`""`/`"[]"` → 空 cell；malformed、非陣列、缺 value、numeric id、未知 category → 空 cell
- [x] 6.9 export-csv normalize 邊界 → 空 cell：**(a)** 清洗後重複 name（如 `"a"` 與 `" a "`）；**(b)** 101 筆；**(c)** name 或 value 超長；**(d)** name 含需清洗字元（首尾空白/控制/bidi/換行）；**(e)** value 含 null byte
- [x] 6.10 執行目標 pytest 與 `node --check app/static/js/test-case-management/bulk.js`；必要時跑 i18n coverage

## 7. Verification

- [x] 7.1 `openspec validate support-test-data-bulk-create-export-clone --strict` 通過
- [x] 7.2 對照 delta specs 逐條確認場景有對應實作或測試
