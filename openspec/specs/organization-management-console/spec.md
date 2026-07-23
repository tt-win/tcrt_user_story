# organization-management-console Specification

## Purpose
定義獨立的「組織與系統設定」頁面（`/organization-management`）——統整人員管理、組織同步、Service 管理（排程服務）、MCP Token 簽發、組織自動化基礎設施、AI 助手設定六個組織層分頁（前五者原本擠在 `/team-management` 頁面「組織與系統設定」modal 內；AI 助手設定原為獨立頁面 `/assistant-admin`），對應既有 `organization` permission page key，並提供 `/team-management` 到本頁的入口連結與舊分頁錨點的相容性提示。由 `redesign-team-settings-information-architecture` change 建立，`move-assistant-admin-into-organization-tab` change 新增第 6 個分頁。

## Requirements

### Requirement: Organization management page exists as an independent route

系統 SHALL 提供獨立路由 `/organization-management`（template `app/templates/organization_management.html`），並沿用既有 permission page key `organization`（`GET /api/permissions/ui-config?page=organization`）決定頁面內元件可視性；不得新增平行的 permission page key。

#### Scenario: User with organization_management:view permission opens the page
- **WHEN** 具備 `organization_management:view` 權限的使用者開啟 `/organization-management`
- **THEN** 頁面 SHALL 載入並顯示導覽 shell（人員管理／組織同步／Service 管理／MCP Token／組織自動化基礎設施五個分頁的容器）

#### Scenario: User without organization_management permission cannot access
- **WHEN** 不具備 `organization_management` 任何 action 權限的使用者嘗試開啟 `/organization-management`
- **THEN** 頁面內容 SHALL 依既有 `ui-config` gating 行為不顯示任何分頁內容（與現行 team_management modal 對非授權使用者隱藏整顆按鈕的行為一致）

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

### Requirement: Org-automation-infra tab visibility MUST be declared in ui_capabilities.yaml with a pinned action value

`tab-org-automation-infra` 的 Super-Admin-only 可視性 SHALL 透過 `config/permissions/ui_capabilities.yaml` 的 `pages.organization.components.tab-org-automation-infra` 宣告式設定達成，設定值 MUST 為 `{ feature: organization_management, action: advanced }`（與同頁 `tab-org`、`tab-service-management`、`tab-mcp-token` 採用相同 action 值），取代現行寫死在 JS（`applyOrganizationUiVisibilityByRoleFallback`）的角色判斷。此 yaml 設定 MUST 與讀取它的前端程式碼在同一次部署內一起上線，不可分批部署。

#### Scenario: Tab visibility driven by declarative config with the pinned action value
- **WHEN** 維運人員查看 `ui_capabilities.yaml` 內 `tab-org-automation-infra` 對應設定
- **THEN** 設定值 SHALL 為 `action: advanced`；分頁可視性 SHALL 依此設定生效，不需修改 JS 程式碼

#### Scenario: Admin role must not gain visibility via a misconfigured action value
- **WHEN** 具 ADMIN（非 Super Admin）角色的使用者請求 `page=organization` 的 ui-config
- **THEN** 回應中 `tab-org-automation-infra` 的可視性 SHALL 為 false（`organization_management:advanced` 對 ADMIN 角色不放行，僅 `view` 才放行，兩者不可混用）

### Requirement: Team management page links to organization management page

`/team-management` 頁面 SHALL 提供一個入口連結導向 `/organization-management`，文字沿用既有字樣「組織與系統設定」（不使用「組織管理」，避免與既有「組織同步」功能混淆，見 `organization-management-console` 對應 design 決策），僅在使用者具備 `organization_management:view`（或更高）權限時可見；不再提供開啟「組織與系統設定」modal 的按鈕。

#### Scenario: Authorized user navigates from team management to organization management
- **WHEN** 具備 `organization_management:view` 權限的使用者在 `/team-management` 點擊「組織與系統設定」連結
- **THEN** 瀏覽器 SHALL 導向 `/organization-management`

#### Scenario: Unauthorized user does not see the link
- **WHEN** 不具備 `organization_management` 任何 action 權限的使用者開啟 `/team-management`
- **THEN** 「組織與系統設定」連結 SHALL 不顯示

### Requirement: Legacy tab anchors show a relocation notice instead of failing silently

`/team-management` 頁面 SHALL 偵測 URL hash 是否命中已搬遷分頁的舊錨點（`#tab-pane-personnel`、`#tab-pane-org`、`#tab-pane-service-management`、`#tab-pane-mcp-token`、`#tab-pane-org-automation-infra`），若命中，SHALL 顯示一次性提示，告知該功能已搬至 `/organization-management` 並提供連結，而非留給使用者看到一個沒有對應內容、找不到任何反應的頁面。

#### Scenario: User follows a bookmarked legacy tab anchor
- **WHEN** 使用者開啟 `/team-management#tab-pane-mcp-token`（舊書籤或舊文件連結）
- **THEN** 頁面 SHALL 正常載入，並顯示提示「此功能已搬至組織與系統設定頁面」與可點擊連結，而非靜默無反應
