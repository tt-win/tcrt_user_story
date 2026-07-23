# app-token-management-ui Specification

## Purpose
TBD - created by archiving change add-team-app-token-apis. Update Purpose after archive.
## Requirements
### Requirement: Team App Token Management Surface
系統 SHALL 在既有 team / organization management UI 中提供 app token 管理體驗。Team Admin SHALL 能在 team context 管理該 team app tokens；Super Admin SHALL 能在 organization context 檢視與撤銷所有 team app tokens。

#### Scenario: Team Admin 看見 app token 分頁
- **WHEN** 使用者對某 team 具備 admin 權限
- **THEN** team management UI SHALL 顯示 App Tokens 管理入口

#### Scenario: 非授權使用者看不到管理入口
- **WHEN** 使用者沒有 team admin 或 super admin 權限
- **THEN** UI SHALL 隱藏 app token 管理入口

### Requirement: Token Create Modal
建立 app token SHALL 使用 modal 或等價既有 TCRT 表單模式，包含 name、description、expires_in_days、scope 選擇與一次性 raw token 顯示。Scope 控制 SHALL 使用 checkbox / segmented control 等明確控制項，避免自由文字輸入。到期設定 SHALL 預設 90 天；「不設到期」SHALL 為明確選項並顯示風險提示，不得是預設值。

#### Scenario: 建立後顯示一次性 token
- **WHEN** 使用者成功建立 app token
- **THEN** modal SHALL 顯示 raw token 與 copy action
- **AND** 關閉後再次開啟列表 SHALL 只顯示 metadata

#### Scenario: scope 選擇
- **WHEN** 使用者選擇 token scope
- **THEN** UI SHALL 清楚顯示 read / write / execute / admin 的差異

#### Scenario: 不設到期需要明確選擇
- **WHEN** 使用者開啟建立 modal
- **THEN** 到期欄位 SHALL 預設 90 天
- **AND** 選擇「不設到期」時 UI SHALL 顯示風險提示文案

### Requirement: Metadata-only Token List
App token 列表 SHALL 只顯示 metadata：name、description、owner team、token_prefix、status、scopes、expires_at、last_used_at、created_at、created_by 與 actions。`token_prefix` SHALL 以截斷形式顯示（例如 `tcrt_app_ab12…`），讓使用者能辨識手上的 token 對應哪筆 credential。列表 SHALL NOT 顯示 raw token 或 token hash。

#### Scenario: 列表不顯示 secret
- **WHEN** 使用者載入 app token 列表
- **THEN** table SHALL NOT 包含 raw token 或 token hash 欄位
- **AND** table SHALL 顯示 token_prefix 欄位

#### Scenario: revoked / expired 顯示狀態
- **WHEN** token 已撤銷或過期
- **THEN** UI SHALL 顯示清楚 status badge
- **AND** revoke action SHALL 對 revoked token disabled 或隱藏

### Requirement: Revoke and Rotate Interactions
UI SHALL 支援 revoke 與 rotate action。兩者皆 SHALL 顯示確認流程，並在成功後 refresh metadata list。Rotate SHALL 顯示新的 raw token 一次；rotate 確認流程 SHALL 明確警告舊 token 會立即失效、沒有 grace period，外部整合需在 rotate 後立即更新設定。

#### Scenario: revoke token
- **WHEN** 使用者確認 revoke active token
- **THEN** UI SHALL 呼叫 revoke API
- **AND** 成功後列表 SHALL 顯示 token 為 revoked

#### Scenario: rotate token
- **WHEN** 使用者確認 rotate active token
- **THEN** 確認訊息 SHALL 警告舊 token 立即失效且無 grace period
- **AND** UI SHALL 顯示新的 raw token 一次
- **AND** 舊 token SHALL 立即失效

### Requirement: i18n and Existing TCRT UI Pattern
所有 app token UI 新文案 SHALL 同步更新 `en-US`、`zh-CN`、`zh-TW` locales，並沿用既有 TCRT/TestRail 樣式、modal、button、table 與 i18n lifecycle。

#### Scenario: 三語系完整
- **WHEN** app token UI 新增任何 user-facing string
- **THEN** 三個 locale 檔 SHALL 都包含對應 key

#### Scenario: 動態 DOM retranslate
- **WHEN** JS 動態渲染 token list 或 modal state
- **THEN** UI SHALL 使用既有 i18n helper 或 retranslate lifecycle

