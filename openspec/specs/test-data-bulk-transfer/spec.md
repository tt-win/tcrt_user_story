# test-data-bulk-transfer Specification

## Purpose
TBD - created by archiving change support-test-data-bulk-create-export-clone. Update Purpose after archive.
## Requirements
### Requirement: Bulk Create API SHALL Accept Optional test_data
`POST /api/teams/{team_id}/testcases/bulk_create` 的每個 item SHALL 接受可選欄位 `test_data`，型別為 `TestDataItem` 陣列（`id` 可省略、`name` 必填、`value` 必填且為字串並允許空字串、`category` 可省略並預設 `text`）。省略 `test_data` 或傳 `null` / 空陣列時，該 case 的 `test_data_json` SHALL 為空（null 或不含項目），且不得影響其他欄位建立。

請求驗證分為多層，回應契約不同且 **envelope 欄位分流**：

1. **Request schema（Pydantic / FastAPI）**：進入 handler 前驗證巢狀 `TestDataItem`。缺少 `value`、`value` 非字串、`id` 存在但非字串（例如 number）、或其他無法建構 model 的情況 SHALL 產生 **HTTP 422**，且 **不得** 寫入任何 test case。此層 **不會** 回傳 `BulkCreateResponse`。
2. **編號 duplicate（既有契約）**：handler 偵測到 `test_case_number` 與 DB 或請求內衝突時，SHALL 回傳 **HTTP 200** 與 `BulkCreateResponse(success=false, created_count=0, duplicates=[...], errors=[])`。SHALL NOT 僅以 `errors` 表達編號衝突（前端依 `duplicates` 標記 Conflict）。
3. **Handler normalize（`normalize_test_data_items`）**：schema 通過後執行。清洗後空白 name、同 case 內 name 重複、超過 100 筆等失敗時，SHALL 回傳 **HTTP 200** 與 `BulkCreateResponse(success=false, created_count=0, errors=[...], duplicates=[])`。SHALL NOT 將 normalize 錯誤放入 `duplicates`。

Handler 實作 SHALL 採兩階段：先完成編號衝突檢查與每筆 test_data normalize（皆僅記憶體）；**僅當全部成功後**才建立任何 `TestCaseLocalDB`。不得在仍可能失敗的後續驗證之前 `session.add`（避免 `run_sync_write` 半成功 commit）。

#### Scenario: 帶 test_data 批次建立成功
- **WHEN** 呼叫 bulk_create，其中一筆 item 含 `test_data: [{ "name": "user", "category": "email", "value": "qa@example.com" }]` 且其餘驗證通過
- **THEN** 系統建立該 test case，且其 `test_data_json` 反序列化後包含 name=`user`、category=`email`、value=`qa@example.com` 的項目（id 由 server 補齊若未提供）

#### Scenario: 省略 test_data 時行為與既有相容
- **WHEN** 呼叫 bulk_create 且所有 item 皆未提供 `test_data`
- **THEN** 系統仍成功建立案例（其他欄位正常），且新建案例沒有可用的 test_data 項目

#### Scenario: schema 缺少 value 或非字串 id 回 HTTP 422 且零寫入
- **WHEN** 請求中任一 test_data 元素缺少 `value`、或 `value` 非字串、或 `id` 為 number（例如 `1`）
- **THEN** 回應 **HTTP 422**（非 `BulkCreateResponse`），且資料庫未新增任何 test case

#### Scenario: DB 既有編號 duplicate 維持 duplicates 欄位
- **WHEN** bulk_create 請求中的 `test_case_number` 已存在於該 team
- **THEN** 回應 `BulkCreateResponse` 且 `success=false`、`created_count=0`、`duplicates` 含衝突編號、`errors` 為空陣列，且 DB 未新增任何列

#### Scenario: 同一 request 內編號重複維持 duplicates 欄位
- **WHEN** 同一 bulk_create 請求 body 的 `items` 中出現兩筆相同 `test_case_number`（DB 中尚無該編號亦可）
- **THEN** 回應 `BulkCreateResponse` 且 `success=false`、`created_count=0`、`duplicates` 含該編號、`errors` 為空陣列，且 DB 未新增任何列
#### Scenario: normalize 失敗回 errors 且零寫入
- **WHEN** 同一請求已通過 Pydantic schema，第 1 筆 item 的 test_data 合法，第 2 筆 item 的 test_data 違反 normalize 規則（例如同 case 內 name 重複、清洗後空白 name、超過 100 筆）
- **THEN** 回應 `BulkCreateResponse` 且 `success=false`、`created_count=0`、`errors` 含可定位說明、`duplicates` 為空陣列，且 DB 未新增任何 test case（含第 1 筆合法 item）

### Requirement: Bulk Create Text Mode CSV SHALL Support Optional Eighth Column for test_data
Bulk Create 文字模式的每行 CSV SHALL 支援既有最多 7 欄格式，並可選第 8 欄為 test_data 的 JSON 陣列字串。第 8 欄的 JSON 形狀 SHALL 與 Test Case Set CSV Export 的非空 `test_data` 儲存格相同。多於 8 欄 SHALL 視為格式錯誤。第 8 欄空白 SHALL 視為無 test_data。

當第 8 欄非空時，解析後 SHALL 為 JSON 陣列，且整份陣列 SHALL 通過與 Export 相同的**共用可 round-trip 判定**（含完整 normalize 穩定性，見 Export requirement）。未通過（含 >100 筆、normalize 後重複 name、超長、name 會被清洗、value 含 null byte、型別非法等）SHALL 使該行格式錯誤，且不得進入 bulk_create 成功寫入。

#### Scenario: 第 8 欄合法 JSON 被解析並送出
- **WHEN** 使用者輸入一行 8 欄且第 8 欄為通過可 round-trip 判定的 JSON 陣列
- **THEN** 前端解析成功，確認請求 body 的對應 item 包含等價的 `test_data` 陣列

#### Scenario: 僅 7 欄的舊格式仍可建立
- **WHEN** 使用者輸入符合既有「編號,標題,...,TCG,優先級」的 7 欄（或更少但至少編號+標題）且無第 8 欄
- **THEN** 系統不得因缺少 test_data 欄而拒絕；行為與加入 test_data 支援前相容

#### Scenario: 第 8 欄非法 JSON 被拒
- **WHEN** 第 8 欄非空但不是合法 JSON 陣列
- **THEN** 該行標記為格式錯誤，且不得進入 bulk_create 成功寫入

#### Scenario: 第 8 欄元素缺少 value 被拒
- **WHEN** 第 8 欄為 `[{"name":"user"}]`（元素無 `value` 鍵）
- **THEN** 該行標記為格式錯誤，且不得僅依預覽進入成功 bulk_create

#### Scenario: 第 8 欄 numeric id 或未知 category 被拒
- **WHEN** 第 8 欄元素含 `id: 1`（number）或 `category: "not-a-real-category"`
- **THEN** 該行標記為格式錯誤

### Requirement: Bulk Create Preview SHALL Summarize test_data Without Exposing Credential Values
Bulk Create 預覽 UI 若顯示 test_data，SHALL 以摘要形式呈現（至少 name 與 category）。對於 `category=credential` 的項目，預覽 SHALL NOT 顯示明文 value（得顯示遮罩符號或省略 value）。

#### Scenario: credential 在預覽中被遮罩
- **WHEN** 解析結果含 `category=credential` 且 value 為明文密碼
- **THEN** 預覽區域不出現該明文密碼字串

### Requirement: Bulk Create Audit SHALL Not Persist Credential test_data Values
bulk_create 寫入 audit log 的 details SHALL NOT 包含任何 `category=credential` 的明文 value。允許記錄 test_data 筆數、name 列表，或經 `redact_credential_test_data` 遮罩後的結構。

#### Scenario: audit 不含 credential 明文
- **WHEN** bulk_create 成功建立含 credential test_data 的案例並寫入 audit
- **THEN** 該 audit details 中找不到該 credential 的原始 value 字串

### Requirement: Bulk Clone SHALL Copy test_data
`run_bulk_clone_sync`（含 JWT `bulk_clone` 與 app-token 對應路徑）在建立新 test case 時 SHALL 從來源複製 `test_data_json`，使新案例的 test_data 內容與來源等價。來源無 test_data 時，新案例 SHALL 亦無 test_data 項目。

#### Scenario: clone 帶有 test_data 的來源
- **WHEN** 使用者 bulk clone 一筆含兩項 test_data 的來源案例且新編號不衝突
- **THEN** 新建案例可讀出兩項等價的 test_data（name/category/value 與來源一致）

#### Scenario: clone 無 test_data 的來源
- **WHEN** 來源案例沒有 test_data
- **THEN** 新建案例也沒有 test_data 項目，且其他既有 clone 欄位行為不變

### Requirement: Test Case Set CSV Export SHALL Emit test_data Cell Contract
`GET /api/teams/{team_id}/test-case-sets/{set_id}/export-csv` 的表頭 SHALL 包含 `test_data` 欄（位於既有 `TEST_CASE_SET_CSV_COLUMNS` 順序中）。每一資料列的 `test_data` 儲存格 SHALL 依 DB `test_data_json` 映射如下：

| DB `test_data_json` | Export cell |
|---------------------|-------------|
| `null` | 空字串 |
| 空字串或僅空白 | 空字串 |
| 可解析的空陣列 `[]` | 空字串 |
| 可解析的非空 JSON 陣列，且通過**共用可 round-trip 判定**（見下） | compact JSON 陣列字串（元素保留 `id` / `name` / `category` / `value`） |
| 可解析的非空 JSON 陣列，但**未通過**共用可 round-trip 判定 | 空字串（不得輸出該陣列） |
| 可解析但非陣列 | 空字串（不得輸出該非陣列 JSON） |
| 無法解析（malformed） | 空字串（不得原樣輸出 raw） |

**共用可 round-trip 判定**（export helper 與 Bulk Create 第 8 欄**同一規則**；對齊完整 `normalize_test_data_items`，不僅欄位型別）：

**A. Schema / 型別層**

- 元素為 object（非 null、非 array）。
- `name`：string，且非空白（見 B：須已是 normalize 後形態）。
- `value`：鍵存在且為 string（可為 `""`）。
- `id`：省略、JSON `null`、或 string；**其他型別非法**（含 number）。
- `category`：省略、JSON `null`、`""`、或合法 enum 字串（case-insensitive）；**未知 category 非法**。

**B. 清單與 normalize 穩定性（對齊 `normalize_test_data_items`）**

整份陣列 MUST 同時滿足：

1. 元素數量 ≤ `MAX_TEST_DATA_ITEMS`（**100**）。
2. 對每一元素，將 `name` / `value` 套用與 server 相同的清洗後，結果 MUST **等於** 原始 `name` / `value`（已穩定，不會在寫入時被改寫）：
   - `name` 清洗：移除 C0 控制字元（保留語意同 server：不含 `\t` 於「須移除」集合時以 server 為準）、bidi override、將 `\n`/`\r` 視為需清洗、strip 首尾空白；清洗後非空、長度 ≤ **500**。
   - `value` 清洗：僅移除 NULL byte（`\x00`）；長度 ≤ **100_000**。
   - 因此含首尾空白、換行/控制/bidi 的 name，或含 `\x00` 的 value，**不**通過（export 空字串 / 前端行錯誤）。
3. 清洗後（亦等於原始）的 `name` 在同一陣列內 **唯一**（case-sensitive）。例：`[{name:"a",value:""},{name:" a ",value:""}]` — 第二項 name 非穩定；`[{name:"a",value:""},{name:"a",value:"x"}]` — 重複 name。皆不通過。
4. 可構造成 `TestDataItem` 列表並通過 `normalize_test_data_items` 而不 raise。

實作建議：export / 前端判定可「試跑」與 server 等價的 normalize；僅當成功且每個 name/value 與 normalize 輸出字面相同時視為可 round-trip。

**Category 正規化（canonical effective category）**（僅 category 允許非字面等價）：

| 輸入 | 有效 category（canonical） |
|------|---------------------------|
| 鍵省略、JSON `null`、`""` | `text` |
| 合法 enum（任意大小寫） | 小寫 canonical（如 `email`） |
| 未知字串 | 非法 |

不合法 / 不可 round-trip 示例：scalar、`[1]`、缺 value、`id:1`、未知 category、**101 筆**、**normalize 後重複 name**、**name 首尾空白或含控制/bidi/換行**、**name/value 超長**、**value 含 null byte**。

當輸出為非空陣列時，Export SHALL NOT 因 credential category 而遮罩或移除 value（保真匯出）。Export 整列表頭與欄序 SHALL NOT 為了本需求而變更既有欄名順序（非 breaking）。

**Round-trip 保證範圍**：僅「Export 輸出的非空 `test_data` cell」保證：(1) 可被 Bulk Create 第 8 欄接受且 bulk_create **成功寫入**（不會因 normalize 被拒）；(2) 寫入後 **name / value 與 cell 字面等價**；(3) **category 依上表正規化後等價**。`id` 可保留或重發。未通過判定的 legacy / 髒資料 **不得** 以非空 cell 出現（故不在保證內）。

#### Scenario: 匯出含合法 test_data 的案例
- **WHEN** Set 內有一筆案例其 test_data 為合法形狀且含 text 與 credential 各一項
- **THEN** CSV 對應列的 `test_data` 儲存格可解析為長度 2 的陣列，且 credential 項的 value 為 DB 中原始值

#### Scenario: null 或空字串匯出為空儲存格
- **WHEN** 案例的 `test_data_json` 為 null 或空字串
- **THEN** 該列 `test_data` 儲存格為空字串

#### Scenario: 空陣列匯出為空儲存格
- **WHEN** 案例的 `test_data_json` 為字串 `[]`
- **THEN** 該列 `test_data` 儲存格為空字串（不得輸出 `[]`）

#### Scenario: malformed 或非陣列 JSON 匯出為空儲存格
- **WHEN** 案例的 `test_data_json` 為無法解析字串，或可解析但非 JSON 陣列
- **THEN** 該列 `test_data` 儲存格為空字串，且不得包含原始 malformed 全文或非陣列 JSON 原文作為 cell 內容

#### Scenario: 元素形狀不合法的陣列匯出為空儲存格
- **WHEN** 案例的 `test_data_json` 為可解析非空陣列，但含不合法元素（例如 `[1]`、缺 value、**`id` 為 number**、或 **未知 category**）
- **THEN** 該列 `test_data` 儲存格為空字串，且不得輸出該陣列原文

#### Scenario: normalize 會拒絕或改寫的陣列匯出為空儲存格
- **WHEN** 案例的 `test_data_json` 為可解析非空陣列，但會被 `normalize_test_data_items` 拒絕或改寫 name/value，例如：超過 100 筆、清洗後 name 重複（含 `"a"` 與 `" a "`）、name 或 value 超過長度上限、name 含需清洗字元、value 含 null byte
- **THEN** 該列 `test_data` 儲存格為空字串，且不得輸出該陣列原文

#### Scenario: 合法非空 Export cell 可 round-trip（name/value 字面、category 正規化後等價）
- **WHEN** 將 Export 某列的**非空** `test_data` 儲存格字串作為 Bulk Create 第 8 欄（其他欄依 Bulk Create 格式另行填寫）並 bulk_create
- **THEN** bulk_create 成功；寫入後每項的 name 與 value 與 cell 中字面等價；category 等於對該 cell 元素套用「Category 正規化」表後的有效值；id 可不同

#### Scenario: 省略或空 category 正規化為 text
- **WHEN** bulk_create（或第 8 欄）的 test_data 元素省略 `category`、或為 JSON `null`、或為 `""`（其餘通過可 round-trip 判定）
- **THEN** 寫入後該項的 category 有效值為 `text`

