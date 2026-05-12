# automation-hub-provider-framework Specification

## Purpose
定義 Automation Hub 的 Provider 抽象框架：三個 `Protocol` 介面（Storage / CI / Result）、provider 註冊機制、per-team 設定表、credential 加密、與 v1 內建適配器（GitHub、LocalGit、GitHub Actions、Allure、Playwright HTML）。本能力讓 TCRT 不綁特定 git / CI / 報表工具，未來可擴充。

## ADDED Requirements

### Requirement: System MUST define StorageProvider Protocol for git-like file operations
`app/services/automation/providers/base.py` SHALL 定義 `StorageProvider` 為 Python `typing.Protocol`，包含以下 async methods 與 dataclass：

- `async def list_scripts(self, path: str, ref: str | None = None) -> list[ScriptRef]`
- `async def read_script(self, path: str, ref: str | None = None) -> ScriptContent`（含 content + etag）
- `async def write_script(self, path: str, content: str, message: str, branch: str | None = None) -> CommitRef`
- `async def list_branches(self) -> list[BranchRef]`
- `async def create_pull_request(self, branch: str, title: str, body: str) -> PullRequestRef | None`（不支援的 provider 回 None）
- `async def health_check(self) -> HealthStatus`（whoami / connectivity test）

對應 dataclass SHALL 為 frozen Pydantic models，欄位明確。

#### Scenario: Protocol is structural, not nominal
- **WHEN** 第三方適配器實作上述 methods 但不顯式 inherit
- **THEN** Python typing SHALL 接受其作為 `StorageProvider`，無需修改 core

### Requirement: System MUST define CIProvider Protocol for execution orchestration
`StorageProvider` 同檔案 SHALL 定義 `CIProvider` Protocol：

- `async def list_workflows(self) -> list[WorkflowRef]`
- `async def trigger_run(self, workflow_id: str, branch: str, inputs: dict[str, str]) -> ExternalRunRef`
- `async def get_run_status(self, external_run_id: str) -> RunStatusSnapshot`
- `async def cancel_run(self, external_run_id: str) -> None`
- `async def get_run_url(self, external_run_id: str) -> str`
- `async def list_artifacts(self, external_run_id: str) -> list[ArtifactRef]`
- `async def health_check(self) -> HealthStatus`

#### Scenario: trigger_run accepts tcrt_run_id input for correlation
- **WHEN** TCRT 觸發 run
- **THEN** TCRT SHALL 注入 `inputs.tcrt_run_id` (uuid4)，並期望 workflow 在 metadata / log 中 echo 此值，以利後續配對

### Requirement: System MUST define ResultProvider Protocol for report URLs
`base.py` SHALL 定義 `ResultProvider` Protocol：

- `async def get_run_report_url(self, ci_external_run_id: str) -> str | None`
- `async def get_dashboard_url(self) -> str | None`
- `async def health_check(self) -> HealthStatus`

#### Scenario: Report URL may not always be available
- **WHEN** report 尚未產生（如 run 仍 RUNNING）
- **THEN** provider SHALL 回 None，UI 顯示「報表生成中」

### Requirement: Provider registry MUST support type-based lookup and per-team binding
`app/services/automation/provider_registry.py` SHALL 維護 `{provider_type: provider_class}` 對照表，類型格式為 `<slot>:<vendor>`（如 `storage:github`、`ci:github_actions`、`result:allure`）。

`get_provider(team_id, slot)` factory SHALL：
1. 從 `team_automation_providers` 查該 team 的 active provider for slot
2. 解密 credentials
3. 實例化對應 provider class，注入 config + credentials
4. 回傳實例（可選擇 cache 一段時間）

#### Scenario: Unknown provider_type rejected at config time
- **WHEN** admin 嘗試建立 `provider_type=storage:unknown` 的 config
- **THEN** API SHALL 回 400，錯誤訊息 SHALL 列出可用的 provider types

#### Scenario: Team without provider configured
- **WHEN** team 未配置 storage provider 但前端嘗試 list scripts
- **THEN** API SHALL 回 412 `PROVIDER_NOT_CONFIGURED`，UI SHALL 顯示引導至 settings 頁

### Requirement: System MUST store per-team provider configuration
資料表 `team_automation_providers` SHALL 包含：

- `id` PK
- `team_id` FK NOT NULL, indexed
- `provider_slot` enum(`STORAGE`/`CI`/`RESULT`) NOT NULL
- `provider_type` VARCHAR(60) NOT NULL（如 `storage:github`）
- `name` VARCHAR(100) NOT NULL
- `config_json` TEXT NOT NULL（plaintext config，含 owner / repo / base_url 等）
- `credentials_encrypted` TEXT nullable（AES-256-GCM；含 PAT / password / API key；nonce 內嵌）
- `is_active` BOOLEAN default true
- `last_health_check_at` DATETIME nullable
- `last_health_status` VARCHAR(40) nullable
- `created_by`, `updated_by`, timestamps
- UniqueConstraint `(team_id, provider_slot, name)`
- Index `(team_id, provider_slot, is_active)`

#### Scenario: One active provider per slot per team (recommended, not enforced)
- **WHEN** team 有兩筆 `provider_slot=STORAGE, is_active=true` 的 provider
- **THEN** 系統 SHALL 允許（可能用於不同 repo），但 `get_provider(team_id, 'STORAGE')` SHALL 取最新 `updated_at` 的；admin UI SHALL 警示「建議只保留一個 active storage provider」

### Requirement: Provider credentials MUST be encrypted at rest with AES-256-GCM
所有 credential 欄位（PAT、password、API key、SSH key 內容）SHALL 透過 `provider_credential_service.encrypt_credentials()` 加密後存入 `credentials_encrypted`。金鑰由 `AUTOMATION_PROVIDER_ENCRYPTION_KEY` 環境變數提供（base64-encoded 32 bytes for AES-256）。

Bootstrap 啟動時若 `team_automation_providers` 表非空但金鑰缺失：SHALL 阻擋啟動並列印生成指引（如 `python -c "import secrets,base64;print(base64.b64encode(secrets.token_bytes(32)).decode())"`）。

API 永遠不回傳 plaintext credentials；GET 端點 SHALL 回傳 `credentials_set: bool` 與最末 4 字元 fingerprint（如 GitHub PAT `ghp_***abcd`）。

#### Scenario: API never returns plaintext credential
- **WHEN** admin 呼叫 `GET /api/teams/{id}/automation-providers/{provider_id}`
- **THEN** 回應 SHALL 包含 `credentials_set: true`、`credentials_fingerprint: "...abcd"`，**不** 包含完整 credential

#### Scenario: Missing key blocks bootstrap when providers exist
- **WHEN** TCRT 啟動，`team_automation_providers` 有 ≥1 筆但 `AUTOMATION_PROVIDER_ENCRYPTION_KEY` 未設定
- **THEN** bootstrap SHALL 拋錯並列出生成指令

### Requirement: System MUST ship GitHub storage adapter as v1 default
`app/services/automation/providers/github_storage.py` SHALL 實作 `StorageProvider`，使用 GitHub REST API v3：

- 認證：支援 PAT（`Authorization: token <pat>`）與 GitHub App（installation token，由 config 提供 app_id + private_key）
- `list_scripts`：GET `/repos/{owner}/{repo}/contents/{path}`，遞迴展開資料夾
- `read_script`：GET 同上，base64 decode；保留 `sha` 作為 etag
- `write_script`：PUT contents API，帶 sha；支援 branch 參數
- `list_branches`：GET `/repos/{owner}/{repo}/branches`
- `create_pull_request`：POST `/repos/{owner}/{repo}/pulls`
- `health_check`：GET `/user`，回 ok / fail
- Rate limit：使用 `If-None-Match` header；304 不計入 quota

Config schema：`{ owner: str, repo: str, default_branch: str = "main", auth_method: "pat" | "github_app", api_base_url: str = "https://api.github.com" }`
Credential schema：`{ pat: str }` 或 `{ app_id: str, installation_id: str, private_key_pem: str }`

#### Scenario: PAT authentication
- **WHEN** admin 配置 GitHub provider with PAT
- **THEN** provider SHALL 用 `token` header 認證；`health_check` SHALL 回 user login

#### Scenario: GitHub App authentication
- **WHEN** admin 配置 GitHub App with app_id + private_key
- **THEN** provider SHALL 自行產生 JWT + 換 installation token；token 過期前自動 refresh

### Requirement: System MUST ship LocalGit storage adapter for air-gapped deployments
`app/services/automation/providers/local_git_storage.py` SHALL 實作 `StorageProvider`，透過 `git` CLI 對本機 mount 的 working copy 操作。

Config：`{ working_dir: str, remote_name: str = "origin", default_branch: str = "main", ssh_key_path: str | None = None }`

不支援 `create_pull_request`（回 None）；其他 method 透過 subprocess git 完成。

#### Scenario: Air-gapped GitLab via mount
- **WHEN** team 配置 LocalGit provider 指向 `/data/repos/playwright-tests`
- **THEN** TCRT SHALL 透過 git CLI 讀寫該目錄；commit + push 透過 SSH key 推到內部 GitLab

### Requirement: System MUST ship GitHub Actions CI adapter
`app/services/automation/providers/github_actions_ci.py` SHALL 實作 `CIProvider`：

- `list_workflows`：GET `/repos/{owner}/{repo}/actions/workflows`
- `trigger_run`：POST `/repos/{owner}/{repo}/actions/workflows/{id}/dispatches`，body 帶 `ref`、`inputs`（含 `tcrt_run_id` uuid）
- `get_run_status`：GET `/repos/{owner}/{repo}/actions/runs/{run_id}`，把 `status`/`conclusion` 映射到 `QUEUED/RUNNING/SUCCEEDED/FAILED/CANCELLED/UNKNOWN`
- `cancel_run`：POST `/repos/{owner}/{repo}/actions/runs/{id}/cancel`
- `get_run_url`：組 `https://github.com/{owner}/{repo}/actions/runs/{id}`
- `list_artifacts`：GET `/repos/{owner}/{repo}/actions/runs/{id}/artifacts`

#### Scenario: workflow_dispatch correlation
- **WHEN** TCRT 觸發 workflow_dispatch 後 30 秒內查詢
- **THEN** provider SHALL 透過 `event=workflow_dispatch` + 時間範圍 + `inputs.tcrt_run_id` 比對找出 external_run_id；找到 → 回傳；找不到 → 視為 pending（後續 sync job 繼續找）

#### Scenario: Workflow status mapping
- **WHEN** GH 回 `status=in_progress, conclusion=null`
- **THEN** provider SHALL 回 `RunStatusSnapshot(status='RUNNING')`
- **WHEN** GH 回 `status=completed, conclusion=success`
- **THEN** provider SHALL 回 `status='SUCCEEDED'`
- **WHEN** GH 回 `status=completed, conclusion=cancelled`
- **THEN** provider SHALL 回 `status='CANCELLED'`

### Requirement: System MUST ship Jenkins CI adapter
`app/services/automation/providers/jenkins_ci.py` SHALL 實作 `CIProvider`，使用 Jenkins REST API：

- 認證：Basic Auth（`username + api_token`）或 trigger token plugin（per-job）；adapter SHALL 先呼叫 `GET /crumbIssuer/api/json` 取得 CSRF crumb（若 Jenkins 啟用 CSRF protection），後續所有寫操作攜帶 `Jenkins-Crumb` header
- `list_workflows`：`GET /api/json?tree=jobs[name,url,buildable]`，列出所有 buildable jobs
- `trigger_run`：`POST /job/{name}/buildWithParameters?tcrt_run_id=<uuid>&<other_params>`；回應 201 + `Location: /queue/item/{queue_id}/` header
- `get_run_status`：先 `GET /queue/item/{queue_id}/api/json` 取 `executable.url`（含 build number）；取得後切到 `GET /job/{name}/{build_id}/api/json`；狀態映射：
  - `result=SUCCESS` → `SUCCEEDED`
  - `result=FAILURE` 或 `UNSTABLE` → `FAILED`
  - `result=ABORTED` → `CANCELLED`
  - `result=null` + `building=true` → `RUNNING`
  - `result=null` + `building=false` + 仍在 queue → `QUEUED`
  - 其他 → `UNKNOWN`
- `cancel_run`：`POST /job/{name}/{build_id}/stop`
- `get_run_url`：直接用 `executable.url`
- `list_artifacts`：`GET /job/{name}/{build_id}/api/json?tree=artifacts[*]`
- `health_check`：`GET /me/api/json`

Config schema：`{ base_url: str, auth_method: "api_token" | "trigger_token", default_job_name: str | None, csrf_protection_enabled: bool = true }`
Credential schema（auth_method=api_token）：`{ username: str, api_token: str }`
Credential schema（auth_method=trigger_token）：`{ job_token: str }`（無法呼叫 user-scoped API 如 health_check / list_workflows，僅能 trigger）

#### Scenario: Basic Auth with CSRF crumb
- **WHEN** Jenkins 啟用 CSRF protection
- **THEN** adapter SHALL 在 trigger_run 前先取 crumb，並在 POST 攜帶 `Jenkins-Crumb` header；缺 crumb 而 Jenkins 拒絕時 SHALL 自動 retry 一次取新 crumb

#### Scenario: Queue item correlation
- **WHEN** TCRT 觸發 buildWithParameters 後立即查詢
- **THEN** adapter SHALL 解析 `Location` header 取 queue_id，後續輪詢 queue item；`executable.url` 出現後切換 endpoint

#### Scenario: Build status mapping
- **WHEN** Jenkins 回 `result=FAILURE, building=false`
- **THEN** adapter SHALL 回 `RunStatusSnapshot(status='FAILED')`
- **WHEN** Jenkins 回 `result=UNSTABLE`（測試有失敗但 build 沒 error）
- **THEN** adapter SHALL 回 `status='FAILED'`（v1 不區分 UNSTABLE；若有需要區分 v2 加 `FLAKY` status）

#### Scenario: Trigger-token-only mode limits health_check
- **WHEN** team 使用 `auth_method=trigger_token`
- **THEN** `health_check` SHALL 回 `HealthStatus(status="LIMITED", message="trigger_token mode cannot verify user API; only trigger is testable")`；admin UI SHALL 警示但不阻擋使用

### Requirement: System MUST ship Allure result adapter as the sole v1 result provider
`app/services/automation/providers/allure_result.py` SHALL 實作 `ResultProvider`，為 v1 唯一內建 result provider。其他 result 候選（Playwright HTML、ReportPortal、Jenkins built-in）皆留 v2 評估。

Config schema：

- `base_url: str`：Allure server / static host 根 URL（如 `https://allure.internal.tcg.com`）
- `run_url_template: str = "{base_url}/runs/{ci_external_run_id}"`：可用 placeholder `{base_url}`、`{ci_external_run_id}`、`{project}`
- `embed_mode: "link" | "iframe" = "link"`
- `dashboard_url: str | None = None`：optional，hub 首頁「Team Dashboard」按鈕用
- `project: str | None = None`：optional，多專案場景下指定

`get_run_report_url(ci_external_run_id)` SHALL 用 template 字串 interpolation 組 URL；`embed_mode=iframe` 時 UI 改為 iframe 嵌入；偵測到目標頁面 `X-Frame-Options: DENY` 或 `Content-Security-Policy: frame-ancestors 'none'` 時 SHALL fallback 為 link mode 並警示 admin。

#### Scenario: Default link mode
- **WHEN** team 配置 Allure with `embed_mode=link`
- **THEN** UI SHALL 顯示「在 Allure 中開啟」按鈕，新分頁打開

#### Scenario: iframe mode opt-in
- **WHEN** team 配置 `embed_mode=iframe`
- **THEN** UI SHALL 嵌入 `<iframe>` 顯示報表

#### Scenario: iframe blocked by CSP
- **WHEN** Allure server 回 `X-Frame-Options: DENY`，使用者開啟 run detail
- **THEN** UI SHALL 偵測 iframe load 失敗（透過 onerror / postMessage probe），自動降級為 link 模式並顯示「無法嵌入，請聯絡 admin 調整 Allure server CSP」

#### Scenario: Template with project
- **WHEN** team 配置 `run_url_template="{base_url}/projects/{project}/launches/{ci_external_run_id}"` + `project="frontend"`
- **THEN** `get_run_report_url("123")` SHALL 回傳 `{base_url}/projects/frontend/launches/123`

### Requirement: Provider self-test MUST be available
admin UI SHALL 提供「Test Connection」按鈕，呼叫 `POST /api/teams/{team_id}/automation-providers/{provider_id}/test-connection`，後端執行該 provider 的 `health_check()`，結果寫回 `last_health_check_at` + `last_health_status`，並即時回應給 UI。

#### Scenario: Failed health check stored
- **WHEN** GitHub PAT 過期，admin 點 Test Connection
- **THEN** API SHALL 回 200 with `{status: "FAILED", error: "Bad credentials"}`，`last_health_status` SHALL 更新

### Requirement: Provider config schema MUST be reflectable
每個 provider class SHALL 暴露 `config_schema()` 與 `credential_schema()` 回傳 Pydantic model class。admin 設定 UI SHALL 透過此 schema 動態渲染表單（field name / type / description），避免 hard-code 表單。

#### Scenario: New provider added
- **WHEN** 開發者新增 `providers/gitlab_storage.py` 並於 registry 註冊
- **THEN** admin UI 在選擇 `storage:gitlab` 時 SHALL 自動依其 `config_schema()` 渲染對應欄位，無需動 frontend
