## ADDED Requirements

### Requirement: CIProvider suite job lifecycle MUST support trigger-scoped job variants
為了讓同一 suite 的 webhook 觸發與 test-run-set 觸發在 CI 端使用不同 job，`CIProvider.create_suite_job` 與 `update_suite_job` SHALL 接受可選的 `job_suffix`（預設 `""`），附加於推導出的 job 名之後。

- provider 對 `job_suffix` **無業務語意認知**（只是字串）；service 層以 `"_hook"` 代表 webhook job 變體。
- `job_suffix=""` 時行為 SHALL 與變更前完全一致（主 job 名不含 suffix）。
- 同一 suite 各 variant 的 job XML / workflow 內容 SHALL 相同；唯一差異為 job 名（suffix）。
- 各 variant SHALL 加入**同一個** team view（`TCRT_{team_name}`）；view 由 TCRT **一律自動建立／維護**（無 `auto_manage_views` 開關），不分離 view。
- `update_suite_job` 帶 `existing_job_name` 時 SHALL 對該 variant 的舊 job 套用既有 `doRename` 改名同步邏輯。
- Jenkins adapter 的 `_suite_job_name` SHALL 在既有 `tcrt_{team_slug}_{suite_slug}` 之後附加 suffix，使 webhook job 形如 `tcrt_{team}_{suite}_hook`，並保留 `tcrt_` 前綴讓 `list_suite_jobs` discovery 不受影響。

#### Scenario: Suffix derives a distinct job name
- **WHEN** service 以 `job_suffix="_hook"` 呼叫 `create_suite_job`
- **THEN** provider SHALL 建立 job 名為 `<主 job 名>_hook`，內容與主 job 相同，並加入同一 team view

#### Scenario: Update with suffix renames the suffixed job
- **WHEN** suite 改名，service 以 `existing_job_name=<舊 webhook job>`、`job_suffix="_hook"` 呼叫 `update_suite_job`
- **THEN** provider SHALL 將舊 webhook job `doRename` 為 `<新主 job 名>_hook`，再更新其 config

#### Scenario: Default (no suffix) preserves existing behavior
- **WHEN** service 不帶 `job_suffix` 呼叫 `create_suite_job` / `update_suite_job`
- **THEN** 推導出的 job 名 SHALL 不含任何 suffix，與變更前一致

#### Scenario: View management is unconditional
- **WHEN** TCRT 建立或更新任一 suite job（主 job 或 webhook job）
- **THEN** TCRT SHALL 確保 team view `TCRT_{team_name}` 存在（不存在則建立）並把該 job 加入，無需任何設定開關

### Requirement: Allure result project MUST be isolated per trigger source
Allure result adapter 的 per-suite project id 推導 SHALL 納入觸發來源：webhook 觸發（`run.triggered_by == WEBHOOK`）的 run SHALL 解析到獨立 project（在 `suite_slug` 後附加 `-webhook`），其餘觸發沿用既有 per-suite project。reclaim（suite 刪除 / 改名 / team 刪除）SHALL 同時清理 primary 與 webhook 兩個 project variant。

#### Scenario: Webhook run resolves to a dedicated Allure project
- **WHEN** 一筆 `triggered_by=WEBHOOK` 的 run 上傳 Allure 結果
- **THEN** 結果 SHALL 寫入 `<suite project>-webhook` project，與 test-run-set 觸發的 project 趨勢歷史分離

#### Scenario: Reclaim covers both project variants
- **WHEN** suite 被刪除或改名
- **THEN** reclaim SHALL 對 primary project 與 webhook project 各執行一次 best-effort delete（project 不存在回 404 視為成功）

### Requirement: CIProvider MUST support team view deletion
`CIProvider` SHALL 提供 `delete_view(team_id, team_name)`，刪除 team 的 list view（用於 team 改名後清理孤兒舊 view）。view 不存在（404）SHALL 視為 no-op。無 view 概念的 provider MAY no-op。

#### Scenario: Delete old team view after rename
- **WHEN** team 改名後 service 以舊 team 名呼叫 `delete_view`
- **THEN** provider SHALL 刪除 `TCRT_{舊名}` view；該 view 已不存在則為 no-op，不報錯
