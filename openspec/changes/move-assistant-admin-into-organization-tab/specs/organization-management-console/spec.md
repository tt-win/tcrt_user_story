## RENAMED Requirements
- FROM: `### Requirement: Organization management page hosts the five relocated tabs`
- TO: `### Requirement: Organization management page hosts the six relocated tabs`

## MODIFIED Requirements

### Requirement: Organization management page hosts the six relocated tabs

`/organization-management` SHALL 內建 6 個分頁，各自沿用其原本獨立掛載位置的功能與存取層級，僅搬遷 DOM 掛載位置與所屬頁面：

1. 人員管理（`tab-pane-personnel`，ADMIN+）
2. 組織同步（`tab-pane-org`，ADMIN+）
3. Service 管理／排程服務（`tab-pane-service-management`，Super Admin；行為契約見 `scheduled-service-management`）
4. MCP Token 簽發（`tab-pane-mcp-token`，Super Admin）
5. 組織自動化基礎設施（`tab-pane-org-automation-infra`，Super Admin；行為契約見 `automation-hub-provider-framework`）
6. AI 助手設定（`tab-pane-assistant-admin`，Super Admin；行為契約見 `assistant-prompt-skills-admin`），內含 System Prompt／Skills 兩個巢狀子分頁（`aaTabPrompt`／`aaTabSkills`）

各分頁呼叫的既有 API（`app/api/users.py`、`app/api/organization_sync.py`、`app/api/system_automation_providers.py`、`app/api/system_automation_hub.py`、`/api/admin/assistant/*` 等）路徑與 request/response contract SHALL 不變。

#### Scenario: Super Admin sees all six tabs
- **WHEN** Super Admin 開啟 `/organization-management`
- **THEN** 頁面 SHALL 顯示全部 6 個分頁，且每個分頁內容與搬遷前功能一致

#### Scenario: Admin (non-Super-Admin) sees a subset of tabs
- **WHEN** 僅具 ADMIN 角色（非 Super Admin）的使用者開啟 `/organization-management`
- **THEN** 頁面 SHALL 僅顯示人員管理與組織同步分頁，Service 管理／MCP Token／組織自動化基礎設施／AI 助手設定四個分頁 SHALL 不可見

#### Scenario: AI 助手設定 tab visible to Super Admin only
- **WHEN** Super Admin 開啟 `/organization-management`
- **THEN** `tab-assistant-admin` 分頁 SHALL 可見，展開後 SHALL 看到 System Prompt／Skills 兩個子分頁
- **WHEN** 非 Super Admin user 進入同一頁
- **THEN** `tab-assistant-admin` 分頁 SHALL 不可見
