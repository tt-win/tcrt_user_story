## MODIFIED Requirements

### Requirement: Super Admin UI

系統 SHALL 於 `/organization-management` 頁面（見 `organization-management-console`）提供分頁 `tab-assistant-admin`（tabs：System Prompt｜Skills），僅 Super Admin 可有效使用；分頁可視性沿用該頁既有 `organization_management:manage` ui-config gating（與 `tab-org-automation-infra` 等其餘 Super-Admin-only 分頁同一存取層級）。編輯區 MUST 使用純文字控件（非 raw HTML 渲染 skill body）。UI MUST 警告內容會影響外部 LLM 規劃，且勿貼入密鑰。

#### Scenario: 非 Super Admin 開啟頁面
- **WHEN** 非 Super Admin 開啟 `/organization-management` 並呼叫 admin API
- **THEN** `tab-assistant-admin` 分頁不可見；API 呼叫仍 403
