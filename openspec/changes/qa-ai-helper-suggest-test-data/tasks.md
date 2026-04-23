## 1. Prompt Templates

- [ ] 1.1 更新 `prompts/jira_testcase_helper/seed.md`：輸出 schema 新增 `test_data_suggestions: [{category, name}]`（id 由後端補），列出 9 類 category 定義與 1–2 句說明、few-shot 正例/反例各一；明列「不確定則輸出 `[]`」嚴格條款
- [ ] 1.2 更新 `prompts/jira_testcase_helper/testcase.md`：input `generation_items` 新增 `test_data_suggestions` 欄位；output schema 新增 `test_data: [{category, name, value}]`；列出嚴格 value 規則（含 credential 強制空字串）與 few-shot 正例/反例

## 2. Backend Models & Normalize

- [ ] 2.1 `app/models/qa_ai_helper.py`：擴充 seed body / testcase draft body 的 Pydantic 結構（或保留 Dict[str, Any] 並於 service 層 normalize）
- [ ] 2.2 `app/services/qa_ai_helper_service.py::_normalize_seed_output()`：解析 LLM 輸出的 `test_data_suggestions`，容錯缺失 / 型別錯誤為 `[]`，為每筆補上 UUID `id`，過濾 category 不在 enum 的項目
- [ ] 2.3 `_testcase_generation_items_from_seed_set()`：從 `seed_body_json.test_data_suggestions` 取出建議並注入 generation_items payload
- [ ] 2.4 `_normalize_testcase_output()`：解析 `test_data`，容錯 fallback 為 `[]`，強制 `category == "credential"` 時 value 為空字串，為每筆補上 UUID `id`

## 3. Backend API

- [ ] 3.1 `app/api/qa_ai_helper.py` seed review update endpoint：payload 擴充 `test_data_suggestions: List[{id, category, name}]`，整批覆蓋 `seed_body_json.test_data_suggestions`
- [ ] 3.2 Testcase draft update endpoint：payload 擴充 `test_data`，整批覆蓋 draft `body_json.test_data`
- [ ] 3.3 Commit 流程：將 draft 的 `test_data` 寫入目標 test case `test_data_json`
- [ ] 3.4 舊 seed / draft 讀取時 fallback 為空陣列

## 4. Frontend - Seed Review (Screen 4)

- [ ] 4.1 `app/static/js/qa-ai-helper/main.js` 於 seed 卡片下方新增「Test Data Suggestions」摺疊區
- [ ] 4.2 每筆建議列：category `<select>`（9 類）+ name `<input>` + 刪除 icon；底部「+ 新增建議」按鈕
- [ ] 4.3 使用者變更時觸發 seed item update API（debounce 或 blur）
- [ ] 4.4 Seed set locked / 使用者無編輯權限時控制項 readonly

## 5. Frontend - Testcase Draft Editor (Screen 5)

- [ ] 5.1 Draft 編輯器 test_data 區塊：復用 `buildTestDataValueEditor` 或同構 per-category 編輯器
- [ ] 5.2 支援新增 / 刪除列、編輯 category / name / value
- [ ] 5.3 儲存 draft 時 payload 帶入 `test_data`

## 6. Frontend - Test Run Execution

- [ ] 6.1 確認 `app/static/js/test-run-execution/render.js` 的空 value warning icon 能正確覆蓋 AI 產出路徑（理應已覆蓋，僅驗證）

## 7. i18n

- [ ] 7.1 `app/static/locales/{en-US,zh-TW,zh-CN}.json`：新增 seed review 建議區塊文案（標題、新增建議、刪除、空狀態、category 對應已有 key 可復用）
- [ ] 7.2 新增 testcase draft 編輯器 test_data 區塊文案（可復用 test case management 的 key）
- [ ] 7.3 新增/確認 `testRun.testDataValueMissing`（已於前一 change 加入）

## 8. Testing

- [ ] 8.1 `app/testsuite` 新增 seed normalize 測試：輸入含 / 不含 / malformed `test_data_suggestions`，驗證 fallback 與 UUID 補入
- [ ] 8.2 新增 testcase normalize 測試：credential 強制空 value、unknown category 過濾、value 嚴格規則
- [ ] 8.3 新增 seed review update API 測試：覆蓋 add / edit / delete
- [ ] 8.4 手動 E2E：以一筆真實需求跑完 seed → review → testcase → commit → test run 執行，驗證流程串接

## 9. Documentation

- [ ] 9.1 於 `design.md` Open Questions 的結論若於實作中有定案，回寫至 design.md 或於 proposal.md 補註
- [ ] 9.2 完成後執行 openspec archive
