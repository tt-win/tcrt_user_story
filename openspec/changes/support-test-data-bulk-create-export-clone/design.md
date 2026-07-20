## Context

Test Data 已落地於：

- 儲存：`test_cases.test_data_json`（JSON 陣列，元素為 `TestDataItem`：`id` / `name` / `category` / `value`）
- 正規化：`normalize_test_data_items()`（數量/長度/name 唯一/字元清洗/補 UUID）
- 讀取 redact helper：`redact_credential_test_data()`（audit 等下游用）
- 單筆 create/update、app-token batch create、QA AI Helper、MCP read、**Set CSV export 欄位** 已涵蓋

缺口集中在批次轉移：

| 路徑 | 現況 |
|------|------|
| Bulk Create UI/API | 7 欄 CSV；`BulkTestCaseItem` 無 `test_data`；不寫 `test_data_json` |
| Bulk Clone（`run_bulk_clone_sync`） | 複製正文/priority/set/section，**不複製** `test_data_json` |
| Set CSV Export | 已有 `test_data` 欄，但缺正式行為契約與 credential 文件化 |

利害關係人：QA 批次建案／複製、需要備份 Set 的 team admin、後續自動化消費端。

約束：

- 無 Node bundler；Bulk Create 邏輯在 `bulk.js`
- JWT bulk_create 與 app-token `/test-cases/batch` 是不同端點；後者已支援 test_data，本 change 不重複做 app-token bulk_create
- Clone 的 JWT 與 app-token 共用 `run_bulk_clone_sync`——只改此一處即可雙路徑生效
- 不新增 schema / migration

## Goals / Non-Goals

**Goals:**

1. Bulk Create 可選帶入 test_data，寫入前走既有 normalize，失敗整批拒絕。
2. Bulk Create CSV 第 8 欄 JSON 形狀與 Export 的 `test_data` cell 對齊。
3. Bulk Clone 複製 test_data 內容等價。
4. Export 的 test_data 欄位成為可測試契約；文件標註敏感與「整列不可直接 bulk 貼回」。
5. 預覽與 audit 對 credential value 遮罩；DB/export 保真。

**Non-Goals:**

- 整份 Export CSV 一鍵 re-import UI（欄序與 Bulk Create 不同）。
- Bulk Edit test_data、MCP mutate、Lark sync。
- 第二套 pipe/DSL 格式。
- 變更 `TEST_CASE_SET_CSV_COLUMNS` 欄序或欄名（避免 **BREAKING**）。
- 改變 clone 對 TCG/附件/執行結果的既有策略（本 change 只補 test_data）。

## Decisions

### 1. Bulk Create：可選 API 欄位 + CSV 第 8 欄 JSON（方案 A）

- **Decision**：`BulkTestCaseItem.test_data: Optional[List[TestDataItem]] = None`；前端 `parseBulkText` 允許最多 8 欄，第 8 欄空 = 無 test_data。
- **JSON 形狀**：與 normalize 輸入一致——陣列物件至少含 `name`、`value`；`category` 可省略（預設 text）；`id` 可省略（server 補）。
- **Rationale**：與模型/export cell 一致；不發明 DSL；Excel 雖麻煩但可 sample + 引號說明。
- **Alternatives**：
  - DSL `name=x|value=y` → 拒絕（跳脫地獄、與 export 不一致）。
  - 只做 API 不做 CSV → 拒絕（Bulk Create Mode 主路徑是文字）。

### 2. 驗證分層與原子性（schema 422 vs envelope 欄位分流；兩階段寫入）

- **Decision — 失敗契約分層**（不可混用；**envelope 內欄位也不可混用**）：

  | 失敗類型 | 典型原因 | HTTP | Body |
  |----------|----------|------|------|
  | Request schema（Pydantic 巢狀 `TestDataItem`） | 缺少 `value`、`value` 非 string、`id` 非 string、無法建構 model | **422** | FastAPI validation error（**不是** `BulkCreateResponse`） |
  | 編號 duplicate（既有行為） | request 內或 DB 已存在相同 `test_case_number` | **200** + envelope | `success=false`, **`duplicates=[...]`**, `errors=[]`, `created_count=0` |
  | Handler normalize | 清洗後空白 name、同 case name 重複、>100 筆 | **200** + envelope | `success=false`, **`errors=[...]`**, `duplicates=[]`, `created_count=0` |

  - **禁止**把編號衝突塞進 `errors`，也禁止把 normalize 訊息塞進 `duplicates`。
  - UI（`bulk.js`）依 `data.duplicates` 標記 `(Conflict)`；依 `data.errors` 顯示一般失敗——必須維持此分流。
  - 各層皆 **DB 零寫入**。缺 `value` / 非 string `id` 在 schema 層 422，不會進 envelope。

- **Decision — 兩階段寫入**（僅 schema 通過後）：禁止「邊驗證邊 `session.add`」：
  1. **Phase A1 — 編號衝突**：若有 duplicates → 立即 `BulkCreateResponse(success=false, duplicates=..., errors=[])`，**不得** `add`。
  2. **Phase A2 — test_data normalize**：對每筆 `normalize_test_data_items`，結果暫存。任一失敗 → `success=false, errors=[...]`, `duplicates=[]`，**不得** `add`。
  3. **Phase B — 全批寫入**：僅 A1+A2 全過後才 `add` ORM 列。
- **為何必須兩階段**：`run_sync_write` 在 callable **正常返回**（含 `success=false` envelope）時仍可能 commit pending inserts。
- **回歸測試契約**：
  - Duplicate 相容：既有編號衝突 → `duplicates` 非空、`errors` 為空、DB 0 筆。
  - 原子性 / normalize：第 1 合法、第 2 **同 case 重複 name 或僅空白字元 name**（schema 合法）→ `errors` 非空、`duplicates` 空、DB 0 筆。
  - Schema：缺 `value` 或 `id: 1`（number）→ **HTTP 422**、DB 0 筆。
- **Rationale**：反映 Pydantic 邊界 + 保全 UI 對 `duplicates` 的依賴。
- **Alternatives**：統一只回 `errors` → 拒絕（破壞 bulk.js Conflict 流程）。

### 3. Bulk Clone 複製 `test_data_json`

- **Decision**：在 `run_bulk_clone_sync` 建立新列時，`test_data_json=src.test_data_json`（字串淺層複製即可；內容等價）。來源為 null/空則新列同為 null/空。
- **不**在 clone 路徑強制 re-normalize（避免舊資料因嚴格化而 clone 失敗）；資料已在寫入時 normalize 過。
- **Rationale**：最小改動、JWT/app-token 同時修復。
- **Alternatives**：clone 時 regenerate 每個 id → 可選優化，非必須；本版保留 id。

### 4. Export 契約：保真、不改欄序、明確空值／異常語意

- **Decision**：
  - 欄位清單維持 `TEST_CASE_SET_CSV_COLUMNS`（含 `test_data`）；**不**改欄名順序。
  - 含 `category=credential` 且陣列有資料時 **value 原樣匯出**（備份/搬移保真）。
  - UI/文件警告 export 可能含敏感資料。
  - **`test_data` 儲存格對 DB `test_data_json` 的映射**（本 change 調整 helper，不再「原樣透傳」畸形字串）：

    | DB `test_data_json` | Export cell |
    |---------------------|-------------|
    | `null` | `""` |
    | `""` 或僅空白 | `""` |
    | 可解析且為 **空陣列** `[]` | `""` |
    | 可解析且為 **非空陣列**，且通過**共用可 round-trip 判定** | compact JSON 陣列 |
    | 可解析且為 **非空陣列**，但未通過判定 | `""` |
    | 可解析但 **非陣列** | `""` |
    | **無法解析**（malformed） | `""` |

- **共用可 round-trip 判定**（export helper 與前端第 8 欄**同一規則**）＝ schema 型別 + **完整 `normalize_test_data_items` 穩定性**：
  - **型別**：object 元素；string `name`；string `value`（可 `""`）；`id` 省略/`null`/string；`category` 省略/`null`/`""`/合法 enum（case-insensitive）；未知 category 非法。
  - **清單**：長度 ≤ **100**。
  - **穩定 name/value**：對每項跑與 server 相同清洗後，結果必須 **等於** 原始 name/value（已是 canonical 字面）：
    - name：去 C0（同 server）、去 bidi、`\n`/`\r` 清洗、strip；非空；≤ **500** 字。
    - value：僅去 `\x00`；≤ **100_000** 字。
  - **name 唯一**（case-sensitive，以穩定後＝原始 name 計）。
  - 等價實作：構建 `TestDataItem` 列表 → `normalize_test_data_items` 成功，且每項 `name`/`value` 與 normalize 輸出字面相同；否則整格 `""` / 前端行錯誤。
- **Category 正規化**（唯一允許的非字面等價欄位）：omit/`null`/`""` → `text`；合法 enum 任意大小寫 → 小寫 canonical。
- **Round-trip 保證**（僅非空 export cell）：第 8 欄可接受 + bulk_create **成功**；寫入後 **name/value 字面等價**；**category 正規化後等價**；`id` 可重發。會被 normalize 拒或改寫的 legacy 資料不得以非空 cell 出現。
- **與現況差異（刻意）**：不再用寬鬆 `_csv_json_cell` 透傳髒 JSON。
- **Rationale**：強 round-trip 必須涵蓋完整 normalize，否則「可 export 卻寫入失敗或 value 被改」會破契約。
- **Alternatives**：縮小 round-trip 只保證「已 normalize 過的標準資料」並允許髒資料仍 export → 較弱；本版選方案 1（嚴格判定）。

### 5. Export 與 Bulk Create 的對齊邊界

- **Decision**：**僅** `test_data` JSON 形狀對齊；**不**讓 Export 整列成為 Bulk Create 輸入。
- **使用者旅程**：
  1. Bulk Create：貼 CSV（可選第 8 欄 JSON）→ 解析 → 衝突檢查 → 預覽（test_data 摘要、credential 遮罩）→ 確認 → bulk_create。
  2. Export：Set 列表/管理 → Export CSV → 取得含 test_data 的備份檔。
  3. Clone：選 cases → bulk clone → 新 case 帶 test_data。
- **資料持久化邊界**：全部寫入 main DB `test_cases.test_data_json`；不寫 audit DB 的明文 credential；不寫 run item snapshot（仍即時讀 case）。

### 6. 前端解析與預覽

- **Decision**：
  - `columns.length > 8` → too_many_columns。
  - 第 8 欄空白 → 無 test_data。
  - 第 8 欄非空：`JSON.parse` 成功且結果為 **array**；否則該行 error。
  - 第 8 欄整份陣列必須通過 design §4「共用可 round-trip 判定」（型別 + ≤100 + name/value 已穩定 + name 唯一 + 等價 normalize 成功）；`id: 1`、未知 category、缺 value、超長、null byte、清洗後重複 name 等 → 該行 error。
  - **預覽 category 顯示**（與 §4 Category 正規化一致）：
    - 鍵省略、`null`、`""` → 顯示 **`text`**
    - 合法 enum 任意大小寫 → 顯示 **小寫 canonical**（`Email` → `email`）
    - 未知 / 未通過判定 → 該行已 error，不進入預覽成功路徑
  - 送 API 時可省略 category（server 視為 `text`）；若帶 enum，大小寫不限，server 存 canonical。
  - 預覽欄：例如 `user (text), pwd (credential)`；credential **不**顯示明文 value。
  - 送 API 前 **不得** 對 test_data JSON / 其 value 套用正文用的 `\\n` → `\n` 轉換；正文欄位維持現有轉換。
- **Rationale**：與 export 同一嚴格判定，避免「預覽過、API normalize 拒」或 name/value 被清洗後與使用者貼上字面不一致。

### 7. Audit

- **Decision**：bulk_create audit `details` 不包含完整 test_data value；最多記每筆 `test_data_count` 或 redacted names。bulk_clone 同理若日後擴 details。
- **Rationale**：credential 已有 redact helper，必須用於 mutation audit 路徑。

### 8. 文件與 sample

- 更新三語系 `bulkText.help` / `placeholder`、sample CSV 至少一列示範第 8 欄。
- manual 同步格式：`編號,標題,前置條件,步驟,預期結果,TCG,優先級[,test_data_json]`。

## Risks / Trade-offs

| Risk | Mitigation |
|------|------------|
| Excel 破壞 JSON 引號 | sample + 明確錯誤列號；help 強調雙引號包住 JSON |
| Credential 經 CSV/clipboard 外洩 | 預覽遮罩、audit redact、export/import 文件警告 |
| 超大 test_data 撐爆 body | 沿用 normalize 單筆上限；必要時錯誤訊息提示 |
| 未知 category 被 coerce 成 text | 沿用既有 validator；文件列合法 enum |
| Clone 複製舊格式 JSON | 不 re-normalize；讀路徑已寬鬆解析 |
| 使用者誤把 export 整列貼進 bulk | help 明確「不可整列 round-trip」 |

## Migration Plan

1. 部署 API + 前端 + 文件（無 migration）。
2. 既有 7 欄 bulk 腳本無需改。
3. **Rollback**：還原程式與文件；已寫入 test_data 保留。
4. **驗證**：`uv run pytest` 針對 bulk_create / bulk_clone / export-csv；`node --check` bulk.js；i18n coverage 若動 key。

## Open Questions

- 無阻塞決策。若產品日後要「Export CSV 一鍵 re-import」，另開 change 對齊欄序或新增 import 模式。
