## Why

目前「組織架構同步管理」只支援手動同步，而既有 scheduler 只是已啟動但沒有註冊任務的 in-memory 框架。Super Admin 無法從系統介面管理可排程服務、設定執行時間，或檢視上次執行結果與當前狀態，導致自動化維運能力不可見也不可控。

## What Changes

- 在「組織架構同步管理」新增一個僅 Super Admin 可見的「Service 管理」tab，延續現有 Organization / MCP Token 的頁籤模式。
- 新增後端可排程服務 registry，讓 UI 能讀取目前系統支援排程的服務清單，而不是前端硬編碼。
- 新增可持久化的排程設定與執行狀態儲存，支援為服務啟用/停用每日排程時間，並保存上次執行結果。
- 新增 Super Admin 專用 API，供前端查詢服務清單、讀取目前排程、更新排程時間，以及查看目前狀態與上次執行狀態。
- 擴充 scheduler，使其在啟動時載入持久化設定、在執行時回寫狀態，並維持目前 TCRT 既有的同步頁風格與交互習慣。

## Capabilities

### New Capabilities
- `scheduled-service-management`: 在組織架構同步管理中管理可排程服務、設定每日執行時間，並查看排程服務的目前狀態與上次執行結果。

### Modified Capabilities
- None.

## Impact

- Affected code: `app/services/scheduler.py`, `app/api/organization_sync.py`, `app/templates/team_management.html`, `app/static/js/team-management/main.js`, `app/static/css/team-management.css`, `config/permissions/ui_capabilities.yaml`
- Affected data: 新增 scheduler 相關持久化表與 migration，並需同步更新 `database_init.py`
- Affected UX: 組織架構同步管理 modal 會新增一個僅 Super Admin 可見的 service 排程管理分頁
- Validation: scheduler/service API tests、permission UI tests、focused frontend interaction tests
