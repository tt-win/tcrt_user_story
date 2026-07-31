# app-token-management-ui Delta Specification

## MODIFIED Requirements

### Requirement: Team App Token Management Surface

系統 SHALL 在既有 team / organization management UI 中提供 app token 管理體驗。Team Admin SHALL 能在 team context 管理該 team app tokens；Super Admin SHALL 能在 organization/system context 一次檢視所有團隊的 app token metadata（包含 owner team 已停用但 token 尚存的資料），並在同一 global modal 對任一 active token 執行撤銷與輪替操作。Super Admin 建立 token 時 SHALL 在表單中明確選擇 active owner team；不得要求先切換 `currentTeam` 或先進入單一 Team 的 modal。

#### Scenario: Team Admin 看見 app token 分頁

- **WHEN** 使用者對某 team 具備 admin 權限
- **THEN** team management UI SHALL 顯示 App Tokens 管理入口
- **AND** 該入口 SHALL 維持 team-bound token list 與 mutation 行為
- **AND** server SHALL require explicit admin permission for that team; a global Admin role alone SHALL NOT authorize another team's token.

#### Scenario: Super Admin 看見所有團隊 token

- **WHEN** Super Admin 從 system/organization context 開啟 App Token 管理
- **THEN** UI SHALL 直接呼叫 Super Admin global list endpoint 並顯示所有團隊的 token metadata
- **AND** 列表每筆 SHALL 顯示 owner team identity；owner name 缺少時 SHALL 顯示穩定 owner team id
- **AND** UI SHALL NOT 先要求選擇 Team 或呼叫 team-scoped list endpoint

#### Scenario: Super Admin 在 global modal 管理 token

- **WHEN** Super Admin 對 global list 中任一 token 執行撤銷或輪替
- **THEN** revoke SHALL 呼叫 `DELETE /api/app-tokens/{token_id}`，rotate SHALL 呼叫 `POST /api/app-tokens/{token_id}/rotate`
- **AND** rotate endpoint SHALL 由 server 依 token id 解析 owner team，不接受 client team id
- **AND** UI SHALL NOT 修改 `currentTeam` 或 global modal context
- **AND** server SHALL 重新執行 Super Admin authorization 與既有 audit

#### Scenario: Super Admin 建立 token 指定 owner team

- **WHEN** Super Admin 在 global modal 建立 token
- **THEN** UI SHALL 要求 explicit active owner team selection
- **AND** SHALL 呼叫受 Super Admin guard 保護的 `POST /api/app-tokens` 並在 body 明確提供 `owner_team_id`
- **AND** SHALL 在成功後重新載入 global metadata list

#### Scenario: 非授權使用者看不到或不能使用 global management

- **WHEN** 使用者沒有 Super Admin 權限
- **THEN** UI SHALL 不提供 global management action
- **AND** global list/create/rotate/revoke endpoint SHALL 拒絕請求

### Requirement: Metadata-only Token List

App token 列表 SHALL 只顯示 metadata：name、description、owner team、token_prefix、status、scopes、expires_at、last_used_at、created_at、created_by 與 actions。`token_prefix` SHALL 以截斷形式顯示（例如 `tcrt_app_ab12…`），讓使用者能辨識手上的 token 對應哪筆 credential。列表 SHALL NOT 顯示 raw token 或 token hash；global list 與 team-bound list 均 SHALL 遵守此邊界。

#### Scenario: 列表不顯示 secret

- **WHEN** 使用者載入任一 App Token 列表
- **THEN** table SHALL NOT 包含 raw token 或 token hash 欄位
- **AND** table SHALL 顯示 token_prefix 與 owner team 欄位

#### Scenario: 一次性 raw token 仍只在 lifecycle response 顯示

- **WHEN** Super Admin 建立或輪替 token 成功
- **THEN** raw token SHALL 只在該次成功 response 的 warning panel 顯示
- **AND** global metadata reload SHALL NOT 將 raw token 保存或渲染為列表欄位
- **AND** while create/rotate is pending, the modal SHALL prevent close or context replacement until the one-time response is handled, so a successful rotation cannot silently lose the new credential.
