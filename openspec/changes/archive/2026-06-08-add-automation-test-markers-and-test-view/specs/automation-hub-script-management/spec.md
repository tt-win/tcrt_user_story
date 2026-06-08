## ADDED Requirements

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
- **THEN** Smart Scan SHALL 在該 entry_point 的 `test_entries` 中產出 `{name: "test_login_happy", markers: [{tc_ids: ["TC-001"], link_type: "covers"}]}`

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

## MODIFIED Requirements

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

### Requirement: Suites UI MUST allow composing from GitHub file list

Suites tab 為 Automation Hub 的**主頁籤**。UI SHALL 允許 QA 從左側檔案列表勾選 scripts，並在右側建立或更新 suite；頁面直接顯示從 GitHub 載入的檔案列表與 suite 管理。

**View 切換**：

- Suites tab 工具列 SHALL 提供 `[Script view] ◀▶ [Test view]` 切換，預設為 Script view
- View 狀態 SHALL 以 `localStorage` 持久化（per-team），下次開啟還原
- 兩個 view 共用同一份 smart-scan / list API 資料

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
