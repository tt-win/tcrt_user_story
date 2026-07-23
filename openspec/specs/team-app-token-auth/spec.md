# team-app-token-auth Specification

## Purpose
TBD - created by archiving change add-team-app-token-apis. Update Purpose after archive.
## Requirements
### Requirement: Team App Token Credential Model
系統 SHALL 提供 team-owned app token credential，作為外部非互動式 API 存取的正式憑證模型。Token SHALL 以 opaque raw token 核發，server 端僅儲存 hash；raw token SHALL 只在建立或輪替成功的 response 中顯示一次。

Raw token SHALL 使用可識別格式：固定前綴 `tcrt_app_` 加上隨機片段，隨機熵 SHALL 不低於現有 machine token（256-bit）。系統 SHALL 另儲存 `token_prefix`（raw token 開頭固定長度片段，例如前 16 字元），足以在列表與 audit 中識別 token，但不足以重建 raw token。

Credential metadata SHALL 至少包含：`id`、`name`、`description`、`owner_team_id`、`token_hash`、`token_prefix`、`status`、`expires_at`、`last_used_at`、`created_by_user_id`、`created_at`、`updated_at`、`revoked_at`、`scopes_json`。`status` SHALL 至少支援 `active`、`revoked`、`expired` 的可判斷語意；DB 可用 `active/revoked` 搭配 `expires_at` 推導 expired。

Token 到期政策：建立 API 的 `expires_in_days` SHALL 為 optional，未指定時 SHALL 預設 90 天；呼叫端 SHALL 可用明確值（`expires_in_days=0`）選擇不設到期，且該選擇 SHALL 是明確的，不得成為隱含預設。

#### Scenario: 建立 token 只回一次 raw token
- **WHEN** 授權使用者建立 team app token
- **THEN** response SHALL 包含一次性 `raw_token`，且 raw token SHALL 以 `tcrt_app_` 開頭
- **AND** DB SHALL 只保存 raw token 的 hash 與 `token_prefix`，不保存 raw token 明文

#### Scenario: 未指定到期日時套用預設
- **WHEN** 建立 payload 未帶 `expires_in_days`
- **THEN** 系統 SHALL 設定 `expires_at` 為 90 天後

#### Scenario: 明確選擇不到期
- **WHEN** 建立 payload 帶 `expires_in_days=0`
- **THEN** 系統 SHALL 建立不到期 token（`expires_at` 為 NULL）

#### Scenario: metadata 列表不外洩 secret
- **WHEN** 使用者列出 team app tokens
- **THEN** response SHALL NOT 包含 `raw_token`
- **AND** response SHALL NOT 包含 `token_hash`
- **AND** response SHALL 包含 `token_prefix` 供使用者識別手上的 token

#### Scenario: revoked token 無法再使用
- **WHEN** app token 狀態為 revoked
- **THEN** 任何 `/api/app/*` 與相容 `/api/mcp/*` request SHALL 被拒絕

### Requirement: App Token Principal Authentication
系統 SHALL 將有效 app token 解析為 app-token principal，而非 `User`。App-token principal SHALL 包含 credential id/name、team scope（新 app token 為單一 owner team；legacy machine credential 映射時 SHALL 原樣保留其 `allow_all_teams` 與多 team scope 清單，不得縮減或擴大）、scope 清單、token status、legacy credential 來源標記與 audit actor name。

#### Scenario: 有效 token 解析為 app principal
- **WHEN** request 攜帶 `Authorization: Bearer <raw_app_token>`
- **THEN** 系統 SHALL 驗證 hash、status 與 expires_at
- **AND** request state SHALL 設定 app-token principal

#### Scenario: 無效 token 被拒
- **WHEN** request 未帶 token、token 不存在、已撤銷或已過期
- **THEN** 系統 SHALL 回傳 401；缺 token 使用 `APP_TOKEN_REQUIRED`，token 不存在、已撤銷、已過期對外統一使用 `APP_TOKEN_INVALID`，不得對外洩漏 token 狀態差異
- **AND** 系統 SHALL 寫入 deny audit，並在 audit 內細分 invalid / revoked / expired 原因

#### Scenario: legacy 多 team credential 映射不失真
- **WHEN** 既有 `mcp_machine_credentials` token（含 `allow_all_teams=true` 或多 team scope）經相容路徑解析
- **THEN** principal 的 team scope SHALL 與原 credential 完全一致
- **AND** principal SHALL 標記 legacy credential 來源

#### Scenario: app token 不冒充人類使用者
- **WHEN** app-token request 通過認證
- **THEN** 系統 SHALL NOT 將其注入 `request.state.current_user`
- **AND** audit actor SHALL 使用 app principal 身分，例如 `app-token:<credential_name>`

### Requirement: Team Scope and Operation Scope Authorization
系統 SHALL 以 owner team / explicit team scope 限制 app token 可操作的 team，並以 operation scope 控制 read / write / admin 操作。所有 mutation SHALL 預設拒絕，除非 token 明確具有對應 scope。

Scope SHALL 使用穩定字串，至少包含：
- `test_case:read`
- `test_case:write`
- `test_case:admin`
- `test_run:read`
- `test_run:write`
- `test_run:execute`
- `test_run:admin`
- `automation:execute`

破壞性操作與 scope 的對應 SHALL 為：test case 刪除、批次刪除與 set/section 刪除需要 `test_case:admin`；test run config 刪除與 test run set 刪除/archive 需要 `test_run:admin`；run item 建立/更新/刪除屬一般執行流程，維持 `test_run:write`；automation run 的 trigger/cancel/reconcile 需要 `automation:execute`。

#### Scenario: team scope 允許同 team 存取
- **WHEN** app token owner team 為 team A 且呼叫 `/api/app/teams/{team_a}/...`
- **THEN** 系統 SHALL 進一步檢查 operation scope

#### Scenario: team scope 拒絕跨 team
- **WHEN** app token owner team 為 team A 且呼叫 team B 的 endpoint
- **THEN** 系統 SHALL 回 403 `APP_TOKEN_TEAM_SCOPE_DENIED`
- **AND** 系統 SHALL 寫入 deny audit

#### Scenario: mutation 缺少 write scope
- **WHEN** token 只有 `test_case:read` 卻呼叫 test case 更新 endpoint
- **THEN** 系統 SHALL 回 403 `APP_TOKEN_SCOPE_DENIED`
- **AND** mutation SHALL NOT 執行

### Requirement: App Token Lifecycle Management API
系統 SHALL 提供 team-scoped app token 管理 API，允許授權使用者建立、列出、撤銷與輪替 token。Team Admin SHALL 只能管理自己有 admin 權限的 team token；Super Admin SHALL 可跨 team 檢視與撤銷。

#### Scenario: Team Admin 建立 team token
- **WHEN** Team Admin 對自己有 admin 權限的 team 建立 app token
- **THEN** 系統 SHALL 建立 owner team 為該 team 的 app token
- **AND** token scopes SHALL 不得超過該管理 API 允許的 scope 集合

#### Scenario: 非 admin 不能建立 token
- **WHEN** 沒有 team admin 權限的 user 呼叫建立 token API
- **THEN** 系統 SHALL 回 403

#### Scenario: 輪替 token
- **WHEN** 授權使用者輪替 active token
- **THEN** 系統 SHALL 產生新的 raw token 並更新 token hash
- **AND** 舊 raw token SHALL 立即失效
- **AND** response SHALL 只顯示新的 raw token 一次

### Requirement: App Token Auditability and Redaction
系統 SHALL 對所有 app-token allow、deny 與 mutation request 寫入 audit。Audit details SHALL 包含 credential id/name、owner team id、requested team id、endpoint、method、operation scope、resource id 與 result；audit details SHALL NOT 包含 raw token、token hash 或 credential 類 test data 明文。

#### Scenario: allow request 寫入 audit
- **WHEN** app token 成功讀取或寫入資源
- **THEN** 系統 SHALL 寫入 allow audit 並標記 app-token principal

#### Scenario: deny request 寫入 audit
- **WHEN** app token 因 token、team scope 或 operation scope 被拒
- **THEN** 系統 SHALL 寫入 deny audit 並包含拒絕原因

#### Scenario: credential 類資料不進 audit 明文
- **WHEN** app token mutation payload 或 response 包含 `test_data[].category == "credential"`
- **THEN** audit detail SHALL redacted 該 value，不得落明文

