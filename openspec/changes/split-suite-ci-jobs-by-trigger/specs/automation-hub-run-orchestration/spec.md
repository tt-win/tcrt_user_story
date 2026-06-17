## ADDED Requirements

### Requirement: Webhook-triggered runs MUST execute on a dedicated CI job
同一 suite 的 run SHALL 依 `triggered_by` 路由到不同 CI job，使 webhook 觸發與 test-run-set（及未來 schedule / MCP）觸發在 Jenkins 端的 build 歷史與佇列物理隔離：

- `triggered_by == WEBHOOK` 的 run SHALL 觸發 suite 的 **webhook job**（`automation_script_groups.ci_job_name_webhook`，job 名 `tcrt_{team}_{suite}_hook`）。
- 其餘觸發來源 SHALL 觸發 suite 的**主 job**（`ci_job_name`）。
- webhook job SHALL **lazy 建立**：第一次 webhook 觸發時，透過既有 self-heal（`update_suite_job` → 404 → `create_suite_job`，帶 `job_suffix="_hook"`）建立並回填 `ci_job_name_webhook`；既有 suite 無需 backfill。
- run row 的 `workflow_id` SHALL 記錄實際觸發的 trigger-scoped job 名（webhook run 為 `*_hook`）。
- 路由 SHALL NOT 改變既有觸發 / 歷史 API 的對外契約（路徑、payload、回應不變）。

#### Scenario: Webhook trigger routes to the webhook job
- **WHEN** 一個 suite 經 inbound webhook 觸發（`triggered_by=WEBHOOK`）
- **THEN** run SHALL 在 `tcrt_{team}_{suite}_hook` job 執行，`workflow_id` SHALL 為該 webhook job 名

#### Scenario: Test Run Set trigger routes to the primary job
- **WHEN** 同一 suite 經 Test Run Set 觸發（`triggered_by=USER`）
- **THEN** run SHALL 在主 job `tcrt_{team}_{suite}` 執行，`workflow_id` SHALL 為主 job 名

#### Scenario: First webhook trigger lazily creates the webhook job
- **WHEN** 一個 `ci_job_name_webhook` 為 NULL 的 suite 首次被 webhook 觸發
- **THEN** TCRT SHALL 透過 self-heal 在 CI 端建立 webhook job，回填 `ci_job_name_webhook`，並在該 job 執行 run
