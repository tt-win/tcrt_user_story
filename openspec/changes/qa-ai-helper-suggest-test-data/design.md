## Context

QA AI Helper 的生成流程為兩段 LLM pass：

- **Pass 1（seed）**：`app/services/qa_ai_helper_service.py::generate_seed_set()` 以 `prompts/jira_testcase_helper/seed.md` 產生 seeds，每個 seed 存入 `qa_ai_helper_seed_items.seed_body_json`（目前結構為 `{text: string}`）。
- **Pass 2（testcase）**：`generate_testcase_draft_set()` 以 `prompts/jira_testcase_helper/testcase.md`，將 seed 的 `seed_body_json` 與相關 hint 組成 `generation_items`，產出 testcase drafts 寫入 `qa_ai_helper_testcase_drafts.body_json`（目前含 `title/priority/preconditions/steps/expected_results`）。

Test case 本身已於先前 change `add-test-data-crud`（已 archive 於 2026-04-23）支援 `test_data_json`（`[{id, category, name, value}]`，9 類 category）。

本 change 的目標：把 test_data 資訊注入這兩段 pass，並在 seed review（screen 4）加上使用者編輯能力，讓 Pass 2 可以取得「AI + 使用者共同確認過」的建議骨架。

## Goals / Non-Goals

**Goals**
- Seed 層輸出 `test_data_suggestions: [{id, category, name}]`，嚴格標準下允許空陣列
- Seed review UI 支援逐筆增刪改
- Testcase 層以 seed 建議為骨架輸出 `test_data: [{id, category, name, value}]`，嚴格標準下 value 可留空
- Credential 類 value 一律空字串（安全基線）
- 沿用 `app/static/js/common/test-data-utils.js` 的 per-category UI

**Non-Goals**
- 不做欄位命名字典或團隊標準化
- 不對使用者自行新增的建議做 AI 再建議
- 不新增資料庫欄位或獨立資料表
- 不改變既有 seed 生成的其他輸出結構（`coverage_tags`、`seed_summary` 等）

## Decisions

### 1. 儲存位置：巢狀於 `seed_body_json`

- **Rationale**：seed items 是過渡資料，不會有查詢或分析需求；nested 可避免 migration，實作最小化
- **結構**：
  ```json
  {
    "text": "原本的自然語言 body",
    "test_data_suggestions": [
      {"id": "uuid-1", "category": "email", "name": "登入帳號"},
      {"id": "uuid-2", "category": "number", "name": "密碼長度上限"}
    ]
  }
  ```
- **Alternatives considered**：獨立欄位 `test_data_suggestions_json` — 拒絕，因為 seed 是過渡資料、無查詢需求，migration 屬於不必要的成本
- **Fallback**：讀取時若 `seed_body_json` 無 `test_data_suggestions` key → 回傳空陣列

### 2. Seed-level 嚴格產生條件

Prompt 明確要求：

**允許建議**（category / name）
- Spec 明確指出需要輸入或參考的欄位：如帳號、密碼、email、URL、日期、JSON payload、boundary 值的目標欄位
- 邊界 / 例外 case 指向的欄位：如「密碼長度 ≥ 8」→ 建議 `{credential, 登入帳號}` 與 `{number, 密碼長度}`

**禁止建議**（回傳空陣列或略過該筆）
- 不涉及輸入資料的 case（純 UI 顯示驗證、純檢視流程）
- spec 未提及具體欄位的籠統 case
- 系統 constant / 環境變數（不屬於測試輸入資料）

### 3. Testcase-level 嚴格 value 產生條件

**允許填 value**
- 需求/seed 明確指出邊界值或 magic number：`{number, 密碼長度}` + spec「上限 8」→ `value="12345678"` 或 `"123456789"`
- Spec 給定的 URL / endpoint / 錯誤碼 / 測試帳號（明示為公用 fixture）
- 明確的 enum 值（如「狀態必須是 APPROVED」）

**強制留空字串**
- `category == "credential"`：任何情況下 value 都是空字串（password 不得由 LLM 產生）
- PII：姓名、身分證、電話、地址、email（即使是虛構的也不填）
- 環境相依：production URL、部署相關識別碼、session id
- 無 spec 支撐的猜測值

Prompt 的嚴格條款會以「若不確定，value 一律留空」作為保底。

### 4. Seed review 使用者編輯

- `app/api/qa_ai_helper.py` 的 seed item update endpoint（`update_seed_item_review()`）payload 擴充 `test_data_suggestions: List[{id, category, name}]`
- 送出時整批覆蓋 `seed_body_json.test_data_suggestions`，不做 per-item diff
- 無編輯權限或 seed set 已 lock 時，UI 區塊為 readonly（沿用現有 pattern）
- 使用者新增的建議標記為 user-added（前端用 UUID 生成 id 即可，後端不另存 flag——反正 Pass 2 一律以最終陣列內容為準）

### 5. Pass 2 `generation_items` 注入

`_testcase_generation_items_from_seed_set()` 產出的 `generation_items` 每筆增加 `test_data_suggestions` 欄位，直接從 `seed_body_json` 取；Pass 2 prompt template 中以此為骨架要求輸出 `test_data`。

### 6. Category enum 對齊

9 類 category 與 `app/models/test_case.py::TestDataCategory` 完全一致：
`text | number | credential | email | url | identifier | date | json | other`

Prompt template 會附上每類的一句話定義與範例，避免 LLM 誤用（特別是 credential vs text、identifier vs text 的區分）。

### 7. UI 復用

- Screen 4（seed review）新區塊用原生 `<select>` + `<input>` + 刪除 icon，不套用 `buildTestDataValueEditor` 的完整 per-category 編輯器（因 seed 層無 value）
- Screen 5（testcase draft 編輯器）test_data 列表：復用 `buildTestDataValueEditor` 或同構實作，讓 draft 編輯體驗與 test case detail 一致

### 8. 向後相容

- 舊 seed 的 `seed_body_json` 無 `test_data_suggestions` → 解析時填 `[]`
- 舊 testcase draft 的 `body_json` 無 `test_data` → 解析時填 `[]`
- Commit 時 `test_data` 為空則不寫入 `test_data_json`（或寫入 `[]`，與既有行為一致即可）

## Risks / Trade-offs

- **LLM JSON 解析失敗率**：多一層巢狀結構，可能提高 Pass 1 JSON parse 錯誤率。對策：normalize 層對 `test_data_suggestions` 缺失或 malformed 時 fallback 為 `[]`，不中斷整個 seed 產生
- **Category 誤用**：LLM 可能把 password 標成 text。對策：prompt 中給明確對照表，加 few-shot；credential 強制 value 空字串也是第二道防線
- **使用者編輯 + 重新產生 seed 的衝突**：若使用者修改了 `test_data_suggestions` 後又觸發 seed refine，refine 結果會覆蓋使用者修改。對策：維持現有 refine 行為（seed 是 regenerable，使用者已知風險），不在本 change 內處理 merge。後續若問題明顯可另立 change。
- **Prompt token 增量**：9 類定義 + few-shot 約增加 ~500 token。對 seed stage 使用的高階模型成本可接受
- **credential 特例與使用者期待衝突**：使用者若真的希望 AI 給 sample password，會拿到空字串。以安全基線為優先，UI tooltip 會說明理由

## Migration Plan

- 無 DB migration
- 前端對 seed / testcase 物件的讀取路徑全部加 fallback
- Prompt 改版：seed.md / testcase.md 直接更新，不保留舊版（舊 session 已完成的 seed 不會再觸發新 prompt）

## Open Questions

1. 使用者在 seed review 新增的建議是否要視覺上區分（icon/顏色）AI 產出 vs 使用者手動？目前傾向不區分（減少認知負擔），但留待實作階段依 UI 負擔度調整
2. Testcase draft 重新產生時，test_data 使用者編輯會被覆蓋——是否需要 per-field 保留？目前範圍內不處理（與其它 draft 欄位規則一致）
