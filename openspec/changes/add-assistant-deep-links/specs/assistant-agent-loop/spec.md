# assistant-agent-loop Delta — add-assistant-deep-links

## MODIFIED Requirements

### Requirement: 建立類操作的路徑總結含可點擊連結
當 create 類工具（`create_test_case`、`create_test_case_set`、`create_test_run_config`、`create_test_run_set`、`restart_test_run`、`bulk_create_test_cases`、`bulk_clone_test_cases`）執行成功且 tool result payload 含 `_deep_links` 欄位時，系統 prompt MUST 指示 LLM 在路徑總結中為每個已建立的資源附上 markdown 連結。連結 URL MUST 直接取自 `_deep_links` 對應值，LLM 不得自行編造、修改或拼接 URL。連結顯示文字使用資源名稱/標題/摘要，不得顯示裸 ID；URL query parameter 中的 ID 不受「回覆中禁止出現 ID」規則限制。

#### Scenario: 建立單一 test case 後回覆含連結
- **WHEN** 使用者透過助手建立一筆 test case，`create_test_case` 執行成功，tool result 含 `_deep_links: {"test_case": "/test-case-management?set_id=5&tc=TC001"}`
- **THEN** LLM 路徑總結中包含 markdown 連結如 `[登入模組的 case](/test-case-management?set_id=5&tc=TC001)`，使用者點擊後跳轉到對應頁面

### Requirement: 查詢與建立結果含 `_deep_links` 時必須輸出可點擊連結
當任何 tool result（含單筆 get、列表 list、create 結果）或其 list item 含 `_deep_links` 欄位時，系統 prompt MUST 指示 LLM 在回覆中為對應資源輸出可點擊 markdown 連結。單筆結果直接附連結；列表結果只為 LLM 實際提及/引用的項目附連結。URL MUST 直接取自 `_deep_links`，LLM 不得自行編造。若 tool result 不含 `_deep_links` 或為空，LLM MUST NOT 輸出任何連結。此規則獨立於「路徑總結」，適用於所有查詢與建立回覆。

`_deep_links` 欄位由 executor 的 `build_deep_links()` / `build_list_deep_links()` 以固定 URL 模板產生，URL 為相對路徑（以 `/` 開頭），識別碼經型別驗證與 URL encoding。前端 markdown 渲染（marked + DOMPurify）已阻擋 `javascript:` 等危險 scheme。

#### Scenario: 查詢單筆 test case 後回覆含連結
- **WHEN** 使用者詢問「有沒有 TCG-114460.030.060 這個 case」，助手透過 `get_test_case` 取得結果，tool result 含 `_deep_links: {"test_case": "/test-case-management?set_id=63&tc=TCG-114460.030.060"}`
- **THEN** LLM 在回覆中附上 markdown 連結，例如「有的，[這個 case](/test-case-management?set_id=63&tc=TCG-114460.030.060) 在系統中。」

#### Scenario: 查詢列表後為提及項目附連結
- **WHEN** 使用者要求「列出登入模組的 test cases」，助手透過 `list_test_cases` 取得結果，每個 item 含 `_deep_links`
- **THEN** LLM 只為實際提及的項目附上連結，不要列出所有項目的連結；例如「找到 3 筆 case，建議從 [登入流程](url) 開始。」

#### Scenario: 工具結果不含 _deep_links 時不輸出連結
- **WHEN** 使用者執行的工具不含 `_deep_links`（例如純統計、外部 URL、無 ID 的 result）
- **THEN** LLM 回覆中不出現任何 markdown 連結

#### Scenario: LLM 回覆失敗時連結不出現但不影響操作結果
- **WHEN** create/get/list 工具執行成功但後續 LLM 回覆為空或錯誤
- **THEN** 使用者仍可從 tool success 狀態圖示或頁面本身得知結果，連結因依賴 LLM 文字而不出現（可接受的殘餘風險）