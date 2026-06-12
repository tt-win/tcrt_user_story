## Why

Automation Hub 目前所有「執行」按鈕（`Run Now` 觸發單一 script、`Run Suite` 觸發整個 script_group）都掛在 Hub 自己的 UI 上，把 Hub 變成「scan + link + run」三合一。但實務上：

1. **「執行」與「維護」混雜在同個 UI**：QA 進入 Hub 是想看「哪個 script 對應到哪個 manual test case」（marker sync 視角），點進去卻看到「Run Now」「Run Suite」CTA，混淆 Hub 的核心抽象。Hub 應收斂為 **sync hub**（同步 + 連結 + 維護），執行屬於另一個 surface。

2. **雙重入口造成 CI workflow 重複維護**：Hub 對「單一 script run」與「suite run」各要求一條 CI workflow（`tcrt-suite-N-*.yml`），這些 workflow 與 Jenkins 端 `ci_job_name` 是 1:1 對應的。在 Hub 與 Test Run 兩處同時暴露「執行」按鈕，會出現「同一支 script 在兩處都有『Run』按鈕，user 不知道該點哪個」。

3. **Test Run Set 已經是「批次執行」的自然抽象**：Test Run Set 在產品其他位置已是「把多個 test runs 包成一個 group」的標準介面（與 schedule / archive / rerun 互動）。把 automation suite 也收斂到 Test Run Set 的「Automation Suites」成員，讓 Test Run Set 成為「manual 與 automation 統一觸發入口」更直覺。

4. **Automation Hub 的 sync / link 抽象與執行抽象本就分屬兩個 capability**：Hub 的 sync（`smart-scan`、`sync_markers_for_team`）與 link（`sync_markers_for_team` 衍生的 case 連結）已成熟且獨立；執行則是 CI Provider + workflow + Runner 的獨立鏈。把執行搬走，Hub 失去「run」按鈕但「scan / link」完全不受影響。

**取而代之的行為**：

- Automation Hub 變純 sync hub：保留 scan / smart-scan / sync_markers / case linking / script group（suite）metadata 維護，**移除**所有 trigger UI 與公開 trigger API。
- Test Run Set 取得新能力「Automation Suites」：可把多個 `automation_script_groups`（suite）加為 Test Run Set 的成員，由 Test Run Set detail 頁的「Run as Automation」按鈕統一觸發。
- 觸發鏈不變：Test Run Set endpoint 內部仍呼叫既有 `CIProvider.trigger_run(workflow_id, branch, inputs=...)`，最終寫入 `automation_runs` 表（保留向後相容讀取路徑）。Hub 與 Test Run Set 共享同一份 CI workflow 設定。

## What Changes

- **BREAKING**：移除 `POST /api/teams/{team_id}/automation-scripts/{script_id}/runs`（單一 script run）
- **BREAKING**：移除 `POST /api/teams/{team_id}/automation-script-groups/{group_id}/runs`（suite run）
- **BREAKING**：移除 Automation Hub UI 所有「執行」CTA：
  - Script preview 的 `Run Now` 按鈕（已在 `remove-single-script-run` 範疇）
  - Suite detail 內的 `Run Suite` 按鈕
  - Suite detail 內的「Run this script only」按鈕
  - Coverage tab script row 的 `Run Now` / `Run` 按鈕
  - Case detail Automation 面板的 `Run` CTA
- **BREAKING**：移除 `AutomationRunService.trigger_script()` 與 `trigger_group()` 公開方法
- **BREAKING**：移除 `AutomationScriptRunCreate` 與 `AutomationSuiteRunCreate` Pydantic schema
- 移除 `app/api/automation_scripts.py` 的 `trigger_automation_script_run` handler
- 移除 `app/api/automation_script_groups.py` 的 `trigger_automation_script_group_run` handler
- 移除前端：suites / coverage / automation-panel 的 trigger click handler 與對應 markup / CSS / i18n
- 保留 `app/services/automation/run_service.py` 的 `trigger_run_for_group()` 之類的**內部** helper（給 Test Run Set endpoint 呼叫，不對外）
- 保留 `CIProvider` 與 Jenkins / GitHub Actions workflow 設定（仍為 Test Run Set 觸發鏈的後端）
- 保留 `automation_runs` 表（Test Run Set 觸發後仍寫入此表；既有查詢 / cancel / reconcile 端點不變）
- 保留 `automation_runs.automation_script_id` FK 為 nullable（向後相容歷史 row，新 run 一律 NULL — 詳見舊 change 備註）
- **NEW**：Test Run Set 新增 `automation_suite_ids: list[int]` 欄位
- **NEW**：`POST /api/teams/{team_id}/test-run-sets/{set_id}/run-automation` 端點 — 觸發所有 `automation_suite_ids` 對應的 suite
- **NEW**：Test Run Set 詳情頁新增「Automation Suites」section 與「Run as Automation」按鈕
- 跨 change 同步：編修 `add-webhook-suite-trigger` 的 `proposal.md` / `design.md` / `specs/automation-hub-webhook-integration/spec.md`，移除「automation_script_id 為 webhook event 必填錨點」相關段落（與 `remove-single-script-run` 當時要求的同步編修一致）

**保留**（不在本 change 處理）：
- `automation_runs` 表整體不變
- `GET /api/teams/{team_id}/automation-runs` / `GET .../automation-runs/{run_id}` 列表 / 詳情
- `POST /api/teams/{team_id}/automation-runs/{run_id}/cancel` / `reconcile`（不限定 run 來源，Test Run Set 觸發的 run 仍可 cancel / reconcile）
- `POST /api/teams/{team_id}/automation-scripts/sync`（scan 仍從 Hub 觸發）
- `GET /api/teams/{team_id}/automation-scripts` / `GET .../automation-script-groups` 列表 / 詳情
- `POST /api/teams/{team_id}/automation-scripts/{script_id}` 更新 metadata
- Test Run / Test Run Set 既有功能（manual 測試執行、adhoc、TP tickets 整合）完全不動
- `tcrt-automation-pomify` skill（繼續教 user 在 script 內寫 `@pytest.mark.tcrt(...)` 即可，不需改）
- MCP `POST .../mcp/automation-scripts/{id}/run` 端點若仍存在，標 deprecate 但不在本 change 強制移除（建議後續 change 收尾）

## Capabilities

### Modified Capabilities

- `automation-hub-run-orchestration`：
  - **移除** `System MUST trigger runs via CIProvider with tcrt_run_id injection`（單一 script 觸發）
  - **移除** `System MUST trigger suite runs via CIProvider`（suite 觸發；本 change 連這個也拔）
  - **移除** `Script preview MUST surface recent runs and quick-run button` 中的「Run Now」段
  - **移除** `UI MUST list runs and embed report links` 的 `script / suite` 雙欄位呈現，改為只顯示 suite（或 legacy single-script 名稱）
  - **新增** `Automation Hub SHALL NOT expose any run trigger UI or API`：對外契約只有 read + sync + link，無 trigger
  - **保留** `System MUST store run metadata as external references`、`reconcile external_run_id via correlation polling`、`sync run status periodically`、`cancel runs`、`run list and detail`、`audit MUST record` — 但需改寫 source 說明：run 來源由 Test Run Set 觸發，不再由 Hub 觸發
- `automation-hub-script-management`：
  - **移除** Script preview 的 `Run Now` 段（已在 `remove-single-script-run` 範疇）
  - **移除** Suite detail 內的 `Run Suite` 與 `Run this script only` 按鈕段（本 change 新增）
  - **保留** Script preview 本身（Recent Runs read-only、CodeMirror、Open in GitHub/VS Code）
  - **保留** Script group（suite）CRUD 端點 — 仍可建立 / 編輯 / 刪除 suite，只是無法從 Hub 觸發
- `test-run-management-ui`：
  - **新增** `Test Run Set MUST support automation suite membership`：Test Run Set detail 顯示「Automation Suites」section，列出 / 加入 / 移除 `automation_suite_ids` 對應的 suite
  - **新增** `Test Run Set MUST provide Run as Automation button`：Test Run Set detail 頁的「Run as Automation」CTA 觸發 `POST .../test-run-sets/{set_id}/run-automation`
  - **保留** Test Run Set 既有手動測試流程（status、TP tickets、archive、rerun、search 等）

### New Capabilities

無（皆掛在既有 capability 上）。

## Impact

**Code**：

- `app/api/automation_scripts.py`（刪 `trigger_automation_script_run` handler）
- `app/api/automation_script_groups.py`（刪 `trigger_automation_script_group_run` handler）
- `app/api/test_run_sets.py`（新增 `run_automation_for_set` handler + payload schema）
- `app/services/automation/run_service.py`（刪 `trigger_script` / `trigger_group` 公開方法；保留內部 helper 給 Test Run Set 呼叫）
- `app/services/test_run_set_service.py`（新增 `trigger_automation_suites` 方法 — 內部呼叫 `CIProvider.trigger_run` + 寫 `automation_runs`）
- `app/models/automation_run.py`（刪 `AutomationScriptRunCreate` / `AutomationSuiteRunCreate` schema）
- `app/models/test_run_set.py`（`TestRunSetCreate` / `TestRunSetUpdate` / `TestRunSetResponse` 加 `automation_suite_ids: list[int]` 欄位，預設 `[]`）
- `app/testsuite/test_automation_script_runs_api.py`（刪 `trigger_automation_script_run` / `trigger_automation_script_group_run` 測試）
- `app/testsuite/test_automation_group_runs_api.py`（刪對應測試）
- `app/testsuite/test_test_run_set_automation.py`（**新檔**）：Test Run Set 觸發 automation suite 的整合測試

**APIs**（破壞性）：

- 2 個端點移除：`POST /automation-scripts/{id}/runs`、`POST /automation-script-groups/{id}/runs`
- 1 個端點新增：`POST /test-run-sets/{id}/run-automation`
- 1 個欄位新增：`TestRunSet.{automation_suite_ids}`
- 既有 GET 列表 / 詳情 / cancel / reconcile / sync 端點完全不變

**Database**：

- `test_run_sets` 表新增 `automation_suite_ids_json` TEXT 欄位（nullable；用 JSON array 存 `[int, ...]`，因 SQLite / PG 對 list[int] 無原生 array 支援）
- alembic revision 新增
- `automation_runs` 表無變更
- 無資料遷移

**Dependencies / Systems**：

- `MainAccessBoundary`：`run_write` 觸發點從 Hub 兩處移轉到 Test Run Set 一處
- audit log：歷史 `AUTOMATION_SCRIPT` 觸發紀錄**保留**；未來 `AUTOMATION_RUN` audit 的 `details.automation_script_group_id` 與 `details.test_run_set_id` 並列，方便追溯觸發來源
- `add-webhook-suite-trigger` change：payload 規格的 `automation_script_id` 從「nullable 必填」改為「純 nullable legacy 欄位」；`script_group_id` 與（新增的）`test_run_set_id` 為主要識別
- CIProvider：Jenkins / GitHub Actions workflow 設定完全不動（Test Run Set 觸發鏈沿用既有 workflow 檔名格式）
- `tcrt-automation-pomify` skill：完全不需要改（skill 仍教 marker 撰寫 + POM refactor）

**Risk / Rollback**：

- 主要風險 1：原本依賴「在 Hub 點 Run Now / Run Suite」的 QA 工作流中斷；緩解為 release notes + 提示「請到 Test Run Set 觸發，並把 suite 加為 Automation Suites 成員」
- 主要風險 2：Test Run Set detail 頁 UX 變更（新增 Automation Suites section），需在 1 sprint 內收齊內部 user 回饋
- 跨 change 風險：`add-webhook-suite-trigger` 必須同步編修，否則 webhook payload 規格與本 change 不一致
- Rollback：從 git history 還原 2 個端點 + Test Run Set 不加 `automation_suite_ids` 欄位即可

## Cross-Change 同步（archive 前必做）

- 編修 `openspec/changes/add-webhook-suite-trigger/proposal.md`：移除「automation_script_id 為 webhook event 必填錨點」相關假設段
- 編修 `add-webhook-suite-trigger/design.md`：webhook event payload 的 `automation_script_id` 從「必填」改為「nullable」，`script_group_id` 與（新增的）`test_run_set_id` 為主要識別
- 編修 `add-webhook-suite-trigger/specs/automation-hub-webhook-integration/spec.md`：
  - `run.triggered` contract 改寫：「payload 必有 `script_group_id` 與 `test_run_set_id`（皆 nullable，但 trigger 來源為 Test Run Set 時至少 `test_run_set_id` 必有）；`automation_script_id` 為 nullable legacy 欄位」
  - 加 scenario：「WHEN Test Run Set 觸發 automation suite THEN payload SHALL NOT 包含非 NULL `automation_script_id`」

## Out of Scope

- ❌ Test Run / Test Run Set 既有功能改動（手動測試流程、adhoc、TP tickets、archive、rerun、search）
- ❌ CIProvider / Jenkins / GitHub Actions workflow 檔案本身（沿用既有 `tcrt-suite-N-*.yml` 格式）
- ❌ `tcrt-automation-pomify` skill 內容
- ❌ Automation Hub 的 scan / link 介面（完全保留）
- ❌ `automation_runs` 表結構（保留）
- ❌ MCP `POST .../mcp/automation-scripts/{id}/run` 端點的 deprecate 與移除（建議後續 change）
- ❌ Test Run / Test Run Set 的 DB 對 automation_suite_ids 的反向查詢（目前無此需求；spec 內可加 follow-up note）
