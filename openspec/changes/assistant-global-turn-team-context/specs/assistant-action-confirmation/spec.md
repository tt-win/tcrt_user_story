## ADDED Requirements

### Requirement: Confirm 只使用 pending target snapshot

Team-scoped mutation pending MUST 保存 target id、server name snapshot 與 raw selector。Confirm endpoint MUST 只從 pending action 取得 authoritative target；confirm request、目前頁面 team、conversation history 與 LLM text 都不得覆蓋它。Execution payload 內的 target id也必須與 pending 相等。

Confirm 在 claim 前 MUST 重新驗證 target id/name 非 NULL、team 仍存在、角色 permission、resource ownership equality 與 confirmation fingerprint。任一安全條件不成立時 MUST 原子 expire action、清除 execution payload、寫 synthetic result，且不 dispatch。

#### Scenario: 頁面切換不影響確認

- **WHEN** ART mutation pending 建立後，使用者切換至 CID 頁面再 confirm
- **THEN** action 仍只以 pending `target_team_id=ART` 執行

#### Scenario: Confirm request 偽造 team 參數無效

- **WHEN** confirm request 夾帶任意 team query/body parameter
- **THEN** endpoint 不讀取該值，執行 target 仍為 pending snapshot

#### Scenario: Pending target 不完整或 team 不存在

- **WHEN** legacy pending 無法安全回填 target，或 target team 已刪除
- **THEN** confirm 將 action expire 且不 dispatch

### Requirement: Team metadata 與 fingerprint 綁定

Confirmation summary MUST 以 pending target id 由伺服器 lookup team name，並顯示 `team_name` 與 `team_id`；兩者納入 canonical summary/fingerprint。LLM selector name 不得直接成為卡片顯示來源。Team lookup 發生暫時性錯誤時 MUST 回可重試錯誤，禁止使用 `Team-{id}` placeholder 造成假性 stale；權威 name/id 任一缺失時伺服器不得產生可確認卡，前端亦必須停用確認。

#### Scenario: Team rename 要求重新確認

- **WHEN** pending 建立後 target team 改名
- **THEN** confirm 重算 summary 產生新 fingerprint並回 `CONFIRMATION_STALE`
- **AND** 使用者必須查看更新後 team name 再次確認

### Requirement: Confirm-time authorization 與 ownership 重驗證

Pending 建立後若角色 permission 被撤銷、resource 被移至其他 team、resource 被刪除或 target team 不存在，confirm MUST fail-closed。

#### Scenario: Permission revoked

- **WHEN** 使用者建立 pending 後角色不再具該 write permission
- **THEN** confirm expire action，不執行 loopback

#### Scenario: Resource team 改變

- **WHEN** pending payload 指向的 resource 在 confirm 前不再屬 pending target
- **THEN** confirm expire 或 stale，不得在新 team 執行

### Requirement: Audit 使用 pending target

Confirm claim 建立的 `AssistantToolExecution.team_id` MUST 直接取 pending `target_team_id`，`target_selector_json` MUST 保存原始 selector。Journal resolved team MUST 與實際 loopback routing team 相同。

#### Scenario: Global mutation journal

- **WHEN** global conversation 對 CID mutation 成功
- **THEN** journal `team_id` 為 CID，不得記錄前一個 read target或頁面 team
