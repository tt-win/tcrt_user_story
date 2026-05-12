## 1. Data Model & Migration (P1)

- [ ] 1.1 於 `app/models/database_models.py` 新增 5 張 ORM 表：`TeamAutomationProvider`、`AutomationScript`、`AutomationScriptCaseLink`、`AutomationRun`、`AutomationWebhook`，含 enum / FK / 索引 / unique constraint
- [ ] 1.2 `TeamAutomationProvider`：`team_id` FK、`provider_slot` enum(`storage`/`ci`/`result`)、`provider_type` (varchar, 例如 `storage:github`)、`name`、`config_json` (TEXT)、`credentials_encrypted` (TEXT, AES-256-GCM)、`is_active`、timestamps；unique `(team_id, provider_slot, name)`
- [ ] 1.3 `AutomationScript`：`team_id`、`provider_id` FK、`name`、`description`、`script_format` enum、`ref_path`、`ref_branch`、`cached_content` (MEDIUMTEXT)、`cached_content_etag`、`last_synced_at`、`tags_json`、`created_by`、`updated_by`、timestamps；unique `(team_id, provider_id, ref_path, ref_branch)`
- [ ] 1.4 `AutomationScriptCaseLink`：`team_id` 索引、`automation_script_id` FK CASCADE、`test_case_id` FK → `test_cases.id` CASCADE、`link_type` enum、`note`、`created_by`、`created_at`；unique `(automation_script_id, test_case_id)`；index `(test_case_id)`
- [ ] 1.5 `AutomationRun`：`team_id`、`automation_script_id` FK、`provider_id` FK (ci slot)、`external_run_id` (varchar 120 index)、`external_run_url`、`status` enum(`QUEUED`/`RUNNING`/`SUCCEEDED`/`FAILED`/`CANCELLED`/`UNKNOWN`)、`triggered_by` enum、`triggered_by_user_id`、`triggered_by_webhook_id`、`tcrt_correlation_id` (uuid)、`ci_correlation_id`、`workflow_id`、`branch`、`inputs_json`、`report_url`、`started_at`、`finished_at`、`duration_ms`、`error_summary` (TEXT) timestamps
- [ ] 1.6 `AutomationWebhook`：`team_id`、`direction` enum(`INBOUND`/`OUTBOUND`)、`name`、`token` (varchar 64 unique)、`secret` (varchar 128)、`target_url`、`events_json`、`is_active`、`last_triggered_at`、`last_status`、timestamps
- [ ] 1.7 Alembic migration `alembic/versions/<hash>_add_automation_hub_tables.py`，含 indexes、unique、enum；downgrade 可還原
- [ ] 1.8 更新 `app/database_init.py` 的 `MAIN_REQUIRED_TABLES`；bootstrap 驗證 `AUTOMATION_PROVIDER_ENCRYPTION_KEY` 是否設定（若 `team_automation_providers` 表非空且金鑰缺失 → 阻擋啟動並提供生成指引）
- [ ] 1.9 新增 Pydantic schemas：`app/models/automation_provider.py`、`automation_script.py`、`automation_run.py`、`automation_webhook.py`、`automation_link.py`
- [ ] 1.10 `app/audit/__init__.py` 新增 `ResourceType.AUTOMATION_PROVIDER / AUTOMATION_SCRIPT / AUTOMATION_SCRIPT_LINK / AUTOMATION_RUN / AUTOMATION_WEBHOOK`

## 2. Provider Framework (P1)

- [ ] 2.1 `app/services/automation/providers/base.py`：定義三個 `Protocol`（StorageProvider / CIProvider / ResultProvider）+ 共用 dataclass（ScriptRef / ScriptContent / CommitRef / BranchRef / PullRequestRef / WorkflowRef / ExternalRunRef / RunStatusSnapshot / ArtifactRef）
- [ ] 2.2 `app/services/automation/provider_registry.py`：`{provider_type: provider_class}` 對照表 + `get_provider(team_id, slot)` 工廠
- [ ] 2.3 `app/services/automation/provider_credential_service.py`：AES-256-GCM 加解密；nonce per record；fetch from env `AUTOMATION_PROVIDER_ENCRYPTION_KEY`
- [ ] 2.4 `app/services/automation/providers/github_storage.py`：GitHub REST API；含 `list_scripts`（GET `/repos/{owner}/{repo}/contents/{path}` recursive）、`read_script`（GET contents + base64 decode + etag 處理）、`write_script`（PUT contents with sha）、`list_branches`、`create_pull_request`；支援 PAT 與 GitHub App auth
- [ ] 2.5 `app/services/automation/providers/local_git_storage.py`：local filesystem + `git` CLI subprocess（air-gapped fallback）
- [ ] 2.6 `app/services/automation/providers/github_actions_ci.py`：`list_workflows`、`trigger_run`（POST workflow_dispatches，注入 `tcrt_run_id` uuid input）、`get_run_status`（GET runs 配對）、`cancel_run`、`list_artifacts`
- [ ] 2.7 GH Actions 觸發後輪詢配對：60 秒內找 `inputs.tcrt_run_id` 相等的 run，找不到標 UNKNOWN 並允許 user 手動 reconcile
- [ ] 2.8 `app/services/automation/providers/jenkins_ci.py`：
  - 認證：Basic Auth (username + API token) 或 trigger token；自動 GET `/crumbIssuer/api/json` 取 CSRF crumb
  - `list_workflows`：GET `/api/json?tree=jobs[name,url,buildable]` 列 jobs
  - `trigger_run`：POST `/job/{name}/buildWithParameters?tcrt_run_id=...`；回應 `Location` header 拿 queue_item id
  - `get_run_status`：先查 queue（若尚未排入 build），再查 `/job/{name}/{build_id}/api/json`；狀態映射 `SUCCESS/FAILURE/UNSTABLE/ABORTED/building`
  - `cancel_run`：POST `/job/{name}/{build_id}/stop`
  - `list_artifacts`：GET `/job/{name}/{build_id}/api/json?tree=artifacts[*]`
- [ ] 2.9 Jenkins 配對：queue item → executable.url → build number；queue 中 cancelled 或 60 秒未上 build 都標 UNKNOWN
- [ ] 2.10 `app/services/automation/providers/allure_result.py`：依 `base_url` 與 `run_url_template` 組 URL；支援 `link` / `iframe` 兩種 mode；config 含 optional `project` 與 `dashboard_url`
- [ ] 2.11 Provider self-test：每個 provider 啟動時呼叫 `health_check()`（GH whoami / Jenkins `/me/api/json` / Allure base_url 200 check），結果寫入 `last_status`；admin UI 可看
- [ ] 2.12 Provider config schema：每個 provider 提供 Pydantic config model（GH: `{owner, repo, default_branch, auth_method, ...}`；Jenkins: `{base_url, auth_method, username, default_job_token, ...}`；Allure: `{base_url, run_url_template, embed_mode, project, dashboard_url}`），用於 settings UI validation 與 docs 自動生成

## 3. Provider Settings UI & API (P1)

- [ ] 3.1 `app/api/automation_providers.py`：CRUD 端點 + 設定驗證 + `POST .../test-connection` 觸發 health_check
- [ ] 3.2 `app/templates/automation_provider_settings.html`：admin 設定頁，依 provider type 動態渲染 config 表單（用 provider config schema 反射）
- [ ] 3.3 `app/static/js/automation-hub/providers/`：JS 模組，依 provider_type 渲染表單；test connection 按鈕
- [ ] 3.4 i18n 文案：每個 provider 的 label / description / help text
- [ ] 3.5 Audit：provider CRUD 寫 audit

## 4. Script Management API & UI (P2)

- [ ] 4.1 `app/api/automation_scripts.py`：CRUD（register script reference + manual fetch + 列表）+ 篩選（`?provider_id=&format=&linked_test_case_id=&q=`）+ cursor 分頁
- [ ] 4.2 `app/services/automation/script_service.py`：
  - register: 給 `provider_id + ref_path + ref_branch + name` 建立紀錄，立即呼叫 `read_script` 拉 cached_content + etag
  - sync: 強制重新 fetch；比對 etag，未變則不動
  - update_content: 寫入 git（透過 StorageProvider）→ 更新 cached_content
  - delete: TCRT 端刪 reference，不刪 git 檔案
- [ ] 4.3 自動同步策略：cached_content TTL 30 秒；list 頁載入時若超時自動 refresh
- [ ] 4.4 `app/api/automation_links.py`：M2M link CRUD（`POST /api/teams/{team_id}/automation-scripts/{script_id}/links`、`DELETE`、`PATCH`）；反向 `GET /api/teams/{team_id}/test-cases/{case_id}/linked-automation`
- [ ] 4.5 Service 層驗證：同 case 至多一支 script 標 PRIMARY；cascade 測試
- [ ] 4.6 `app/templates/automation_hub.html`：team 內 hub 入口頁，4 tabs（Scripts / Runs / Coverage / Settings）
- [ ] 4.7 `app/templates/automation_script_detail.html`：單 script 頁，含 metadata + CodeMirror 6 編輯器（讀 cached_content / 觸發 sync）+ linked test cases + 最近 runs
- [ ] 4.8 `app/static/js/automation-hub/scripts/`：list / detail / register modal / link-picker
- [ ] 4.9 編輯器整合：CodeMirror 6 via CDN（JS / Python / JSON modes），編輯完詢問「直接 commit / 開新分支 + PR」
- [ ] 4.10 `app/templates/team_management.html`：團隊卡片新增「Automation Hub」連結
- [ ] 4.11 `app/templates/test_case_management.html` + 對應 JS：case detail 新增「Automation」面板，列 linked scripts、last_run_status、跳 CI / report 連結；admin 可解除 link
- [ ] 4.12 i18n 文案
- [ ] 4.13 Audit：script CRUD、link CRUD 寫 audit

## 5. Run Orchestration (P2)

- [ ] 5.1 `app/api/automation_runs.py`：`POST /api/teams/{team_id}/automation-scripts/{script_id}/runs` 觸發；`GET .../runs`（列表）、`GET .../runs/{run_id}`（detail）、`POST .../runs/{run_id}/cancel`、`POST .../runs/{run_id}/reconcile`
- [ ] 5.2 `app/services/automation/run_service.py`：
  - trigger: 解析 script 所屬 CI provider（從 script.provider_ci_id 或 user 選擇）+ workflow → 呼叫 CIProvider.trigger_run（注入 tcrt_correlation_id）→ 寫 `automation_runs`
  - sync: 對 QUEUED/RUNNING runs 每 60 秒呼叫 `CIProvider.get_run_status` 對齊；終態時呼叫 `ResultProvider.get_run_report_url` 填 report_url
  - reconcile: 處理觸發後 60 秒配對失敗（標 UNKNOWN + 提供 user 介面手動關聯外部 run_id）
  - 同 team 多 CI provider：UI 在「執行」按鈕的 modal 顯式選擇 provider + workflow
- [ ] 5.3 `app/services/scheduler.py` 註冊 60 秒 sync job
- [ ] 5.4 `app/templates/automation_run_history.html`：執行歷史列表，跨 script、跨 workflow；篩選 status / branch / triggered_by；點開直接跳 CI 原生 UI（external_run_url）
- [ ] 5.5 Script detail 頁的「最近 5 筆 runs」區塊
- [ ] 5.6 「執行此 script」按鈕：modal 讓 user 選 branch + workflow inputs（若 workflow 有 declared inputs）
- [ ] 5.7 Cancel run：API 呼叫 `CIProvider.cancel_run` + 更新 status
- [ ] 5.8 Audit：run trigger / cancel 寫 audit

## 6. Result Provider Integration (P3)

- [ ] 6.1 Per-run report URL：run detail 顯示「在 Allure 中開啟」按鈕 → `AllureProvider.get_run_report_url(external_run_id)`
- [ ] 6.2 iframe embed mode（opt-in）：provider config 加 `embed_mode: link | iframe`；UI 依設定顯示 iframe 或 button；偵測到 X-Frame-Options DENY 時 fallback 為 link + 警示
- [ ] 6.3 Dashboard 連結：Hub 頁顯示「Team Dashboard」按鈕 → `AllureProvider.get_dashboard_url()`（若 config 有設）
- [ ] 6.4 Test case detail 的 Automation 面板：每筆 linked script 顯示 last_run 的 report 跳轉連結（Allure URL）
- [ ] 6.5 docs 提供 Allure 部署 pattern：GitHub Pages、S3 + CloudFront、公司內 nginx + history dir 保留
- [ ] 6.6 i18n 文案

## 7. Coverage Tab (P3)

- [ ] 7.1 `app/api/automation_coverage.py`：`GET /api/teams/{team_id}/automation-coverage` 計算「總 test case 數」、「已 PRIMARY 覆蓋數」、「已 COVERS 覆蓋數」、「未覆蓋清單」、「stale scripts」（30 天無 run）
- [ ] 7.2 Hub Coverage tab：渲染統計 + 未覆蓋 case 列表 + 一鍵「為此 case 連結既有 script」+ stale scripts 警示
- [ ] 7.3 30 天 trend：簡單 SVG line chart（純前端，不引外部 lib）
- [ ] 7.4 i18n 文案

## 8. MCP Read API (P3)

- [ ] 8.1 `app/models/mcp.py` 新增 schemas：`MCPAutomationScriptItem`、`MCPAutomationRunItem`、`MCPLinkedAutomationSummary`
- [ ] 8.2 `app/api/mcp.py` 新增端點：
  - `GET /api/mcp/teams/{team_id}/automation-scripts`（含 last_run_status、linked_test_case_numbers）
  - `GET /api/mcp/teams/{team_id}/automation-runs`（最近 N 筆）
  - `GET /api/mcp/teams/{team_id}/automation-coverage`（與 7.1 對齊但 read-only）
- [ ] 8.3 既有 `GET /api/mcp/teams/{team_id}/test-cases/{id}` 追加 `linked_automation_scripts` 欄位（向後相容）
- [ ] 8.4 MCP 端 audit 寫入
- [ ] 8.5 更新 `openspec/specs/mcp-read-api/spec.md`（archive 階段）

## 9. Webhook (Inbound + Outbound) (P4)

- [ ] 9.1 `app/api/automation_webhooks.py`：webhook CRUD（per team）+ 建立時一次性回 token / secret + fingerprint
- [ ] 9.2 `app/api/automation_webhooks_public.py`：`POST /api/v1/webhooks/ci/{token}/run-status`：HMAC 驗章 + idempotency（X-TCRT-Delivery）+ 更新 `automation_runs.status`
- [ ] 9.3 `app/services/automation/webhook_service.py`：outbound 發送 + 簽章（簡化，無 retry queue）
- [ ] 9.4 事件：`script.linked` / `script.unlinked` / `run.triggered` / `run.tracked` / `run.completed`
- [ ] 9.5 失敗只寫 audit + UI 警告（v1 不做 retry）
- [ ] 9.6 `app/templates/automation_webhook_config.html` + JS：webhook 設定頁，含「複製 curl 範例」、「發送測試 ping」
- [ ] 9.7 i18n + audit

## 10. Local Git Provider & Air-gapped Support (P5)

- [ ] 10.1 `providers/local_git_storage.py`：以 `git` CLI subprocess 讀寫；clone 預先 mount 的 working copy；fetch / pull / commit / push
- [ ] 10.2 設定欄位：`{ working_dir, remote_name, ssh_key_path, default_branch }`
- [ ] 10.3 Provider 本身不做 PR（只支援 commit + push）
- [ ] 10.4 文件：air-gapped 部署範例（GitLab self-hosted、Gitea + Jenkins）

## 11. Documentation

- [ ] 11.1 `docs/automation-hub-overview.md`：使用者 onboarding（從 extension 產出腳本 → register 到 TCRT → 連結 case → 觸發 → 看結果）
- [ ] 11.2 `docs/automation-provider-setup.md`：GitHub（PAT vs App）、LocalGit、GH Actions、Jenkins（API token / trigger token / CSRF crumb）、Allure 設定範例
- [ ] 11.3 `docs/automation-webhook.md`：inbound webhook payload / 簽章 / curl 範例；outbound 事件 schema
- [ ] 11.4 `docs/automation-workflow-templates/`：
  - `github-actions-playwright.yml`：含 `tcrt_run_id` input、Allure 上傳到 Pages、完成後 curl 回 TCRT webhook
  - `jenkinsfile-playwright.groovy`：含 `tcrt_run_id` 參數、Allure publishHTML、完成後 sh curl 回 TCRT webhook
- [ ] 11.5 `README.md` 新增 Automation Hub 章節與 `AUTOMATION_PROVIDER_ENCRYPTION_KEY` 環境變數說明
- [ ] 11.6 `docs/automation-security.md`：credential 加密、HMAC、Provider 認證選擇建議

## 12. Testing

- [ ] 12.1 `app/testsuite/automation/test_provider_registry.py`：註冊、查詢、未知 provider type 報錯
- [ ] 12.2 `app/testsuite/automation/test_provider_credential_service.py`：加解密、key 缺失行為、nonce 唯一性
- [ ] 12.3 `app/testsuite/automation/test_github_storage_provider.py`：mock GH API；list / read / write / etag 304 / error 處理
- [ ] 12.4 `app/testsuite/automation/test_local_git_storage_provider.py`：tmpdir + 本地 git；commit / list
- [ ] 12.5 `app/testsuite/automation/test_github_actions_ci_provider.py`：mock GH API；trigger + tcrt_run_id 配對、status sync、cancel
- [ ] 12.5.1 `app/testsuite/automation/test_jenkins_ci_provider.py`：mock Jenkins API；CSRF crumb、buildWithParameters、queue item 配對、build 狀態映射、cancel、artifact list
- [ ] 12.6 `app/testsuite/automation/test_script_service.py`：register、sync、edit-and-commit、edit-and-PR
- [ ] 12.7 `app/testsuite/automation/test_linkage_service.py`：M2M CRUD、PRIMARY 唯一、cascade
- [ ] 12.8 `app/testsuite/automation/test_run_service.py`：trigger、sync、reconcile UNKNOWN、cancel
- [ ] 12.9 `app/testsuite/automation/test_webhook_inbound.py`：HMAC 驗章、idempotency、status 轉換
- [ ] 12.10 `app/testsuite/automation/test_webhook_outbound.py`：簽章、事件 dispatch、失敗 audit
- [ ] 12.11 `app/testsuite/automation/test_mcp_endpoints.py`：MCP 端唯讀、coverage 計算、test case detail 反向欄位
- [ ] 12.12 手動 E2E：建立 GitHub PAT 設定 provider → register 一支 Playwright script → 連結 manual case → 觸發執行 → 收 webhook 回 → case detail 看到 SUCCEEDED + 報表連結

## 13. OpenSpec Sync & Archive

- [ ] 13.1 完成所有實作與測試後，執行 `openspec validate add-automation-hub`
- [ ] 13.2 同步 `openspec/specs/<capability>/spec.md`（5 新增 capability + mcp-read-api 修改）
- [ ] 13.3 執行 `openspec archive add-automation-hub`
