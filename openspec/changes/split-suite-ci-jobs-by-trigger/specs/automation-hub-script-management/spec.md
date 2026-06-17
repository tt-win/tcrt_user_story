## MODIFIED Requirements

### Requirement: System MUST support automation script groups (suites)
資料表 `automation_script_groups` SHALL 提供 script 的邏輯分組，用於將多個 script 組合成一個可執行的 suite：

- `id` PK
- `team_id` FK NOT NULL, indexed
- `name` VARCHAR(200) NOT NULL
- `description` TEXT nullable
- `script_paths_json` TEXT NOT NULL（script ref_path 陣列，如 `["tests/test_login.py","tests/test_logout.py"]`）
- `ci_job_name` VARCHAR(200) nullable（**主** CI job/workflow 名稱，服務 Test Run Set（及未來 schedule / MCP）觸發；由 TCRT 自動管理）
- `ci_job_name_webhook` VARCHAR(200) nullable（**webhook 觸發專屬**的 CI job 名稱；**lazy 建立**，僅在該 suite 第一次被 inbound webhook 觸發時才產生，未觸發過維持 NULL）
- `ci_job_type` ENUM(`GITHUB_ACTIONS`, `JENKINS`) nullable
- `created_by`, `updated_by`, timestamps

UniqueConstraint `(team_id, name)`。

API：
- `POST /api/teams/{team_id}/automation-script-groups`：建立 group；service SHALL 呼叫 `CIProvider.create_suite_job()` 建立**主 job**。建立時 SHALL NOT 預先建立 webhook job。
- `PUT /api/teams/{team_id}/automation-script-groups/{group_id}`：更新 metadata 與 scripts；service SHALL 呼叫 `CIProvider.update_suite_job()` 同步主 job；若該 suite 已有 webhook job（`ci_job_name_webhook` 非空），SHALL 一併同步/改名 webhook job。
- `DELETE /api/teams/{team_id}/automation-script-groups/{group_id}`：刪除 group；service SHALL 呼叫 `CIProvider.delete_suite_job()` 清理主 job，並在 `ci_job_name_webhook` 非空時一併清理 webhook job。
- `GET /api/teams/{team_id}/automation-script-groups`：列表
- `GET /api/teams/{team_id}/automation-script-groups/{group_id}`：詳情，含 scripts 列表與最近 runs

#### Scenario: Create suite syncs only the primary CI job
- **WHEN** QA 建立 suite「Login Regression」，包含 3 個 scripts
- **THEN** TCRT SHALL 自動在 CI 端建立**主 job**（Jenkins：`tcrt_{team}_{suite}`）並記錄於 `ci_job_name`
- **AND** `ci_job_name_webhook` SHALL 維持 NULL（webhook job 不在建立時產生）

#### Scenario: Update suite syncs to CI
- **WHEN** QA 從 suite 移除一個 script
- **THEN** TCRT SHALL 呼叫 `CIProvider.update_suite_job()` 更新主 job 配置，反映新的 test paths

#### Scenario: Rename suite syncs both jobs when webhook job exists
- **WHEN** QA 改名一個 `ci_job_name_webhook` 非空的 suite
- **THEN** TCRT SHALL 將主 job 與 webhook job 各自 `doRename` 到新名稱，不留下孤兒 job
- **WHEN** QA 改名一個尚無 webhook job（`ci_job_name_webhook` 為 NULL）的 suite
- **THEN** TCRT SHALL 只改主 job，不建立 webhook job

#### Scenario: Delete suite cleans up CI
- **WHEN** QA 刪除 suite
- **THEN** TCRT SHALL 呼叫 `CIProvider.delete_suite_job()` 清理主 job；若 `ci_job_name_webhook` 非空 SHALL 一併清理 webhook job，不留下孤兒

## ADDED Requirements

### Requirement: Team rename MUST re-sync the team's suite jobs, view, and Allure projects
Jenkins view 名 embed team name、suite job 名與 Allure project id embed team slug，皆由 team 名推導，因此 team 改名會孤兒化舊 view / 舊 job / 舊 project。`PUT /api/teams/{team_id}` 偵測到 `name` 變更時 SHALL 對該 team 每個 suite：

- 將主 job 與（若存在）webhook job 以 `doRename` 搬到新 team 名（保留 build 歷史），並加入新 team view `TCRT_{新名}`；
- 刪除孤兒的舊 team view `TCRT_{舊名}`；
- reclaim 舊 team slug 下每個 suite 的 primary 與 webhook Allure project。

此 re-sync SHALL 為 **best-effort**：CI / report server 失敗 SHALL NOT 讓改名失敗或 rollback；逐 suite 隔離，單一 suite 失敗不影響其餘。

#### Scenario: Team rename relocates jobs and migrates the view
- **WHEN** team 從「A」改名為「B」，其下某 suite 同時有主 job 與 webhook job
- **THEN** 兩個 job SHALL `doRename` 到以「B」推導的新名並加入新 view `TCRT_B`
- **AND** 舊 view `TCRT_A` SHALL 被刪除
- **AND** 舊 team slug 下該 suite 的 primary 與 webhook Allure project SHALL 被 reclaim

#### Scenario: Team rename re-sync is non-fatal
- **WHEN** 改名當下 CI 或 Allure 不可用
- **THEN** team 改名本身 SHALL 仍成功；re-sync 失敗 SHALL 僅記 log，不 rollback 改名

#### Scenario: Team rename recreates a missing job under the new name
- **WHEN** 改名時某 suite 的舊 job 在 CI 上已不存在（rename 探測回 404）
- **THEN** re-sync SHALL 改以新 team 名**建立**該 job（取代 rename），使 suite 仍取得有效 job，不視為失敗

#### Scenario: No-op when team name unchanged
- **WHEN** `PUT /api/teams/{team_id}` 未變更 `name`
- **THEN** SHALL NOT 觸發任何 CI / Allure re-sync
