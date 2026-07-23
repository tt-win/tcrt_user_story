# mcp-read-api Specification

## Purpose
定義 TCRT 對 MCP consumer 提供的唯讀查詢 API，包括 team、test case 與 test run 的統一讀取模型與過濾規則。
## Requirements
### Requirement: MCP Teams Read Endpoint
系統 SHALL 透過 `/api/mcp/teams` 保留 read-only 團隊清單相容端點，並在 `/api/app/teams` 提供正式 app-token 等價 read endpoint。兩者 SHALL 回傳經過清理的欄位與總數資訊；`/api/app/*` SHALL 使用 app-token principal，`/api/mcp/*` SHALL 使用相容 app-token principal。

#### Scenario: Team list returns count and sanitized fields
- **WHEN** machine principal 查詢 `/api/mcp/teams`
- **THEN** 回應包含可公開欄位與總筆數，不暴露不必要的內部資訊

#### Scenario: App namespace returns equivalent team list
- **WHEN** app-token principal 查詢 `/api/app/teams`
- **THEN** 回應 SHALL 與 `/api/mcp/teams` read model 相容

### Requirement: MCP Test Case Set and Test Case Query with Filters
系統 SHALL 支援依 team scope、test case set、ticket / tcg、關鍵字與內容展開等條件查詢 test cases。`/api/mcp/*` SHALL 保留 read-only 相容；`/api/app/*` SHALL 成為正式 app-token read/write namespace，其中 read payload SHALL 與 MCP read model 相容。

#### Scenario: Test case filtering works consistently
- **WHEN** 呼叫 team-scoped test case 查詢端點並帶入支援的篩選條件
- **THEN** 回傳結果與 scope / filter 一致，且未授權資料不會被洩漏

#### Scenario: App namespace supports the same read filters
- **WHEN** app token 呼叫 `/api/app/teams/{team_id}/test-cases` 並帶入 MCP read filters
- **THEN** response SHALL 使用相同 filter 語意與 pagination model

### Requirement: MCP Unified Test Run Read Model
系統 SHALL 提供統一的 test run 讀取模型，涵蓋一般 run、adhoc run 與相關類型資料。`/api/app/*` SHALL 提供正式等價 read endpoint，並另外提供受 app-token scope 控制的 mutation endpoints。

#### Scenario: Unified response includes all three run categories
- **WHEN** 呼叫 team-scoped test run 查詢
- **THEN** 回應使用統一格式呈現各類 run

#### Scenario: Run filters apply to all categories
- **WHEN** 帶入 test run 查詢條件
- **THEN** 系統以一致規則套用到各 run 類型

#### Scenario: App namespace provides equivalent test run read model
- **WHEN** app token 呼叫 `/api/app/teams/{team_id}/test-runs`
- **THEN** response SHALL 與 `/api/mcp/teams/{team_id}/test-runs` read model 相容

### Requirement: Backward Compatibility for Existing APIs
新增 app-token API 與 MCP 相容讀取能力 SHALL 不改變既有 user JWT API 的行為與契約。既有 `/api/mcp/*` read endpoints SHALL 在相容期內保持可用，但正式外部 API 文件 SHALL 以 `/api/app/*` 為 canonical namespace。

#### Scenario: Existing user JWT APIs remain unchanged
- **WHEN** 既有前端或一般使用者 API 呼叫原本端點
- **THEN** 不需配合 MCP 驗證模式而變更

#### Scenario: Existing MCP read clients remain functional
- **WHEN** 既有 `tcrt_mcp` client 在相容期內呼叫 `/api/mcp/*`
- **THEN** read-only request SHALL 繼續回應

#### Scenario: Mutation requires app namespace
- **WHEN** client 對 `/api/mcp/*` 發送 mutation
- **THEN** request SHALL 被拒絕
- **AND** response SHALL 指向 `/api/app/*` mutation API

### Requirement: MCP SHALL Provide Read-Only Test Case Sections Endpoint
系統 SHALL 提供 `GET /api/mcp/teams/{team_id}/test-case-sections` 相容端點，回傳指定 team 範圍內的 test case sections。端點 SHALL 維持唯讀；不接受 POST / PUT / PATCH / DELETE。正式 app-token namespace SHALL 另提供 `/api/app/teams/{team_id}/test-case-sections` 等價 read endpoint，並可在 `/api/app/*` 下提供受 scope 控制的 section mutation endpoints。

#### Scenario: 預設查詢回傳 team 全部 sections
- **WHEN** machine principal 對某 team 呼叫 `GET /api/mcp/teams/{team_id}/test-case-sections` 而不帶任何 query 參數
- **THEN** 回應的 `sections` 包含該 team 所有 set 下的所有 sections，`filters` echo 為 `{set_id: null, set_not_found: false, parent_section_id: null, roots_only: false, include_empty: true}`，`total` 等於 `sections` 長度

#### Scenario: 端點僅支援 GET
- **WHEN** 對 `/api/mcp/teams/{team_id}/test-case-sections` 發出 POST / PUT / DELETE 請求
- **THEN** API 回應 `405 Method Not Allowed` 或 `404`（依 FastAPI router 配置），不執行任何寫入

#### Scenario: 不存在的 team 回 404
- **WHEN** machine principal 對不存在的 `team_id` 呼叫 sections 端點
- **THEN** API 回應 `404` 並指明 `找不到團隊 ID {team_id}`

#### Scenario: 超出 team scope 的請求被拒
- **WHEN** 一個 `team_scope_ids` 不含目標 team 的 machine principal 呼叫該 team 的 sections 端點
- **THEN** API 回應 `403` 並 audit log 記錄 `TEAM_SCOPE_DENIED`

#### Scenario: App namespace section read is equivalent
- **WHEN** app token 呼叫 `/api/app/teams/{team_id}/test-case-sections`
- **THEN** response SHALL 與 MCP section read model 相容

### Requirement: Sections Endpoint SHALL Return Flat List With Tree Reconstruction Metadata
回應的 `sections[i]` 物件 SHALL 為扁平結構，server 端 SHALL NOT 預組 nested children。每筆 SHALL 包含完整的 tree reconstruction metadata：`id`、`test_case_set_id`、`parent_section_id`（root section 為 `null`）、`name`、`description`、`level`（1–5）、`sort_order`、`test_case_count`、`created_at`、`updated_at`。

#### Scenario: 扁平結構，不夾 children
- **WHEN** sections 端點回傳一個含 root section 與其兩個直系子 section 的 set
- **THEN** 回應的 `sections` 為長度 3 的扁平陣列，root section 物件中**不包含** `children` 鍵；消費端可透過 `parent_section_id` 重建樹

#### Scenario: root section 的 parent_section_id 為 null
- **WHEN** 回傳的 section 沒有 parent
- **THEN** 該 item 的 `parent_section_id == null`（不是 `0`、不是省略）

#### Scenario: test_case_count 為直接掛在該 section 的 case 數量（不遞迴）
- **WHEN** root section 「Login」直接掛 12 個 case，其子 section 「Login - SSO」直接掛 5 個 case
- **THEN** 回應中 Login section 的 `test_case_count == 12`（不含 SSO 的 5 個），SSO section 的 `test_case_count == 5`

### Requirement: Sections Endpoint SHALL Support set_id and parent_section_id Filters
端點 SHALL 接受 `set_id: int? = null`、`parent_section_id: int? = null`、`roots_only: bool = false`、`include_empty: bool = true` 四個 query 參數，並將實際接受的值 echo 至回應 `filters` 物件。

#### Scenario: set_id 過濾
- **WHEN** 呼叫 `GET /api/mcp/teams/{team_id}/test-case-sections?set_id=10`
- **THEN** 回應的 `sections` 僅包含 `test_case_set_id == 10` 的 sections，`filters.set_id == 10`

#### Scenario: set_id 不存在於 team
- **WHEN** 呼叫帶 `set_id` 的 sections 端點，該 set 不存在於目標 team
- **THEN** API 回應 `200` 並回傳 `sections: []`、`filters.set_not_found == true`、`total == 0`

#### Scenario: parent_section_id 過濾出直系 children
- **WHEN** 呼叫 `GET /api/mcp/teams/{team_id}/test-case-sections?parent_section_id=88`
- **THEN** 回應僅包含 `parent_section_id == 88` 的 sections（即 88 的直系子 section），不含遞迴後代

#### Scenario: roots_only 過濾出 parent_section_id 為 null 的 sections
- **WHEN** 呼叫 `GET /api/mcp/teams/{team_id}/test-case-sections?roots_only=true`
- **THEN** 回應的 `sections` 僅包含 `parent_section_id IS NULL` 的 root sections

#### Scenario: include_empty=false 排除無 case 的 section
- **WHEN** team 內某 section 直接掛的 case 數為 0，呼叫 `GET /api/mcp/teams/{team_id}/test-case-sections?include_empty=false`
- **THEN** 該 section **不**出現在回應的 `sections` 陣列中

#### Scenario: 多個 filter 同時生效
- **WHEN** 呼叫 `GET /api/mcp/teams/{team_id}/test-case-sections?set_id=10&roots_only=true&include_empty=false`
- **THEN** 回應包含「set 10 內的 root section 且 test_case_count > 0」的 sections，三個條件 AND 套用，`filters` 物件完整 echo 三個參數

### Requirement: Sections Endpoint SHALL Order Results Deterministically
回應的 `sections` 陣列 SHALL 按以下優先序排序：`test_case_set_id ASC, level ASC, sort_order ASC, id ASC`，確保同樣的 query 在同樣的資料下永遠回傳同樣的順序。

#### Scenario: 跨 set 查詢按 set_id 分群
- **WHEN** team 同時有 set 10 與 set 20 的 sections，無 set_id 過濾
- **THEN** 回應的 `sections` 中 set 10 的所有 sections 排在 set 20 的所有 sections 之前

#### Scenario: 同 set 內按 level + sort_order
- **WHEN** set 10 內有 root section A（level=1, sort_order=0）與其子 section B（level=2, sort_order=0）
- **THEN** A 排在 B 之前

#### Scenario: 同 level 同 sort_order 用 id tie-break
- **WHEN** 同 set 同 level 同 sort_order 有兩個 sections（id=5 與 id=12）
- **THEN** id=5 排在 id=12 之前

### Requirement: MCP Test Case Detail SHALL Expose test_data
單筆 test case detail 端點 (`GET /api/mcp/teams/{team_id}/test-cases/{test_case_id}`) SHALL 在回應中包含 `test_data` 陣列；陣列中的每一項 SHALL 完整保留 `id` / `name` / `category` / `value` 四個欄位，不在 server 端做任何 redaction。當 test case 沒有 test_data 時，SHALL 回傳 `[]` 而非 `null`。

#### Scenario: Detail 端點回傳 test_data 陣列
- **WHEN** machine principal 呼叫 `GET /api/mcp/teams/{team_id}/test-cases/{test_case_id}`，且該 test case 已有兩筆 test_data（分別為 `category="text"` 與 `category="credential"`）
- **THEN** 回應 `test_case.test_data` 為長度 2 的陣列，每筆物件包含 `id`、`name`、`category`、`value` 四欄位且 value 未被截斷或遮罩

#### Scenario: 沒有 test_data 的 test case
- **WHEN** machine principal 對一個未設定任何 test_data 的 test case 呼叫 detail 端點
- **THEN** 回應 `test_case.test_data` 為空陣列 `[]`

#### Scenario: 異常 test_data_json 不應導致 500
- **WHEN** DB 中的 `test_data_json` 欄位包含無法解析的 JSON 字串（資料毀損）
- **THEN** 端點 SHALL 回傳 `test_data: []` 而非 500 錯誤

### Requirement: MCP List/Lookup SHALL Support include_test_data Query Parameter
`GET /api/mcp/teams/{team_id}/test-cases` 與 `GET /api/mcp/test-cases/lookup` 端點 SHALL 接受 `include_test_data: bool = false` query param。當為 `true` 時，回應中每筆 test_case payload SHALL 包含 `test_data` 陣列；當為 `false`（預設）或未提供時，回應 SHALL 不包含 `test_data` 欄位以維持向後相容。回應的 `filters` 物件 SHALL 回 echo `include_test_data` 的實際值。

#### Scenario: include_test_data=true 帶出 test_data
- **WHEN** 呼叫 `GET /api/mcp/teams/{team_id}/test-cases?include_test_data=true`
- **THEN** 回應的每筆 `test_cases[i]` 包含 `test_data` 陣列，且 `filters.include_test_data == true`

#### Scenario: 預設不帶 test_data（向後相容）
- **WHEN** 呼叫 `GET /api/mcp/teams/{team_id}/test-cases` 且未提供 `include_test_data`
- **THEN** 回應的 `test_cases[i]` 不包含 `test_data` 鍵，且 `filters.include_test_data == false`

#### Scenario: lookup 端點支援同樣語意
- **WHEN** 呼叫 `GET /api/mcp/test-cases/lookup?test_case_number=TC-A-001&include_test_data=true`
- **THEN** 回應的 `items[i].test_case` 包含 `test_data` 陣列

#### Scenario: include_test_data 與 include_content 解耦
- **WHEN** 呼叫 `GET /api/mcp/teams/{team_id}/test-cases?include_content=true&include_test_data=false`
- **THEN** 回應的 `test_cases[i]` 包含 `precondition` / `steps` / `expected_result` 但不包含 `test_data`

### Requirement: MCP test_data Payload SHALL Preserve Category Without Server-Side Redaction
所有 MCP 端點回傳的 `test_data[i]` 物件 SHALL 完整保留 `category` 欄位（值為 `text|number|credential|email|url|identifier|date|json|other` 之一）。對於 `category="credential"` 等敏感分類，server SHALL NOT 在回應中對 `value` 進行截斷、遮罩或雜湊化；redaction 屬下游消費端職責（例如 audit log 寫入時）。

#### Scenario: credential 類別 value 完整回傳
- **WHEN** test case 含一筆 `category="credential", name="admin_password", value="P@ssw0rd!"` 的 test_data，machine principal 呼叫 detail 端點
- **THEN** 回應 `test_case.test_data[0].value == "P@ssw0rd!"` 且 `category == "credential"`

#### Scenario: 未知 category 字串回傳原值
- **WHEN** DB 中存有 `category="legacy_secret"`（不在 enum 列表中）的 test_data 項
- **THEN** 端點回傳該項時 `category` 為原字串（由 `TestDataItem` 的 `field_validator` 在寫入路徑早已 fallback 至 `text`，但讀取路徑 SHALL 不再做二次 normalization）

### Requirement: MCP test case detail schema MUST include linked automation scripts
既有 `MCPTestCaseDetailItem` SHALL 追加兩個欄位：

- `linked_automation_script_count`：integer，該 case 被連結的 automation script 總數
- `linked_automation_scripts`：array，每筆包含：
  - `script_id`：integer
  - `name`：string
  - `script_format`：string（`PLAYWRIGHT_PY_ASYNC` / `PYTEST` / `PLAYWRIGHT_JS` / `OTHER`）
  - `link_type`：string（`PRIMARY` / `COVERS` / `REFERENCES`）
  - `last_run_status`：string（`SUCCEEDED` / `FAILED` / `RUNNING` / `QUEUED` / `CANCELLED` / `UNKNOWN` / `null`）
  - `last_run_at`：string (ISO 8601) or null
  - `last_run_url`：string or null（CI 端 run URL）
  - `report_url`：string or null（ResultProvider 提供）

當該 case 無 linked script 時 `linked_automation_script_count=0`、`linked_automation_scripts=[]`。

#### Scenario: Existing clients remain compatible
- **WHEN** 既有 MCP client 取得 test case detail，無視新欄位
- **THEN** 回應 SHALL 保留所有原欄位，client SHALL 不受影響

#### Scenario: Test case with multiple linked automation scripts
- **WHEN** test case 同時被 1 支 PRIMARY + 2 支 COVERS automation script 連結
- **THEN** `linked_automation_script_count=3`，`linked_automation_scripts` SHALL 為 3 筆，各帶對應 `link_type` 與最新 run 狀態

#### Scenario: Linked script with no run yet
- **WHEN** linked script 從未執行過
- **THEN** 該筆的 `last_run_status`, `last_run_at`, `last_run_url`, `report_url` SHALL 全為 `null`

#### Scenario: Audit records remain unchanged
- **WHEN** MCP client 取得擴充後的 test case detail
- **THEN** 既有 audit 紀錄行為 SHALL 不變（仍為單筆 READ on TEST_CASE），新欄位 SHALL 不額外觸發 audit

