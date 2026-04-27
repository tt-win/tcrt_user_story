# mcp-read-api Specification

## Purpose
定義 TCRT 對 MCP consumer 提供的唯讀查詢 API，包括 team、test case 與 test run 的統一讀取模型與過濾規則。本次 change 新增 test case sections 的唯讀端點。

## ADDED Requirements

### Requirement: MCP SHALL Provide Read-Only Test Case Sections Endpoint
系統 SHALL 提供 `GET /api/mcp/teams/{team_id}/test-case-sections` 端點，回傳指定 team 範圍內的 test case sections。端點 SHALL 維持唯讀；不接受 POST / PUT / PATCH / DELETE。回應 SHALL 包含 `team_id`、`filters`（query 參數 echo）、`sections`（扁平陣列）、`total`（陣列長度）四個頂層欄位。

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
