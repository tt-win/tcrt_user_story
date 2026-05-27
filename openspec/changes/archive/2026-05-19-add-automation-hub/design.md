## Context

TCRT 是 FastAPI async + Jinja2 + SQLite/MySQL + Bootstrap 5（無 JS build）的測試管理系統，所有資料 team-scoped。手動測試完整生命週期已支援；自動化測試目前依賴外部生態（git + CI + Allure / ReportPortal），但沒有與 TCRT 的 manual test case 對照。

本 change 採 **Backend for Frontend / Facade** 模式：TCRT 變成「自動化測試 Hub」，定義 Provider 適配器抽象介面，把實際工作委派給專業 OSS 工具（GitHub、GH Actions、Allure），自己只守住「manual case ↔ automation 對照」、「team-scoped UI 整合」、「MCP 給 AI Helper」。

## Goals / Non-Goals

**Goals**
- 一個 single pane of glass：QA 在 TCRT 看 case + 看 script + 觸發 run + 看 report，不需要切五個工具
- 不重造輪子：執行、儲存、報表全部交給 OSS
- Provider 抽象：未來換 CI / git 平台不痛
- M2M linkage 是核心；test case detail 上即時可見「哪些自動化覆蓋」
- AI Helper / MCP 可看到自動化覆蓋與最近執行狀態
- v1 air-gapped 場景仍可用（LocalGit + 自架 Jenkins）

**Non-Goals**
- 不 host runner、不執行 Playwright
- 不複製 script content 為主存（git 是主存）
- 不重做 Allure / ReportPortal 的報表
- v1 不支援 GitLab / ReportPortal / Playwright HTML 適配器
- 不做 test_data 加密與綁定（交給 CI secret 與環境變數注入）
- 不做 marker 替換（CI 已有 secret 注入機制）

## Decisions

### 1. Hub 模式優於完整 lifecycle

**Decision**：TCRT 是 facade / aggregator，不是 IDE + runner + report 平台。

**Rationale**：
- `ai_steps_recorder` + `element_locator_generator` 已能產出腳本；TCRT 不需要當 IDE
- GitHub / GitLab + Playwright Docker image + native CI runner 已是業界標準；TCRT 自己做 runner 是重造輪子且維運成本高
- Allure / ReportPortal / Playwright HTML 已比我們能做的好；TCRT 只做連結 / iframe 即可
- TCRT 真正不可替代的是「**manual case ↔ automation 對照**」+「**AI Helper 上下文**」

**Alternatives considered**：
- 完整 lifecycle（自家 runner + 編輯器 + 報表）：4 週工時、~120 任務、長期維運負擔大
- 純 metadata（只存連結，不代理 git / CI）：UI 體驗碎片化，使用者仍要切多個工具

### 2. Provider Protocol 抽象

定義三個 Python `Protocol`（type-only），讓真實適配器實作：

```python
class StorageProvider(Protocol):
    """git-like 儲存。負責讀寫 script 檔案、列分支、列檔案。"""
    async def list_scripts(self, path: str, ref: str | None = None) -> list[ScriptRef]: ...
    async def read_script(self, path: str, ref: str | None = None, etag: str | None = None) -> ScriptContent: ...
    async def write_script(self, path: str, content: str, message: str, branch: str | None = None) -> CommitRef: ...
    async def list_branches(self) -> list[BranchRef]: ...
    async def create_pull_request(self, branch: str, title: str, body: str) -> PullRequestRef | None: ...

class CIProvider(Protocol):
    """執行端。負責觸發、查狀態、列 artifact。"""
    async def list_workflows(self) -> list[WorkflowRef]: ...
    async def trigger_run(self, workflow_id: str, branch: str, inputs: dict[str, str]) -> ExternalRunRef: ...
    async def get_run_status(self, run_id: str) -> RunStatusSnapshot: ...
    async def cancel_run(self, run_id: str) -> None: ...
    async def get_run_url(self, run_id: str) -> str: ...
    async def list_artifacts(self, run_id: str) -> list[ArtifactRef]: ...

class ResultProvider(Protocol):
    """報表 / 結果視覺化。負責 per-run report URL 與 dashboard URL。"""
    async def get_run_report_url(self, ci_external_run_id: str) -> str | None: ...
    async def get_dashboard_url(self) -> str | None: ...
```

**Rationale**：標準 Python typing，無需引入額外抽象框架；好測試、好替換、好擴充。

### 3. Provider 註冊與選擇

`provider_registry.py` 維護一份 `{provider_type: provider_class}` 對照表。內建：

| Provider type | Module |
|---|---|
| `storage:github` | `providers/github_storage.py` |
| `storage:local_git` | `providers/local_git_storage.py` |
| `ci:github_actions` | `providers/github_actions_ci.py` |
| `ci:jenkins` | `providers/jenkins_ci.py` |
| `result:allure` | `providers/allure_result.py` |

每個 team 在 `team_automation_providers` 中為三個 slot（storage / ci / result）各選一個。同 team 同時用 GitHub Actions 與 Jenkins 兩個 CI 的場景，v1 透過「每個 script register 時指定 provider_id」處理；單 team 多 CI provider 並存允許但 UI 列「執行」按鈕需要顯式選擇要去哪個 CI。

未來新增 `storage:gitlab`、`storage:gitea`、`result:reportportal`、`result:playwright_html` 只需加 module + 註冊；無需動 core。

### 4. Credential 加密

`team_automation_providers.credentials_encrypted` 為 AES-256-GCM 加密的 JSON（含 token / password / API key）。金鑰由 `AUTOMATION_PROVIDER_ENCRYPTION_KEY` 環境變數提供（base64-encoded 32 bytes），可與既有設定共用同一個 secret 服務。

Bootstrap 啟動時若 `team_automation_providers` 表非空但金鑰缺失：報錯並提供生成指引。

**為何不沿用 SCRIPT_DATA_ENCRYPTION_KEY**：原計畫該金鑰用於 test_data 加密，現已不存 test_data；本 change 引入新 namespace 的金鑰避免概念混淆。

### 5. Script 是「指標」不是「內容」

`automation_scripts` 欄位：

| 欄位 | 用途 |
|---|---|
| `id`、`team_id`、`name` | 基本身份 |
| `provider_id` FK → `team_automation_providers` | 屬於哪個 storage provider |
| `ref_path` | 在 repo 中的路徑（如 `tests/test_login.py`） |
| `ref_branch` | 預設讀寫的 branch（如 `main`） |
| `script_format` | `PLAYWRIGHT_JS` / `PLAYWRIGHT_PY_ASYNC` / `PYTEST` / `OTHER` |
| `cached_content` | optional：上次讀到的內容，用於離線 preview 與 diff |
| `cached_content_etag` | provider 端 etag / SHA，cache 失效用 |
| `last_synced_at` | 上次同步時間 |
| `linked_test_case_count` | 反向計數（query 效能） |
| `description`、`tags_json` | 使用者自訂 metadata |

**Source of truth 是 git**。TCRT cache 一份是為了 list 頁不用每次打 GH API、case detail 顯示時可秒回；過期 / 失效時透明 refresh。

### 6. Script 管理流程（TCRT 不編輯，只觸發與連結）

TCRT **不**提供內建編輯器，所有 script 的建立與修改由使用者在慣用 IDE 完成後推上 git。

使用者在 TCRT 管理 script：

1. **Register**：使用者在 IDE 建立 `tests/test_login.py` 並 push → 在 TCRT 填 `ref_path`、`ref_branch`、`name` → TCRT 呼叫 `StorageProvider.read_script` 驗證存在 → 建立 `automation_scripts` 紀錄 → 拉 `cached_content` 用於 preview
2. **Preview**：在 Suites tab 點擊檔案 → 展開 CodeMirror **read-only** 顯示 cached_content；點擊「Open in GitHub」跳轉到 IDE 編輯
3. **Sync**：使用者編輯並 push 後 → TCRT 背景 sync 或手動 Refresh → 比對 etag → 更新 cached_content
4. **Link**：在 suite 詳情或 case detail 建立 `automation_script_case_links`
5. **Run**：點「Run Now」→ TCRT 觸發 CI → 建立 `automation_runs` → 輪詢狀態 → 收 webhook 更新

**Rationale**：TCRT 是觸發與管理平台，不是 IDE。讓 QA 在專業工具（VS Code / PyCharm）編輯，確保 POM、import、debug 等複雜場景都能處理；TCRT 只負責「登記、預覽、連結、觸發、看報告」。

### 7. M2M linkage 是 TCRT 端純資料

`automation_script_case_links` 完全活在 TCRT DB：

| 欄位 | 用途 |
|---|---|
| `id`、`team_id` | |
| `automation_script_id` FK CASCADE | |
| `test_case_id` FK → `test_cases.id` CASCADE | |
| `link_type` | `PRIMARY` / `COVERS` / `REFERENCES`，預設 `COVERS` |
| `note` | |
| `created_by`、`created_at` | |

UniqueConstraint `(automation_script_id, test_case_id)`；同 case 至多一支 PRIMARY（service 層驗證）。

**Rationale**：linkage 是 TCRT 唯一不該外包的概念；獨立表方便反向查詢與將來的 coverage 分析。

### 8. Run 觸發委派 CIProvider

使用者在 TCRT 點「執行此 script」：

1. TCRT 解析 script 所屬的 CI provider 與 workflow（從 script.tags 或讓使用者選；若 team 有多 CI provider，UI 提示選定）
2. 產生 `tcrt_correlation_id = uuid4()`
3. TCRT 呼叫 `CIProvider.trigger_run(workflow_id, branch, inputs={**user_inputs, "tcrt_run_id": tcrt_correlation_id})`
4. TCRT 建立 `automation_runs` 紀錄，status=QUEUED；external_run_id 可能尚未取得
5. 背景任務輪詢配對 external_run_id；成功 → 更新；60 秒失敗 → 標 UNKNOWN

#### GitHub Actions 配對機制
- API：`POST /repos/{owner}/{repo}/actions/workflows/{id}/dispatches`，body `{ref, inputs}`，**fire-and-forget**，不回 run_id
- 配對：注入 `inputs.tcrt_run_id`，後續 60 秒內輪詢 `GET /repos/.../actions/runs?event=workflow_dispatch&created>=<trigger_time-5s>`，用 workflow + branch + event + 建立時間做 best-effort 配對。GitHub REST run list API 不回傳 workflow_dispatch input 值，因此 `inputs.tcrt_run_id` 只保留為 CI 端排查與後續 reconcile 線索，不能當作 list API 上的精準比對條件
- workflow YAML 範例：第一步 `echo "tcrt_run_id=${{ inputs.tcrt_run_id }}"` 讓 user 後續排查

#### Jenkins 配對機制
- API：`POST /job/{name}/buildWithParameters?token=<trigger_token>&tcrt_run_id=<uuid>`，可帶任意自訂參數
- 認證：Basic Auth (username + API token) 或 trigger token plugin；adapter 先 GET `/crumbIssuer/api/json` 取 CSRF crumb（若啟用）
- 回應：201 Created + `Location: /queue/item/{queue_id}/` header
- 配對：輪詢 `GET /queue/item/{queue_id}/api/json`，取 `executable.url`（含 build number）；queue 中 `cancelled=true` 則標 CANCELLED；60 秒未上 build 也標 UNKNOWN
- 一旦取得 build number，後續切到 `GET /job/{name}/{build_id}/api/json` 同步狀態
- 狀態映射：`result=SUCCESS → SUCCEEDED`、`FAILURE/UNSTABLE → FAILED`、`ABORTED → CANCELLED`、`result=null + building=true → RUNNING`、`result=null + building=false → QUEUED`

v1 兩個 adapter 都採「uuid 注入 + 配對」模式；docs 各提供一份 workflow / Jenkinsfile 範例。

### 9. Run 狀態同步：webhook 為主、輪詢為輔

**Webhook 為主**：CI 完成後 POST 到 TCRT inbound endpoint，更新 `automation_runs.status` + `finished_at` + result_report_url。

**輪詢為輔**：對 status=QUEUED / RUNNING 的 run，TCRT 每 60 秒呼叫 `CIProvider.get_run_status` 對齊。避免完全依賴 webhook（會丟）。

**狀態值**：`QUEUED` / `RUNNING` / `SUCCEEDED` / `FAILED` / `CANCELLED` / `UNKNOWN`（API 回傳超出已知範圍時）。

### 10. Result 嵌入策略（v1：Allure 單一）

v1 只內建 `result:allure`。理由（與其他三個方案比較）：

| 方案 | 為何不在 v1 |
|---|---|
| Playwright HTML | 沒 history / trend，只支援 Playwright；Jenkins / GH Actions 內已可直接看 |
| ReportPortal | 5 個 docker service ~3-4GB RAM，部署成本高；可由 team 自行加 v2 adapter 接 |
| Jenkins built-in | 介面老舊、iframe CSP 常炸；Jenkins job URL 已由 `ci:jenkins` 提供，按鈕跳過去自然能看 |

`result:allure` 兩種模式並存：

- **URL link mode**（預設）：UI 顯示按鈕「在 Allure 中開啟」→ 新分頁；最簡單、最不出錯
- **iframe embed mode**：UI 內嵌 `<iframe src="...">`；需要 Allure server 允許跨域（移除 X-Frame-Options DENY、設適當 CSP）；好處是不切頁

Allure config schema：
- `base_url`: e.g. `https://allure.internal.tcg.com`
- `run_url_template`: e.g. `{base_url}/projects/{project}/launches/{ci_external_run_id}`
- `embed_mode`: `link` | `iframe`，預設 `link`
- `dashboard_url`: optional，hub 首頁 dashboard 連結
- `project`: optional，多專案場景下指定

Allure 的部署由 user 自理（GitHub Pages / S3 / 公司內 nginx 都可）；TCRT 不負責。docs 提供常見部署 pattern。

### 11. Webhook 設計（簡化）

#### Inbound：`POST /api/v1/webhooks/ci/{token}/run-status`

| Header | 用途 |
|---|---|
| `X-TCRT-Signature: sha256=<hex>` | HMAC-SHA256 over raw body |
| `X-TCRT-Delivery: <uuid>` | idempotency |

Body：`{ "tcrt_run_id": "uuid", "external_run_id": "...", "status": "SUCCEEDED", "report_url": "...", "finished_at": "ISO8601" }`

#### Outbound：對 user 設定的 URL 發送事件

事件：`script.discovered`、`script.synced`、`script.linked`、`script.unlinked`、`run.triggered`、`run.tracked`、`run.completed`

無 retry queue（v1）：發送失敗只寫 audit + UI 顯示警告。理由：外部訂閱者一般有自己的訂閱機制（Slack incoming webhook 失敗就丟），不需要 TCRT 端 retry 引擎。

未來若有 webhook reliability 強需求，可另立 change 加入 retry。

### 12. UI 結構

TCRT team 工作區內新增 **Automation Hub** 入口（與 manual test case management 並列），分三個 tab（**無 Scripts tab**）：

1. **Suites**：從 GitHub 自動載入檔案列表（左側），組合成 suite / 執行 suite（右側）；點擊單一檔案可展開 read-only preview
2. **Runs**：執行歷史列表，跨 suite，跨 workflow；點開直接跳 CI 原生 UI
3. **Coverage**：顯示「manual cases 自動化覆蓋率」+ 未覆蓋清單；補強 manual case detail 的反向 panel
4. **Settings**：admin 配置 storage / ci / result providers

Manual `test_case_management.html` 內每個 case detail 新增「Automation」面板：顯示 linked scripts（來自 auto-discovery）、last run status、跳轉到報表的連結。

### 13. AI Helper / MCP 整合

新增 MCP 端點讓 AI Helper（與第三方 MCP client）能：

- `GET /api/mcp/teams/{team_id}/automation-scripts`：列所有 script + last_run_status + linked_test_case_numbers
- `GET /api/mcp/teams/{team_id}/automation-runs`：最近 N 筆 runs
- `GET /api/mcp/teams/{team_id}/test-cases/{id}` 既有端點追加 `linked_automation_scripts: [{name, format, last_run_status, link_type}]`

AI Helper 場景：
- 「這個 sprint 要產 case 100 張」→ 先看哪些既有 case 有自動化 → 推薦複用 / 不重複建
- 「最近 7 天 fail 最多的自動化是？」→ 直接 query MCP
- 「TC-456 有自動化嗎？沒有的話有沒有類似的 script 可以複用？」

### 14. Audit 整合

新增 `ResourceType`：`AUTOMATION_PROVIDER`、`AUTOMATION_SCRIPT`、`AUTOMATION_SCRIPT_LINK`、`AUTOMATION_RUN`、`AUTOMATION_WEBHOOK`。所有寫入操作 SHALL 寫 audit；inbound webhook 觸發的 run status 變更標 `change_source=ci_webhook`。

### 15. Smart Scan：repo contract + deterministic scan + optional LLM enrichment

TCRT 在 Suites tab 提供「Smart Scan」按鈕：

1. **非同步 scan run**：`POST .../smart-scan` 立即回 `scan_run_id`；UI 輪詢 progress / result，避免大型 repo 或 LLM timeout 卡住 request
2. **Automation Repo Contract**：優先讀取 repo root 的 `tcrt-automation.yml`，取得 `paths.tests`、POM/support paths、include/exclude、suite grouping、artifact paths；沒有 manifest 時才 fallback 到 provider `smart_scan` config
3. **Repo structure validation**：檢查標準 QA automation 結構（`tests/`、`pages/`、`flows/`、`fixtures/`、`resources/`、`config/`），並把 manifest 狀態、missing paths、violations 寫入 scan result
4. **Deterministic entry point detection**：`list_scripts(recursive=True)` 掃描 effective tests path → path filtering → Python AST / JS bounded lexical scan 判斷 test entry points；POM、fixtures、resources、config、scripts、reports 一律視為 support / ignored path
5. **Rule-based 分組**：按子目錄結構初步分群（`tests/auth/` → Auth group），此結果即為可用 fallback
6. **Optional LLM enrichment**：若 `enable_llm=true` 且 OpenRouter 設定可用，將每個 group 的 `ref_path + test function names + format + estimated count` 送給 LLM，產生較語意化的 suite 名稱與描述
7. **建議清單**：UI 顯示 repo contract validation、推薦 suites、excluded files 與 enrichment source，使用者確認/修改後批次建立

建議的 repo contract：

```text
automation-repo/
  tcrt-automation.yml
  tests/       # test entry points only
  pages/       # POM / Page Object Model
  flows/       # reusable business flows
  fixtures/    # setup helpers
  resources/   # data, files, locators
  config/      # env templates, no secrets
  scripts/     # local helper scripts
  reports/     # generated artifacts
```

有效掃描設定解析順序：
1. provider config 中 admin-enforced 的值
2. valid `tcrt-automation.yml`
3. provider `smart_scan` defaults

**LLM 輸入限制**：預設只傳送 `ref_path` + test function names + detected format + estimated count，不傳完整內容或 snippet；除非 admin 明確設定 `send_source_snippets_to_llm=true`，才可傳送經截斷與 masking 的 snippet。timeout 10 秒，超時 fallback 為 rule-based 名稱。

**增量掃描**：以 `manifest_etag + ref_path + branch + etag + scan_config_hash` 判斷變更；再次掃描時重用未變更 entry point / enrichment 結果，建議「加入既有 suite」或「建立新 suite」。

### 16. Rate limit 與 cache

GitHub API 限 5000 req/hour authenticated。TCRT 使用：
- `If-None-Match` / `etag` cache（GitHub 不算 304 入 rate limit）
- script list cache TTL 5 分鐘
- script content cache TTL 30 秒（預覽體驗）
- run status cache TTL 30 秒（變化頻繁）
- workflow list cache TTL 30 分鐘
- **Smart Scan result cache**：cache key 含 manifest etag、script etags、test_names hash、model id、prompt version、scan_config_hash

team 等級啟用 GitHub App 而非 PAT 可把 limit 提升到 15000 / hour；docs 建議 production 走 GitHub App。

### 17. 雙工部署模式

- **與 cloud git / CI 整合**（多數場景）：用 `storage:github` + `ci:github_actions`
- **Air-gapped**（無外部網路）：v1 用 `storage:local_git`（mount 內部 git server 的 working copy）+ `ci:jenkins`
  - Jenkins provider 透過自架 Jenkins REST API 整合；若團隊不用 Jenkins，仍可自行擴充 provider

### 18. 升級 / migration plan

- 純新增資料；既有 manual test case 流程不變
- 既有 team 升級後看到「Automation Hub」入口；點進去若未設 provider 顯示引導頁
- Migration 不種預設 provider（每 team 自行配置）

## Risks / Trade-offs

- **外部依賴**：GitHub down 時 script list / 預覽不可用。對策：UI 友善降級顯示 cached content + 提示「無法連線到 GitHub」；run history 仍可看（純 TCRT DB）
- **API rate limit**：高峰時可能打到 GitHub 限制。對策：etag cache + 鼓勵 GitHub App
- **Provider API 變化**：GH Actions API 改版可能破壞觸發流程。對策：適配器版本化、CI 對適配器做 integration smoke test、API version pin
- **workflow_dispatch 不回 run_id**：觸發後需要輪詢配對。對策：注入 uuid input + 60 秒 windowed search；若 60 秒內配對不到標 UNKNOWN，user 可手動關聯
- **Multi-CI 並存**：有些 team 同時用 GH 與 GitLab；v1 不支援單 team 多 CI provider。對策：v2 改為多 provider per team；v1 可拆 team 處理
- **IDE 學習曲線**：非技術 QA 可能不會使用 IDE 或 git。對策：提供 Starter Template Repo（GitHub Template）降低門檻；文件清楚說明「TCRT 只負責觸發，編輯請用 IDE」；半技術 QA 可用 GitHub Web Editor 作為輕量替代
- **Webhook 不可靠**：偶有丟訊。對策：60 秒輪詢補位
- **iframe embed CSP**：Allure 預設未必允許被嵌入。對策：v1 預設 link mode，iframe 為 opt-in 並提供 docs 教 user 設 Allure server header
- **Smart Scan LLM 成本與隱私**：每次掃描呼叫 LLM 產生 API cost；prompt 預設只含公開路徑與 function names，不含 source snippet。對策：LLM enrichment 可關閉；結果 cache key 包含 etag / model / prompt / config；`send_source_snippets_to_llm` 預設 false
- **Smart Scan 誤判**：helper 檔案被誤認為 entry point，或目錄分組不符合語意。對策：Python AST / JS bounded lexical scan 過濾 false positive；UI 顯示 excluded reasons 與 enrichment source；允許手動調整
- **Repo contract 採用門檻**：既有 automation repo 可能沒有 `tcrt-automation.yml` 或資料夾命名不一致。對策：v1 預設 warning + fallback；只有 admin 設定 `require_manifest=true` 或 `enforce_repo_contract=true` 時才阻擋；提供 starter template / 文件降低導入成本

## Migration Plan

### 資料庫
- Alembic migration 新增 5 張表 + 索引 + unique constraint
- 更新 `app/database_init.py` 的 `MAIN_REQUIRED_TABLES`
- 不種預設 provider

### Deployment
- 必填新環境變數 `AUTOMATION_PROVIDER_ENCRYPTION_KEY`（base64 32 bytes）
- 提供 `make automation-key-gen` 簡化生成

### 程式碼
- 全部新增；既有 API 不變
- MCP `test_cases/{id}` detail 響應追加欄位（向後相容）

## Open Questions

1. **GitHub App 還是 PAT？** v1 兩者都支援，docs 強烈推薦 GitHub App for production
2. **Script list 是自動掃描還是手動註冊？** v1 採自動掃描；掃描路徑優先由 `tcrt-automation.yml` 的 `paths.tests` 決定，找不到 manifest 時 fallback 到 provider config 的 `scan_path`
3. **掃描範圍控制**：如何避免掃到非 test 檔案？v1 由 Automation Repo Contract + include/exclude + Python AST / JS bounded lexical scan 控制；POM、flows、fixtures、resources、config 皆視為 support path
4. **Starter Template Repo**：是否提供官方 GitHub Template Repository（`tcrt-playwright-starter`）供新團隊快速開始？v1 建議提供，內容至少包含 `tcrt-automation.yml` 與標準目錄
5. **Smart Scan enrichment 準確度**：rule-based 分群後 LLM 命名是否夠準？若 confidence 低，fallback 策略是否夠好？需實際 repo 測試調整 prompt
6. **Cache invalidation 策略**：v1 用 TTL，未來可加 webhook（GitHub push event）即時失效
7. **Workflow inputs 對應 test data**：使用者可能在 workflow 內定義輸入（如 `environment: staging/prod`）；UI 是否要解析 workflow YAML 並提供下拉？v1 不做，使用者自填；v2 評估
