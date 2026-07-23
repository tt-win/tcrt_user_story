## 1. Data model + migration

- [ ] 1.1 在 `app/models/database_models.py` 的 `AutomationScriptGroup` 新增 `ci_job_name_webhook = Column(String(200), nullable=True)`
- [ ] 1.2 新增 Alembic migration（chained 到目前 head）：`add_column automation_script_groups.ci_job_name_webhook`；`downgrade` 為 drop column
- [ ] 1.3 確認 `database_init.py` 的 bootstrap schema 與 model 一致（若以 create_all 建表則自動涵蓋）

## 2. Jenkins provider：job_suffix variant

- [ ] 2.1 `_suite_job_name` 新增 `job_suffix: str = ""` 參數，附加於推導名之後
- [ ] 2.2 `create_suite_job` / `update_suite_job` 新增 `job_suffix: str = ""`，傳遞給 `_suite_job_name`，view 加入兩個 variant 共用
- [ ] 2.3 確認 `update_suite_job` 的 `existing_job_name` + `doRename` 對 suffixed job 正確運作（不存在時拋 404 走 create）

## 3. script_group_service：路由 + 雙 job 生命週期

- [ ] 3.1 `trigger_group_run` 依 `triggered_by == WEBHOOK` 選 `(field, suffix)`，self-heal 對應 job 並回填正確欄位；`trigger_run` 與 `workflow_id` 用解析出的 job 名
- [ ] 3.2 `update_group`：`ci_job_name_webhook` 非空時，對 webhook job 也呼叫 `update_suite_job(existing_job_name=ci_job_name_webhook, job_suffix="_hook")` 同步/改名
- [ ] 3.3 `delete_group`：`ci_job_name_webhook` 非空時，一併 `delete_suite_job(...,ci_job_name_webhook)`
- [ ] 3.4 `create_group` 維持只建主 job（lazy 不動）

## 4. Allure proxy：trigger-scoped project + reclaim

- [ ] 4.1 `_resolve_project_id` 在 `run.triggered_by == WEBHOOK` 時於 `suite_slug` 後附加 `-webhook`
- [ ] 4.2 `delete_project_for_group` / `delete_renamed_project` / `delete_projects_for_team` reclaim primary 與 webhook 兩個 variant

## 5. 序列化

- [ ] 5.1 `AutomationScriptGroupResponse` 與 `script_group_to_dict` 增列 `ci_job_name_webhook`（read-only）
- [ ] 5.2 評估 MCP suite 序列化是否揭露（預設不揭露）

## 6. 測試

- [ ] 6.1 webhook 觸發走 `_hook` job、`workflow_id` 為 webhook job、首次觸發 lazy 建立並回填欄位
- [ ] 6.2 test-run-set 觸發仍走主 job（回歸）
- [ ] 6.3 改名 / 刪除有 webhook job 的 suite → 兩個 job 同步；無 webhook job 時只動主 job
- [ ] 6.4 Allure：webhook run 解析到 `-webhook` project；reclaim 兩個 variant

## 7. 文件

- [ ] 7.1 更新 `docs/automation-workflow.md`、`docs/automation-webhook.md`：說明雙 job 與 Allure 分流

## 8. View 管理（無開關）

- [ ] 8.1 移除 `JenkinsCIConfig.auto_manage_views`；`create_suite_job` / `update_suite_job` 一律呼叫 `_ensure_view_contains_job`（兩個 variant 同進 `TCRT_{team_name}`）
- [ ] 8.2 清掉 provider 測試與 docs 中的 `auto_manage_views`（含 provider-setup 設定表）

## 9. Team rename re-sync（併入）

- [ ] 9.1 Provider 加 `delete_view`（jenkins_ci + base Protocol）
- [ ] 9.2 `AutomationScriptGroupService.resync_team_after_rename`：逐 suite rename 主+webhook job、掛新 view、刪舊 view、reclaim 舊 Allure
- [ ] 9.3 `allure_proxy.delete_projects_for_team_rename`（舊 team slug 的 primary + webhook 兩 variant）
- [ ] 9.4 `teams.py update_team`：偵測 `name` 變更 → best-effort re-sync（獨立 write，不擋改名）

## 10. 驗證

- [ ] 10.1 `pytest app/testsuite -q`（聚焦 automation suite / webhook / allure / provider 相關）全綠
- [ ] 10.2 `openspec validate split-suite-ci-jobs-by-trigger` 通過
