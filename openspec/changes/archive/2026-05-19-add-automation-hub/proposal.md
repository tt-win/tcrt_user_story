## Why

TCRT 已具備手動測試案例管理；團隊有兩個外部工具產生 Playwright 腳本（`ai_steps_recorder` 錄製、`element_locator_generator` 出 selector）；CI 系統（GitHub Actions / GitLab CI / Jenkins）已負責執行；Allure / ReportPortal / Playwright HTML Reporter 已負責結果與報表。**這些工具已能解決「寫、跑、報」的問題**。

但仍存在三個 TCRT 才能解決的痛點：

1. **手動 Test Case ↔ 自動化腳本的對照消失**：沒有任何工具知道 TCRT 的 `test_cases` 表；QA 不知道哪些 case 已有自動化、覆蓋率多少
2. **跨工具切換成本**：QA 在 TCRT 看 case，然後跳到 GitHub 看 script，再跳到 GH Actions 看 run，再跳到 Allure 看 report；缺乏「single pane of glass」
3. **AI Helper 缺少自動化視角**：QA AI Helper 推薦 test case 時不知道哪些 case 已自動化，無法建議「補手動 case」vs「複用既有 script」

本 change 把 TCRT 改造為 **「自動化測試的 Hub」**：用 Provider 適配器代理 git / CI / 報表工具，UI 整合在 TCRT 既有 team 工作區。**所有重活由專業 OSS 工具負責，TCRT 只做：協調 + 對照 + AI 介接**。

## What Changes

### 核心：Provider 抽象框架
- 定義三個 `Protocol` 介面：`StorageProvider`、`CIProvider`、`ResultProvider`
- 內建適配器（v1）：
  - StorageProvider：`GitHubProvider`（透過 GitHub REST API）、`LocalGitProvider`（air-gapped）
  - CIProvider：`GitHubActionsProvider`（透過 `workflow_dispatch` API）、`JenkinsProvider`（透過 buildWithParameters + queue item 配對）
  - ResultProvider：`AllureProvider`（URL 連結 / iframe）
- 未來可擴充（v2 候選，不在本 change）：`GitLabProvider`、`GiteaProvider`、`GitLabCIProvider`、`ReportPortalProvider`、`PlaywrightHTMLProvider`、`JenkinsBuiltinResultProvider`
- 每個 team 配置一組 provider 設定，credentials AES-256-GCM 加密落地

### Script 自動發現，不手動管理
- `automation_scripts` 表為**自動掃描快取**：TCRT 呼叫 `StorageProvider.list_scripts()` 掃描 repo（如 `tests/` 目錄），自動填入/更新快取
- **無**手動 register 流程；使用者直接在 GitHub / IDE 管理檔案
- TCRT 只負責：載入列表 → 顯示於 Suites tab → 讓使用者勾選組合成 suite → 產生 CI workflow/job
- Script preview 為 read-only；所有編輯在 IDE 完成後推上 git

### 觸發執行 → 委派 CIProvider
- TCRT 提供「執行此 script」/「執行整 set」按鈕
- 後端透過 CIProvider 觸發外部 CI（GH Actions 用 `workflow_dispatch`、GitLab 用 pipeline trigger token）
- 新增 `automation_runs` 表紀錄 external_run_id + url + status，不存 stdout / artifact
- 狀態同步：CI 完成後 webhook 通知 TCRT；過渡狀態 TCRT 可低頻 poll（cache + etag）

### 看結果 → 嵌入 / 跳轉 ResultProvider
- Per-run 報表：iframe 嵌入 Allure URL 或 Playwright HTML 報表，或直接跳轉
- Trend / dashboard：跳轉到 ReportPortal（若 team 有部署）或 GH Actions Insights
- TCRT 自己**不重做**這些介面

### M2M linkage 是 TCRT 的核心價值
- 新增 `automation_script_case_links` 表：script ↔ test_case 多對多，含 `link_type ∈ {PRIMARY, COVERS, REFERENCES}`、`note`
- Script preview（嵌入在 Suites tab 或 case detail）可檢視 linked cases 與執行歷史，提供「Open in GitHub」連結至 IDE 編輯
- Test case detail 頁新增「Automation Coverage」面板：列出所有 linked scripts 與 last_run_status + 跳轉到 CI / Allure 的連結
- Audit 整合：linkage 變更寫稽核

### Webhook 雙向（簡化版）
- **Inbound**：`POST /api/v1/webhooks/ci/{token}` 接收 CI 完成事件（GH Actions / GitLab CI 都有 native webhook），更新 `automation_runs` status
- **Outbound**：TCRT 對 user 設定的目標 URL 發送 `script.linked`、`script.unlinked`、`run.tracked` 等事件（給 Slack / Lark / 第三方）
- 不需要自家 webhook retry queue（events 是輕量 broadcast，丟掉就丟掉，UI 上仍能看到）

### MCP 唯讀擴充
- `GET /api/mcp/teams/{team_id}/automation-scripts` 列出所有 script 與 last_run_status
- `GET /api/mcp/teams/{team_id}/automation-runs` 列出最近 runs
- 既有 `GET /api/mcp/teams/{team_id}/test-cases/{id}` 追加 `linked_automation_scripts` 陣列
- AI Helper 可問「哪些 case 還沒有自動化覆蓋」、「最近哪些自動化跑 fail 了」

## 非目標

- **不在 TCRT 內 host runner**：執行交給 GH Actions / GitLab CI / Jenkins
- **不存 script 內容為 source of truth**：git 是主存，TCRT 只快取
- **不重做 Allure / ReportPortal 的報表**：直接連結 / iframe
- **不做自家 CodeMirror IDE 體驗**：TCRT **不**提供內建編輯器，所有編輯由使用者在慣用 IDE（VS Code / PyCharm / GitHub Web Editor）完成後推上 git；TCRT 只提供唯讀預覽
- **不做 test_data 加密管理**：交給 GH Secrets / GitLab Variables / Vault；TCRT 只記錄「這個 workflow 用了哪些 secret key 名稱」供 UI 顯示
- **不做 marker 替換 / 偵測 Playwright fill 的綁定**：交給標準環境變數注入（CI 既有能力）
- **v1 不做 GitLab / Gitea / ReportPortal / Playwright HTML / Jenkins 內建報表適配器**：先聚焦 GitHub + Jenkins（CI）+ Allure（Result），v2 再擴充
- **不取代既有 manual test case management**：純粹是補強

## Capabilities

### Added Capabilities
- `automation-hub-provider-framework`：Provider Protocol 抽象 + per-team 設定表 + credential 加密 + GitHub / LocalGit / GH Actions / Allure 內建適配器
- `automation-hub-script-management`：Script 自動發現（auto-discovery from StorageProvider）+ M2M linkage to test cases + 唯讀預覽（read-only preview）+ Suite 組合與管理 + 反向 panel on test case detail
- `automation-hub-smart-suite-recommendation`：**Smart Scan** — Automation Repo Contract + deterministic repo scan 自動識別 test script 進入點並推薦 regression suite 組合；LLM 僅做 optional suite 名稱/描述 enrichment；一鍵掃描、確認後批次建立 suites
- `automation-hub-run-orchestration`：觸發 run（delegate to CIProvider）+ 狀態同步 + 歷史列表 + 報表跳轉 / 嵌入
- `automation-hub-webhook-integration`：Inbound CI 完成 webhook + Outbound 事件廣播 + HMAC 簽章
- `automation-hub-mcp-read`：MCP 端 scripts / runs / linkage 唯讀暴露

### Modified Capabilities
- `mcp-read-api`：test case detail 追加 `linked_automation_scripts` 概要

## Impact

- **程式**：
  - 新增 ORM 於 `app/models/database_models.py`（5 張表：`team_automation_providers`、`automation_scripts`、`automation_script_case_links`、`automation_runs`、`automation_webhooks`）
  - 新增 Pydantic schemas：`app/models/automation_provider.py`、`automation_script.py`、`automation_run.py`、`automation_webhook.py`
  - 新增 services：
    - `app/services/automation/providers/base.py`（Protocol 定義）
    - `app/services/automation/providers/github_storage.py`、`local_git_storage.py`
    - `app/services/automation/providers/github_actions_ci.py`、`jenkins_ci.py`
    - `app/services/automation/providers/allure_result.py`
    - `app/services/automation/provider_registry.py`、`provider_credential_service.py`
    - `app/services/automation/script_service.py`、`run_service.py`、`linkage_service.py`、`webhook_service.py`
  - 新增 routers：
    - `app/api/automation_providers.py`、`automation_scripts.py`、`automation_runs.py`、`automation_webhooks.py`、`automation_links.py`、`automation_webhooks_public.py`
  - 修改：`app/api/__init__.py`、`app/api/mcp.py`、`app/models/mcp.py`、`app/database_init.py`、`app/audit/__init__.py`、`app/templates/team_management.html`、`app/templates/test_case_management.html`
  - 新增 templates：`automation_hub.html`（team 內 hub 入口，含 Suites tab / Runs tab / Coverage tab / Settings tab）、`automation_run_history.html`、`automation_provider_settings.html`；**無** `automation_script_detail.html`（script preview 為嵌入式展開區塊）
  - 新增 JS 模組：`app/static/js/automation-hub/`（list / detail / runs / providers）
- **API**：
  - Team-scoped：providers / scripts / runs / links / webhooks
  - 公開：inbound CI webhook
  - MCP：automation scripts / runs 列表 + test case 反向
- **資料**：5 張新表 + Alembic migration；不存 script content 為主存（cached_content 為快取）
- **安全**：
  - Provider credentials（GitHub PAT、Jenkins password）AES-256-GCM 加密
  - Webhook secret 一次性顯示
  - Inbound webhook 走 HMAC 驗章
- **i18n**：新增 `automationHub.*` namespace
- **相容性**：所有變更為新增；既有 manual test case 流程不變
- **部署**：
  - 必填新環境變數 `AUTOMATION_PROVIDER_ENCRYPTION_KEY`（AES-256 base64-encoded 32 bytes）
  - 不新增 Docker service；user 自備 CI（GH Actions / GitLab / Jenkins）
  - 不強制依賴 ReportPortal 等外部報表（Allure 已足夠）
- **文件**：新增 `docs/automation-hub-overview.md`、`docs/automation-provider-setup.md`（含 GitHub / LocalGit / GH Actions 設定範例）、`docs/automation-webhook.md`
