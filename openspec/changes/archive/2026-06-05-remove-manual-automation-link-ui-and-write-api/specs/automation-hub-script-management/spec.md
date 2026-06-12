# Delta Spec — automation-hub-script-management

> 對 `openspec/specs/automation-hub-script-management/spec.md` 的 delta，記錄「拿掉手動連結、以 pytest marker 自動同步取代」對既有 requirement 的影響。

## ADDED Requirements

### Requirement: System MUST auto-sync script↔test case links from pytest marks on scan

TCRT 不再提供任何人工路徑建立 script ↔ test case link；link 寫入來源 SHALL 僅限於 pytest marker 自動同步，由 scan / import 流程觸發。

**觸發時機（任一發生即跑 marker → link sync）**：
- 使用者呼叫 `POST /api/teams/{team_id}/automation-scripts/sync`（Suites tab「重新掃描」按鈕）
- 背景排程每小時自動 sync（見 `scheduled-service-management` 規格）
- Script 首次從 StorageProvider（GitHub / Local Git）匯入 `automation_scripts` 快取表
- 既有 script 偵測到 `last_synced_at` 過期，依既有 cache 規範觸發 sync

**Marker 解析與 link 寫入行為**：
- 解析 script 內容中的 pytest marker（具體文法、Python AST 走訪、JS/TS 行對位規則、未知 TC 處理於 `add-automation-test-markers-and-test-view` 規範）
- 對每個 `(script_id, test_case_number)` marker pair：
  - 反查 `test_cases` 表（team-scoped）取得 `test_case_id`
  - 若 case 不存在 → 不建 link，於 scan response `warnings[]` 紀錄 `unknown_tc`
  - 若 link 不存在 → 建立：`created_by="marker-sync"`、`link_type=marker.link_type`（預設 `COVERS`）、`note` 內含 `{test_name, line, marker_args}`
  - 若 link 已存在且 `created_by="marker-sync"` → 若 `link_type` 不同則更新；若 `note` 內 marker metadata 變動亦同步
- Reconcile cleanup：對該 script 所有 `created_by="marker-sync"` 既存 link，若當下掃描無對應 marker pair → 刪除
- 對 `created_by` 非 marker-sync 的既存 link（本 change 之前的人工列）**不**動 — 已由 `scripts/cleanup_manual_automation_links.py` 一次性清理

**Audit**：
- 每筆 marker-sync 的建立 / 更新 / 刪除 SHALL 寫 `AUTOMATION_SCRIPT_LINK` audit，details 含 `source: "marker-sync"`、`script_id`、`test_case_number`、`reason`（`marker_added` / `marker_updated` / `marker_removed`）、`marker_args` 摘要

**Webhook event**：
- 同步行為 SHALL 觸發既有 `script.linked` / `script.unlinked` outbound event（先前由手動 link 寫入觸發，現改由 marker sync 觸發；event 訂閱契約不變）

**Out of scope**（於 `add-automation-test-markers-and-test-view` 規範）：
- Marker 具體文法（`@pytest.mark.tcrt(...)` 與 `// tcrt: ...`）
- Smart-scan response `marker_links` / `warnings` 欄位 shape
- AI 建議式連結（`ai-link-suggestions` endpoint）
- Suites tab Script ↔ Test view 切換
- tcrt-automation-pomify skill marker 章節

#### Scenario: 首次 scan 因 marker 建立 link
- **WHEN** `tests/test_login.py` 內含 `@pytest.mark.tcrt("TC-001")` 且該 script 首次被 sync 進 `automation_scripts`
- **THEN** `automation_script_case_links` SHALL 出現對應 link 紀錄，`created_by="marker-sync"`、`link_type=COVERS`、`note` 內含 `test_name` 與 `line` 資訊
- **THEN** audit log SHALL 出現 `AUTOMATION_SCRIPT_LINK` + `CREATE`，details 含 `source: "marker-sync"`、`reason: "marker_added"`

#### Scenario: 後續 scan 更新 link_type
- **WHEN** 既有 marker-sync link `(script=5, case=TC-001, link_type=COVERS)`，marker 改成 `@pytest.mark.tcrt("TC-001", link_type="primary")`
- **THEN** 下次 sync SHALL 更新該 link 的 `link_type=PRIMARY`
- **THEN** audit log SHALL 出現 `AUTOMATION_SCRIPT_LINK` + `UPDATE`，details `reason: "marker_updated"`

#### Scenario: Marker 自程式碼移除觸發 link 清理
- **WHEN** 既有 marker-sync link 上次 sync 為有，本次 sync marker 已從程式碼移除
- **THEN** sync SHALL 刪除該 link 並寫 audit，details `reason: "marker_removed"`
- **THEN** outbound `script.unlinked` event SHALL 觸發，payload 含 `link_id`、`script_id`、`actor_user_id="system:marker-sync"`

#### Scenario: 未知 TC id 僅警告不建 link
- **WHEN** marker 寫了 `"TC-999"` 但 `test_cases` 表無此編號
- **THEN** sync SHALL **不**建立 link，於 scan response `warnings[]` 紀錄 `{type: "unknown_tc", tc_id: "TC-999", script_id: 5, line: 42}`

#### Scenario: 手動重掃觸發 link 更新
- **WHEN** team admin 從 Automation Hub Suites tab 點擊「重新掃描」按鈕（呼叫 `POST .../automation-scripts/sync`）
- **THEN** 該次 sync SHALL 解析所有 script 內的 marker 並 upsert `automation_script_case_links`；UI（Suites 列表的 link 計數、Test Case 詳情 Automation 面板）下次載入應反映最新 link 狀態

#### Scenario: 背景排程 sync
- **WHEN** 背景排程每小時觸發 sync
- **THEN** 該次 sync SHALL 跑 marker 解析並更新 link 表，使用者無需手動介入；`last_synced_at` 與 `linked_test_case_count` 一併刷新

#### Scenario: 解析失敗不阻擋 sync
- **WHEN** script 內 marker 格式不合（語法錯誤、變數而非字面量）
- **THEN** scan SHALL fail-open：該 entry 的 marker 視為空、不建立 link，於 `warnings[]` 紀錄解析錯誤；其他 script 的 sync 不受影響

---

## REMOVED Requirements

### Requirement: Manual link write APIs (POST / PATCH / DELETE / Batch)

**Reason for removal**：手動 UI/API 建立 link 路徑收斂為 marker sync 單一來源；既有 4 個寫入端點移除。`AutomationScriptCaseLink` 表格本身保留給 marker sync 寫入與讀取端點使用。

**原本內容**（節錄自既有 spec）：

對應 API（刪除）：
- `POST /api/teams/{team_id}/automation-scripts/{script_id}/links`（payload: `test_case_id`, `link_type`, `note`）
- `PATCH /api/teams/{team_id}/automation-scripts/{script_id}/links/{link_id}`（更新 link_type / note）
- `DELETE /api/teams/{team_id}/automation-scripts/{script_id}/links/{link_id}`
- `POST /api/teams/{team_id}/automation-scripts/{script_id}/links/batch`（批次新增；partial success 走 `skipped[]`）

Service 層 SHALL 拒絕同 case 出現第二筆 `link_type=PRIMARY`（規則由 marker sync 寫入路徑負責；本 service 層不再強制）。

#### Scenario: PRIMARY uniqueness per case
- **WHEN** 為 test_case_id=5 已有 PRIMARY link，再次建立 PRIMARY
- **THEN** API SHALL 回 409 並提示「該 case 已有 PRIMARY link」

> 此 requirement 移除後，PRIMARY 唯一性保護由 marker sync 寫入路徑於 `add-automation-test-markers-and-test-view` 內保證。

### Requirement: UI MUST provide Manage test case links entry in Suites / Coverage tab

**Reason for removal**：manage-links modal 與按鈕移除；不再提供手動連結 UI。

**原本行為**：
- Suites tab 每個 script row 有「Manage test case links」按鈕，開啟 modal 可批次連結 / 編輯 / 刪除
- Coverage tab 每個 script row 有「Manage links」按鈕（同 modal）

#### Scenario: User opens manage links modal
- **WHEN** QA 在 Suites tab 點某 script 的「Manage test case links」按鈕
- **THEN** modal 開啟，顯示既有 links 清單與搜尋新增區塊

> 此 requirement 移除後，script 對應的 link 資訊僅以唯讀方式呈現（badge / 計數）。

### Requirement: Test case detail panel MUST provide + Link automation script CTA

**Reason for removal**：Test Case 詳情 Automation 面板移除「+ Link automation script」與「+ Link script」CTA；linked scripts 列表本身仍保留。

**原本行為**：
- Empty state：「This case has no automation coverage」+「+ Link automation script」按鈕
- 「+ Link script」按鈕：開啟 picker 搜尋 `automation_scripts` 快取表，選擇後建立 link

#### Scenario: Test case without automation — CTA visible
- **WHEN** 使用者開啟一筆無 link 的 test case detail
- **THEN** Automation 面板 SHALL 顯示 empty state 與「+ Link automation script」CTA

> 此 requirement 移除後，Automation 面板的 empty state 改為純文字「This case has no automation coverage」與提示「請於 IDE 為對應 test function 加上 marker sync 標記」。

### Requirement: Audit log MUST record manual link create / update / delete

**Reason for removal**：手動 link 寫入路徑移除，相關 audit scenario 失去對應操作來源。歷史 audit 紀錄保留（audit 表不可變更）；未來 marker sync 寫入如需 audit，於 `add-automation-test-markers-and-test-view` 補 scenario。

#### Scenario: Audit on link create
- **WHEN** 使用者連結 script 到 test_case_number=TC-001 with link_type=PRIMARY
- **THEN** audit log SHALL 出現 `AUTOMATION_SCRIPT_LINK` + `CREATE`，details 含 `script_name`、`test_case_number`、`link_type`

---

## MODIFIED Requirements

### Requirement: System MUST provide M2M linkage between scripts and test cases (READ-ONLY after this change)

資料表 `automation_script_case_links` SHALL 提供 script ↔ manual test case 多對多關聯，**寫入來源僅限 marker sync（`add-automation-test-markers-and-test-view` 規範）**：

- `id` PK
- `team_id` FK indexed
- `automation_script_id` FK → `automation_scripts.id` ON DELETE CASCADE
- `test_case_id` FK → `test_cases.id` ON DELETE CASCADE
- `link_type` ENUM(`PRIMARY`, `COVERS`, `REFERENCES`) default `COVERS`
- `note` TEXT nullable
- `created_by` STRING（marker sync 寫入時填 `"marker-sync"`；保留歷史值）
- `created_at`
- UniqueConstraint `(automation_script_id, test_case_id)`
- Index `(test_case_id)`、`(team_id)`

唯讀 API（保留）：
- `GET /api/teams/{team_id}/automation-scripts/{script_id}/links`：列示該 script 的 links，含 `test_case_number` / `title` 給 UI 顯示
- `GET /api/teams/{team_id}/test-cases/{case_identifier}/linked-automation`：反向查詢，給 Test Case 詳情 Automation 面板用

寫入端點（移除）：
- ~~`POST /api/teams/{team_id}/automation-scripts/{script_id}/links`~~
- ~~`POST .../links/batch`~~
- ~~`PATCH /api/teams/{team_id}/automation-scripts/{script_id}/links/{link_id}`~~
- ~~`DELETE /api/teams/{team_id}/automation-scripts/{script_id}/links/{link_id}`~~

PRIMARY 唯一性保護由 marker sync 寫入路徑於 `add-automation-test-markers-and-test-view` 內保證，本 service 層不再強制；歷史「人工手建 PRIMARY」紀錄在一次性清理腳本中視條件移除。

#### Scenario: Cascade on script delete（保留）
- **WHEN** 使用者刪除一支 script
- **THEN** 該 script 的所有 `automation_script_case_links` 紀錄 SHALL 透過 FK CASCADE 一併刪除

#### Scenario: Cascade on test case delete（保留）
- **WHEN** 刪除一筆 `test_cases` 紀錄
- **THEN** 指向該 case 的所有 link 紀錄 SHALL 被清除，script 本體保留

#### Scenario: Marker sync writes link（新增，與 marker change 對齊）
- **WHEN** TCRT 對某 script 跑 marker sync，解析出 `test_login_with_2fa` 對應 TC-005
- **THEN** `automation_script_case_links` SHALL 被 upsert 一列，`automation_script_id` 為該 script、`test_case_id`=TC-005 的 local id、`link_type` 由 marker 推斷（預設 `COVERS`，marker 顯式指定時取指定值）、`created_by="marker-sync"`
- **WHEN** marker sync 重跑發現 marker 移除某 TC
- **THEN** 既有 `created_by="marker-sync"` 的對應列 SHALL 被刪除

#### Scenario: Read endpoint still functions（新增）
- **WHEN** Test Case 詳情 Automation 面板載入 case_id=5
- **THEN** API SHALL 回傳該 case 既有 links（即便來源是 marker sync），含 `script_id` / `name` / `link_type` / `last_run_status` 等欄位

---

### Requirement: Test case detail MUST display reverse Automation Coverage panel (read-only after this change)

`app/templates/test_case_management.html` 的 case detail 區域 SHALL 包含「Automation」面板，**唯讀**呈現該 case 的 linked scripts（不提供 CTA 按鈕）：

- 該 case 所有 linked scripts，每筆含：script name、format、link_type badge、last_run_status badge（PASSED / FAILED / RUNNING / etc.）、provider 名稱、展開 preview 的連結、跳轉到最近 run report 的連結
- Empty state：「This case has no automation coverage. 請於 IDE 為對應 test function 加上 marker sync 標記。」（**不**再提供 CTA 按鈕）
- 對應 API：`GET /api/teams/{team_id}/test-cases/{case_id}/linked-automation`（見上一 requirement）

#### Scenario: Test case without automation（修改為唯讀）
- **WHEN** 使用者開啟一筆無 link 的 test case detail
- **THEN** Automation 面板 SHALL 顯示 empty state 與提示文字，**不**顯示任何 CTA 按鈕

#### Scenario: Last run status badge updates（保留）
- **WHEN** linked script 完成新 run（透過 webhook 更新 status）
- **THEN** 下次 case detail 載入 SHALL 顯示新的 last_run_status

#### Scenario: Marker sync 後 linked scripts 列表更新（新增）
- **WHEN** team 對某 repo 跑 marker sync，新建立 3 個 links 對應到 case_id=5
- **THEN** 下次 case detail 載入 SHALL 顯示新增的 3 個 linked scripts（badge 標示來源為 marker sync）

---

### Requirement: All write operations MUST write audit records

script / group 的 CREATE / UPDATE / DELETE / sync 操作 SHALL 透過 `audit_service.log_action()` 寫 audit（TCRT **不**記錄 content_commit 或 content_proposed_via_pr，因為所有編輯由 IDE 完成，版控歷史在 git 中），`resource_type ∈ {AUTOMATION_SCRIPT, AUTOMATION_SCRIPT_GROUP}`，details 含相關上下文（如 PR URL、commit sha、group name、CI job name）。

link 的 audit 改由 marker sync 寫入路徑於 `add-automation-test-markers-and-test-view` 內決定是否記錄；本 spec 不再強制。

#### Scenario: Audit on suite create（保留）
- **WHEN** QA 建立 suite「Login Regression」並同步到 Jenkins Job `tcrt-suite-5-login-regression`
- **THEN** audit log SHALL 出現 `AUTOMATION_SCRIPT_GROUP` + `CREATE`，details 含 `group_name`、`script_count`、`ci_job_name`

> 原「Audit on link create」scenario 已隨寫入端點移除而失效，列於本檔 REMOVED Requirements 內。
