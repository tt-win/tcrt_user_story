## Context

每個 automation suite（`AutomationScriptGroup`）目前在 CI 端只有一個 Jenkins job，job 名由 `JenkinsCIProvider._suite_job_name()` 以 `job_name_template = "tcrt_{team_slug}_{suite_slug}"` 推導，並存在 `automation_script_groups.ci_job_name`。

兩種觸發來源最終都呼叫 `AutomationScriptGroupService.trigger_group_run()` → `provider.trigger_run(group.ci_job_name, ...)`：

- Test Run Set：`TestRunSetAutomationService` 以 `triggered_by=USER`、`test_run_set_id=<id>` 呼叫。
- Inbound webhook：`AutomationWebhookService.trigger_suite_run()` 以 `triggered_by=WEBHOOK`、`triggered_by_webhook_id=<id>` 呼叫。

兩者打**同一個 job**，且 Allure project id 由 `allure_proxy._resolve_project_id()` 以 `team_slug + suite_slug`（與 job 名無關）推導，因此 build 歷史、佇列、Allure 報表趨勢全部混在一起。

**約束**：
- CI provider 為 org-scoped；job 名須在 render 時才以 team context 展開。
- Jenkins 無 rename API 以外的安全改名，改名走 `doRename`；Allure 無 rename API，改名等於丟棄舊 project。
- suite 名在 team 內唯一（既有不變式）。
- 既有 run row 與既有單 job 的報表不可被破壞。

## Goals / Non-Goals

**Goals**
- 每個 suite 的 webhook 觸發與 test-run-set 觸發在 **Jenkins job** 與 **Allure project** 兩層物理隔離。
- 既有 suite 不需 backfill；未用 webhook 的 suite 行為與成本完全不變。
- 非破壞性 migration，可 rollback。

**Non-Goals**
- 不改觸發 / 歷史 API 對外契約。
- schedule / MCP 觸發仍走主 job（未來若要再分開另議）。
- 不分離 Jenkins view：兩個 job 同屬 `TCRT_{team_name}` view。view 管理改為**一律自動建立／維護**（移除 `auto_manage_views` 開關），不再可關閉。
- 不改 suite job XML 模板內容（兩個 job 的 XML 相同）。

## Decisions

### D1. 第二個 job 用 `_hook` 後綴，而非新模板

webhook job 名 = 主 job 名 + `_hook`（例：`tcrt_qa_login-regression_hook`）。

- 作法：`_suite_job_name()` / `create_suite_job()` / `update_suite_job()` 新增 `job_suffix: str = ""` 參數；provider 對 suffix **無語意認知**（只是字串），由 service 層決定何時傳 `"_hook"`。
- 保留 `tcrt_` 前綴 → `list_suite_jobs()` 既有 discovery 不受影響。
- **Alternative**：另開 `webhook_job_name_template` 設定。否決：兩個可配置模板易漂移、且 provider 不該知道「webhook」這個業務語意。

### D2. 觸發來源 → job 的路由放在 `trigger_group_run()`

```
is_webhook = triggered_by == WEBHOOK
job_suffix = "_hook" if is_webhook else ""
field      = "ci_job_name_webhook" if is_webhook else "ci_job_name"
```

self-heal（update→404→create）改成作用在「該來源的 job」上，結果寫回對應欄位；`trigger_run()` 與 run row 的 `workflow_id` 都用解析出的 job 名。

- **Alternative**：在 `webhook_service` 直接決定 job 名。否決：job 名推導屬於 provider/service 職責，且 self-heal、改名同步都集中在 `trigger_group_run` / `update_group`，分散會重複邏輯。

### D3. webhook job 採 lazy 建立，重用既有 self-heal

webhook job **不在 suite 建立時建**，而在**第一次 webhook 觸發**時，由 `trigger_group_run` 的 self-heal 自動建立（`update_suite_job` 對不存在的 job 拋 404 → fallback `create_suite_job`）。`existing_job_name` 傳 `group.ci_job_name_webhook`（首次為 `None` → 不改名、直接走 create 路徑）。

- 大多數 suite 沒有 webhook，避免為它們開無用的第二個 job。
- 既有 suite 零 backfill。

### D4. Allure project 以 `-webhook` 後綴分流

webhook run 的 project id：在 `suite_slug` 後接 `-webhook`（例 project `qa-login-regression-webhook`），沿用既有 `project_id_template` 機制，不動 config。

- `_resolve_project_id()` 依 `run.triggered_by == WEBHOOK` 決定是否加後綴。
- reclaim（delete / rename）須同時清 **primary 與 webhook 兩個 variant**：`delete_project_for_group` / `delete_renamed_project` / `delete_projects_for_team` 各對兩個 variant 各打一次 best-effort delete（404 視為成功）。
- **Alternative**：把 trigger 併入 `suite_id`。否決：`suite_id` 多處作為穩定鍵，改它牽連較廣；改 `suite_slug` 後綴最局部。

### D5. 資料模型：新增 `ci_job_name_webhook` 欄位

`automation_script_groups` 新增 `ci_job_name_webhook VARCHAR(200) NULL`。`None` 表示「此 suite 尚未有 webhook job」。

- **Alternative**：從主 job 名衍生 `{ci_job_name}_hook` 而不存欄位。否決：Jenkins 可能正規化 job 名、改名後衍生不可靠；顯式儲存與既有 `ci_job_name` 模式一致，也讓 delete 能精準帶名。

### D6. Team rename → best-effort re-sync（併入本 change）

team 改名後，view 名（embed team name）、job 名與 Allure project（embed team slug）會孤兒化。`update_team` 偵測 `name` 變更 → 以**獨立、best-effort** 的 write 呼叫 `AutomationScriptGroupService.resync_team_after_rename`：逐 suite `doRename` 主 + webhook job 到新名並掛新 view、刪舊 view、reclaim 舊 Allure project；CI / report 失敗只記 log，不 rollback 改名。新增 provider 方法 `delete_view`（清舊 view）。

- **Alternative**：lazy（下次觸發才補）。否決：舊 view / job / project 會長期殘留成孤兒，且新舊並存易混淆。
- **Alternative**：在同一個 rename 交易內同步。否決：對 Jenkins/Allure 的多次 HTTP 失敗會 rollback 改名；改用獨立 best-effort write 隔離。

## Risks / Trade-offs

- **[改名時 webhook job 漏改 → 孤兒 job]** → `update_group` 在 `ci_job_name_webhook` 非空時，對 webhook job 也做 `update_suite_job(existing_job_name=ci_job_name_webhook, job_suffix="_hook")`，與主 job 同步改名。
- **[webhook job 自我修復誤判]** → 沿用主 job 已驗證的 `_job_exists` 探針 + update→404→create 流程，不另寫路徑。
- **[Allure variant reclaim 殘留]** → reclaim 一律對兩個 variant 各打一次；project 不存在回 404 當成功，故對「從未產生 webhook 報表」的 suite 也安全。
- **[兩個 job 同 view 顯示略增雜訊]** → 可接受；view 隔離列為非目標。
- **[並發：首次 webhook 觸發同時也被 test-run-set 觸發]** → 兩者寫不同欄位、建不同 job，無互相覆寫；self-heal 為冪等。

## Migration Plan

1. Alembic migration：`automation_script_groups` add column `ci_job_name_webhook`（nullable，無預設）。既有 row 維持 `NULL`。
2. 部署後：既有 suite 的 webhook job 於下次 webhook 觸發時 lazy 建立；primary job 與既有報表不受影響。
3. **Rollback**：migration `downgrade` 為 drop column。回滾後 webhook 觸發回退為走主 job（行為退回變更前），不需資料清理；Jenkins 上已建立的 `_hook` job 與 `-webhook` Allure project 為孤兒，可人工或留待後續清理（不影響功能）。

## Open Questions

- MCP suite 序列化（`models/mcp.py`）是否需揭露 `ci_job_name_webhook`？預設先不揭露（read API 以 suite 業務語意為主，job 名屬 CI 細節），如有需求再加。
