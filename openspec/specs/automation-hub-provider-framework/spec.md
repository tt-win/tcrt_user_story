# automation-hub-provider-framework Specification

## Purpose
TBD - created by archiving change add-automation-hub. Update Purpose after archive.
## Requirements
### Requirement: System MUST define StorageProvider Protocol for git-like file operations
`app/services/automation/providers/base.py` SHALL 定義 `StorageProvider` 為 Python `typing.Protocol`，包含以下 async methods 與 dataclass：

- `async def list_scripts(self, path: str, ref: str | None = None) -> list[ScriptRef]`
- `async def read_script(self, path: str, ref: str | None = None, etag: str | None = None) -> ScriptContent`（含 content + etag；etag 命中時可回 `not_modified=true`）
- `async def write_script(self, path: str, content: str, message: str, branch: str | None = None) -> CommitRef`（**主要供 CIProvider suite job 管理內部使用**，如寫入 `.github/workflows/tcrt-suite-*.yml`；TCRT **不**提供使用者編輯 script 內容的功能，所有 script 編輯由 IDE 完成後推上 git）
- `async def list_branches(self) -> list[BranchRef]`
- `async def create_pull_request(self, branch: str, title: str, body: str) -> PullRequestRef | None`（不支援的 provider 回 None；**TCRT 不主動為 script 內容開 PR**，此 method 保留供未來擴充或 suite job 相關操作）
- `async def health_check(self) -> HealthStatus`（whoami / connectivity test）

對應 dataclass SHALL 為 frozen Pydantic models，欄位明確。

#### Scenario: Protocol is structural, not nominal
- **WHEN** 第三方適配器實作上述 methods 但不顯式 inherit
- **THEN** Python typing SHALL 接受其作為 `StorageProvider`，無需修改 core

### Requirement: System MUST define CIProvider Protocol for execution orchestration
`StorageProvider` 同檔案 SHALL 定義 `CIProvider` Protocol：

- `async def list_workflows(self) -> list[WorkflowRef]`
- `async def list_runners(self) -> list[RunnerRef]`（GitHub Actions 與 Jenkins 皆支援；其他 CI 若無節點概念可回 empty list）
- `async def trigger_run(self, workflow_id: str, branch: str, inputs: dict[str, str]) -> ExternalRunRef`
- `async def get_run_status(self, external_run_id: str) -> RunStatusSnapshot`
- `async def cancel_run(self, external_run_id: str) -> None`
- `async def get_run_url(self, external_run_id: str) -> str`
- `async def list_artifacts(self, external_run_id: str) -> list[ArtifactRef]`
- `async def health_check(self) -> HealthStatus`

對應 dataclass：

```python
@dataclass
class RunnerRef:
    id: int
    name: str
    os: str
    status: str          # "online" | "offline"
    busy: bool
    labels: list[str]
```

#### Scenario: trigger_run accepts tcrt_run_id input for correlation
- **WHEN** TCRT 觸發 run
- **THEN** TCRT SHALL 注入 `inputs.tcrt_run_id` (uuid4)，並期望 workflow 在 metadata / log 中 echo 此值，以利後續配對

#### Scenario: Runner list for self-hosted deployments
- **WHEN** team 使用 GitHub Actions 並在內網部署 self-hosted runners
- **THEN** `list_runners()` SHALL 呼叫 GitHub API `GET /repos/{owner}/{repo}/actions/runners`，回傳每個 runner 的 name、labels、status、busy 狀態
- **WHEN** runner status="offline"
- **THEN** UI SHALL 顯示為不可選（disabled）並標註「offline」
- **WHEN** runner busy=true
- **THEN** UI SHALL 顯示為「執行中」並仍可選擇（排隊）

#### Scenario: Jenkins node list for distributed builds
- **WHEN** team 使用 Jenkins 並有多台 slave/agent（如 staging、prod、專用測試機）
- **THEN** `list_runners()` SHALL 呼叫 Jenkins API `GET /computer/api/json`，回傳每個 node 的 displayName、assignedLabels、idle、offline 狀態
- **WHEN** node offline=true
- **THEN** UI SHALL 顯示為不可選（disabled）並標註「offline」
- **WHEN** node idle=false（busy）
- **THEN** UI SHALL 顯示為「執行中」並仍可選擇（Jenkins 會自動排隊）

### Requirement: System MUST define ResultProvider Protocol for report URLs
`base.py` SHALL 定義 `ResultProvider` Protocol：

- `async def get_run_report_url(self, ci_external_run_id: str) -> str | None`
- `async def get_dashboard_url(self) -> str | None`
- `async def health_check(self) -> HealthStatus`

#### Scenario: Report URL may not always be available
- **WHEN** report 尚未產生（如 run 仍 RUNNING）
- **THEN** provider SHALL 回 None，UI 顯示「報表生成中」

### Requirement: Provider registry MUST support type-based lookup and slot-aware scope dispatch
`app/services/automation/provider_registry.py` SHALL 維護 `{provider_type: provider_class}` 對照表，類型格式為 `<slot>:<vendor>`（如 `storage:github`、`ci:jenkins`、`result:allure`）。

`get_active_provider_record(team_id, slot, session)` SHALL 依 slot 分流查詢來源：

1. `slot == AutomationProviderSlot.STORAGE` → 從 `team_automation_providers` 查該 `team_id` 的 active provider
2. `slot in (AutomationProviderSlot.CI, AutomationProviderSlot.RESULT)` → 從 `system_automation_providers` 查 org-level active provider（`team_id` 參數忽略）
3. 解密 credentials
4. 實例化對應 provider class，注入 config + credentials
5. 回傳實例（可選擇 cache 一段時間）

簽名保持 `(team_id, slot, session)` 不變以維持 9 個既有呼叫端零改動；helper `is_system_scoped_slot(slot) -> bool` SHALL 暴露給其他需區分 scope 的程式碼（如 audit logging）。

#### Scenario: Unknown provider_type rejected at config time
- **WHEN** admin 嘗試建立 `provider_type=storage:unknown` 的 config
- **THEN** API SHALL 回 400，錯誤訊息 SHALL 列出可用的 provider types

#### Scenario: Team without storage provider configured
- **WHEN** team 未配置 storage provider 但前端嘗試 list scripts
- **THEN** API SHALL 回 412 `PROVIDER_NOT_CONFIGURED`，UI SHALL 顯示引導至 settings 頁

#### Scenario: Org without CI provider configured
- **WHEN** team 觸發 run、但 org-level CI provider 未設定
- **THEN** API SHALL 回 412 `PROVIDER_NOT_CONFIGURED`，錯誤訊息 SHALL 提示「請 Super Admin 至『同步組織架構』設定 CI provider」

#### Scenario: Slot-scope dispatch is transparent to caller
- **WHEN** `run_service` 呼叫 `get_active_provider_record(team_id=5, slot=CI, session)` 與 `get_active_provider_record(team_id=7, slot=CI, session)`
- **THEN** 兩次呼叫 SHALL 解析到**同一份** org-level CI provider，`team_id` 參數被內部忽略

### Requirement: System MUST store per-team storage provider configuration only
資料表 `team_automation_providers` SHALL 包含：

- `id` PK
- `team_id` FK NOT NULL, indexed
- `provider_slot` enum(`STORAGE`/`CI`/`RESULT`) NOT NULL — **但 CHECK constraint `ck_team_provider_storage_only` SHALL 限制 `provider_slot = 'storage'`**
- `provider_type` VARCHAR(60) NOT NULL（如 `storage:github`）
- `name` VARCHAR(100) NOT NULL
- `config_json` TEXT NOT NULL（plaintext config，含 owner / repo 等）
- `credentials_encrypted` TEXT nullable（AES-256-GCM；含 PAT / SSH key；nonce 內嵌）
- `is_active` BOOLEAN default true
- `last_health_check_at` DATETIME nullable
- `last_health_status` VARCHAR(40) nullable
- `created_by`, `updated_by`, timestamps
- UniqueConstraint `(team_id, provider_slot, name)`
- Index `(team_id, provider_slot, is_active)`

#### Scenario: Inserting ci / result row rejected at DB level
- **WHEN** code 嘗試 `INSERT INTO team_automation_providers (..., provider_slot = 'ci', ...)`
- **THEN** DB SHALL 違反 CHECK constraint 並拋 `IntegrityError`，service 層攔截後回 400 `WRONG_PROVIDER_SCOPE`

#### Scenario: One active storage provider per team (recommended, not enforced)
- **WHEN** team 有兩筆 `provider_slot=STORAGE, is_active=true` 的 provider
- **THEN** 系統 SHALL 允許（可能用於不同 repo），但 `get_active_provider_record(team_id, STORAGE)` SHALL 取最新 `updated_at` 的；admin UI SHALL 警示「建議只保留一個 active storage provider」

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

Config schema：`{ owner: str, repo: str, default_branch: str = "main", auth_method: "pat" | "github_app", api_base_url: str = "https://api.github.com", default_runner_label: str = "ubuntu-latest", scan_path: str = "tests/" }`

`scan_path` 為 TCRT auto-discovery 時掃描的起始路徑（預設 `"tests/"`）；`list_scripts(path=scan_path, recursive=True)` 會遞迴列出所有檔案。
Credential schema：`{ pat: str }` 或 `{ app_id: str, installation_id: str, private_key_pem: str }`

`default_runner_label` 用於觸發 run 時的預設 runner（當 script 未設定 `preferred_runner_label` 時 fallback）。GitHub Actions workflow YAML 必須使用 `runs-on: ${{ github.event.inputs.runner_label }}` 才能動態接收。

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
- **THEN** provider SHALL 注入 `inputs.tcrt_run_id`，並以 `event=workflow_dispatch` + branch + workflow + 時間範圍做 best-effort 配對找出 external_run_id；GitHub REST run list API 不回傳 workflow_dispatch input 值，因此不得宣稱已驗證 `inputs.tcrt_run_id` 精準相等；找不到 → 視為 pending（後續 sync job 或 user 手動 reconcile）

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
- `list_runners`：`GET /computer/api/json?tree=computer[displayName,idle,offline,assignedLabels[name]]`，回傳 Jenkins nodes/agents（master + 所有 slave/agent）；`offline=true` 標為 offline；`idle=false` 標為 busy
- `trigger_run`：`POST /job/{name}/buildWithParameters?tcrt_run_id=<uuid>&NODE_LABEL=<label>&<other_params>`；回應 201 + `Location: /queue/item/{queue_id}/` header；`NODE_LABEL` 傳入目標 node label
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

Config schema：`{ base_url: str, auth_method: "api_token" | "trigger_token", default_job_name: str | None, default_runner_label: str = "any", csrf_protection_enabled: bool = true }`
Credential schema（auth_method=api_token）：`{ username: str, api_token: str }`
Credential schema（auth_method=trigger_token）：`{ job_token: str }`（無法呼叫 user-scoped API 如 health_check / list_workflows / list_runners，僅能 trigger）

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

#### Scenario: Jenkins runner selection via NODE_LABEL parameter
- **WHEN** TCRT 觸發 Jenkins build with `NODE_LABEL=staging-agent-01`
- **THEN** `trigger_run` SHALL 將 `NODE_LABEL` 作為 build parameter 傳入 `buildWithParameters`
- **WHEN** Jenkins Pipeline 使用 `agent { label "${params.NODE_LABEL ?: 'any'}" }`
- **THEN** build SHALL 在對應 label 的 node 上執行
- **WHEN** 目標 node 目前 busy（已有 build 在跑）
- **THEN** Jenkins SHALL 自動排隊；TCRT 端 status 仍為 QUEUED，不報錯

#### Scenario: Jenkins node offline
- **WHEN** `list_runners` 發現某 node `offline=true`
- **THEN** UI SHALL 將該 node 顯示為 disabled 並標註「offline」
- **WHEN** 使用者嘗試選擇 offline node 觸發 run
- **THEN** API SHALL 接受請求（Jenkins 會自行處理 queue / 等待 node 上線），但 UI SHALL 顯示警示「目標節點目前離線，build 將排隊等待"

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

### Requirement: CIProvider MUST support suite job lifecycle management
`CIProvider` Protocol SHALL 定義 suite job 管理 methods，讓 TCRT 自動在 CI 端建立/更新/刪除對應的 job/workflow：

```python
class CIProvider(Protocol):
    # 既有方法...
    
    # Suite job 管理（新增）
    async def create_suite_job(
        self,
        suite_id: str,
        suite_name: str,
        test_paths: list[str],
        default_runner_label: str,
    ) -> str: ...  # 回傳 CI 端 job/workflow 名稱
    
    async def update_suite_job(
        self,
        suite_id: str,
        suite_name: str,
        test_paths: list[str],
        default_runner_label: str,
    ) -> str: ...  # 回傳更新後的 job/workflow 名稱
    
    async def delete_suite_job(self, suite_id: str, job_name: str) -> None: ...
    
    async def list_suite_jobs(self) -> list[WorkflowRef]: ...  # 列出所有 TCRT 管理的 suite jobs
```

#### GitHub Actions 實作
`github_actions_ci.py` 的 suite job 管理 SHALL 透過 **StorageProvider.write_script** / **delete_file** 實作：

- `create_suite_job`：產生 workflow YAML 內容 → `write_script(path=".github/workflows/tcrt-suite-{suite_id}-{sanitized_name}.yml", content=..., sha=None)`
- `update_suite_job`：重新產生 YAML → `write_script(path=..., content=..., sha=<current>)`
- `delete_suite_job`：`delete_file(path=..., sha=<current>)`
- `list_suite_jobs`：`list_workflows()` 並過濾 `name starts_with "tcrt-suite-"`

Workflow YAML 模板（TCRT 內建）：
```yaml
# ============================================
# AUTO-GENERATED BY TCRT
# Suite: {{ suite_name }}
# DO NOT EDIT MANUALLY - Changes will be overwritten
# ============================================
name: TCRT Suite - {{ suite_name }}

on:
  workflow_dispatch:
    inputs:
      tcrt_run_id:
        description: 'TCRT correlation ID'
        required: true
      runner_label:
        description: 'Runner label'
        required: false
        default: '{{ default_runner_label }}'

jobs:
  test:
    runs-on: ${{ github.event.inputs.runner_label }}
    steps:
      - uses: actions/checkout@v4
      
      - name: Setup Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      
      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install pytest-playwright
          playwright install
      
      - name: Run TCRT Suite
        run: |
          paths=({% for path in test_paths %}"{{ path }}" {% endfor %})
          pytest "${paths[@]}"
      
      - name: Notify TCRT
        if: always()
        run: |
          curl -X POST "${{ secrets.TCRT_WEBHOOK_URL }}" \
            -H "Content-Type: application/json" \
            -d "{\"tcrt_run_id\":\"${{ inputs.tcrt_run_id }}\",\"status\":\"${{ job.status }}\"}"
```

#### Jenkins 實作
`jenkins_ci.py` 的 suite job 管理 SHALL 透過 **Jenkins REST API** 實作：

- `create_suite_job`：產生 config.xml → `POST /createItem?name={job_name}` → `POST /view/{view_name}/addJobToView`
- `update_suite_job`：產生 config.xml → `POST /job/{job_name}/config.xml`
- `delete_suite_job`：`POST /job/{job_name}/doDelete`
- `list_suite_jobs`：`list_workflows()` 並過濾 `name starts_with "tcrt-suite-"`

Config.xml 模板（TCRT 內建）：
```xml
<?xml version='1.1' encoding='UTF-8'?>
<flow-definition plugin="workflow-job">
  <description>TCRT Suite - {{ suite_name }}</description>
  <properties>
    <hudson.model.ParametersDefinitionProperty>
      <parameterDefinitions>
        <hudson.model.StringParameterDefinition>
          <name>tcrt_run_id</name>
          <description>TCRT correlation ID</description>
          <defaultValue></defaultValue>
          <trim>true</trim>
        </hudson.model.StringParameterDefinition>
        <hudson.model.StringParameterDefinition>
          <name>NODE_LABEL</name>
          <description>Target node label</description>
          <defaultValue>{{ default_runner_label }}</defaultValue>
          <trim>true</trim>
        </hudson.model.StringParameterDefinition>
      </parameterDefinitions>
    </hudson.model.ParametersDefinitionProperty>
  </properties>
  <definition class="org.jenkinsci.plugins.workflow.cps.CpsFlowDefinition" plugin="workflow-cps">
    <script>
pipeline {
    agent { label "${params.NODE_LABEL ?: '{{ default_runner_label }}'}" }
    stages {
        stage('Setup') {
            steps {
                sh '''
                python3 -m pip install --upgrade pip
                pip install pytest-playwright
                playwright install
                '''
            }
        }
        stage('Test') {
            steps {
                echo "TCRT Suite: {{ suite_name }}"
                echo "TCRT ID: ${params.tcrt_run_id}"
                sh 'pytest {% for path in test_paths %}{{ path }} {% endfor %}'
            }
        }
    }
    post {
        always {
            sh '''
            curl -X POST "${TCRT_WEBHOOK_URL}" \
              -H "Content-Type: application/json" \
              -d "{\\"tcrt_run_id\\":\\"${params.tcrt_run_id}\\",\\"status\\":\\"${currentBuild.result}\\"}"
            '''
        }
    }
}</script>
    <sandbox>true</sandbox>
  </definition>
  <triggers/>
  <disabled>false</disabled>
</flow-definition>
```

#### Scenario: GitHub Actions suite auto-created
- **WHEN** QA 建立 suite「Login Regression」
- **THEN** `github_actions_ci.create_suite_job()` SHALL 建立 `.github/workflows/tcrt-suite-5-login-regression.yml`
- **WHEN** workflow 成功建立
- **THEN** TCRT SHALL 在 `automation_script_groups.ci_job_name` 記錄 `tcrt-suite-5-login-regression`

#### Scenario: Jenkins suite auto-created
- **WHEN** QA 建立 suite「Login Regression」，team 已配置 Jenkins provider
- **THEN** `jenkins_ci.create_suite_job()` SHALL：
  1. 若 team view 不存在 → `create_view("TCRT-TCG-QA", "...")`
  2. `create_job("tcrt-suite-5-login-regression", config_xml)`
  3. `add_job_to_view("TCRT-TCG-QA", "tcrt-suite-5-login-regression")`

#### Scenario: Suite modification syncs to CI
- **WHEN** QA 從 suite 移除一個 script
- **THEN** `update_suite_job()` SHALL 重新產生 config 並更新 CI 端；GitHub Actions 更新 YAML 內容；Jenkins 更新 config.xml

#### Scenario: Delete suite cleans up CI
- **WHEN** QA 刪除 suite
- **THEN** `delete_suite_job()` SHALL：
  - GitHub Actions：`delete_file(path=".github/workflows/tcrt-suite-xxx.yml")`
  - Jenkins：`delete_job("tcrt-suite-xxx")`（Jenkins 自動從 view 移除）

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

### Requirement: Changes to infer_script_format MUST sync the tcrt-automation-pomify skill
`infer_script_format()` 為 TCRT 對「使用者的 script 檔案 → `script_format`」的權威映射函式。任何對其判定條件的變更（新增副檔名、改變優先順序、新增/移除 enum 對應）SHALL 在同一個 change / PR 中同步更新可攜 skill 的對照表，否則該 change 不得 archive。

需同步檔案：

- `tools/skills/tcrt-automation-pomify/references/tcrt-format-rules.md` 的 §4「`script_format` 推斷」段落
- `tools/skills/tcrt-automation-pomify/references/framework-detection.md` 的 Step 3 對照表
- `tools/skills/tcrt-automation-pomify/SKILL.md` 步驟 4 的檔名規則表

#### Scenario: Adding .cy.ts extension
- **WHEN** 開發者擴充 `infer_script_format` 讓 `*.cy.ts` 也回 `PLAYWRIGHT_JS`（or 新 enum `CYPRESS_JS`）
- **THEN** 同 PR SHALL 更新 skill references 把 `.cy.ts` 加入對照表；若引入新 enum 也 SHALL 新增 `templates/typescript/cypress_ts/` 範本

#### Scenario: Provider Protocol signature change
- **WHEN** `StorageProvider` / `CIProvider` 新增的 method 不影響 script 對外格式（例如新增 cache 內部 method）
- **THEN** skill 同步義務 NOT applicable；無需更動 skill 檔案

### Requirement: System MUST store org-level CI and Result provider configuration
資料表 `system_automation_providers` SHALL 包含與 `team_automation_providers` **相同的欄位集合，但無 `team_id`**：

- `id` PK
- `provider_slot` enum(`CI`/`RESULT`) NOT NULL — **CHECK constraint `ck_system_provider_ci_or_result_only` SHALL 限制 `provider_slot IN ('ci', 'result')`**
- `provider_type` VARCHAR(60) NOT NULL（如 `ci:jenkins`、`result:allure`）
- `name` VARCHAR(100) NOT NULL
- `config_json` TEXT NOT NULL
- `credentials_encrypted` TEXT nullable
- `is_active` BOOLEAN default true
- `last_health_check_at` DATETIME nullable
- `last_health_status` VARCHAR(40) nullable
- `created_by`, `updated_by`, timestamps
- UniqueConstraint `(provider_slot, name)`
- Index `(provider_slot, is_active)`

ORM class `SystemAutomationProvider` SHALL 共用一份欄位 mixin 與 `TeamAutomationProvider` 以避免漂移。

Bootstrap 啟動時「主資料庫缺重要表」檢查 SHALL 包含 `system_automation_providers`。

#### Scenario: Inserting storage row into system table rejected
- **WHEN** code 嘗試 `INSERT INTO system_automation_providers (..., provider_slot = 'storage', ...)`
- **THEN** DB SHALL 違反 CHECK constraint 並拋 `IntegrityError`

#### Scenario: Org-level uniqueness independent of team
- **WHEN** Super Admin 嘗試新增第二筆 `provider_slot=CI, name='production-jenkins'`
- **THEN** UniqueConstraint SHALL 拒絕並回 409 `DUPLICATE_NAME`

### Requirement: Per-team provider API MUST reject ci and result slot at app layer
`POST /api/teams/{team_id}/automation-providers` 與 `PUT /api/teams/{team_id}/automation-providers/{id}` SHALL：

1. 驗證 payload 的 `provider_slot` 與 `provider_type` 的 slot prefix 都是 `storage`
2. 嘗試指定 `ci` / `result` slot SHALL 回 400 `WRONG_PROVIDER_SCOPE`，錯誤訊息 SHALL 指引至「組織與系統設定」頁面（`/organization-management`）的 Org Automation Infra 分頁

#### Scenario: Team admin posts ci provider rejected
- **WHEN** team admin 對 `/api/teams/5/automation-providers` POST `{"provider_slot": "ci", "provider_type": "ci:jenkins", ...}`
- **THEN** API SHALL 回 `400 WRONG_PROVIDER_SCOPE`，訊息 SHALL 包含「請 Super Admin 至『組織與系統設定』設定」

#### Scenario: Team admin posts storage provider accepted
- **WHEN** team admin 對 `/api/teams/5/automation-providers` POST `{"provider_slot": "storage", "provider_type": "storage:github", ...}`
- **THEN** API SHALL 接受並建立 row（既有行為不變）

### Requirement: Org-level provider API MUST require Super Admin
新增 router `/api/system/automation-providers` SHALL 提供與 team-scoped router 對等的端點集合（list / get / create / update / delete / test-connection / test-config / discover-runners / types）。全部端點 SHALL `Depends(require_super_admin)`。

非 Super Admin 呼叫 SHALL 回 `403 INSUFFICIENT_PERMISSION`。

#### Scenario: Super Admin creates Jenkins org provider
- **WHEN** Super Admin 對 `/api/system/automation-providers` POST `{"provider_slot": "ci", "provider_type": "ci:jenkins", "name": "company-jenkins", ...}`
- **THEN** API SHALL 接受並建立 row

#### Scenario: Team admin attempts to call system endpoint
- **WHEN** 非 Super Admin user 對 `/api/system/automation-providers` GET
- **THEN** API SHALL 回 `403 INSUFFICIENT_PERMISSION`

#### Scenario: System endpoint accepts only ci or result slot
- **WHEN** Super Admin 對 `/api/system/automation-providers` POST `{"provider_slot": "storage", ...}`
- **THEN** API SHALL 回 400 `WRONG_PROVIDER_SCOPE`，訊息 SHALL 指引「Storage provider 請至 team 設定頁」

### Requirement: Org-level provider UI MUST live in the organization management page

`/organization-management` 頁面 SHALL 包含一個分頁 `tab-org-automation-infra`，顯示 Jenkins / Allure provider 管理表格與 Add Provider modal。整個分頁 SHALL 沿用既有 Super Admin 守門（透過 `ui_capabilities.yaml` 的 `pages.organization.components.tab-org-automation-infra` 宣告式設定，見 `organization-management-console`）。

`/automation-provider-settings` 頁面 SHALL：

1. 頁面標題改為「Git 來源設定」(i18n key `gitSourceSettings.title`)
2. `CANONICAL_TYPES` 在 JS 端僅保留 `storage:github`
3. 編輯既有非 canonical type（如 `storage:local_git`）的 row 仍允許，但 slot dropdown 不顯示 ci/result 選項
4. UI 不再暴露 Jenkins / Allure 的 Add Provider 路徑

#### Scenario: Git Source Settings page only lists storage providers
- **WHEN** team admin 開啟 `/automation-provider-settings`
- **THEN** 頁面標題 SHALL 顯示「Git 來源設定」；Provider table SHALL 只列 `provider_slot = storage` 的 row

#### Scenario: Org Automation Infra tab visible to Super Admin only
- **WHEN** Super Admin 開啟 `/organization-management`
- **THEN** 頁面 SHALL 包含 `tab-org-automation-infra` 分頁，展開後 SHALL 看到既有的 org-level CI / Result provider 列表 + Add Provider 按鈕
- **WHEN** 非 Super Admin user 進入同一頁
- **THEN** `tab-org-automation-infra` 分頁 SHALL 不可見（既有行為，僅入口位置從 team_management modal 改為 organization-management 頁面）

### Requirement: Provider audit log MUST identify scope
provider CRUD 的 audit log SHALL 透過獨立的 `ResourceType.SYSTEM_AUTOMATION_PROVIDER` 與既有 `ResourceType.AUTOMATION_PROVIDER` 區分；team-scoped 紀錄保留 `team_id`，org-scoped 紀錄 `team_id` 欄位為 NULL。

#### Scenario: Org provider create logs system-scope resource type
- **WHEN** Super Admin 建立一個 org-level Jenkins provider
- **THEN** audit log SHALL 寫入 `resource_type = SYSTEM_AUTOMATION_PROVIDER`、`team_id = NULL`、`actor = super_admin_user_id`

