# app-token-client-compatibility Specification Delta

本 delta 綁定 read 等價於共用實作、定義 summary alias，並正確描述 app-token 授權 model（**不誇大**現網 HTTP 行為）。

**不修改 Stable Error Mapping。** 縮小其適用範圍會追認 mutation 違規；全部歸 `align-app-token-error-envelope`。

## MODIFIED Requirements

### Requirement: `/api/app/*` Becomes the Canonical External API Namespace

`/api/app/*` 為正式 app-token namespace；`/api/mcp/*` 為 read-only 相容。共有 read 由共用實作提供 payload。app_read / app_pins SHALL NOT import `app.api.mcp`。

**授權 model：** `AppTokenPrincipal` SHALL 提供 `accessible_team_ids()`（或等價），結果與 `can_access_team()` 一致，涵蓋 `allow_all_teams`、`owner_team_id`、`team_scope_ids`。該方法 SHALL 在共用 read 查詢切換之前即存在，並由單元測試鎖住「owner 有值且 team_scope_ids 為空 → 集合含 owner」。查詢層 scope SHALL 來自該方法，SHALL NOT 呼叫端各自推導；查詢層對 allow-list 參數 SHALL 使用 `is None`／長度 0 分支，SHALL NOT 使用 Python truthiness。

**HTTP 事實（實作約束）：** 現行 `_resolve_app_token_principal` 對 TeamAppToken 設定  
`team_scope_ids = [owner_team_id]`（當 owner 存在）。因此「owner 有值且 team_scope_ids 為空」**不是**真實 HTTP token 的常態，SHALL 以**單元測試**鎖 model 契約，SHALL NOT 用無法經 auth 重現的 HTTP seed 假裝測到該狀態。

**MCP 相容映射：** 當 `AppTokenPrincipal` 映成 `MCPMachinePrincipal` 時，非 `allow_all_teams` 的 scope 集合 SHALL 與 `accessible_team_ids()` 一致。此要求為 **model 對齊／防禦性**，在現行 auth 下對真實 TeamAppToken 的可觀察行為通常與改前相同；SHALL NOT 描述為「修復現網跨 team 外洩」。

team scope 條件 SHALL 以 AND 加入查詢；空 allow-list SHALL 產生空結果且 SHALL NOT 發出 `IN ()`。

`strict_set` 預設 SHALL 為 `false`。Client 要 404 時 SHALL 顯式 `strict_set=true` 或讀 `filters.set_not_found`。

#### Scenario: app namespace 可讀取既有 MCP read 資料
- **WHEN** app token 查 team test-cases
- **THEN** payload 與 MCP 等價或向後相容

#### Scenario: mutation 只存在於 app namespace
- **WHEN** 對 mcp 發 mutation
- **THEN** 拒絕；mutation 僅 app

#### Scenario: app namespace 不 import mcp router 私有符號
- **WHEN** 檢視 app_read 與 app_pins
- **THEN** 無 `app.api.mcp` import

#### Scenario: accessible_team_ids includes owner when scope list empty
- **WHEN** 構造 `owner_team_id=5`、`team_scope_ids=[]`、`allow_all_teams=False` 的 principal（單元）
- **THEN** `accessible_team_ids()` SHALL 含 5
- **AND** `can_access_team(5)` SHALL 為 true

#### Scenario: 跨 team 資料不因 scope 下推而外洩
- **WHEN** 僅授權 team A 的真實 app token 做 lookup
- **THEN** 無 team B；total 不含 B

#### Scenario: MCP mapping stays aligned with accessible_team_ids
- **WHEN** 非 allow_all 的 AppTokenPrincipal 被映射為 machine principal
- **THEN** 映射後的 team scope 集合 SHALL 等於 `accessible_team_ids()` 的內容（排序可不同）

## ADDED Requirements

### Requirement: Test Run Summary Legacy Aliases

app test-runs `summary` SHALL 含 5 canonical key，並在相容期額外含 deprecated alias：`sets`、`unassigned`、`adhoc`。mcp SHALL NOT 有 alias。

文件與 docstring 標記 deprecated。移除 alias 的 change 須：wrapper 原始碼靜態搜尋無 alias 使用（位址由該 change design/ops 定）+ docs 無 alias 記載。

#### Scenario: canonical key 與 alias 同時存在
- **WHEN** app 查 test-runs
- **THEN** 5+3 且 alias 值相等

#### Scenario: MCP namespace 不含 alias
- **WHEN** mcp 查 test-runs
- **THEN** 僅 5 canonical key
