# automation-hub-script-management Specification

## Purpose
定義 Automation Script 在 TCRT 端的「指標」資料模型、CRUD API、編輯體驗（delegate to StorageProvider）、M2M linkage 到手動 test case、與 case detail 上的反向「Automation Coverage」面板。Script 內容 source of truth 為 git，TCRT 僅保留 cached_content 用於 list / preview / diff。

## ADDED Requirements

### Requirement: System MUST store automation scripts as references, not content owners
資料表 `automation_scripts` SHALL 為 script 的指標紀錄，schema MUST 包含：

- `id` PK
- `team_id` FK NOT NULL, indexed
- `provider_id` FK → `team_automation_providers.id` NOT NULL
- `name` VARCHAR(200) NOT NULL（顯示用）
- `description` TEXT nullable
- `script_format` ENUM(`PLAYWRIGHT_JS`, `PLAYWRIGHT_PY_ASYNC`, `PYTEST`, `OTHER`)
- `ref_path` VARCHAR(500) NOT NULL（相對於 repo root，例：`tests/login.spec.ts`）
- `ref_branch` VARCHAR(200) NOT NULL（預設讀取的 branch）
- `cached_content` MEDIUMTEXT nullable（最近一次 fetch 的內容）
- `cached_content_etag` VARCHAR(120) nullable
- `last_synced_at` DATETIME nullable
- `tags_json` TEXT nullable
- `linked_test_case_count` INT default 0（反向計數，由 service 層維護）
- `created_by`, `updated_by`, `created_at`, `updated_at`
- UniqueConstraint `(team_id, provider_id, ref_path, ref_branch)`
- Index `(team_id, script_format)`、`(provider_id, last_synced_at)`

#### Scenario: Same path different branch is allowed
- **WHEN** team 為同 provider 同 ref_path 但不同 ref_branch 各 register 一支 script
- **THEN** 兩筆紀錄皆允許存在（例如 `main` 與 `release-1.0` 並存）

#### Scenario: cached_content is cache, not source of truth
- **WHEN** team 將 `automation_scripts.cached_content` 直接從資料庫 truncate
- **THEN** 下次使用者開啟 script detail，service 層 SHALL 透過 StorageProvider 重新 fetch 並回填，UI 體驗不受影響

### Requirement: API MUST support register / sync / update / delete script references
端點 SHALL 提供：

- `POST /api/teams/{team_id}/automation-scripts`：register（payload 含 `provider_id`, `name`, `script_format`, `ref_path`, `ref_branch`）；service SHALL 立即呼叫 `StorageProvider.read_script` 拉 cached_content + etag
- `GET /api/teams/{team_id}/automation-scripts`：列表，支援 `?provider_id=&format=&linked_test_case_id=&q=&cursor=&limit=`（預設 50，max 200）
- `GET /api/teams/{team_id}/automation-scripts/{script_id}`：詳情，含最近 5 筆 runs、linked test cases、cached_content 與 stale 旗標
- `POST /api/teams/{team_id}/automation-scripts/{script_id}/sync`：強制重新 fetch；比對 etag，未變動只更新 `last_synced_at`，有變動更新 cached_content
- `PUT /api/teams/{team_id}/automation-scripts/{script_id}`：更新 metadata（name / description / format / tags）；**不** 更改 ref_path / ref_branch（需另外提供 rename endpoint，v1 不做）
- `DELETE /api/teams/{team_id}/automation-scripts/{script_id}`：僅刪 TCRT 端 reference，**不** 刪 git 檔案；cascade linked 紀錄
- `POST /api/teams/{team_id}/automation-scripts/{script_id}/content`：更新 script content；payload 含 `content`, `commit_message`, `mode: "direct" | "pull_request"`, `target_branch`（mode=pull_request 時必填新 branch 名）

所有寫端點 SHALL 寫 audit。

#### Scenario: Register triggers immediate sync
- **WHEN** 使用者 register 一支 script
- **THEN** API 在 commit 前 SHALL 完成 first fetch；若 fetch 失敗（404、權限不足）SHALL 回 400 並不寫 DB

#### Scenario: Delete only removes TCRT reference
- **WHEN** 使用者刪除 script
- **THEN** TCRT 端紀錄刪除，git repo 內檔案 SHALL 不被觸碰

### Requirement: Content update flow MUST respect git workflow
`POST .../content` 端點 SHALL 支援兩種模式：

- **direct mode**：`mode=direct`，直接呼叫 `StorageProvider.write_script(branch=ref_branch)` commit 到原 branch；cached_content 更新；audit 寫 `automation_script.content_committed`
- **pull_request mode**：`mode=pull_request`，呼叫 `StorageProvider.write_script(branch=target_branch)` + `create_pull_request`；回傳 PR URL；audit 寫 `automation_script.content_proposed_via_pr`；TCRT 端 cached_content **不** 更新（等 PR merge 才會在下次 sync 看到變化）

UI 預設應建議 `mode=pull_request`，`mode=direct` 為 admin opt-in（team setting flag `automation.allow_direct_commit`，預設 false）。

#### Scenario: Direct commit blocked by team policy
- **WHEN** team 未開啟 `allow_direct_commit`，使用者送出 `mode=direct`
- **THEN** API SHALL 回 403，錯誤訊息 SHALL 引導改用 pull_request mode

#### Scenario: PR creation when provider does not support
- **WHEN** team 使用 LocalGit provider（不支援 PR），使用者送 `mode=pull_request`
- **THEN** API SHALL 回 400，建議改 direct mode 或切換 provider

### Requirement: Script content cache MUST be transparent and bounded
Service 層 SHALL 以下列策略管理 cached_content：

1. List 頁載入時，若 `last_synced_at` 距今 > 5 分鐘 → 背景 sync（不阻擋 UI）
2. Detail 頁開啟時，若 `last_synced_at` 距今 > 30 秒 → 同步 sync（顯示 loading）
3. cached_content 上限 1 MB；超過此值的檔案 SHALL `cached_content = null`，UI 提示「檔案過大，請至 git 直接查看」
4. Cache 失效採 etag 304；GitHub provider 透過 `If-None-Match` 不消耗 rate limit
5. UI SHALL 顯示「Last synced: X minutes ago」與「Refresh」按鈕（手動觸發 sync）

#### Scenario: Stale content auto-refreshed
- **WHEN** 使用者開啟 script detail，last_synced_at 為 10 分鐘前
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
- `note` TEXT nullable
- `created_by`, `created_at`
- UniqueConstraint `(automation_script_id, test_case_id)`
- Index `(test_case_id)`、`(team_id)`

對應 API：
- `POST /api/teams/{team_id}/automation-scripts/{script_id}/links`（payload: `test_case_id`, `link_type`, `note`）
- `DELETE /api/teams/{team_id}/automation-scripts/{script_id}/links/{link_id}`
- `PATCH /api/teams/{team_id}/automation-scripts/{script_id}/links/{link_id}`（更新 link_type / note）
- `GET /api/teams/{team_id}/test-cases/{case_id}/linked-automation`（反向）

Service 層 SHALL 拒絕同 case 出現第二筆 `link_type=PRIMARY`。

#### Scenario: PRIMARY uniqueness per case
- **WHEN** 為 test_case_id=5 已有 PRIMARY link，再次建立 PRIMARY
- **THEN** API SHALL 回 409 並提示「該 case 已有 PRIMARY link」

#### Scenario: Cascade on script delete
- **WHEN** 使用者刪除一支 script
- **THEN** 該 script 的所有 `automation_script_case_links` 紀錄 SHALL 透過 FK CASCADE 一併刪除

#### Scenario: Cascade on test case delete
- **WHEN** 刪除一筆 `test_cases` 紀錄
- **THEN** 指向該 case 的所有 link 紀錄 SHALL 被清除，script 本體保留

### Requirement: UI MUST provide Automation Hub entry in team workspace
`app/templates/team_management.html` SHALL 為每張團隊卡片新增「Automation Hub」連結，導向 `/teams/{team_id}/automation-hub`。

`app/templates/automation_hub.html` SHALL 提供 4 個 tabs：
- **Scripts**：script 列表，依 provider 分組或統一檢視；搜尋 / 篩選
- **Runs**：執行歷史，依時間排序，跨 script
- **Coverage**：覆蓋率統計與未覆蓋 case 清單
- **Settings**：admin 配置 storage / ci / result providers

未配置任何 provider 的 team 開啟 Hub 時 SHALL 看到引導頁，主動帶到 Settings tab。

#### Scenario: First-time onboarding
- **WHEN** 一個從未配置 provider 的 team 進入 Hub
- **THEN** UI SHALL 顯示「Welcome to Automation Hub」引導，提供「設定 GitHub」「設定 Local Git」兩個 CTA

### Requirement: Script detail UI MUST support inline editing with branch / PR options
`automation_script_detail.html` SHALL 提供：

- Metadata 區塊（name、description、format、provider、ref_path、ref_branch、tags、last_synced_at + Refresh 按鈕）
- CodeMirror 6 編輯器顯示 cached_content；支援 JS / Python / JSON syntax highlight
- 「儲存」按鈕觸發 modal：
  - 預設選項：「開新分支 + Pull Request」（user 輸入 branch 名 + PR title + body）
  - 進階選項（team admin 已開 allow_direct_commit）：「直接 commit 到 {ref_branch}」
  - Commit message 預設「Update {name} via TCRT」（user 可改）
- 「Linked Test Cases」區塊：列出所有 link，支援多選 picker（搜尋 case + 標 link_type + 備註）
- 「最近 Runs」區塊：顯示最近 5 筆，含 status badge、started_at、external_run_url 跳轉

#### Scenario: Edit and PR flow
- **WHEN** 使用者修改編輯器內容並選擇「開新分支 + PR」，輸入 branch="fix/typo"、title="Fix typo in login spec"
- **THEN** TCRT SHALL 呼叫 `StorageProvider.write_script(branch="fix/typo")` + `create_pull_request`，UI SHALL 顯示新 PR 連結並提示「請至 GitHub 完成 review」

#### Scenario: Direct commit blocked
- **WHEN** 使用者選擇「直接 commit」但 team 未開啟 allow_direct_commit
- **THEN** UI SHALL 隱藏該選項或顯示 disabled 狀態 + tooltip「請聯絡 admin 啟用」

### Requirement: Test case detail MUST display reverse Automation Coverage panel
`app/templates/test_case_management.html` 的 case detail 區域 SHALL 新增「Automation」面板，顯示：

- 該 case 所有 linked scripts，每筆含：script name、format、link_type badge、last_run_status badge（PASSED / FAILED / RUNNING / etc.）、provider 名稱、跳轉到 script detail 的連結、跳轉到最近 run report 的連結
- Empty state：「This case has no automation coverage」+「+ Link automation script」按鈕
- 「+ Link script」按鈕：開啟 picker 搜尋既有 script 或 register 新 script

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

### Requirement: All write operations MUST write audit records
script / link 的 CREATE / UPDATE / DELETE / sync / content_commit / content_proposed_via_pr 操作 SHALL 透過 `audit_service.log_action()` 寫 audit，`resource_type ∈ {AUTOMATION_SCRIPT, AUTOMATION_SCRIPT_LINK}`，details 含相關上下文（如 PR URL、commit sha、被連結的 case number）。

#### Scenario: Audit on link create
- **WHEN** 使用者連結 script 到 test_case_number=TC-001 with link_type=PRIMARY
- **THEN** audit log SHALL 出現 `AUTOMATION_SCRIPT_LINK` + `CREATE`，details 含 `script_name`、`test_case_number`、`link_type`
