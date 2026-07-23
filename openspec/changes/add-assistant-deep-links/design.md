## Context

AI Assistant 的 tool result payload 經 `project_and_redact()` 投影後，以 `json.dumps` 寫入 `assistant_messages`（`role="tool"` content），再由 `history_builder` 讀出送往 LLM。現狀 projection allowlist 不含任何 URL/連結欄位。

前端 `assistant-widget.js` 已支援 markdown 渲染（marked@4.3.0 + DOMPurify），`<a>` 標籤自動加 `target="_blank"`。DOMPurify 預設阻擋 `javascript:` scheme。

前端路由：test case → `/test-case-management?set_id={id}&tc={num}`；test case set → 同上（無 set_id 時列表頁）；test run config → `/test-run-execution?config_id={id}`；test run set → `/test-run-management`（modal，需新增 `?set_id=` 支援）。

## Goals / Non-Goals

**Goals:** 建立 test case/set/run/run-set 後，LLM 文字回覆含可點擊 markdown 連結；查詢結果也同樣輸出連結。

**Non-Goals:** 不在 tool step 圖示旁加連結按鈕（方案 C）；不處理 `batch_execute_actions` 中的 child create deep link；不修改 API endpoint response schema。

## Design

### deep_links.py

靜態規則表 `_LINK_RULES`：`tool_name → (link_key, url_template, source, id_field)`。`build_deep_links(tool_name, result_payload, tool_arguments)` 回傳 `dict[str, str]`。ID 做 `int()` 或 `str()` + `urllib.parse.quote()`。失敗回空 dict。`build_list_deep_links(tool_name, result_payload)` 對 list 或 `{items: [...]}` 結果的每個 item 注入 `_deep_links`。

### Projection allowlist

在 `tools_test_cases.py`、`tools_test_case_sets.py`、`tools_test_runs.py` 中，create 與 get/list 類工具的 `projection` tuple 追加 `"_deep_links"`。`apply_projection()` 不會從 API response 生成此欄位（它不存在於 response），但 allowlist 宣告使其合法存在於 result payload。

### 注入點

在 `conversation_service.append_tool_call_and_result()`（read 路徑）和 `finalize_confirm_outcome()`（confirm write 路徑）中，`json.dumps(tool_result_payload)` 之前注入 `_deep_links`。

- `append_tool_call_and_result` 已有 `arguments_for_history` 參數，可用於 `tool_arguments`（`bulk_create` 需要 `test_case_set_id`）。
- `finalize_confirm_outcome` 從 `run_confirm_turn` 傳入 `execution_payload.body_params` 作為 `tool_arguments`。

### System prompt

在 `prompts/assistant/system.md` 新增獨立段落「工具結果含 `_deep_links` 時的連結規則（必做，不得遺漏）」，明確要求無論 create/get/list，只要 result 含 `_deep_links` 就必須輸出 `[名稱](url)` markdown 連結，並給出具體正確/錯誤範例。

### 前端 Test Run Set 深連

`app/static/js/test-run-management/init.js`：頁面載入且 set 列表 render 完成後，讀取 `URLSearchParams.get('set_id')`，若有效則自動開啟 set detail modal。

### 前端 Markdown 渲染

`app/static/js/assistant-widget.js` 在載入 marked 後設定 `gfm: true, breaks: true`，並在 `setAssistantText` 等待 libs 載入完成後重新 render，避免初次顯示為純文字。

### History compaction 保留 `_deep_links`

`app/services/assistant/history_builder.py` 的 `_struct_compact_tool_content` 在壓縮 list、`{items: [...]}`、單筆 dict 結果時，保留 `_deep_links` 採樣，避免長對話中連結資訊遺失。

### 部署與 prompt 同步

Runtime system prompt 從 DB (`AssistantPromptDocument`) 讀取，而非直接讀檔。`ensure_seeded()` 僅在 DB 缺少資料時插入 factory prompt，不會自動覆蓋既有資料。因此部署後必須由 Super Admin 執行：

- 組織管理頁面 → Assistant Admin → 「還原 factory（overwrite builtins）」，或
- `POST /api/admin/assistant/restore {"mode":"overwrite-builtins","confirm":true}`

**風險**：`overwrite-builtins` 會覆蓋 system prompt 與所有 builtin skill 的內容，並保留 `is_enabled` 旗標；若組織曾自訂 system prompt，將被 factory 版本覆蓋。如要保留自訂內容，請在 restore 前匯出或改用手動貼上連結規則。

### 殘餘風險

- LLM 回覆失敗 → 連結消失（tool success 圖示仍為權威來源）
- LLM 自行編造 URL → 最多 404，DOMPurify 阻擋 XSS
- `batch_execute_actions` child create → 不生成 `_deep_links`（後續可擴充）

## Architecture Diagram

```
tool result (API response)
    ↓ project_and_redact() — projection allowlist now includes "_deep_links"
    ↓ json.dumps() 前注入 build_deep_links() / build_list_deep_links() 結果
    ↓ assistant_messages (role=tool, content=JSON)
    ↓ history_builder → LLM context (compaction preserves _deep_links sample)
    ↓ LLM 生成 markdown 連結
    ↓ SSE text_delta → assistant-widget.js renderMarkdown() → <a> (same-tab navigation)
```

## 附件上傳與建立 Test Case 的組合流程（選項 A）

### 問題
使用者在 assistant 中上傳附件後呼叫 `create_test_case`，工具無 `temp_upload_id` 欄位，附件無法在建立時帶入。

### 解決方案
1. **Schema 擴充**：`create_test_case` 的 `body_schema` 新增 `temp_upload_id` 欄位（可選 string）。
2. **Auto-staging**：`assistant_agent_service._run_llm_loop` 在 tool call 為 `create_test_case` 時，自動把 `temp_upload_id` 注入 `call.arguments`（若 LLM 未顯式提供）。
3. **Staging helper**：`attachment_storage.py` 新增 `staging_dir()` 與 `stage_assistant_attachments()` helper，把 assistant 暫存附件複製到 TCRT staging 目錄。
4. **System prompt**：新增附件指示，告知 LLM 使用 `create_test_case` 時系統會自動處理附件。

### 流程
```
使用者上傳附件 → assistant 暫存 (conversation_id/turn_id/attachment_index)
    ↓ LLM 呼叫 create_test_case (body 含 temp_upload_id)
    ↓ _run_llm_loop 偵測到 temp_upload_id，自動 staging
    ↓ create_test_case API 收到 temp_upload_id，複製附件到 staging
    ↓ confirm 執行時，附件從 staging 轉為 TCRT 附件
```