## Why

Test case 已支援結構化 `test_data`（`{id, category, name, value}`，9 類 category），但 QA AI Helper 產出的 seed 與 testcase draft 尚未將測試資料納入生成契約。使用者需在執行前逐張 case 手動回想「這張要準備什麼輸入資料」，也無法在 seed review 階段就看見 AI 建議哪些欄位、分類為何。

AI 擅長從需求文字推斷「需要哪些輸入欄位」，但不擅長（且不該）捏造沒有 spec 支撐的具體值（真實帳號、PII、環境相依 URL、情境化識別碼）。因此本 change 將 test_data 的產生切成兩層：

- **Seed 層（Pass 1）**：LLM 依 seed 性質建議 `{category, name}`（無 value），使用者在 seed review 可增、刪、編輯這些建議。
- **Testcase 層（Pass 2）**：LLM 以 seed 上的建議為骨架，只在需求/seed 有明確值（邊界、帳號、API URL、錯誤碼…）時填 `value`；否則留空由使用者於執行前補齊。credential 類一律留空。

嚴格標準：無明確 spec → 不產生建議；無明確值 → 不填 value。AI 寧可少產也不亂產。

## What Changes

### Seed 生成（Pass 1）

- Seed JSON schema 於 `seed_body_json` 內新增 key `test_data_suggestions: [{id, category, name}]`
  - `category` 為 9 類固定 enum：`text | number | credential | email | url | identifier | date | json | other`
  - `name` 簡短描述欄位角色（例：`登入帳號`、`密碼長度上限`、`API endpoint`）
  - 允許空陣列；spec 不明確或不需要輸入資料時 SHALL 回傳空陣列
  - `id` 由後端於儲存時補上（client / user 新增時也必須具備）
- Prompt 明列 9 類 category 定義與嚴格條款、few-shot 正反例
- 使用者於 seed review（screen 4）可逐筆刪除、編輯（category / name）、新增建議

### Testcase 生成（Pass 2）

- Pass 2 傳給 LLM 的 `generation_items` payload 帶入 seed 上最終的 `test_data_suggestions`（含使用者修改結果）
- Testcase JSON schema 輸出 `test_data: [{id, category, name, value}]`
  - 以 seed 的 `test_data_suggestions` 為骨架（同 category / name）
  - value 嚴格條款：
    - 需求/seed 明確給出邊界值、magic number、spec 帳號/URL/錯誤碼 → 填入
    - 否則 value 為空字串
    - **credential 類 value 一律為空字串**（不論需求是否提供）
  - 使用者於 seed review 新增/修改的建議同樣被 Pass 2 採用
- Commit 時 `test_data` 一併寫入既有 test case `test_data_json`

### UI

- Seed review 卡片（screen 4）內新增「Test Data Suggestions」摺疊區：每筆為 `category 下拉 + name input + 刪除 icon`；底部「+ 新增建議」
- Testcase draft 編輯器（screen 5）test_data 列表改用同一組 per-category UI（復用 `app/static/js/common/test-data-utils.js`）
- Test Run 執行頁：test_data 若 value 為空字串，顯示 warning icon 提示執行前補齊（不阻擋執行；現有 render.js 已實作，僅需確認覆蓋 AI 產出路徑）

## 非目標

- 不建立欄位命名字典 / 團隊標準化
- 不強制儲存時 value 必填
- 不對使用者「自行新增」的建議做 AI 驗證或再建議
- 不在 seed 層輸出 value

## Capabilities

### Modified Capabilities
- `helper-final-generation-contract`: seed 生成契約新增 `test_data_suggestions`、seed review 支援增刪改建議、testcase 生成契約新增 `test_data`（含嚴格 value 規則與 credential 特例）
- `test-case-editor-ai-assist`: screen 5 draft 編輯器 test_data 列表支援 category / name / value 三欄，per-category UI
- `test-run-execution-ui`: test_data 空 value 顯示 warning icon 提示補齊

## Impact

- **程式**：
  - `prompts/jira_testcase_helper/seed.md`、`prompts/jira_testcase_helper/testcase.md`：prompt 與 JSON schema 擴充
  - `app/services/qa_ai_helper_service.py`：seed 輸出 normalize、testcase `generation_items` 注入、testcase 輸出 normalize
  - `app/models/qa_ai_helper.py`：seed / testcase draft Pydantic 欄位擴充
  - `app/api/qa_ai_helper.py`：seed review update endpoint 擴充 payload 以承接 `test_data_suggestions`
  - `app/static/js/qa-ai-helper/main.js`：screen 4 建議編輯 UI、screen 5 test_data 編輯 UI
  - `app/static/js/test-run-execution/render.js`：確認空 value warning 覆蓋 AI 產出路徑
  - i18n：新增建議 / 嚴格標準相關文案
- **API**：seed review update payload 新增 `test_data_suggestions`；testcase draft payload 新增 `test_data`
- **資料**：無 schema 變更。建議巢狀於 `qa_ai_helper_seed_items.seed_body_json`；舊 seed 解析時 fallback 為空陣列
- **AI 成本**：每個 seed 多一段小型 JSON（通常 0–3 筆），token 增量可控
- **相容性**：新欄位皆選填，舊 session / 舊 draft 可直接讀取
