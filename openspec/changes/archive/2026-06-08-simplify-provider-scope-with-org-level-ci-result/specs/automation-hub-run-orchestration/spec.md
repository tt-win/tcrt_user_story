## ADDED Requirements

### Requirement: Run orchestration MUST resolve CI and Result providers from org-level table
觸發 run、查 status、reconcile、取 report URL 等流程使用的 `get_active_provider_record(team_id, slot, session)` SHALL 對 `slot == CI` 與 `slot == RESULT` 解析至 `system_automation_providers`；`team_id` 參數僅用於 storage slot。

呼叫端不需修改簽名，但 SHALL 透過明確的 slot enum 表達意圖；硬編 `"ci"` / `"result"` 字串 SHALL 視為 lint 違規（tasks 階段加 grep check）。

#### Scenario: Trigger run uses org-level CI provider regardless of caller team
- **WHEN** team A user 與 team B user 各自觸發一支 script
- **THEN** 兩個 run record SHALL 共用同一個 `system_automation_providers.id`（org-level）作為 CI provider 來源
- **AND** `automation_runs.provider_id` SHALL 指向該 org provider row

#### Scenario: Result URL fetched via org-level Result provider
- **WHEN** UI 渲染某 run 的「Open report」連結
- **THEN** `get_run_report_url(external_run_id)` SHALL 由 org-level Allure provider 提供，無論 run 屬於哪個 team

#### Scenario: Org CI provider missing blocks trigger across all teams
- **WHEN** Super Admin 尚未建立任何 org-level CI provider
- **THEN** 任何 team 觸發 run SHALL 失敗回 412 `PROVIDER_NOT_CONFIGURED`，錯誤 SHALL 指向「同步組織架構」modal 設定指引
