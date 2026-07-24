# assistant-agent-loop Delta — extend-assistant-deep-links-global

## ADDED Requirements

### Requirement: global/knowledge 工具含 `_deep_links` 時 MUST 輸出可點擊連結

SHALL 在 `add-assistant-deep-links` delta 已建立的 general requirement「查詢與建立結果含 `_deep_links` 時必須輸出可點擊連結」之下，增加以下 global/knowledge 工具專屬 scenario 以預防回歸。

#### Scenario: get_test_case_global 查詢後回覆含連結
- **WHEN** 使用者詢問「有沒有 TCG-114460.030.060 這個 case」，助手透過 `get_test_case_global` 取得結果，tool result 含 `_deep_links: {"test_case": "/test-case-management?set_id=63&tc=TCG-114460.030.060"}`
- **THEN** LLM 在回覆中附上 markdown 連結，例如「有的，[這個 case](/test-case-management?set_id=63&tc=TCG-114460.030.060) 在 Team-A。」

#### Scenario: search_test_cases_global 結果中為提及項目附連結
- **WHEN** 使用者要求「搜尋登入相關的 cases」，助手透過 `search_test_cases_global` 取得結果列表，每個結果 item 含 `_deep_links`
- **THEN** LLM 只為實際提及的項目附上連結，例如「找到 3 筆 case，例如 [登入流程](url)。」

#### Scenario: search_knowledge 結果中僅 test_case 實體附連結
- **WHEN** 使用者查詢「什麼團隊負責登入功能」，助手透過 `search_knowledge` 取得結果，其中包含 test_case 實體（含 `_deep_links`）與 USM node / Jira ticket 實體（不含 `_deep_links`）
- **THEN** LLM 只在提及 test_case 實體時附上 markdown 連結；非 test_case 實體無連結，LLM 不自行編造

#### Scenario: search_knowledge 結果中無 test_case 實體時不輸出連結
- **WHEN** `search_knowledge` 只回傳 USM node 或 Jira ticket 實體
- **THEN** LLM 回覆中不出現任何 markdown 連結（因所有 items 皆不含 `_deep_links`）

#### Scenario: search_test_cases_global 回傳無 set_id 的孤立 case 時不產生連結
- **WHEN** `search_test_cases_global` 結果中某一筆 `test_case_number` 存在但 `set_id` 為 NULL
- **THEN** 該 item 不產生 `_deep_links`；LLM 仍可依 `test_case_number` 告知使用者該 case 存在但屬於孤立資料，無法直接導航
