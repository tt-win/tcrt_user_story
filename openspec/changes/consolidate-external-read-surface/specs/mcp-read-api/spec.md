# mcp-read-api Specification Delta

本 delta 收斂「App namespace 等價」為可機械驗證的 parity 與 canonical 語意，並補上 cross-team lookup。分歧 **D1–D43（34 FIX / 9 KEEP）** 見 change `design.md`。測試採分層（Tier A/B/C），不要求每個 FIX 具名 regression。

## MODIFIED Requirements

### Requirement: MCP Teams Read Endpoint

系統 SHALL 透過 `/api/mcp/teams` 保留 read-only 團隊清單相容端點，並在 `/api/app/teams` 提供正式 app-token 等價 read endpoint。兩者 SHALL 回傳經過清理的欄位與總數資訊。

`is_lark_configured` SHALL 一律為 `false` 並視為 deprecated。

`status` 為 NULL 時兩個 namespace SHALL 回傳 `"active"`，SHALL NOT 回傳 `"None"`。

查詢層 team 限制參數（`allowed_team_ids` 或等價）SHALL 遵守：`None` 表示不限；**空集合表示零結果且 SHALL NOT 產生 SQL `IN ()`**。

#### Scenario: Team list returns count and sanitized fields
- **WHEN** machine principal 查詢 `/api/mcp/teams`
- **THEN** 回應包含可公開欄位與總筆數

#### Scenario: App namespace returns equivalent team list
- **WHEN** app-token principal 查詢 `/api/app/teams`
- **THEN** 回應 SHALL 與 `/api/mcp/teams` read model 相容

#### Scenario: Deprecated Lark flag is always false
- **WHEN** 查詢 teams
- **THEN** 每筆 `is_lark_configured` SHALL 為 `false`

#### Scenario: Null team status falls back to active on both namespaces
- **WHEN** team.status 為 NULL
- **THEN** 兩側 status SHALL 為 `"active"`

#### Scenario: Empty team-id allow-list yields empty result without IN ()
- **WHEN** 查詢層收到空的 allowed team id 集合
- **THEN** SHALL 回傳空清單
- **AND** SHALL NOT 對資料庫發出空的 `IN ()` 條件

#### Scenario: Empty allow-list applies to teams list and cross-team lookup
- **WHEN** 以空 allow-list 呼叫 teams 列表與 cross-team lookup 共用查詢
- **THEN** 兩者 SHALL 皆回傳零筆（`total`／`page.total` 為 0）
- **AND** 實作 SHALL 對上述兩個入口各自處理 empty allow-list（不得只覆蓋其一）

#### Scenario: allowed_team_ids branching does not use Python truthiness
- **WHEN** 檢視共用 read 查詢模組對 `allowed_team_ids` 的分支
- **THEN** SHALL 以 `is None` 表示不限、以長度為 0 表示空結果
- **AND** SHALL NOT 使用 `if not allowed_team_ids` 或 `if allowed_team_ids:` 這類會把空集合與 None 混淆的寫法

### Requirement: MCP Test Case Set and Test Case Query with Filters

兩個 namespace 的 test case 列表 read payload SHALL 由單一共用實作產生。canonical：

- `search` 比對 title、test_case_number、tcg_json（欄位間 OR）
- `set_id` 以 `is not None` 判定（`set_id=0` 生效）
- 未知 set：預設忽略 set 過濾、整 team、`set_not_found=true`；`strict_set` 預設 **false**；`strict_set=true` → 404
- 排序 `created_at DESC, id DESC`；sets 同
- `page.total` 為 DB count
- team scope 下推；空 allow-list 為空結果

#### Scenario: App namespace supports the same read filters
- **WHEN** app token 帶 MCP 同級 filters 查 test-cases
- **THEN** filter 與 pagination 語意 SHALL 與 MCP 一致

#### Scenario: Keyword search covers number and ticket columns on both namespaces
- **WHEN** 關鍵字只在 number 或 tcg
- **THEN** 兩側皆命中且 total 相同

#### Scenario: Unknown set_id is reported rather than silently emptying the result
- **WHEN** 未知 set_id 且未 strict
- **THEN** `set_not_found` true 且結果為整 team；strict 時 404

#### Scenario: set_id zero applies provided-set semantics
- **WHEN** `set_id=0`（通常無此 set）
- **THEN** SHALL 套用「已提供 set_id」語意（與未知 set 相同：`set_not_found` 且非整頁被 `if set_id` 忽略）
- **AND** SHALL NOT 僅因 filters 已 echo `set_id: 0` 而視為通過

### Requirement: MCP Unified Test Run Read Model

系統 SHALL 以單一共用實作提供 test run 讀取模型（set / unassigned / adhoc），且兩個 namespace 的 read payload SHALL 遵守下列 canonical 語意：

- `run_type` SHALL 套用 set / unassigned / adhoc
- `include_archived` 預設 SHALL 為 false
- set status SHALL 用動態 resolve，SHALL NOT 僅回 raw DB
- 成員 config SHALL 套用 status/archived 過濾並依 `(position,id)` 排序；set 不符但 member 命中時 SHALL 仍可保留 set
- adhoc 計數 SHALL 由 sheet/item 實算
- unassigned SHALL 限定目標 team 的 config；查詢形狀 SHALL 對齊 outerjoin 實作
- unassigned 的正確性 SHALL NOT 被描述成「他 team 資料外洩」的唯一防線——當查詢已含 config.team_id 時不得使用錯誤安全敘事
- summary SHALL 含五 canonical key；共用實作 SHALL 自備 eager-load

#### Scenario: run_type excludes sets on both namespaces
- **WHEN** `run_type=adhoc`
- **THEN** 兩側 `sets` 為空

#### Scenario: Archived test run sets are excluded by default on both namespaces
- **WHEN** 存在 archived set 且未帶 include_archived
- **THEN** 兩側都不含該 set；帶 true 時皆含

#### Scenario: Adhoc counts reflect actual items on both namespaces
- **WHEN** N items、M 有 result
- **THEN** total_test_cases=N、executed_cases=M

#### Scenario: App test-runs match MCP on unified filter matrix
- **WHEN** 同一 seed 以相同參數呼叫兩 namespace 的 test-runs（至少：預設、`status=completed`、`run_type=adhoc`+archived 組合）
- **THEN** sets / unassigned / adhoc 的成員識別集合 SHALL 一致

### Requirement: Sections Endpoint SHALL Order Results Deterministically

回應的 `sections` 陣列 SHALL 按 `test_case_set_id ASC, level ASC, sort_order ASC, id ASC` 排序，且兩個 namespace SHALL 由單一共用實作產生。兩個 namespace SHALL 都提供 `include_empty`（預設 true）。`roots_only` 與 `parent_section_id` 同時出現時，`roots_only` SHALL 優先。未知 set_id 時 SHALL 回傳空 sections 並標記 `filters.set_not_found`。

#### Scenario: 兩個 namespace 的 section 排序一致
- **WHEN** 同資料呼叫兩側
- **THEN** section 順序與 filters key 集合一致

#### Scenario: section order is set-major not sort_order-major only
- **WHEN** team 內有 set_id 較小的 section（sort_order 較大）與 set_id 較大的 section（sort_order 較小）
- **THEN** 兩側回應 SHALL 皆先列出 set_id 較小者之 sections（`test_case_set_id` 優先於跨 set 的 `sort_order`）

## ADDED Requirements

### Requirement: Cross-Team Test Case Lookup SHALL Be Equivalent Across Namespaces

`/api/mcp/test-cases/lookup` 與 `/api/app/test-cases/lookup` SHALL 由單一共用實作產生 read payload。canonical 語意 SHALL 為：多 filter 以 AND 組合；team scope 以 AND 加入且 SHALL NOT 進入 OR 群組；`q` 比對 title/number/tcg；`test_case_number` 為子字串並以 `match_type` 區分 exact/partial；分頁僅在 SQL 層；`page.total` 為 DB count；排序 `created_at DESC, id DESC`；未知 `team_id` SHALL 回 404；無 filter SHALL 回 400；兩側 SHALL 提供 `include_content`（mcp 預設 true、app 預設 false），parity 測試 SHALL 先參數對齊再比 payload。

#### Scenario: 後續分頁不為空且 total 為總命中數
- **WHEN** skip=1&limit=1 且命中 ≥2
- **THEN** 兩側 items 長度 1 且 total 為總命中

#### Scenario: lookup order is created_at desc then id desc
- **WHEN** 至少兩筆命中且 id／建立順序已知
- **THEN** 兩側 items 順序 SHALL 為較新（或同時間較大 id）在前
- **AND** 測試 SHALL NOT 僅驗證「連續兩次呼叫順序相同」

#### Scenario: 多個 filter 取交集
- **WHEN** q 與 ticket 無交集
- **THEN** 兩側 items 空

#### Scenario: team scope 不因 filter 組合而被繞過
- **WHEN** 僅授權 team A
- **THEN** 無 team B 且 total 不含 B

#### Scenario: test_case_number 支援子字串比對
- **WHEN** number 傳真子字串
- **THEN** 兩側命中且 match_type 可分 exact/partial

### Requirement: External Read Surface SHALL Have a Single Implementation

六個共有 read 由共用模組產生 payload。Router 只做 auth、scope 解析、audit、error map、參數。義務**不含** assistant / web JWT 內部查詢。

共用模組 SHALL NOT import `app.api`；app_read/app_pins SHALL NOT import mcp。唯讀：無自開 session、無 commit/rollback、無 mutation。無 HTTPException——拋 domain 例外。

`allowed_team_ids`（或等價）：`None` 不限；空集合空結果且無 `IN ()`。

#### Scenario: 兩個 namespace 不各自實作查詢
- **WHEN** 檢視 app_read
- **THEN** 無 `select(` / `func.count(`

#### Scenario: 共用模組不逆向依賴 api 層 / 不含 mutation / 不決定 HTTP error shape
- **WHEN** 掃描共用模組
- **THEN** 無 app.api import、無 session mutation、無 HTTPException

### Requirement: Namespace Divergence SHALL Be an Explicit Two-Layer Allow-List

兩個 namespace 之間允許存在的 read 差異 SHALL 限於下列 Payload allowlist 與 Behavioral allowlist；清單外的成功回應 payload 差異 SHALL 視為缺陷。

#### Payload allowlist（成功 JSON diff 允許的 key path）

| key path | 說明 |
| --- | --- |
| `summary.sets` / `summary.unassigned` / `summary.adhoc` | 僅 app；= canonical count；deprecated |
| `filters.section_id` | **能力**差：app 可傳過濾；共用後雙邊 filters **可同有 key=null**，happy-path parity 常無 diff |
| `filters.team_name` | **能力**差：僅 mcp 可傳；共用後 key 可雙邊 null |

SHALL NOT 將 `filters.include_content` 列為允許 diff（parity 須參數對齊）。忽略 `created_at` / `updated_at`。

#### Behavioral allowlist（不進 JSON path）

| 差異 | 說明 |
| --- | --- |
| principal 類型 | machine vs app token |
| allow-path audit | mcp 有 / app 無 |
| error payload 結構 | 兩側混合；歸 error-envelope change |
| limit 上限 | test-cases 1000 vs 500；lookup 200 vs 100 |
| include_content **預設** | lookup mcp true / app false |
| 零 scope lookup | mcp 403 / app 200 空 |
| 零 scope teams audit | mcp 有 early audit reason |

#### Scenario: parity 以 payload 白名單驗證
- **WHEN** 參數對齊後比對六 read 成功 JSON
- **THEN** diff key path ⊆ Payload allowlist

#### Scenario: behavioral 差異不要求 JSON path
- **WHEN** 差異屬 behavioral 表
- **THEN** 以行為測或文件記載，不強行編碼為成功 body key
