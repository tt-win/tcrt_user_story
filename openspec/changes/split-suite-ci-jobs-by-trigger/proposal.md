## Why

目前每個 automation suite 在 CI 端只有**一個** Jenkins job（`automation_script_groups.ci_job_name` = `tcrt_{team}_{suite}`），Test Run Set 觸發與 inbound webhook 觸發都打同一個 job。後果是兩種觸發來源在 Jenkins 端**完全無法區分**：build 歷史混在一起、共用同一條佇列。而且因為 Allure project id 是 server 端用 `team_slug + suite_slug` 推導（與 job 名無關），兩者的測試報表與趨勢歷史也寫進同一個 project，在 `KEEP_HISTORY_LATEST` 限制下互相擠掉歷史。

手動 QA 執行（Test Run Set）與外部 CI 整合（webhook）性質不同，混在一起難以稽核與排查。本變更讓兩種觸發來源在 **Jenkins job** 與 **Allure report** 兩個層級都物理隔離。

## What Changes

- 每個 suite 由單一 CI job 變為**兩個 trigger-scoped job**：
  - 主 job `tcrt_{team}_{suite}` —— 服務 Test Run Set（及未來 schedule / MCP）觸發
  - webhook job `tcrt_{team}_{suite}_hook` —— 僅服務 inbound webhook 觸發（保留 `tcrt_` 前綴，讓 `list_suite_jobs` 仍能發現）
- `trigger_group_run` SHALL 依 `triggered_by` 路由到對應 job（`WEBHOOK` → webhook job，其餘 → 主 job）。
- webhook job **lazy 建立**：第一次 webhook 觸發時透過既有 self-heal（update→404→create）建立；既有 suite 無需 backfill。
- Jenkins job 生命週期 SHALL 同時涵蓋兩個 job：create / update / 改名（`doRename`）/ delete / self-heal / 加入 `TCRT_{team_name}` view / 改名與刪除時的 Allure reclaim。
- **Allure report 隔離**：webhook 觸發的 run SHALL 解析到獨立 Allure project（`{suite}` vs `{suite}-webhook`）；project id 推導 SHALL 納入 `run.triggered_by`，reclaim（改名／刪除）SHALL 一併清理 webhook project。
- 資料模型：`automation_script_groups` 新增 `ci_job_name_webhook` VARCHAR(200) nullable + Alembic migration（非破壞，既有 row 為 NULL）。

### 非目標（Non-Goals）

- 不改 Test Run Set 觸發 API 與 inbound webhook 觸發 API 的**對外契約**（路徑、payload、回應）。
- 不為既有 suite 預先建立 webhook job（lazy，不 backfill）。
- 不改 schedule / MCP 觸發（仍走主 job）。
- 不分離 Jenkins view（兩個 job 仍歸同一個 team view `TCRT_{team_name}`）。
- 不改 suite job XML 模板本身（兩個 job 的 XML 內容相同，差異僅在 job 名與 Allure project）。

## Capabilities

### New Capabilities

（無；本變更修改既有 automation-hub 行為，不引入新 capability。）

### Modified Capabilities

- `automation-hub-script-management`: suite schema 新增 `ci_job_name_webhook`；suite 的 create / update / rename / delete 生命週期 SHALL 同時管理主 job 與（若存在）webhook job。
- `automation-hub-provider-framework`: CIProvider 的 suite job lifecycle 契約 SHALL 支援 trigger-scoped job（建立／更新／改名／刪除可指定 job 變體）；Jenkins adapter SHALL 據此管理兩個 job；Allure result adapter 的 project id 推導 SHALL 納入 trigger 來源。
- `automation-hub-run-orchestration`: run 的 `workflow_id` SHALL 反映實際觸發的 trigger-scoped job；report / Allure project 解析 SHALL 依 `triggered_by` 分流。
- `automation-hub-webhook-integration`: 「inbound webhook 觸發 suite」SHALL 改為觸發該 suite 的專屬 webhook job（不再複用主 job）。

## Impact

- **資料**：`automation_script_groups` +1 欄位（`ci_job_name_webhook`）；新 Alembic migration。Rollback 為 drop column；既有 run row 與既有單 job 行為不受影響。
- **服務層**：`script_group_service`（create / update / delete / `trigger_group_run` 路由 + 雙 job self-heal）、`webhook_service.trigger_suite_run`（觸發走 webhook job）、`allure_proxy._resolve_project_id` 與 reclaim helpers（`delete_project_for_group` / `delete_renamed_project` / `delete_projects_for_team`）。
- **Provider**：`providers/jenkins_ci.py`（create / update / rename / delete / view 對兩個 job）。
- **API / 序列化**：`AutomationScriptGroupResponse` 可選擇性增列 `ci_job_name_webhook`（read-only）；MCP suite 序列化（`models/mcp.py`）同步評估是否需揭露。觸發／歷史端點契約不變。
- **相容性**：未配置 webhook 的 suite 行為完全不變（webhook job 永不建立）；migration 非破壞、可 rollback。
- **測試 / 文件**：新增 webhook 觸發走 webhook job、雙 job 生命週期、Allure 分流的測試；更新 `docs/automation-workflow.md`、`docs/automation-webhook.md`。
