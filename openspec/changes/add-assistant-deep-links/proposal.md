## Why

AI Assistant 成功建立 test case、test case set、test run (config)、test run set 後，使用者無法直接從助手回覆跳轉到對應頁面，必須手動在系統中搜尋新建的資源。這降低了助手作為操作入口的實用性。在助手文字回覆中提供可點擊的 markdown 連結，讓使用者一鍵導航到新建資源，是提升助手體驗的關鍵一步。

## What Changes

- 新增 `app/services/assistant/deep_links.py`：server-generated deep link 構建模組，根據 tool name 與 result/arguments 中的 ID，以固定 URL 模板產生前端頁面相對路徑。
- 修改 create 類工具的 `projection` allowlist，追加 `_deep_links` 欄位宣告，使其合法進入 LLM context。
- 在 `conversation_service` 的 `append_tool_call_and_result` 與 `finalize_confirm_outcome` 中，於 `json.dumps` 前將 `build_deep_links()` 結果注入 tool result payload。
- 修改 `prompts/assistant/system.md`：在「路徑總結」段落指示 LLM 使用 `_deep_links` 生成 markdown 連結，禁止自行編造 URL。
- 前端 `test-run-management/init.js` 新增 `?set_id=` query param 解析，自動開啟 Test Run Set detail modal。
- 修改 `assistant-data-boundary` spec：放寬 projection allowlist，允許 server-generated 導航欄位經宣告後進入 tool result。
- 修改 `assistant-agent-loop` spec：在路徑總結 requirement 中補充 `_deep_links` 連結行為。

## Capabilities

### New Capabilities

（無新 capability）

### Modified Capabilities

- `assistant-data-boundary`: 放寬 projection allowlist 規則，允許 server-generated `_deep_links` 導航欄位經宣告後進入 tool result payload 與 LLM context。
- `assistant-agent-loop`: 路徑總結 requirement 補充：當 tool result 含 `_deep_links` 時，LLM 必須在總結中附 markdown 連結，URL 取自 `_deep_links`，禁止自行編造。

## Impact

- **程式碼**：`app/services/assistant/deep_links.py`（新增）、`app/services/assistant/conversation_service.py`（注入點）、`app/services/assistant/tools_test_cases.py` / `tools_test_case_sets.py` / `tools_test_runs.py`（projection allowlist）、`prompts/assistant/system.md`、`app/static/js/test-run-management/init.js`。
- **Spec**：`assistant-data-boundary`、`assistant-agent-loop` delta specs。
- **API contract**：tool result payload 新增 `_deep_links` 欄位（僅 create 類工具），不影響 API endpoint 本身的 response schema。
- **安全**：`_deep_links` 由 server 固定模板產生，ID 經 `int()` / `urllib.parse.quote` 驗證；前端 DOMPurify 阻擋 `javascript:` scheme。
- **資料庫**：無 schema 變更。
- **i18n**：不需要新 UI 文案（連結文字由 LLM 生成）。