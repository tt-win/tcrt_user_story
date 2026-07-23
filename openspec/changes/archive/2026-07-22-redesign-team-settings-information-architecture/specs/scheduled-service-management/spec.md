## RENAMED Requirements
- FROM: `### Requirement: Super Admin can manage scheduled services in organization modal`
- TO: `### Requirement: Super Admin can manage scheduled services in organization management page`

## MODIFIED Requirements

### Requirement: Super Admin can manage scheduled services in organization management page

系統 SHALL 僅允許 Super Admin 在 `/organization-management` 頁面管理 scheduled services。

#### Scenario: Super Admin sees service management tab
- **WHEN** Super Admin 開啟 `/organization-management`
- **THEN** 可見 scheduled service management 分頁

#### Scenario: Non-Super-Admin cannot access service management tab
- **WHEN** 非 Super Admin 使用者開啟相同介面
- **THEN** 看不到或無法存取該分頁
