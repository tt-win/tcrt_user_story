## Why

Test case 現已支援 `test_data` 欄位（name/value 結構），但 QA AI Helper 產生的 testcase drafts 並未輸出 test_data，使用者需要在執行前逐張 case 手動回想「這張要準備什麼輸入資料」。AI 擅長從需求文字推斷需要哪些輸入欄位，但不擅長（且不該）捏造具體值（帳號、PII、環境相依資料）。因此我們只讓 AI 建議欄位名稱（name），value 一律留空由使用者填入，既利用 AI 的結構推斷能力，又避免幻覺與合規風險。

## What Changes

- QA AI Helper 的 testcase generation JSON contract 新增選填欄位 `test_data: [{name: string}]`
  - 允許空陣列；當需求文字無明確輸入資料時 AI SHALL 回傳空陣列而非硬湊
  - `name` 使用 snake_case 英文、單一 case 內不得重複
  - 每筆建議 value 後端一律存為空字串（即使 AI 回傳 value 也忽略）
- Screen 5 testcase draft 編輯器加入 test_data 列表編輯區（可新增 / 刪除 / 改 name；value 欄位為 placeholder 「請填入測試資料」的純顯示文字框）
- Commit 時將 `test_data` 一併寫入既有 test case `test_data_json` 欄位，沿用先前 change `add-test-data-crud` 的儲存格式
- Test Run 執行頁對空 value 的 test_data 顯示 warning icon（提醒使用者執行前補齊），不阻擋執行
- Prompt 明確指示：只列「需要使用者準備、且非環境常數」的輸入；允許空陣列；不得輸出 value；欄位名稱用 snake_case

非目標：
- 不產生 test_data value（包含 mock 值、範例值）
- 不做欄位命名字典 / 團隊標準化（後續可另立 change）
- 不在儲存 test case 時強制 value 必填（僅 soft warning）

## Capabilities

### New Capabilities
（無，沿用既有 capabilities）

### Modified Capabilities
- `helper-final-generation-contract`: testcase generation 輸出新增選填 `test_data` 欄位契約與空 value 規則
- `test-case-editor-ai-assist`: screen 5 draft 編輯器須支援 test_data 列表的增刪與 name 編輯
- `test-run-execution-ui`: 空 value 的 test_data 顯示 warning icon 提醒補齊

## Impact

- 程式：
  - `app/services/qa_ai_helper_prompt_service.py`：prompt 與 JSON schema 擴充
  - `app/services/qa_ai_helper_*.py`：testcase draft 結構、commit 流程需帶入 test_data
  - `app/static/js/qa-ai-helper/main.js`：screen 5 draft 編輯器 UI、send payload
  - `app/static/js/test-run-execution/render.js`：空 value warning icon
  - i18n locale 檔案：新增提示字串
- API：testcase draft 建立 / 送出的 payload schema 新增 `test_data` 欄位
- 資料：沿用既有 `test_cases.test_data_json`，無 migration
- AI 成本：每筆 case 輸出多一段小型 JSON，token 增量可控；需關注 JSON parse 失敗率
- 相容性：新增欄位為選填，舊 draft、舊 prompt template 可直接相容
