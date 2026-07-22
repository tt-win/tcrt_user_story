## RENAMED Requirements
- FROM: `### Requirement: Org-level provider UI MUST live in team management's org-sync modal`
- TO: `### Requirement: Org-level provider UI MUST live in the organization management page`

## MODIFIED Requirements

### Requirement: Org-level provider UI MUST live in the organization management page

`/organization-management` 頁面 SHALL 包含一個分頁 `tab-org-automation-infra`，顯示 Jenkins / Allure provider 管理表格與 Add Provider modal。整個分頁 SHALL 沿用既有 Super Admin 守門（透過 `ui_capabilities.yaml` 的 `pages.organization.components.tab-org-automation-infra` 宣告式設定，見 `organization-management-console`）。

`/automation-provider-settings` 頁面 SHALL：

1. 頁面標題改為「Git 來源設定」(i18n key `gitSourceSettings.title`)
2. `CANONICAL_TYPES` 在 JS 端僅保留 `storage:github`
3. 編輯既有非 canonical type（如 `storage:local_git`）的 row 仍允許，但 slot dropdown 不顯示 ci/result 選項
4. UI 不再暴露 Jenkins / Allure 的 Add Provider 路徑

#### Scenario: Git Source Settings page only lists storage providers
- **WHEN** team admin 開啟 `/automation-provider-settings`
- **THEN** 頁面標題 SHALL 顯示「Git 來源設定」；Provider table SHALL 只列 `provider_slot = storage` 的 row

#### Scenario: Org Automation Infra tab visible to Super Admin only
- **WHEN** Super Admin 開啟 `/organization-management`
- **THEN** 頁面 SHALL 包含 `tab-org-automation-infra` 分頁，展開後 SHALL 看到既有的 org-level CI / Result provider 列表 + Add Provider 按鈕
- **WHEN** 非 Super Admin user 進入同一頁
- **THEN** `tab-org-automation-infra` 分頁 SHALL 不可見（既有行為，僅入口位置從 team_management modal 改為 organization-management 頁面）
