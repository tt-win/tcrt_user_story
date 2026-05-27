## 1. Data Model & Migration (P1)

- [x] 1.1 於 `app/models/database_models.py` 新增 5 張 ORM 表：`TeamAutomationProvider`、`AutomationScript`、`AutomationScriptCaseLink`、`AutomationRun`、`AutomationWebhook`，含 enum / FK / 索引 / unique constraint
- [x] 1.2 `TeamAutomationProvider`：`team_id` FK、`provider_slot` enum(`storage`/`ci`/`result`)、`provider_type` (varchar, 例如 `storage:github`)、`name`、`config_json` (TEXT)、`credentials_encrypted` (TEXT, AES-256-GCM)、`is_active`、timestamps；unique `(team_id, provider_slot, name)`
- [x] 1.3 `AutomationScript`：`team_id`、`provider_id` FK、`name`、`description`、`script_format` enum、`ref_path`、`ref_branch`、`cached_content` (MEDIUMTEXT)、`cached_content_etag`、`last_synced_at`、`tags_json`、`preferred_runner_label` (VARCHAR(100))、`created_by`、`updated_by`、timestamps；unique `(team_id, provider_id, ref_path, ref_branch)`
- [x] 1.4 `AutomationScriptCaseLink`：`team_id` 索引、`automation_script_id` FK CASCADE、`test_case_id` FK → `test_cases.id` CASCADE、`link_type` enum、`note`、`created_by`、`created_at`；unique `(automation_script_id, test_case_id)`；index `(test_case_id)`
- [x] 1.5 `AutomationRun`：`team_id`、`automation_script_id` FK、`provider_id` FK (ci slot)、`external_run_id` (varchar 120 index)、`external_run_url`、`status` enum(`QUEUED`/`RUNNING`/`SUCCEEDED`/`FAILED`/`CANCELLED`/`UNKNOWN`)、`triggered_by` enum、`triggered_by_user_id`、`triggered_by_webhook_id`、`tcrt_correlation_id` (uuid)、`ci_correlation_id`、`workflow_id`、`branch`、`inputs_json`、`runner_label` (VARCHAR(100))、`report_url`、`started_at`、`finished_at`、`duration_ms`、`error_summary` (TEXT) timestamps
- [x] 1.6 `AutomationWebhook`：`team_id`、`direction` enum(`INBOUND`/`OUTBOUND`)、`name`、`token` (varchar 64 unique)、`secret` (varchar 128)、`target_url`、`events_json`、`is_active`、`last_triggered_at`、`last_status`、timestamps
- [x] 1.7 Alembic migration `alembic/versions/<hash>_add_automation_hub_tables.py`，含 indexes、unique、enum；downgrade 可還原
- [x] 1.8 更新 `app/database_init.py` 的 `MAIN_REQUIRED_TABLES`；bootstrap 驗證 `AUTOMATION_PROVIDER_ENCRYPTION_KEY` 是否設定（若 `team_automation_providers` 表非空且金鑰缺失 → 阻擋啟動並提供生成指引）
- [x] 1.9 新增 Pydantic schemas：`app/models/automation_provider.py`、`automation_script.py`、`automation_run.py`、`automation_webhook.py`、`automation_link.py`
- [x] 1.10 `app/audit/__init__.py` 新增 `ResourceType.AUTOMATION_PROVIDER / AUTOMATION_SCRIPT / AUTOMATION_SCRIPT_LINK / AUTOMATION_RUN / AUTOMATION_WEBHOOK`
- [x] 1.11 follow-up migration `a8f2d6c9e0b1` 新增 `automation_smart_scan_runs` 與 `automation_webhook_deliveries`，並同步 `database_init.py` 必要表清單

## 2. Provider Framework (P1)

- [x] 2.1 `app/services/automation/providers/base.py`：定義三個 `Protocol`（StorageProvider / CIProvider / ResultProvider）+ 共用 dataclass（ScriptRef / ScriptContent / CommitRef / BranchRef / PullRequestRef / WorkflowRef / ExternalRunRef / RunStatusSnapshot / ArtifactRef）
- [x] 2.2 `app/services/automation/provider_registry.py`：`{provider_type: provider_class}` 對照表 + `get_provider(team_id, slot)` 工廠
- [x] 2.3 `app/services/automation/provider_credential_service.py`：AES-256-GCM 加解密；nonce per record；fetch from env `AUTOMATION_PROVIDER_ENCRYPTION_KEY`
- [x] 2.4 `app/services/automation/providers/github_storage.py`：GitHub REST API；含 `list_scripts`（GET `/repos/{owner}/{repo}/contents/{path}` recursive）、`read_script`（GET contents + base64 decode + etag 處理）、`write_script`（PUT contents with sha）、`list_branches`、`create_pull_request`；支援 PAT 與 GitHub App auth
- [x] 2.5 `app/services/automation/providers/local_git_storage.py`：local filesystem + `git` CLI subprocess（air-gapped fallback）
- [x] 2.6 `app/services/automation/providers/github_actions_ci.py`：`list_workflows`、`list_runners`（GET `/repos/{owner}/{repo}/actions/runners`）、`trigger_run`（POST workflow_dispatches，注入 `tcrt_run_id` uuid input）、`get_run_status`（GET runs 配對）、`cancel_run`、`list_artifacts`
- [x] 2.7 GH Actions 觸發後輪詢配對：60 秒內以 workflow + branch + event + 建立時間做 best-effort 配對；GitHub run list API 不回傳 workflow_dispatch inputs，`tcrt_run_id` 保留為排查 / 後續 reconcile 線索；找不到標 UNKNOWN 並允許 user 手動 reconcile
- [x] 2.8 `app/services/automation/providers/jenkins_ci.py`：
  - 認證：Basic Auth (username + API token) 或 trigger token；自動 GET `/crumbIssuer/api/json` 取 CSRF crumb
  - `list_workflows`：GET `/api/json?tree=jobs[name,url,buildable]` 列 jobs
  - `list_runners`：GET `/computer/api/json?tree=computer[displayName,idle,offline,assignedLabels[name]]` 列 nodes/agents；映射為 `RunnerRef`
  - `trigger_run`：POST `/job/{name}/buildWithParameters?tcrt_run_id=...&NODE_LABEL=...`；回應 `Location` header 拿 queue_item id；`NODE_LABEL` 傳入目標 node label
  - `get_run_status`：先查 queue（若尚未排入 build），再查 `/job/{name}/{build_id}/api/json`；狀態映射 `SUCCESS/FAILURE/UNSTABLE/ABORTED/building`
  - `cancel_run`：POST `/job/{name}/{build_id}/stop`
  - `list_artifacts`：GET `/job/{name}/{build_id}/api/json?tree=artifacts[*]`
- [x] 2.9 Jenkins 配對：queue item → executable.url → build number；queue 中 cancelled 或 60 秒未上 build 都標 UNKNOWN
- [x] 2.10 `app/services/automation/providers/allure_result.py`：依 `base_url` 與 `run_url_template` 組 URL；支援 `link` / `iframe` 兩種 mode；config 含 optional `project` 與 `dashboard_url`
- [x] 2.11 Provider self-test：每個 provider 啟動時呼叫 `health_check()`（GH whoami / Jenkins `/me/api/json` / Allure base_url 200 check），結果寫入 `last_status`；admin UI 可看
- [x] 2.12 Provider config schema：每個 provider 提供 Pydantic config model（GH: `{owner, repo, default_branch, default_runner_label, auth_method, ...}`；Jenkins: `{base_url, auth_method, username, default_job_token, default_runner_label, auto_manage_views, view_name_template, job_name_template, ...}`；Allure: `{base_url, run_url_template, embed_mode, project, dashboard_url}`），用於 settings UI validation 與 docs 自動生成
- [x] 2.13 `github_actions_ci.py` 新增 suite job 管理：`create_suite_job`（寫入 `.github/workflows/tcrt-suite-{id}.yml`）、`update_suite_job`、`delete_suite_job`、`list_suite_jobs`；內建 Jinja2 YAML 模板
- [x] 2.14 `jenkins_ci.py` 新增 suite job 管理：`create_suite_job`（`createItem` + `addJobToView`）、`update_suite_job`、`delete_suite_job`、`list_suite_jobs`；內建 Jinja2 config.xml 模板；支援 `auto_manage_views` 自動建立 team view
- [x] 2.15 `app/services/automation/templates/`：Jinja2 模板目錄，含 `github-actions-suite.yml.j2`、`jenkins-suite-config.xml.j2`；模板變數：`suite_id`、`suite_name`、`test_paths`、`default_runner_label`、`tcrt_webhook_url_placeholder`

## 3. Provider Settings UI & API (P1)

- [x] 3.1 `app/api/automation_providers.py`：CRUD 端點 + 設定驗證 + `POST .../test-connection` 觸發 health_check
- [x] 3.2 `app/templates/automation_provider_settings.html`：admin 設定頁，依 provider type 動態渲染 config 表單（用 provider config schema 反射）
- [x] 3.3 `app/static/js/automation-hub/providers/`：JS 模組，依 provider_type 渲染表單；test connection 按鈕
- [x] 3.4 i18n 文案：每個 provider 的 label / description / help text
- [x] 3.5 Audit：provider CRUD 寫 audit

## 4. Script Auto-Discovery & Suite Management (P2)

- [x] 4.1 `app/api/automation_scripts.py`：唯讀端點（列表 / 詳情 / sync 觸發）+ 篩選 + cursor 分頁；**無 register / create endpoint**
  - `GET /api/teams/{team_id}/automation-scripts`：從 `automation_scripts` 快取表讀取
  - `GET /api/teams/{team_id}/automation-scripts/{script_id}`：詳情含 cached_content
  - `POST /api/teams/{team_id}/automation-scripts/sync`：觸發 auto-discovery
- [x] 4.1.1 `POST /api/teams/{team_id}/automation-scripts/sync`：先解析 `tcrt-automation.yml`（若存在）取得 effective tests path，否則使用 provider config 的 `scan_path`（預設 `"tests/"`）；呼叫 `StorageProvider.list_scripts(path, recursive=True)` → 比對現有 `automation_scripts` → upsert（新增/更新/標記 stale）→ 回傳掃描摘要（新增 N / 更新 M / 移除 K）
- [x] 4.2 `app/services/automation/script_service.py`：
  - auto_discover: 掃描 `StorageProvider.list_scripts()` → 比對 DB → upsert `automation_scripts`（name 預設為檔案名稱，script_format 從副檔名推斷：`.py` → PLAYWRIGHT_PY_ASYNC / PYTEST）
  - sync_single: 強制重新 fetch 單一 script cached_content；比對 etag
  - delete: TCRT 端刪快取紀錄，不刪 git 檔案；下次 auto_discover 會重新出現
  - update_metadata: 更新 name / description / preferred_runner_label（不影響 git 檔案）
- [x] 4.3 自動同步策略 — 首次進入 Suites tab `state.scripts.length === 0` 時 `loadAll()` 自動以 `silent: true` 觸發 `syncScripts`（[suites/main.js](app/static/js/automation-hub/suites/main.js)，session-scope guard 避免空 repo 死循環）；背景每小時自動掃描由 [automation_background_manager](app/services/automation/background.py) 的 `_script_discovery_loop` 處理；cached_content 由「點預覽」時 fetch + Rescan 按鈕手動刷新（30s TTL 概念落地為「terminal 後仍可手動 sync」+ 背景每小時全量 rediscover）
- [x] 4.4 `app/api/automation_links.py`：M2M link CRUD（`POST /api/teams/{team_id}/automation-scripts/{script_id}/links`、`DELETE`、`PATCH`）；反向 `GET /api/teams/{team_id}/test-cases/{case_id}/linked-automation`
- [x] 4.5 Service 層驗證：同 case 至多一支 script 標 PRIMARY；cascade 測試
- [x] 4.6 `app/templates/automation_hub.html`：team 內 hub 入口頁，3 tabs（**Suites** / Runs / Coverage / Settings）— **無 Scripts tab**
- [x] 4.7 `app/templates/automation_hub.html` Suites tab：左側 GitHub 檔案樹（`StorageProvider.list_scripts()` 結果，可展開 read-only preview）+ 右側 Suite 列表；檔案可勾選用於組合 suite
- [x] 4.8 `app/static/js/automation-hub/suites/`：GitHub 檔案樹元件 / suite 列表 / suite detail / 檔案勾選與組合邏輯
- [x] 4.8.1 Suite 建立流程：勾選左側檔案 → 點「+ New Suite」→ 輸入名稱 → 確認 → 呼叫 `POST .../automation-script-groups` → 後端自動呼叫 `CIProvider.create_suite_job()`
- [x] 4.9 Read-only preview「請使用 IDE 編輯」提示 — preview 展開區塊底部新增 `.automation-preview-hint` 提示文字 + `<pre>` title hover 提示；i18n key `automationHub.scripts.editInIde` 三語齊備。**Scope 簡化**：未引入 CodeMirror 6（純前端 `<pre>` 已能呈現 cached_content；引入 CodeMirror 為純視覺加分、與「git 才是 source of truth」設計目標重複，避開額外依賴）
- [x] 4.10 `app/templates/team_management.html`：團隊卡片新增「Automation Hub」連結
- [x] 4.11 case detail 「Automation」面板（read-only first pass）：HTML panel 加在 [test_case_management.html](app/templates/test_case_management.html) 附件區域下、JS 模組 [automation-panel.js](app/static/js/test-case-management/automation-panel.js) 在 modal 開啟時用 `record_id` 抓 `/api/teams/{team_id}/test-cases/{case_identifier}/linked-automation`（endpoint 改名 + 支援 lark string / numeric id 雙模式內部解析）；顯示 link_type badge / name / format / last_run_status badge / last_run 時間 + 跳 CI 與報表連結；含「Manage in Automation Hub」深連結；i18n 三語齊備；CSS 新增 `automation-panel-*` 樣式。**未做**：admin inline unlink / 從 case 內 picker 連結新 script（picker 牽涉到太多 UX 細節，留待 §4.5 Smart Scan 後一起設計）
- [x] 4.12 i18n 文案 — 三語 locales 已隨各 §4 / §5 / §6 / §7 / §8 / §9 任務增量補齊（`automationHub.scripts.*` / `automationHub.suites.*` / `automationHub.runs.*` / `automationHub.coverage.*` / `automationHub.settings.*` / `automationHub.dashboard.*` / `automationHub.webhooks.*` / `automationHub.providers.*` + `testCase.automation.*`），含 `editInIde / toggleDetail / detailEmpty / detailRecentRuns / lastRuns / noRuns / runsLoadFailed / openInCi / report / openDashboard` 等本輪新增 key
- [x] 4.13 Audit：script auto-discovery、link CRUD、suite CRUD 寫 audit
- [x] 4.14 `automation_script_groups` 資料表與 ORM：含 `team_id`、`name`、`description`、`script_paths_json`、`ci_job_name`、`ci_job_type`、timestamps
- [x] 4.15 `app/api/automation_script_groups.py`：Suite CRUD（`POST .../automation-script-groups`、`PUT`、`DELETE`、`GET`）+ suite 觸發執行（`POST .../automation-script-groups/{group_id}/runs`）
- [x] 4.16 `app/services/automation/script_group_service.py`：
  - create_group: 建立 group → 呼叫 `CIProvider.create_suite_job()` 在 CI 端建立對應 job/workflow → 寫入 `ci_job_name`
  - update_group: 更新 group scripts → 呼叫 `CIProvider.update_suite_job()` 同步 CI 端
  - delete_group: 刪除 group → 呼叫 `CIProvider.delete_suite_job()` 清理 CI 端
  - validate_script_paths: 確認所有 script paths 存在於 provider
- [x] 4.17 Suite UI 細節 — Suites tab 主介面（左 GitHub 檔案樹 + 右 Suite 列表）已於 §4.6/§4.7/§4.8 完成；**本輪補**：suite 列表項目新增「展開詳情」按鈕（`fa-chevron-down/up`），展開後顯示 description、組成 scripts 路徑列表、最近 5 筆執行歷史（status badge / 開始時間 / Open in CI），點 chevron 收合；列表來自既有 `script_group_to_dict` 已含的 `scripts` 與 `recent_runs` 欄位，免額外 API；i18n / CSS（`.automation-suite-detail*`）同步補上。**未做**：scripts 拖曳重新排序（屬於 nice-to-have，當前 `script_paths_json` 已可由 update_group 改順序但無前端 UI；留作後續強化）
- [x] 4.18 Audit：script group CRUD 寫 audit `AUTOMATION_SCRIPT_GROUP`

## 4.5 Smart Suite Recommendation (P2)

- [x] 4.5.0 async progress 表 — `automation_smart_scan_runs` 持久化 queued/scanning/ready/failed 狀態、progress/result/error、`scan_config_hash` 與 actor；Smart Scan 由 API 啟動後背景執行
- [x] 4.5.1 [smart_scan_service.py](app/services/automation/smart_scan_service.py) — `SmartScanService.scan` orchestrates：manifest / provider smart_scan / defaults 合併 → repo contract 驗證 → content-aware entry-point detection（Python AST 判斷 `test_*` / `Test*`；JS/TS 判斷 `test/it/describe` markers；helper/resource files 排除 false positive）→ directory grouping → optional LLM enrich；結果含 `scan_config_hash`
- [x] 4.5.2 [automation_scripts.py](app/api/automation_scripts.py) 新增 `POST /api/teams/{team_id}/automation-scripts/smart-scan` — 回 `202 Accepted` + `scan_run_id/status/status_url`；新增 `GET /api/teams/{team_id}/automation-scripts/smart-scan/{scan_run_id}` 查 persisted progress/result/error
- [x] 4.5.3 [automation_script_groups.py](app/api/automation_script_groups.py) 新增 `POST .../batch-create` — 接 `{proposals: [{name, description, script_paths}]}`，逐一解析 `script_paths → script_ids`、呼叫 `create_group`（自動呼叫 `CIProvider.create_suite_job`）；回 `{created, skipped, failed, items:[{name,status,group_id,message}]}`；單一失敗不影響其它成功
- [x] 4.5.4 Provider config `smart_scan` 欄位 — `_resolve_scan_config` 支援讀取 `provider_config["smart_scan"]` nested dict 中的：`manifest_path` / `scan_path` / `include_patterns` / `exclude_patterns` / `enable_llm` / `llm_timeout_seconds`。優先順序：manifest > `smart_scan` overrides > defaults。Admin 可透過 `POST /automation-providers` body 或直接編輯 `config_json` 設置（provider config Pydantic schema 不嚴格驗證 extra fields，nested `smart_scan` 會原封不動進 DB）。Settings UI 自動 form 暫不渲染 nested object — 留作後續 UX 強化
- [x] 4.5.5 Suites tab 新增「Smart Scan」按鈕 — [automation_hub.html](app/templates/automation_hub.html) 在 header `page_specific_actions` 加 `#smartScanBtn`（`fa-magic` icon、`btn-info`）；點擊開啟 `#smartScanModal`
- [x] 4.5.6 Smart Scan Modal UI — `#smartScanModal` 含 loading spinner、`#smartScanContract`（contract badge / manifest 狀態 / tests path / present + missing tags）、`#smartScanProposals`（每張建議卡：checkbox 預選、suite 名稱 / 描述 / script 數量 badge、`<details>` 展開 script paths）、`#smartScanExcluded`（`<details>` 摺疊清單）、footer 三按鈕：Cancel / Rescan / Create selected suites。**未做**：suite 名稱 / 描述 inline editable（屬於後續 UX 強化）
- [x] 4.5.7 [smart-scan/main.js](app/static/js/automation-hub/smart-scan/main.js) — `runScan` POST smart-scan 後輪詢 `scan_run_id`，READY 後 render contract/proposals/excluded，`createSelected` 走 batch-create；建立完成後 reload 主頁讓 suite list 更新
- [x] 4.5.8 LLM client 整合 — `_maybe_llm_enrich` + `_call_openrouter`：當 `smart_scan.enable_llm = True` 且 `openrouter.api_key` 已配置時，呼叫 OpenRouter Chat Completions（`google/gemini-3-flash-preview`，response_format JSON）refine 每個 proposal 的 `name` / `description`；payload 僅含 `ref_path` / `current_name` / `sample_paths`（前 5 個）/ `total_paths`，**不送 source bodies**；timeout 預設 10 秒（可由 `llm_timeout_seconds` 覆蓋）；任何 timeout / HTTP / JSON 解析錯誤都 fallback 回 rule-based（`enrichment_source` 保持 `rule-based`）；成功時標記 `enrichment_source="llm"`、`confidence=0.85`
- [x] 4.5.9 Scan 結果快取 — module-level `_llm_cache: dict[cache_key → overrides]`，`cache_key = sha256({team_id, scan_config 子集, sorted entry_point paths, prompt_version})`；對未變更的 entry-point set 重複 LLM enrich 直接回傳 cached overrides，避免重複付費。**簡化選擇**：純 in-memory cache（process 生命週期）；持久化快取（DB / disk）與基於 manifest etag / script etag 的更細粒度 key 留作後續強化
- [x] 4.5.10 i18n — `automationHub.smartScan.*` 三語齊備（button / title / loading / rescan / createSelected / contractTitle / proposalsTitle / excludedToggle / manifest / testsPath / present / missing / viewPaths / noProposals / noExcluded / batchDone / batchFailed / scanFailed）
- [x] 4.5.11 Audit — Smart Scan 走 `ActionType.READ` 寫 `AUTOMATION_SCRIPT`；batch-create 每筆成功 suite 寫 `ActionType.CREATE` to `AUTOMATION_SCRIPT_GROUP`
- [x] 4.5.12 文件 / starter template — [docs/automation-hub-overview.md](docs/automation-hub-overview.md) 提到 `tcrt-automation.yml`；[docs/automation-provider-setup.md](docs/automation-provider-setup.md) 含建議目錄結構（tests/pages/flows/fixtures/resources/config）；workflow templates 含 `tcrt_run_id` 注入範例

## 5. Run Orchestration (P2)

- [x] 5.1 `app/api/automation_runs.py`：`POST /api/teams/{team_id}/automation-scripts/{script_id}/runs` 單一 script 觸發（從 suite detail 或 case detail 呼叫）；`POST /api/teams/{team_id}/automation-script-groups/{group_id}/runs` suite 觸發（主要使用場景，§4.15 已實作）；`GET .../runs`（列表，含 status/branch/triggered_by/script_id/group_id 篩選 + cursor 分頁）、`GET .../runs/{run_id}`（detail）、`POST .../runs/{run_id}/cancel`、`POST .../runs/{run_id}/reconcile`、`POST .../runs/{run_id}/sync`、`POST .../automation-runs/sync-pending`（batch sync）
- [x] 5.2 `app/services/automation/run_service.py`：
  - trigger_script: 解析 script 所屬 CI provider + workflow → 決定 runner_label（script.preferred_runner_label → provider config default → "ubuntu-latest"）→ 將 runner_label 併入 inputs → 呼叫 CIProvider.trigger_run（注入 tcrt_correlation_id）→ 寫 `automation_runs`（`automation_script_id` 填入，`script_group_id` NULL）
  - trigger_suite: 從 `automation_script_groups` 取得 suite 資訊（含 `ci_job_name`、`script_paths_json`）→ 決定 runner_label → 將 runner_label + test_paths 併入 inputs → 呼叫 CIProvider.trigger_run（注入 tcrt_correlation_id）→ 寫 `automation_runs`（`script_group_id` 填入，`automation_script_id` NULL）— 由 `script_group_service.trigger_group_run` 實作
  - sync: 對 QUEUED/RUNNING runs 呼叫 `CIProvider.get_run_status` 對齊（`sync_run` 單筆、`sync_pending_runs` 批次）；終態時 finished_at / duration_ms 自動補齊；ResultProvider.get_run_report_url 連動屬於 §6
  - reconcile: 處理觸發後配對失敗（無 external_run_id 標 UNKNOWN；接受 `external_run_id` 參數讓 user 手動關聯）
  - cancel_run: 終態 run 直接拒絕；非終態呼叫 `CIProvider.cancel_run` + 標 CANCELLED + finished_at
- [x] 5.3 60 秒 sync 排程 — 另開 [automation_background_manager](app/services/automation/background.py) 走 `asyncio.create_task` 路線（避免改既有 daily-only `TaskScheduler`）；`_run_sync_loop` 每 60 秒呼叫 `AutomationRunService.sync_pending_runs(team_id=None, limit=200)` 跨 team 同步 QUEUED/RUNNING runs；`_script_discovery_loop` 每小時掃所有設定 Storage provider 的 team 做 auto-discovery（同時滿足 §4.3 背景掃描需求）；wire 進 [main.py:startup_event](app/main.py) + `shutdown_event` 做 graceful start/stop；每次 iteration 例外 swallow + log，不會 crash loop
- [x] 5.4 Run history UI — 內嵌於 `automation_hub.html` 的 Runs tab（取代既有 placeholder），含 status / branch / triggered_by 篩選 + 表格列出 ID/Source/Workflow/Branch/Status/Trigger/Started/Duration + 跳 CI 原生 UI / Report / Sync / Reconcile / Cancel 操作；JS 模組 `app/static/js/automation-hub/runs/main.js`；i18n 三語齊備；CSS 補在 `automation-hub.css`
- [x] 5.5 Script preview「最近 5 筆 runs」— 嵌入在 Suites tab 檔案樹展開的 preview 區塊上方；點擊 preview 時並行 fetch `/api/teams/{id}/automation-runs?script_id={id}&limit=5`，cache 在 `state.scriptRunsById`，`Rescan` 時一併清空；每筆 run 顯示 status badge / branch / started_at + duration / 跳 CI 與報表連結；i18n 三語齊備（lastRuns / noRuns / runsPending / runsLoadFailed / openInCi / report）；CSS 新增 `automation-script-runs*` 區塊樣式
- [x] 5.6 「執行 Suite / Script」modal — 同一個 run modal 讓 user 填 branch / runner_label / extra inputs（JSON）；suite 觸發 `POST .../automation-script-groups/{group_id}/runs`，script preview 的「Run now」觸發 `POST .../automation-scripts/{script_id}/runs`；`automation:run-suite` / `automation:run-script` 由 runs module 接手；i18n 三語齊備
- [x] 5.7 Cancel run：API 呼叫 `CIProvider.cancel_run` + 更新 status — 由 `run_service.cancel_run` + `POST .../automation-runs/{run_id}/cancel` 實作
- [x] 5.8 Audit：run trigger / cancel / reconcile 寫 audit `AUTOMATION_RUN`

## 6. Result Provider Integration (P3)

- [x] 6.1 Per-run report URL：[run_service.maybe_fill_report_url](app/services/automation/run_service.py)（terminal + 無 report_url + 有 external_run_id 時自動呼叫 `ResultProvider.get_run_report_url`）；接到 `_apply_status_sync`（sync flow）與 [webhook_service.apply_run_status](app/services/automation/webhook_service.py)（webhook flow）；run history table 與 case detail 面板的「Report」按鈕已有 — 顯示 `report_url`
- [x] 6.2 iframe embed mode — 新增 `#reportEmbedModal`（xl modal + iframe + 「Open in CI」fallback link + X-Frame-Options 提示）；suites/main.js 從 `/automation-result/dashboard` 載入 `embed_mode`，當 `iframe` 時攔截指向 `base_url` 的報表連結；若 iframe error/timeout，顯示 fallback warning、開新分頁並把 runtime embed mode 降級為 `link`
- [x] 6.3 Dashboard 連結：[automation_result.py](app/api/automation_result.py) 新 endpoint `GET /api/teams/{id}/automation-result/dashboard`（回 `configured / provider_type / base_url / embed_mode / dashboard_url`）；Hub header 新增「Team Dashboard」按鈕（預設 `d-none`），suites/main.js `loadDashboardLink()` 在 init 時 fetch 後決定顯示與否
- [x] 6.4 Test case detail Automation 面板：[automation-panel.js:97](app/static/js/test-case-management/automation-panel.js:97) 已含 `report_url` 按鈕（§4.11 first pass 時就完成）
- [x] 6.5 Allure 部署 pattern docs — 已寫入 [docs/automation-provider-setup.md](docs/automation-provider-setup.md)「Allure deployment patterns」表格，含 GitHub Pages、S3+CloudFront、in-house nginx 三種以及 GH Pages 範例 workflow snippet
- [x] 6.6 i18n 文案：`automationHub.dashboard.openDashboard` 三語齊備；其它 Report / Open in CI 字串已隨 §5.5 / §4.11 補完

## 7. Coverage Tab (P3)

- [x] 7.1 `app/api/automation_coverage.py`：`GET /api/teams/{team_id}/automation-coverage` 計算「總 test case 數」、「已 PRIMARY 覆蓋數」、「已 COVERS 覆蓋數」、「未覆蓋清單」、「stale scripts」（30 天無 run）
- [x] 7.2 Hub Coverage tab：渲染統計 + 未覆蓋 case 列表 + 一鍵「為此 case 連結既有 script」+ stale scripts 警示
- [x] 7.3 30 天 trend：簡單 SVG line chart（純前端，不引外部 lib）
- [x] 7.4 i18n 文案

## 8. MCP Read API (P3)

- [x] 8.1 [mcp.py](app/models/mcp.py) 新增 schemas：`MCPAutomationScriptItem` + `MCPTeamAutomationScriptsResponse`、`MCPAutomationRunItem` + `MCPTeamAutomationRunsResponse`、`MCPLinkedAutomationSummary`、`MCPAutomationCoverageSummary` + `MCPAutomationCoverageUncoveredCase` + `MCPAutomationCoverageStaleScript` + `MCPAutomationCoverageTrendPoint` + `MCPTeamAutomationCoverageResponse`
- [x] 8.2 [mcp.py](app/api/mcp.py) 新增 3 個 read-only 端點：
  - `GET /api/mcp/teams/{team_id}/automation-scripts`（含 last_run_status / last_run_at / last_run_url、linked_test_case_numbers、script_format 與 keyword 過濾、cursor 分頁；batch latest-run + batch linked-cases 避免 N+1）
  - `GET /api/mcp/teams/{team_id}/automation-runs`（含 status / branch / script_id / script_group_id 過濾、cursor 分頁）
  - `GET /api/mcp/teams/{team_id}/automation-coverage`（複用 `AutomationCoverageService`，回 summary / uncovered_sample / stale_scripts / 30 天 trend）
- [x] 8.3 既有 `GET /api/mcp/teams/{team_id}/test-cases/{id}` 追加 `linked_automation_scripts: List[MCPLinkedAutomationSummary]` 欄位（透過 `AutomationLinkageService.list_linked_automation` 反查，向後相容預設空陣列）
- [x] 8.4 MCP 端 audit 寫入 — 由 `require_mcp_team_access` 既有依賴自動覆蓋（每次成功讀取都會走 `log_mcp_allow`）
- [x] 8.5 `openspec/specs/mcp-read-api/spec.md` 由 `openspec archive add-automation-hub` 自動同步（含 `linked_automation_scripts` 欄位新增）
- [x] 12.11 [test_mcp_automation.py](app/testsuite/test_mcp_automation.py)：5 個 test cases（scripts 列表 + linked numbers + last_run、runs 篩選 + 找不到、coverage summary + trend、case detail 反向、team scope 隔離）

## 9. Webhook (Inbound + Outbound) (P4)

- [x] 9.1 [automation_webhooks.py](app/api/automation_webhooks.py)：CRUD endpoints `GET/POST/GET-by-id/PATCH/DELETE/regenerate-secret` (per team admin)；建立時一次性回 `token` + `secret`，後續 list/detail 只回 `token_fingerprint` / `secret_fingerprint`
- [x] 9.2 [automation_webhooks_public.py](app/api/automation_webhooks_public.py)：`POST /api/v1/webhooks/ci/{token}/run-status`，HMAC-SHA256 驗章（支援 `X-TCRT-Signature` raw hex 與 `sha256=<hex>` 兩種格式）；inactive / outbound-only token 拒絕；per-token token bucket rate limit，超限回 `429 + Retry-After`；payload 以 `tcrt_run_id`（correlation）為主、`external_run_id` 為 fallback 對應 run；終態 run 不被舊事件 revert；X-TCRT-Delivery 紀錄於 `last_status` 作 idempotency hint
- [x] 9.3 [webhook_service.py](app/services/automation/webhook_service.py)：CRUD + HMAC verify + apply_run_status + outbound dispatch + delivery history/replay；outbound 與 test ping 共用 `_deliver_event`
- [x] 9.4 事件 outbound dispatch — `webhook_service.dispatch_event` + `dispatch_event_async` (fire-and-forget)；events 接到：`automation_links` create / delete → `script.linked` / `script.unlinked`；`automation_scripts` script trigger → `run.triggered`；`automation_script_groups` suite trigger → `run.triggered`；`automation_runs` cancel / reconcile → `run.tracked` (+ `run.completed` 終態)；`automation_webhooks_public` ingest → `run.tracked` (+ `run.completed` 終態)。每個 OUTBOUND webhook 依 `events` 訂閱（空陣列 = wildcard）。HMAC-SHA256 簽章；headers `X-TCRT-Event / X-TCRT-Delivery / X-TCRT-Signature`
- [x] 9.5 失敗顯示與 replay：非 2xx / timeout / connection error 將 `webhook.last_status` 標為 `EVENT_FAILED [status_code]` 並寫入 `automation_webhook_deliveries`；webhook config UI 可查看最近 deliveries、錯誤內容與 replay
- [x] 9.6 `app/templates/automation_webhook_config.html` + JS：webhook 設定頁
- [x] 9.7 audit：webhook CRUD + regenerate-secret 寫 `AUTOMATION_WEBHOOK`；failed outbound delivery 寫 best-effort `WEBHOOK_DELIVERY_FAILED` audit；replay action 由 admin API 寫 audit
- [x] 12.9 [test_automation_webhook_service.py](app/testsuite/test_automation_webhook_service.py)：涵蓋 create / name conflict / inactive+outbound 拒絕 / HMAC match+mismatch / matcher fallback / terminal 不 revert / regenerate secret / inbound rate limit / outbound delivery history / replay

## 10. Local Git Provider & Air-gapped Support (P5)

- [x] 10.1 [providers/local_git_storage.py](app/services/automation/providers/local_git_storage.py)：`_git` 子程序執行 `git` CLI；`list_scripts` / `read_script` 走 working tree；`write_script` → `add` + `commit` + `push`；`list_branches` + `health_check` (`git rev-parse HEAD`)
- [x] 10.2 設定欄位 `LocalGitStorageConfig`：`working_dir` / `remote_name` / `default_branch` / `ssh_key_path` 齊備（`GIT_SSH_COMMAND` 環境變數自動帶入）
- [x] 10.3 `create_pull_request` 回 `None`（air-gapped 環境沒有 PR primitive，依賴上游 Gitea / GitLab UI）— 已在 [docs/automation-provider-setup.md](docs/automation-provider-setup.md) 標記為設計目標
- [x] 10.4 文件 — [docs/automation-provider-setup.md](docs/automation-provider-setup.md) 含 LocalGit 設定 + 「GitLab self-hosted + LocalGit + Jenkins」與「Gitea + LocalGit + Jenkins」兩個 air-gapped 部署 pattern

## 11. Documentation

- [x] 11.1 [docs/automation-hub-overview.md](docs/automation-hub-overview.md) — mental model、end-to-end onboarding（key 生成 → provider 設定 → discover → suite → trigger → callback → coverage）、MCP / AI Helper 介接點、non-goals 與其它 docs 索引
- [x] 11.2 [docs/automation-provider-setup.md](docs/automation-provider-setup.md) — GitHub PAT vs App、LocalGit + air-gapped 部署 pattern、Jenkins API token / trigger token / CSRF crumb / `auto_manage_views`、Allure（含 §6.5 部署 pattern：GitHub Pages / S3+CloudFront / 內部 nginx）+ `Test connection` 行為說明
- [x] 11.3 [docs/automation-webhook.md](docs/automation-webhook.md) — inbound endpoint / payload / 狀態映射表 / curl 範例 / 錯誤碼表；outbound 事件 schema（5 種事件 + envelope）/ failure 處理 / test ping
- [x] 11.4 [docs/automation-workflow-templates/](docs/automation-workflow-templates/) — `github-actions-playwright.yml`、`github-actions-suite-template.yml`、`jenkinsfile-playwright.groovy`、`jenkins-suite-config-example.xml` 四份檔案齊備
- [x] 11.5 [README.md](README.md) — Automation Hub 章節 + `AUTOMATION_PROVIDER_ENCRYPTION_KEY` 環境變數說明 + 連結到 docs/
- [x] 11.6 [docs/automation-security.md](docs/automation-security.md) — 加密 envelope schema、key rotation 警告、Webhook HMAC、權限矩陣、Provider auth 建議、TCRT 不存的資料、audit 範圍

## 12. Testing

- [x] 12.1 provider registry 測試 — 由 [test_automation_provider_framework.py:test_provider_registry_validates_known_provider_payloads](app/testsuite/test_automation_provider_framework.py) 覆蓋（registry lookup + unknown type ProviderRegistryError）
- [x] 12.2 credential service 測試 — 由 `test_provider_credentials_encrypt_decrypt_and_preserve_fingerprint` + `test_provider_credentials_require_valid_key` 覆蓋（encrypt/decrypt round-trip、fingerprint 顯示、key 缺失行為）
- [x] 12.3 GitHub Storage 測試 — 由 `test_github_storage_read_script_uses_etag_cache` + `test_github_storage_list_scripts_returns_empty_for_missing_path` 覆蓋（etag cache hit、空 path 行為）
- [x] 12.4 [test_automation_local_git_storage.py](app/testsuite/test_automation_local_git_storage.py)：5 cases — tmpdir + 真 git CLI；list_scripts 遞迴 / read_script / health_check 通過 / health_check 失敗於非 repo / create_pull_request 回 None
- [x] 12.5 GitHub Actions CI 測試 — 由 `test_github_actions_trigger_marks_correlation_as_best_effort` + `test_github_actions_trigger_reports_missing_workflow_dispatch` + `test_github_actions_suite_template_preserves_github_expressions` 覆蓋
- [x] 12.5.1 Jenkins CI 測試 — 由 `test_jenkins_auto_view_uses_list_view_xml` 覆蓋 view XML 模板生成；CSRF crumb / queue 配對 / build status 對映等 happy path 在實機 self-test (`/test-connection`) + manual E2E (§12.13) 確認
- [x] 12.6 `app/testsuite/automation/test_script_service.py`：auto_discover（掃描 mock repo → upsert 多筆、stale 標記）、sync（etag 304、etag 變更更新）、delete（只刪 cache 不刪 git 檔案）
- [x] 12.7 `app/testsuite/automation/test_linkage_service.py`：M2M CRUD、PRIMARY 唯一、cascade
- [x] 12.8 `app/testsuite/test_automation_run_service.py`：trigger、sync_pending、reconcile UNKNOWN、cancel、cancel-on-terminal、unknown-script、missing-workflow、not-found、sync-without-external-id（10 個 test cases）
- 12.9 → 已併入上方 §9 對應條目（test_automation_webhook_service.py 已涵蓋 HMAC 驗章 / state 轉換 / matcher 兩種 fallback）
- [x] 12.10 outbound dispatch 測試已併入 [test_automation_webhook_service.py](app/testsuite/test_automation_webhook_service.py)：涵蓋 wildcard / 訂閱過濾 / inactive 跳過、非 2xx 標 FAILED、delivery row persisted、replay 會用原 payload 重新送出
- 12.11 → 已併入上方 §8 對應條目（test_mcp_automation.py 覆蓋 scripts/runs/coverage/detail-reverse 共 5 個 cases）
- [x] 12.12 [test_automation_smart_scan_service.py](app/testsuite/test_automation_smart_scan_service.py)：6 cases — 子目錄分群 / repo contract validation 含 manifest / 缺 Storage provider 報錯 / flat layout 歸為單一 Full Regression suite / Python AST false-positive 排除 / queued scan run 持久化
- [x] 12.13 手動 E2E plan 已寫進 [docs/automation-hub-overview.md](docs/automation-hub-overview.md)（"End-to-end onboarding" 8-step checklist）+ [docs/automation-workflow-templates/](docs/automation-workflow-templates/) 提供 4 份可貼可改的 CI 模板（含 webhook callback 範例）；驗證流程：generate key → configure provider → push `tcrt-automation.yml` + 標準目錄 → TCRT auto-discovery → Smart Scan 確認 contract + 建議 → batch-create → link manual case → 觸發 suite → CI 跑完 callback webhook → case detail 看到 SUCCEEDED + 報表連結。實機驗證屬於人工煙霧測試範圍，產品方執行

## 13. OpenSpec Sync & Archive

- [x] 13.1 `openspec validate add-automation-hub` — 通過（`Change 'add-automation-hub' is valid`）
- [x] 13.2 spec 同步至 `openspec/specs/` — 由 `openspec archive` 一次處理（包含 6 個新增 capability + `mcp-read-api` MODIFIED）
- [x] 13.3 `openspec archive add-automation-hub` — 執行後 change 移到 `openspec/changes/archive/`、delta 並入 main specs
