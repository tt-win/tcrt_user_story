## MODIFIED Requirements

### Requirement: In-process loopback 與 explicit team routing

工具仍 SHALL 透過 in-process ASGI loopback 與既有 JWT router 執行。Global conversation 的 team-scoped tool schema SHALL 接受 `target_team: {id,name}`，但 executor MUST 在組裝 path/query/body 前移除該 selector；既有 endpoint MUST NOT 收到 Assistant selector。

Executor MUST 將 selector 視為未信任資料，依序驗證 JSON shape、目前 DB identity（id+name）、全域角色 permission 與 resource ownership equality。只有全部通過後，才能把 server-resolved id 注入 `{team_id}` 或 dispatch。現行 permission model 不提供 per-team membership isolation；上述控制保證 routing 透明與一致，不得被文件描述成 team isolation。

#### Scenario: 精確 selector 執行 read

- **WHEN** 使用者可存取 ART，LLM 從 `list_teams` 複製 ART `{id,name}` 呼叫 `count_test_cases`
- **THEN** executor 驗證 pair 與 read permission後，以 ART id 注入路徑
- **AND** selector 不出現在 loopback query/body

#### Scenario: 無法解析的 selector 不洩漏資訊

- **WHEN** LLM 提供不存在、stale 或 malformed 的 id/name
- **THEN** executor 一律以 generic `team_selector_unresolved` 拒絕，不 dispatch
- **AND** 回覆不得以不同錯誤透露 team 是否存在

#### Scenario: Stale name 被拒

- **WHEN** selector id 仍存在但 team 已改名，selector name 與 DB 不一致
- **THEN** executor 拒絕並要求重新 `list_teams`，不得只信 id

### Requirement: Resource team 必須等於 explicit target

對 `inject` 加 resource resolver 或 `resolve` 類工具，executor MUST 解析資源實際 team，並要求其等於 global selector id。兩個 team 即使都可存取，也不得靜默跨 team。Team-bound conversation 仍要求等於 conversation team。

#### Scenario: Read resource mismatch 被拒

- **WHEN** selector 是 ART，但 `set_id` 實際屬 CID
- **THEN** executor 在 transport 前拒絕，journal 不得記為成功

#### Scenario: Write resource mismatch 不建立 pending

- **WHEN** selector 是 ART，但 mutation payload 指向 CID resource
- **THEN** executor 回 `target_team_mismatch`，不建立 pending、不 dispatch

### Requirement: Permission 在 resolved target 上即時驗證

Global catalog 的 role filtering 不構成執行授權。每次 read/write prepare MUST 在 resolved selector team 上重新呼叫現行角色 permission check；confirm MUST 再驗一次。Permission lookup 失敗時 MUST fail-closed。此檢查只驗證全域角色能力，並非 per-team membership。

#### Scenario: 角色不允許工具 permission

- **WHEN** selector identity 合法，但使用者角色不具 tool 宣告的 permission
- **THEN** prepare 拒絕且不建立 pending

### Requirement: Batch 不得跨 team

Global batch 的 parent call MUST 有一個 selector；所有 child action 的 resolved team MUST 等於該 selector。任一 child mismatch 使整批在 pending 前被拒。

#### Scenario: Mixed-team batch 被拒

- **WHEN** batch selector 為 ART，但 child actions 同時包含 ART 與 CID resources
- **THEN** executor 拒絕整批且不建立確認卡
