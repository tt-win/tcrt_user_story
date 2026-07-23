# app-token-pins-api Specification

## Purpose
TBD - created by archiving change add-app-token-pins-api. Update Purpose after archive.
## Requirements
### Requirement: App Token Pins API Namespace
系統 SHALL 在 `/api/app/teams/{team_id}/pins` 下提供 team-scoped pin API，使用既有 app-token principal 驗證與 team scope guard，不得依賴 `get_current_user` 或人類 JWT session，且不得修改既有 `/api/pins`（per-user）行為或資料表。

#### Scenario: app token 呼叫 pins API
- **WHEN** app token 呼叫 `/api/app/teams/{team_id}/pins`
- **THEN** 系統 SHALL 以 app-token principal 驗證 team scope 與 operation scope

#### Scenario: 既有人類 Pin API 行為不變
- **WHEN** 既有前端呼叫 `/api/pins`
- **THEN** 既有 JWT per-user Pin API SHALL 保持原契約與資料表，不因新增 app-token pin API 而改變

### Requirement: Team-Scoped Shared Pin List
App-token pin 清單 SHALL 以 team 為單位共享，而非個別 token 私有；同一 team 下任何具足夠 scope 的 app token 建立的 pin，對該 team 其他 app token 皆可見。Mutation（建立／刪除）SHALL 與該 team 底下人類使用者的個人 Pin（`user_pins`）完全獨立：`/api/pins` 的建立與刪除 SHALL 只操作 `UserPin`，`/api/app/teams/{team_id}/pins` 的建立與刪除 SHALL 只操作 `AppTokenPin`，兩者互不寫入或刪除對方的資料列。

#### Scenario: 同 team 不同 token 共用清單
- **WHEN** token A 對某 team 建立一筆 pin
- **THEN** 同 team 的 token B 透過 list API SHALL 看到該筆 pin

#### Scenario: mutation 與人類 Pin 互不影響
- **WHEN** app token 建立或刪除一筆 pin
- **THEN** 該操作 SHALL NOT 新增、修改或刪除任何 `UserPin` 資料列
- **AND** 人類使用者透過 `/api/pins` 建立或刪除個人釘選 SHALL NOT 新增、修改或刪除任何 `AppTokenPin` 資料列

### Requirement: Human-Visible Merge in List View
`/api/pins`（JWT，per-user）的 list 回應 SHALL 將目前使用者在該 team 的個人釘選（`UserPin`）與該 team 的 app-token 團隊共用釘選（`AppTokenPin`）合併回傳，使兩者在既有人類 UI（Test Case Set 列表、Test Run 管理頁）中都能置頂顯示。回應 SHALL 額外提供 `token_pinned` 欄位，依 entity_type 標示哪些 id 來自 app-token 釘選；人類 UI SHALL 將這些項目顯示為不可透過一般取消釘選操作移除的唯讀置頂狀態。

#### Scenario: app-token 釘選在人類 UI 置頂顯示
- **WHEN** app token 對某 test_case_set 建立 pin
- **THEN** 該 team 的人類使用者於 Test Case Set 列表頁 SHALL 看到該 test_case_set 置頂顯示

#### Scenario: 人類無法透過一般 UI 取消 app-token 釘選
- **WHEN** 人類使用者在 UI 對一筆僅由 app token 釘選（未被自己個人釘選）的項目點擊取消釘選
- **THEN** 前端 SHALL NOT 呼叫 `/api/pins` 的刪除端點
- **AND** 該項目 SHALL 持續顯示為置頂，直到對應 app token 透過 `/api/app/teams/{team_id}/pins` 取消釘選為止

#### Scenario: token_pinned 只反映該 team 的 app-token 釘選
- **WHEN** 人類使用者呼叫 `/api/pins?team_id={team_id}`
- **THEN** `token_pinned` 的每個 entity_type 陣列 SHALL 只包含該 `team_id` 下 `AppTokenPin` 的 `entity_id`，不包含其他 team 的資料

### Requirement: Pin Scope Mapping
建立與刪除 pin SHALL 依 `entity_type` 要求對應 scope：`test_case_set` SHALL 要求 `test_case:write`；`test_run_set`、`test_run`、`adhoc_run` SHALL 要求 `test_run:write`。列出 pin SHALL 只要求 `test_case:read` 或 `test_run:read` 任一 scope。不合法的 `entity_type` SHALL 回 400 `APP_TOKEN_VALIDATION_ERROR`。

#### Scenario: 建立 test_case_set pin 需要 test_case:write
- **WHEN** token 缺少 `test_case:write` 並嘗試建立 `entity_type=test_case_set` 的 pin
- **THEN** 系統 SHALL 回 403 `APP_TOKEN_SCOPE_DENIED`

#### Scenario: 建立 test_run 系列 pin 需要 test_run:write
- **WHEN** token 缺少 `test_run:write` 並嘗試建立 `entity_type` 為 `test_run_set` / `test_run` / `adhoc_run` 的 pin
- **THEN** 系統 SHALL 回 403 `APP_TOKEN_SCOPE_DENIED`

#### Scenario: 無效 entity_type
- **WHEN** 建立或刪除 pin 時 `entity_type` 不在允許清單
- **THEN** 系統 SHALL 回 400 `APP_TOKEN_VALIDATION_ERROR`

### Requirement: Idempotent Create and Delete
建立 pin SHALL 為冪等操作：若該 `(team, entity_type, entity_id)` 已存在，SHALL 回傳成功並標示已存在，不得建立重複列。刪除 pin SHALL 為冪等操作：刪除不存在的項目 SHALL 回傳成功並標示刪除數量為 0，不得回 404。

#### Scenario: 重複建立同一筆 pin
- **WHEN** 對已存在的 `(team, entity_type, entity_id)` 再次呼叫建立 pin
- **THEN** 系統 SHALL 回應成功並標示 `already_pinned=true`
- **AND** SHALL NOT 建立第二筆資料列

#### Scenario: 刪除不存在的 pin
- **WHEN** 刪除一筆不存在的 pin
- **THEN** 系統 SHALL 回傳成功且 `deleted=0`

### Requirement: Cross-Team Isolation and Audit
Pin API SHALL 強制 team boundary：token 對某 team 沒有存取權時，SHALL 回 403 `APP_TOKEN_TEAM_SCOPE_DENIED`，且不得讀取或修改該 team 的 pin 資料。所有 allow / deny / mutation SHALL 寫入既有 app-token audit helper，並記錄 `entity_type` 與 `entity_id`。

#### Scenario: 跨 team 存取被拒絕
- **WHEN** token 沒有目標 team 的存取權並呼叫 pins API
- **THEN** 系統 SHALL 回 403 `APP_TOKEN_TEAM_SCOPE_DENIED`
- **AND** SHALL NOT 洩漏該 team 的 pin 資料

#### Scenario: mutation 寫入 audit
- **WHEN** app token 成功建立或刪除一筆 pin
- **THEN** 系統 SHALL 以既有 app-token audit helper 記錄 allow 事件，包含 `entity_type` 與 `entity_id`

