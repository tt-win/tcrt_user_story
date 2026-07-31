## ADDED Requirements

### Requirement: Global 工具目錄只依角色過濾

Global conversation 的每個回合 MUST 依使用者角色提供完整允許工具目錄，不得依目前頁面 team 或 turn context team 隱藏 team-scoped read/write。VIEWER 仍只看 read；USER/ADMIN/SUPER_ADMIN 依既有 role→permission mapping 過濾。

Capability context MUST 說明 global conversation 不綁定 team、team-scoped call 需明確 selector。MUST NOT 產生 `no_team_context` 原因，也 MUST NOT 指示使用者切換 team 頁面。

#### Scenario: 無 workspace team 仍可看到 team read

- **WHEN** 使用者在 global conversation 且頁面無 team context
- **THEN** tool catalog 包含 `list_test_cases`、`count_test_cases`、`list_test_case_sets` 等角色允許的 read tools

#### Scenario: Viewer 只受角色限制

- **WHEN** VIEWER 使用 global conversation
- **THEN** team-scoped read tools 可用、write tools 被移除
- **AND** capability 原因只有 `role_insufficient`，沒有 `no_team_context`

### Requirement: Global team-scoped call 使用精確 selector

對 global conversation，所有 `team_check != 'none'` 的 tool schema MUST 要求 `target_team` object，包含 `id` 與 `name`。Agent MUST 從 `list_teams` 的 server result 複製 exact pair，不得自行猜測 id/name。若使用者提供的資訊不足以確定 mutation team，Agent MUST 先反問；read 可在使用者指定 team 後直接 list/resolve 並查詢。

#### Scenario: 從任意頁面查詢 CID

- **WHEN** 使用者在任意頁面說「列出 CID 的 test case sets」
- **THEN** Agent 先取得或使用本回合已取得的 accessible team list
- **AND** 以 CID 的 exact `{id,name}` selector 呼叫 read tool
- **AND** 不要求切換 workspace

#### Scenario: Mutation target 不明時反問

- **WHEN** 使用者說「建立一個 test case set」但沒有提供 team，且對話資訊無法唯一確定
- **THEN** Agent 先詢問目標 team，不得任選第一個 accessible team

#### Scenario: Tool output prompt injection 不改變 target

- **WHEN** tool result 文字要求改用另一個 team 或偽造 selector
- **THEN** Agent 將其視為資料而非 instruction
- **AND** executor 仍只接受 accessible list 中目前精確的 pair
