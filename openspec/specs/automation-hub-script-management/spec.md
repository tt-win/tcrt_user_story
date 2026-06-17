# automation-hub-script-management Specification

## Purpose
TBD - created by archiving change add-automation-hub. Update Purpose after archive.
## Requirements
### Requirement: System MUST auto-discover scripts from StorageProvider
TCRT **不**提供手動 register 或 script 列表管理功能。`automation_scripts` 資料表 SHALL 為**自動發現的快取**，由 background sync job 或使用者觸發時從 StorageProvider 掃描並填入，schema MUST 包含：

- `id` PK
- `team_id` FK NOT NULL, indexed
- `provider_id` FK → `team_automation_providers.id` NOT NULL
- `name` VARCHAR(200) NOT NULL（預設為檔案名稱，使用者可 override）
- `description` TEXT nullable
- `script_format` ENUM(`PLAYWRIGHT_PY_ASYNC`, `PYTEST`, `PLAYWRIGHT_JS`, `OTHER`)
- `ref_path` VARCHAR(500) NOT NULL（相對於 repo root，例：`tests/test_login.py`）
- `ref_branch` VARCHAR(200) NOT NULL（掃描時的 branch）
- `cached_content` MEDIUMTEXT nullable（最近一次 fetch 的內容）
- `cached_content_etag` VARCHAR(120) nullable
- `last_synced_at` DATETIME nullable
- `tags_json` TEXT nullable
- `preferred_runner_label` VARCHAR(100) nullable（觸發 run 時預設使用的 runner label；NULL 時 fallback 到 provider config 的 default_runner_label）
- `linked_test_case_count` INT default 0（反向計數，由 service 層維護）
- `created_by`, `updated_by`, `created_at`, `updated_at`
- UniqueConstraint `(team_id, provider_id, ref_path, ref_branch)`
- Index `(team_id, script_format)`、`(provider_id, last_synced_at)`

#### Scenario: Auto-discovery from GitHub
- **WHEN** team 首次進入 Automation Hub Suites tab 或點擊「重新掃描」
- **THEN** TCRT SHALL 先解析 `tcrt-automation.yml`（若存在）取得 effective tests path，否則使用 provider config 的 `scan_path`（預設 `"tests/"`），再呼叫 `StorageProvider.list_scripts(path=effective_tests_path, recursive=True)`
- **THEN** 所有符合條件的檔案 SHALL 自動填入 `automation_scripts`；已存在者更新 `last_synced_at`，已不存在者標記為 `stale`（或刪除）

#### Scenario: Script appears after auto-discovery
- **WHEN** 使用者在 IDE 建立 `tests/test_new_feature.py` 並 push 到 `main` branch
- **THEN** 下次 auto-discovery（手動或每小時背景排程）SHALL 自動發現該檔案並填入 `automation_scripts`
- **THEN** 使用者可在 Suites tab 看到該檔案並直接勾選加入 suite，無需任何 register 動作

#### Scenario: cached_content is cache, not source of truth
- **WHEN** team 將 `automation_scripts.cached_content` 直接從資料庫 truncate
- **THEN** 下次使用者開啟 script preview，service 層 SHALL 透過 StorageProvider 重新 fetch 並回填，UI 體驗不受影響

#### Scenario: Script has preferred runner
- **WHEN** script 設定 `preferred_runner_label="self-hosted-staging"`
- **THEN** 觸發 run 時，若使用者未特別指定 runner，UI SHALL 預設選擇該 label
- **WHEN** provider config 設有 `default_runner_label="ubuntu-latest"` 但 script 有自己的 preferred_runner_label
- **THEN** script 層級 SHALL 優先於 provider 層級

### Requirement: API MUST support auto-discovery and sync from StorageProvider
TCRT **不**提供手動 register 或 script 管理功能。API 層 SHALL 只允許讀取、同步與 metadata 更新，不提供建立或改寫 git script content 的端點。所有 script 相關端點皆為**唯讀或自動發現**：

- `GET /api/teams/{team_id}/automation-scripts`：列表（從 `automation_scripts` 快取表讀取），支援 `?provider_id=&format=&linked_test_case_id=&q=&cursor=&limit=`（預設 50，max 200）
- `GET /api/teams/{team_id}/automation-scripts/{script_id}`：詳情，含最近 5 筆 runs、linked test cases、cached_content 與 stale 旗標
- `POST /api/teams/{team_id}/automation-scripts/sync`：強制觸發自動掃描；呼叫 `StorageProvider.list_scripts()` 掃描 repo → 比對現有 `automation_scripts` → 新增/更新/標記 stale
- `PUT /api/teams/{team_id}/automation-scripts/{script_id}`：更新可編輯 metadata（name / description / format / tags / preferred_runner_label）；**不** 更改 ref_path / ref_branch（由 auto-discovery 管理）
- `DELETE /api/teams/{team_id}/automation-scripts/{script_id}`：僅刪 TCRT 端快取紀錄，**不** 刪 git 檔案；cascade linked 紀錄

所有寫端點 SHALL 寫 audit。

#### Scenario: Auto-discovery on first visit
- **WHEN** team 首次進入 Automation Hub Suites tab
- **THEN** 若 `automation_scripts` 表為空或上次掃描超過 1 小時，UI SHALL 自動觸發 sync，顯示 loading spinner
- **THEN** 掃描完成後顯示檔案列表

#### Scenario: Delete only removes TCRT cache
- **WHEN** 使用者刪除 script 快取
- **THEN** TCRT 端紀錄刪除，git repo 內檔案 SHALL 不被觸碰；下次 sync 會重新發現

### Requirement: Script content cache MUST be read-only preview
`cached_content` SHALL 僅供 UI **唯讀預覽**使用，TCRT **不**提供任何編輯或回寫 git 的能力。所有內容變更由使用者在 IDE 完成後推上 git，TCRT 透過下次 `sync` 或背景排程重新 fetch。

#### Scenario: User attempts to edit via TCRT
- **WHEN** 使用者點擊展開的 script preview 內容區域（Suites tab 或 case detail）
- **THEN** UI SHALL 顯示提示「請使用 IDE 編輯後推上 git」+「Open in GitHub」連結，**不**開啟編輯模式

### Requirement: Script content cache MUST be transparent and bounded
Service 層 SHALL 以下列策略管理 cached_content：

1. List 頁載入時，若 `last_synced_at` 距今 > 5 分鐘 → 背景 sync（不阻擋 UI）
2. Preview 展開時（點擊檔案名稱展開 cached_content），若 `last_synced_at` 距今 > 30 秒 → 同步 sync（顯示 loading）
3. cached_content 上限 1 MB；超過此值的檔案 SHALL `cached_content = null`，UI 提示「檔案過大，請至 git 直接查看」
4. Cache 失效採 etag 304；GitHub provider 透過 `If-None-Match` 不消耗 rate limit
5. UI SHALL 顯示「Last synced: X minutes ago」與「Refresh」按鈕（手動觸發 sync）

#### Scenario: Stale content auto-refreshed
- **WHEN** 使用者展開 script preview（於 Suites tab 或 case detail），last_synced_at 為 10 分鐘前
- **THEN** UI SHALL 顯示 cached 內容但同時觸發 sync，sync 完成後 UI SHALL 自動更新並顯示「Updated」提示

#### Scenario: Oversized content not cached
- **WHEN** 嘗試 sync 一個 1.5 MB 的檔案
- **THEN** cached_content SHALL 設為 null，`last_sync_status` 標示 `OVERSIZED`，UI 顯示「檔案超過 1 MB cache 限制，請至 git 查看」+ 跳轉連結

### Requirement: System MUST provide M2M linkage between scripts and test cases
資料表 `automation_script_case_links` SHALL 提供 script ↔ manual test case 多對多關聯：

- `id` PK
- `team_id` FK indexed
- `automation_script_id` FK → `automation_scripts.id` ON DELETE CASCADE
- `test_case_id` FK → `test_cases.id` ON DELETE CASCADE
- `link_type` ENUM(`PRIMARY`, `COVERS`, `REFERENCES`) default `COVERS`
- `note` TEXT nullable（marker-sync 建立的紀錄 SHALL 在 note 內存 JSON `{test_name, line, marker_raw}`）
- `created_by`、`created_at`
- UniqueConstraint `(automation_script_id, test_case_id)`
- Index `(test_case_id)`、`(team_id)`

**`created_by` 欄位 sentinel 值**：

- `"marker-sync"` — 由程式碼 marker 同步而來（見「derived links」 requirement）
- `"ai-suggest:<user_id>"` — AI 建議經人類 Accept 後寫入
- 純數字字串 — 一般使用者手動建立

對應 API：
- `POST /api/teams/{team_id}/automation-scripts/{script_id}/links`（payload: `test_case_id`, `link_type`, `note`）
- `DELETE /api/teams/{team_id}/automation-scripts/{script_id}/links/{link_id}`
- `PATCH /api/teams/{team_id}/automation-scripts/{script_id}/links/{link_id}`（更新 link_type / note）
- `GET /api/teams/{team_id}/test-cases/{case_id}/linked-automation`（反向）

Service 層 SHALL 拒絕同 case 出現第二筆 `link_type=PRIMARY`（無論 `created_by` 為何）。

#### Scenario: PRIMARY uniqueness per case
- **WHEN** 為 test_case_id=5 已有 PRIMARY link，再次建立 PRIMARY（任一 created_by）
- **THEN** API SHALL 回 409 並提示「該 case 已有 PRIMARY link」

#### Scenario: Cascade on script delete
- **WHEN** 使用者刪除一支 script
- **THEN** 該 script 的所有 `automation_script_case_links` 紀錄 SHALL 透過 FK CASCADE 一併刪除（含 marker-sync 與 ai-suggest 紀錄）

#### Scenario: Cascade on test case delete
- **WHEN** 刪除一筆 `test_cases` 紀錄
- **THEN** 指向該 case 的所有 link 紀錄 SHALL 被清除，script 本體保留

#### Scenario: created_by sentinel preserved through reads
- **WHEN** API 回 `GET .../links`
- **THEN** response SHALL 原樣回傳 `created_by` 字串（包含 `marker-sync` / `ai-suggest:<id>` 等 sentinel）讓 UI 顯示 link source badge

### Requirement: UI MUST provide Automation Hub entry in team workspace
`app/templates/team_management.html` SHALL 為每張團隊卡片新增「Automation Hub」連結，導向 `/teams/{team_id}/automation-hub`。

`app/templates/automation_hub.html` SHALL 提供 3 個 tabs（**無 Scripts tab**）：
- **Suites**：suite / group 列表與管理；從 GitHub 檔案列表中選擇 script 組合成 suite；執行 suite
- **Runs**：執行歷史，依時間排序，跨 suite
- **Coverage**：覆蓋率統計與未覆蓋 case 清單
- **Settings**：admin 配置 storage / ci / result providers

未配置任何 provider 的 team 開啟 Hub 時 SHALL 看到引導頁，主動帶到 Settings tab。

#### Scenario: First-time onboarding
- **WHEN** 一個從未配置 provider 的 team 進入 Hub
- **THEN** UI SHALL 顯示「Welcome to Automation Hub」引導，提供「設定 GitHub」「設定 Local Git」兩個 CTA

### Requirement: Script preview UI MUST be embedded in Suites tab context
Script preview **不**作為獨立頁面。UI SHALL 以 read-only preview 呈現 script content，並把編輯入口導向外部 git / IDE；preview 嵌入在以下場景：

**1. Suites tab 檔案樹展開**：
- 點擊左側 GitHub 檔案樹的檔案名稱 → 展開顯示：
  - Metadata（name、format、ref_path、last_synced_at + Refresh 按鈕）
  - CodeMirror 6 **read-only** 顯示 cached_content
  - 「Open in GitHub」「Open in VS Code」連結
  - Recent Runs（最近 5 筆 read-only 列表；**無** trigger CTA）
  - 頂端提示訊息：「To run this script, use a suite or run pytest locally.」

**2. Suite detail 內的 script 列表**：
- 點擊 suite 內的組成 script → 展開顯示 read-only preview + Linked Cases
- 若使用者想執行此 script：引導回到 suite detail 點「Run Suite」（不再提供「Run this script only」CTA）

**3. Case detail Automation 面板**：
- 點擊 linked script → 展開或跳轉顯示 preview + 最近 runs（read-only）

> 變更說明：原 spec 中 Script preview「Run Now」按鈕、Suite detail「Run Suite」與「Run this script only」按鈕，皆已於 `openspec/changes/move-automation-execution-to-test-run-set` 移除。Automation Hub 對外**不暴露任何執行入口**；執行由 Test Run Set 接管（見 `test-run-management-ui`）。

#### Scenario: User wants to edit script
- **WHEN** 使用者點擊「Open in GitHub」
- **THEN** 新分頁開啟 GitHub 檔案頁，使用者可點擊「Edit this file」或「Open with GitHub Desktop」
- **WHEN** 使用者修改並 push 後回到 TCRT
- **THEN** 點擊 Refresh 按鈕或等待背景 sync，cached_content SHALL 更新為最新內容

#### Scenario: Script with external dependencies
- **WHEN** cached_content 包含 `from pages.xxx import ...` 或 `import ./utils/...`
- **THEN** UI SHALL 在預覽區上方顯示提示「⚠️ 此 script 依賴外部模組，請在 IDE 中開啟完整專案以確保正確編輯」

#### Scenario: Script preview without trigger CTA
- **WHEN** 使用者於任何場景展開 script preview
- **THEN** preview 區 SHALL NOT 包含「Run Now」「執行」「Run」等 trigger CTA
- **WHEN** preview 渲染
- **THEN** 頂端 SHALL 顯示引導訊息「To run this script, add its suite to a Test Run Set.」

### Requirement: Test case detail MUST display reverse Automation Coverage panel
`app/templates/test_case_management.html` 的 case detail 區域 SHALL 新增「Automation」面板，顯示：

- 該 case 所有 linked scripts，每筆含：script name、format、link_type badge、last_run_status badge（PASSED / FAILED / RUNNING / etc.）、provider 名稱、展開 preview 的連結、跳轉到最近 run report 的連結
- Empty state：「This case has no automation coverage」+「+ Link automation script」按鈕
- 「+ Link script」按鈕：開啟 picker 搜尋 `automation_scripts` 快取表（由 GitHub 自動掃描填入），顯示 ref_path 與 format；選擇後建立 link

對應 API：`GET /api/teams/{team_id}/test-cases/{case_id}/linked-automation` 已於前文 Requirement 定義。

#### Scenario: Test case without automation
- **WHEN** 使用者開啟一筆無 link 的 test case detail
- **THEN** Automation 面板 SHALL 顯示 empty state 與 CTA

#### Scenario: Last run status badge updates
- **WHEN** linked script 完成新 run（透過 webhook 更新 status）
- **THEN** 下次 case detail 載入 SHALL 顯示新的 last_run_status

### Requirement: System MUST compute coverage statistics per team
端點 `GET /api/teams/{team_id}/automation-coverage` SHALL 回傳：

```json
{
  "total_test_cases": 250,
  "with_primary_link": 80,
  "with_any_link": 145,
  "uncovered_count": 105,
  "uncovered_sample": [{"test_case_id": 1, "test_case_number": "TC-001", "title": "..."}, ...],
  "stale_scripts": [{"script_id": 5, "name": "...", "last_run_at": "...", "days_since_last_run": 45}, ...]
}
```

`stale_scripts` 為 30 天以上無 run 的 scripts。

對應的 Coverage tab UI SHALL 視覺化呈現這些數字（statistic cards + 未覆蓋列表 + stale 列表）。

#### Scenario: Coverage reflects link_type weighting
- **WHEN** team 有 100 case，其中 30 有 PRIMARY、20 有 COVERS、其餘無 link
- **THEN** API SHALL 回 `with_primary_link=30`, `with_any_link=50`, `uncovered_count=50`

### Requirement: System MUST support automation script groups (suites)
資料表 `automation_script_groups` SHALL 提供 script 的邏輯分組，用於將多個 script 組合成一個可執行的 suite：

- `id` PK
- `team_id` FK NOT NULL, indexed
- `name` VARCHAR(200) NOT NULL
- `description` TEXT nullable
- `script_paths_json` TEXT NOT NULL（script ref_path 陣列，如 `["tests/test_login.py","tests/test_logout.py"]`）
- `ci_job_name` VARCHAR(200) nullable（在 CI provider 端的 job/workflow 名稱，由 TCRT 自動管理）
- `ci_job_type` ENUM(`GITHUB_ACTIONS`, `JENKINS`) nullable
- `created_by`, `updated_by`, timestamps

UniqueConstraint `(team_id, name)`。

API：
- `POST /api/teams/{team_id}/automation-script-groups`：建立 group；payload 含 `name`、`description`、`script_ids`（array）；service SHALL 呼叫 `CIProvider.create_suite_job()` 在 CI 端建立對應 job/workflow
- `PUT /api/teams/{team_id}/automation-script-groups/{group_id}`：更新 metadata 與 scripts；service SHALL 呼叫 `CIProvider.update_suite_job()` 同步 CI 端
- `DELETE /api/teams/{team_id}/automation-script-groups/{group_id}`：刪除 group；service SHALL 呼叫 `CIProvider.delete_suite_job()` 清理 CI 端
- `GET /api/teams/{team_id}/automation-script-groups`：列表
- `GET /api/teams/{team_id}/automation-script-groups/{group_id}`：詳情，含 scripts 列表與最近 runs
- `POST /api/teams/{team_id}/automation-script-groups/{group_id}/runs`：觸發執行（見 run-orchestration spec）

#### Scenario: Create suite syncs to CI
- **WHEN** QA 建立 suite「Login Regression」，包含 3 個 scripts
- **THEN** TCRT SHALL 自動在 CI 端建立對應 job：
  - GitHub Actions：建立 `.github/workflows/tcrt-suite-{group_id}-login-regression.yml`
  - Jenkins：建立 Job `tcrt-suite-5-login-regression` 並加入 team View
- **THEN** `automation_script_groups.ci_job_name` SHALL 記錄該 job 名稱

#### Scenario: Update suite syncs to CI
- **WHEN** QA 從 suite 移除一個 script
- **THEN** TCRT SHALL 呼叫 `CIProvider.update_suite_job()` 更新 CI 端配置，反映新的 test paths

#### Scenario: Delete suite cleans up CI
- **WHEN** QA 刪除 suite
- **THEN** TCRT SHALL 呼叫 `CIProvider.delete_suite_job()` 清理 CI 端 job/workflow，不留下孤兒

### Requirement: Suites UI MUST allow composing from GitHub file list

Suites tab 為 Automation Hub 的**主頁籤**。UI SHALL 允許 QA 從左側檔案列表勾選 scripts，並在右側建立或更新 suite；頁面直接顯示從 GitHub 載入的檔案列表與 suite 管理。

**View 切換**：

- Suites tab 工具列 SHALL 提供 `[Script view] ◀▶ [Test view]` 切換，預設為 Script view
- View 狀態 SHALL 以 `localStorage` 持久化（per-team），下次開啟還原
- 兩個 view 共用同一份 list API 資料

**Script view（保留既有行為）**：

- 左側檔案樹：依 provider 設定掃描路徑載入；顯示 ref_path、last_modified、script_format
- 每個檔案可勾選用於加入 suite；點檔名展開 read-only preview
- 「重新掃描」按鈕觸發 `POST .../automation-scripts/sync`

**Test view（新增）**：

- 把 `entry_points[*].test_entries[*]` 攤平成測試函式列表，每列顯示：
  - Test name + kind badge（function / class / js_test）
  - 來源檔案（可點擊回到 Script view 並聚焦該檔案）
  - TC linkage：每個 derived link 顯示 TC number + link_type + source badge（marker / human / ai-suggested）
  - Marker warnings：unknown_tc、link_type_conflict、invalid_tc_format、non_literal_marker、orphan_marker_comment 等以圖示加 tooltip 呈現
  - AI 建議區塊：信心 `≥ 0.85` 預勾顯示，`0.60~0.85` 顯示但不預勾，`< 0.60` 不顯示；行內提供 `[Accept]` 按鈕
- 點擊 test name SHALL 展開 read-only preview，並 highlight 該 test 的程式碼區塊（依 `line`）

**右側：Suites 列表（兩個 view 共用）**：

- 顯示所有 suites（card 或列表），每個 suite 含：名稱、scripts 數量、最後執行狀態 badge、執行按鈕
- 點開 suite 顯示詳情：組成的 scripts 列表、執行歷史、編輯名稱/描述
- 「+ New Suite」按鈕：modal 輸入名稱 → 勾選 scripts → 確認建立 → TCRT 自動呼叫 `CIProvider.create_suite_job()`
- 編輯 suite：勾選/取消勾選調整組成 scripts → 自動呼叫 `CIProvider.update_suite_job()`

> 註：Suite 組成單位**仍為檔案 ref_path**，Test view 只是檢視 / link 管理用途；suite 不接受 per-test 組成（執行端 CI 也無此粒度）。

#### Scenario: Create suite from GitHub file list
- **WHEN** QA 點「+ New Suite」，輸入名稱「Login Regression」，從左側勾選 `tests/test_login.py`、`tests/test_logout.py`、`tests/test_password_reset.py`
- **THEN** TCRT SHALL 自動建立 suite、呼叫 `CIProvider.create_suite_job()` 在 CI 端建立對應 job/workflow

#### Scenario: Edit suite adds new script from GitHub
- **WHEN** QA 在 suite 詳情中點「編輯」，從左側新勾選 `tests/test_2fa.py`
- **THEN** TCRT SHALL 更新 `automation_script_groups.script_paths_json` 並觸發 `CIProvider.update_suite_job()`

#### Scenario: Toggle to test view shows per-function rows
- **WHEN** QA 在 Suites tab 點 `[Test view]`
- **THEN** UI SHALL 把所有檔案的 test 函式攤平成列表，每列顯示 test name、來源檔案、derived links 與 marker warnings

#### Scenario: View preference persisted
- **WHEN** QA 切到 Test view 後關閉分頁、下次再進入該團隊 Automation Hub
- **THEN** UI SHALL 直接以 Test view 開啟（透過 `localStorage`）

#### Scenario: AI suggestion accept writes link
- **WHEN** 在 Test view 對 `test_login_with_2fa` 點 Accept 高信心建議 TC-001
- **THEN** UI SHALL 呼叫 `POST .../links` payload `{test_case_id, link_type: "covers"}`
- **THEN** 該 link SHALL 以 `created_by="ai-suggest:<user_id>"` 建立

### Requirement: All write operations MUST write audit records
script / link / group 的 CREATE / UPDATE / DELETE / sync 操作 SHALL 透過 `audit_service.log_action()` 寫 audit（TCRT **不**記錄 content_commit 或 content_proposed_via_pr，因為所有編輯由 IDE 完成，版控歷史在 git 中），`resource_type ∈ {AUTOMATION_SCRIPT, AUTOMATION_SCRIPT_LINK, AUTOMATION_SCRIPT_GROUP}`，details 含相關上下文（如 PR URL、commit sha、被連結的 case number、group name、CI job name、link source）。

**Marker-sync 與 AI 建議的 audit 規則**：

- Marker 同步建立 / 更新 / 刪除 link → `AUTOMATION_SCRIPT_LINK` audit，details 含 `source: "marker-sync"`、`reason: "marker_added" | "marker_updated" | "marker_removed"`
- AI 建議端點呼叫 → `READ AUTOMATION_SCRIPT` audit，details 含 `script_id`、`test_name`、`suggestions_count`、`model`、`prompt_version`；**不**含 prompt 內容或 candidate summary
- AI 建議被使用者 Accept 寫入 link → 走既有 `POST .../links` 流程，audit `created_by="ai-suggest:<user_id>"`、details 含 `source: "ai-confirmed"`、`ai_confidence`

#### Scenario: Audit on link create
- **WHEN** 使用者連結 script 到 test_case_number=TC-001 with link_type=PRIMARY
- **THEN** audit log SHALL 出現 `AUTOMATION_SCRIPT_LINK` + `CREATE`，details 含 `script_name`、`test_case_number`、`link_type`

#### Scenario: Audit on suite create
- **WHEN** QA 建立 suite「Login Regression」並同步到 Jenkins Job `tcrt-suite-5-login-regression`
- **THEN** audit log SHALL 出現 `AUTOMATION_SCRIPT_GROUP` + `CREATE`，details 含 `group_name`、`script_count`、`ci_job_name`

#### Scenario: Audit on marker-sync derived link
- **WHEN** 一次 sync 為 script=5 建立 marker-sync link TC-001
- **THEN** audit log SHALL 出現 `AUTOMATION_SCRIPT_LINK` + `CREATE`，details 含 `source: "marker-sync"`、`reason: "marker_added"`、`test_case_number: "TC-001"`

#### Scenario: Audit on AI suggestion call excludes prompt content
- **WHEN** 使用者呼叫 ai-link-suggestions 端點
- **THEN** audit log SHALL 出現 `READ AUTOMATION_SCRIPT`，details 僅含 `{script_id, test_name, suggestions_count, model, prompt_version}`，**不**含 prompt body、test docstring 或 candidate summary

### Requirement: Changes to script naming / classification rules MUST sync the tcrt-automation-pomify skill
任何對「TCRT 對外可見的 script 命名規則、目錄結構、`script_format` 推斷邏輯，或 **test-level coverage marker 文法**」造成行為差異的變更，SHALL 在同一個 OpenSpec change / PR 中同步更新 `tools/skills/tcrt-automation-pomify/` 對應檔案；否則該 change 不得 archive，PR 不得 merge。

具體受同步義務拘束的變更類別包含但不限於：

- `script_format` enum 新增 / 重命名 / 刪除值（如新增 `CYPRESS`、`ROBOT_FRAMEWORK`）
- TCRT 對 PYTEST / PLAYWRIGHT_PY_ASYNC / PLAYWRIGHT_JS 的檔名判定條件變動
- `automation_scripts` 表結構變動到會影響 ref_path / ref_branch / script_format 寫入格式
- 自動排除目錄清單變動（例如把 `pages/` 從排除清單移除）
- **Marker 文法變動**：`@pytest.mark.tcrt(...)` 簽名、`// tcrt:` 註解規則、`link_type` 接受值、TC id 格式
- **Marker 註冊 snippet**：`conftest.py` 內 `pytest_configure` 註冊 marker 的範本

對應的 skill 檔案至少包含：

- `tools/skills/tcrt-automation-pomify/SKILL.md`（步驟 2 detection 表、步驟 4 TCRT filename rules 表、新增「步驟 X：宣告 manual test case 對應」描述 marker 寫法）
- `tools/skills/tcrt-automation-pomify/references/tcrt-format-rules.md`（regex 清單、`script_format` 推斷表、**§5 Marker grammar**）
- `tools/skills/tcrt-automation-pomify/templates/*`（範例 test 加 marker、提供 `conftest.py` snippet；新增 framework 時須加 template 子目錄）

#### Scenario: New script_format added without skill sync
- **WHEN** 開發者在 `script_format` enum 加入 `CYPRESS`，未同步更新 skill
- **THEN** code review / `openspec validate` SHALL 標示「skill 未同步」並阻擋 archive；PR template 的「skill sync checklist」必須勾選或附 opt-out 理由

#### Scenario: Skill-only change without spec change
- **WHEN** 只是修 skill 內 typo 或 POM 範本程式碼優化、不涉及 TCRT 對外格式
- **THEN** 該變更可獨立 PR、無需開 OpenSpec change，但仍 SHALL 在 PR 描述註明「skill-only, no TCRT behaviour change」

#### Scenario: Marker grammar change requires skill sync
- **WHEN** 開發者在 `@pytest.mark.tcrt(...)` 接受新 kwarg（如 `severity="high"`），未同步更新 skill 的 marker grammar section
- **THEN** `openspec validate` / code review SHALL 標示「skill 未同步」並阻擋 archive

### Requirement: System MUST support test-level coverage markers in source

測試碼 SHALL 能直接宣告對應的 manual test case，作為 `automation_script_case_links` 的 derived source。本 requirement 規範**兩種**等價文法（Python 與 JS/TS），其餘文法不在支援範圍。

**Python（PYTEST、PLAYWRIGHT_PY_ASYNC）**：

- 使用 `@pytest.mark.tcrt(...)` decorator
- 文法：`@pytest.mark.tcrt("TC-001"[, "TC-002", ...][, link_type="primary"|"covers"|"references"])`
- `link_type` kwarg 缺省為 `"covers"`，case-insensitive
- TC id 必須符合 `^[A-Za-z0-9_-]+$` 的非空字串
- 一個 test 函式可堆疊多個 `@pytest.mark.tcrt` decorator，視為多個獨立的 marker hit
- marker 解析以 `ast` 走訪 `decorator_list` 為準

**JS/TS（PLAYWRIGHT_JS、`.spec.{ts,js}` / `.test.{ts,js}`）**：

- 使用 `// tcrt: ...` 行註解
- 文法：`// tcrt: <TC-list>[ <link_type>]?`，`TC-list` 以 `,` 分隔
- 註解必須**緊鄰** `test(...)` / `it(...)` / `describe(...)` 之上；中間僅允許空行與同類 `// tcrt:` 註解
- 可在同一 test 上堆疊多行 `// tcrt:`
- `link_type` 後綴缺省為 `covers`

**通用語意**：

- 同一 marker 中的多個 TC 共用該 marker 的 `link_type`；若需不同 `link_type`，SHALL 拆成多個 marker
- 解析錯誤（語法不合、非字面量、TC id 不合法）SHALL **fail-open**：不阻擋掃描、記入 scan response 的 `marker_warnings[]`、該 entry 的 marker 視為空
- pytest marker 須在 repo 端的 `conftest.py` 註冊以避免 `PytestUnknownMarkWarning`（由 skill template 提供 snippet）

#### Scenario: Python single TC marker
- **WHEN** `tests/test_login.py` 內含 `@pytest.mark.tcrt("TC-001")\ndef test_login_happy(): ...`
- **THEN** scan SHALL 在該 script 的 `test_entries` 中產出 `{name: "test_login_happy", markers: [{tc_ids: ["TC-001"], link_type: "covers"}]}`

#### Scenario: Python multi-TC marker with link_type
- **WHEN** test 函式上有 `@pytest.mark.tcrt("TC-001", "TC-005", link_type="primary")`
- **THEN** scan SHALL 產出單一 marker hit，`tc_ids=["TC-001","TC-005"]`、`link_type="primary"`

#### Scenario: Python stacked markers
- **WHEN** test 函式上同時有 `@pytest.mark.tcrt("TC-001", link_type="primary")` 與 `@pytest.mark.tcrt("TC-005")`
- **THEN** scan SHALL 產出兩個獨立 marker hits

#### Scenario: JS comment marker adjacent to test
- **WHEN** `tests/login.spec.ts` 內含 `// tcrt: TC-001 primary\ntest('login happy', async () => {})`
- **THEN** scan SHALL 在該 test 的 `markers` 產出 `{tc_ids: ["TC-001"], link_type: "primary"}`

#### Scenario: JS comment marker not adjacent
- **WHEN** `// tcrt: TC-001` 與 `test(...)` 之間有其他非空非 `// tcrt:` 程式碼行
- **THEN** scan SHALL **不**把該註解綁到下方 test，記入 `marker_warnings[]` reason `orphan_marker_comment`

#### Scenario: Invalid TC id format
- **WHEN** marker 寫成 `@pytest.mark.tcrt("TC 001 with space")`（含空白）
- **THEN** scan SHALL 不建立 marker hit，於 `marker_warnings[]` 紀錄 `{type: "invalid_tc_format", tc_id: "TC 001 with space", line: N}`

#### Scenario: Non-literal marker argument
- **WHEN** marker 寫成 `@pytest.mark.tcrt(MY_TC_CONSTANT)`（變數而非字面量）
- **THEN** scan SHALL fail-open，於 `marker_warnings[]` 紀錄 `{type: "non_literal_marker", line: N}`，不解析該 marker

### Requirement: System MUST sync derived links from markers on each script sync

`AutomationScriptService.sync()` SHALL 在掃完 script 檔案後執行 marker → link reconcile：對每個檔案內偵測到的 marker hit，於 `automation_script_case_links` 表執行 upsert / cleanup。

**Sync 流程**：

1. 對每個 `(script_id, tc_id)` marker pair：
   - 透過 `test_cases.test_case_number == tc_id` 反查（team-scoped）取得 `test_case_id`
   - 若 case 不存在 → 不建 link，記入 `marker_warnings[]` `{type: "unknown_tc"}`
   - 若 link 不存在 → 建立 `automation_script_case_links` 紀錄，`created_by="marker-sync"`、`note=JSON{test_name, line, marker_raw}`、`link_type=marker.link_type`
   - 若 link 已存在且 `created_by="marker-sync"` → 若 `link_type` 不同則更新
   - 若 link 已存在且 `created_by != "marker-sync"`（人類或 AI confirm 建立）→ **保留**不動；若 `link_type` 不同則記入 `marker_warnings[]` `{type: "link_type_conflict"}`
2. Reconcile cleanup：對於該 script 所有 `created_by="marker-sync"` 的既存 link，若當下沒有對應 marker pair → 刪除並寫 audit

**衝突解決原則**：

- `created_by` 欄位 sentinel 值定義：
  - `"marker-sync"` — derived from code marker
  - `"ai-suggest:<user_id>"` — AI 建議被使用者確認時寫入
  - `<numeric user id>` — 人類手動建立
- 人類與 AI confirm 建立的 link 永遠勝過 marker，但衝突會以 warning 暴露給 UI

**Audit**：
- 每筆 marker-sync 建立 / 更新 / 刪除 link SHALL 寫 `AUTOMATION_SCRIPT_LINK` audit，details 含 `source: "marker-sync"`、`script_id`、`test_case_number`、`reason` (`marker_added` / `marker_updated` / `marker_removed`)

#### Scenario: Marker creates a new derived link
- **WHEN** sync 偵測到 `test_login_happy` 含 marker `TC-001`，且 `automation_script_case_links` 內無此 pair
- **THEN** service SHALL 建立 link，`created_by="marker-sync"`、`link_type="covers"`、`note` JSON 含 `test_name="test_login_happy"`

#### Scenario: Human link kept on conflict
- **WHEN** 既有 link `(script=5, case=TC-001, link_type=PRIMARY, created_by=42)` 而 marker 寫 `link_type="covers"`
- **THEN** DB 內 link SHALL 保持 `link_type=PRIMARY` 不動
- **THEN** scan response `marker_warnings[]` SHALL 包含 `{type: "link_type_conflict", script_id: 5, tc_id: "TC-001", human_link_type: "primary", marker_link_type: "covers"}`

#### Scenario: Marker removal triggers derived link cleanup
- **WHEN** 上次 sync 建立 link `(script=5, case=TC-001, created_by=marker-sync)`，本次 sync 該 marker 已從程式碼移除
- **THEN** service SHALL 刪除該 link 並寫 audit `{action: DELETE, source: marker-sync, reason: "marker_removed"}`

#### Scenario: Marker change replaces derived link
- **WHEN** 程式碼把 `@pytest.mark.tcrt("TC-001")` 改成 `@pytest.mark.tcrt("TC-002")`
- **THEN** sync SHALL 刪除 marker-sync 建的 TC-001 link，建立 marker-sync 的 TC-002 link，兩個動作於同一 sync 完成

#### Scenario: Unknown TC produces warning only
- **WHEN** marker 指向 `TC-999` 但 `test_cases` 內該 team 無此 number
- **THEN** SHALL 不建 link、不建立空殼 case；scan response `marker_warnings[]` SHALL 含 `{type: "unknown_tc", tc_id: "TC-999", line: N}`

### Requirement: System MUST provide suggestion-only AI link recommendation API

端點 `POST /api/teams/{team_id}/automation-scripts/{script_id}/ai-link-suggestions` SHALL 根據單一 test 函式回傳 top-N TC 候選；本端點為**建議式**，**不**自我建立任何 link。所有 link 必須透過既有 `POST .../links` 端點由使用者確認後寫入。

**Request**:
```json
{ "test_name": "test_login_with_2fa", "limit": 5 }
```
`limit` 預設 5、最大 10。

**Service 端 prompt 輸入白名單**：

- `test_name`（必）
- `docstring`（`ast.get_docstring()` 結果，可能 null）
- `file_imports`（`ast.Import` / `ast.ImportFrom` 的字面 module 名清單）
- `ref_path`、`script_format`
- `candidate_cases`：team 內 manual cases 經前置 BM25 / token overlap 過濾至 top-50，每筆只送 `id` / `number` / `title` / `summary[:300]`

**SHALL NOT** 送出：function body、fixture 內容、同檔其他 test 的 body、同 repo 其他檔案、credentials / config。

**Response**:
```json
{
  "suggestions": [
    {"test_case_id": 12, "test_case_number": "TC-001",
     "title": "Login with 2FA succeeds", "confidence": 0.91,
     "rationale": "<short text>"}
  ],
  "model": "google/gemini-3-flash-preview",
  "prompt_version": "ai-link-suggest.v1"
}
```

**信心門檻**：

- `< 0.60` → service 層 filter 掉、不回傳
- `0.60 ~ 0.85` → 回傳，UI 顯示但不預勾
- `≥ 0.85` → 回傳，UI 預勾但仍需使用者按 Accept

**Accept 行為**：使用者點 Accept SHALL 呼叫既有 `POST .../links`，`created_by="ai-suggest:<user_id>"`、`link_type=COVERS`（保守預設，不自動套 PRIMARY）。

**Audit**：每次呼叫 ai-link-suggestions 端點 SHALL 寫 `READ` audit，details 含 `script_id`、`test_name`、`suggestions_count`、`model`、`prompt_version`；**不**寫 prompt 內容。

**Fallback**：當 OpenRouter key 缺失、HTTP timeout、回傳格式錯誤時，API SHALL 回 200 with `suggestions: []` 與 `error_summary` 欄位，**不**讓 UI 失敗。

#### Scenario: High-confidence suggestion presented as pre-checked
- **WHEN** AI 回傳 `{TC-001, confidence: 0.91}` 給 `test_login_with_2fa`
- **THEN** UI Test view SHALL 顯示該候選並預勾
- **THEN** 使用者點 Accept 後，DB SHALL 出現 link `created_by="ai-suggest:42"`、`link_type=COVERS`

#### Scenario: Mid-confidence suggestion shown unchecked
- **WHEN** AI 回傳 `{TC-005, confidence: 0.72}`
- **THEN** UI SHALL 顯示該候選但不預勾，使用者需手動勾選後 Accept

#### Scenario: Low-confidence suggestion filtered out
- **WHEN** AI 回傳 `{TC-099, confidence: 0.52}`
- **THEN** service SHALL 不回該候選，UI 不顯示

#### Scenario: No function body in prompt
- **WHEN** ai-link-suggestions 觸發，被掛載 mock OpenRouter client 攔截外送 payload
- **THEN** payload SHALL NOT 含該 test 函式的 body、fixture 內容或同檔其他 test 的程式碼

#### Scenario: AI API unavailable
- **WHEN** OpenRouter key 未配置
- **THEN** 端點 SHALL 回 200 `{suggestions: [], error_summary: "ai_disabled"}`、不擲 500

#### Scenario: Audit excludes prompt content
- **WHEN** 端點完成一次呼叫
- **THEN** audit log SHALL 出現 `READ AUTOMATION_SCRIPT` with details `{suggestions_count, model, prompt_version}`，但 **不**含 prompt body 或 candidate summary

