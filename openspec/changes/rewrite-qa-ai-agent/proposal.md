## Why

目前 `rewrite-qa-ai-agent` change 仍以「deterministic seed planner + 單次 final testcase generation」為主軸，並假設使用者會在 intake 階段直接編修 canonical requirement。這和新版 QA AI Agent 的實際產品流程不一致。新版設計要改成固定七畫面、兩段鎖定、兩段模型分工，並且把使用者的工作重心放在「依 Acceptance Criteria 建立驗證項目與檢查條件」，而不是直接改寫 ticket 內容。

## Purpose

中文：將新版 QA AI Agent 重寫為「載入需求單 -> 需求單內容確認 -> 需求驗證項目分類與填充 -> Test Case 種子確認 -> Test Case 確認 -> Test Case Set 選擇 -> 確認新增結果」的七畫面流程，並明確定義 session 建立時機、requirement lock / seed lock、high-tier seed generation、low-tier testcase generation，以及 AI 產物採用率追蹤。  
English: Rewrite the new QA AI Agent around a seven-screen workflow with explicit session creation, requirement lock and seed lock gates, high-tier seed generation, low-tier testcase generation, and AI adoption tracking.

## What Changes

- 新版 QA AI Agent workflow 固定為七畫面：`畫面一 載入需求單 -> 畫面二 需求單內容確認 -> 畫面三 需求驗證項目分類與填充 -> 畫面四 Test Case 種子確認 -> 畫面五 Test Case 確認 -> 畫面六 Test Case Set 選擇 -> 畫面七 確認新增結果`。
- session 不在使用者按下 QA AI Agent 入口時建立；只有在畫面一輸入 Ticket Number 並送出後才建立新 session。
- 使用者在畫面二到畫面六按下「重新開始」後，系統必須清除當前尚未完成的 session 與其下游資料，並回到畫面一重新輸入 Ticket Number；下一次送出後建立全新的 session。
- 畫面二只顯示 Jira 原始 ticket 內容轉成 markdown 的唯讀結果，不允許直接修改原文；parser 行為以 `scripts/qa_ai_helper_preclean.py` 為基準。
- 畫面二要加入格式檢查，至少需要 `User Story Narrative`、`Criteria`、`Acceptance Criteria` 三個區塊；驗證不通過時不得進入畫面三。`Technical Specifications` 若存在需保留，若缺少可視為空白參考區。
- 畫面二格式檢查不只驗證區塊存在，還要驗證 `User Story Narrative` 內含 `As a / I want / So that`，以及 `Acceptance Criteria` 的每個 scenario 都有有效名稱與 `Given / When / Then`；`Unnamed Scenario` 視為 validation fail。
- 畫面三以預清洗 parser 結果為基礎，依 Acceptance Criteria 建立 section。section 編號預設為 `ticket_key.010`, `ticket_key.020`, `ticket_key.030...`，使用者可調整起始 section 號碼。
- 畫面三的每個 section 預設名稱為 AC scenario title，左側 panel 顯示 section 清單，右側編輯該 section 的驗證項目；上方顯示 Given/When/Then 摘要，下方顯示 Criteria 與 Technical Specifications 參考內容。
- 驗證項目分類固定為 `API`、`UI`、`功能驗證`、`其他` 四種；每個驗證項目都必須至少有一個檢查條件，且每個檢查條件都必須標記 coverage 類型：`Happy Path`、`Error Handling`、`Edge Test Case`、`Permission`。
- 畫面三支援每五秒自動儲存與手動「儲存」按鈕。只有在使用者按下「鎖定需求」後，才可進入畫面四產生 Test Case Seed；解開鎖定後要重新禁止 seed generation。
- 畫面四改由 high-tier LLM 依「鎖定的 requirement plan」產生 Test Case Seed。每個 seed 可附加使用者註解，並以註解作為後續 refinement 的唯一人工調整入口。
- 畫面四 seed generation 與畫面五 testcase generation 使用的模型，必須可由 `config.yaml` 的 `ai.qa_ai_helper.models.*` 宣告，且必須支援從 `.env` / process environment 覆蓋；`config.yaml` 可使用 `${ENV_VAR}` 形式引用環境變數。
- 為了讓輸出盡量可預測且穩定，預設溫度策略應採 `seed = 0.1`、`seed_refine = 0.0`、`testcase = 0.0`；若未來要偏離此預設，需以設定明確覆蓋。
- 畫面四的 seed refinement 只能送出使用者新增的註解，做增量 seed 更新；不得整批重生所有 seeds。
- 畫面四必須有 seed lock。只有在 seed set 被鎖定後，才可進入畫面五產生 Test Case；為了讓 seed adoption 有明確意義，畫面四需支援 per-seed 納入/排除後續 testcase 生成。
- 畫面五改由 low-tier LLM 根據鎖定且已納入的 seed 展開完整 Test Case。模型不負責編號，只保留原始 seed/reference；最終編號由本地 allocator 決定。
- Test Case 編號規則改為 section 內固定流水編號：從 `010` 起跳，每筆 testcase 依序加 `10`，不再依 verification item 切換 block。
- 畫面五允許使用者編修 testcase 細節，但僅限 `title / priority / preconditions / steps / expected results`；testcase 編號與 seed/reference 為唯讀。
- 畫面五只能勾選欲 commit 的 testcase；未勾選的 testcase 不得進入畫面六，且未通過驗證的 testcase 不可被勾選。
- 若畫面四的 seed set 重新進入 draft 或被改動，既有畫面五 testcase drafts 必須失效並重新生成。
- 畫面六要讓使用者選擇既有 Test Case Set 或建立新的 Test Case Set，且同一時間只能有一個 commit target；若建立新 set，至少需完成必要欄位驗證後才可提交。
- commit 僅提交畫面五已勾選且通過驗證的 testcase drafts；若部分 testcase 新增失敗，系統需保留 per-draft 成功/失敗結果並回報原因。
- 畫面七顯示新增結果摘要，至少包含目標 set、成功/失敗/略過數量、已建立 testcase IDs 與失敗原因摘要；若目標 set 已存在或已建立成功，應提供導向該 set 的入口。
- 系統必須能追蹤哪些 testcase 與 seed 為 AI 產生、哪些 seed 被納入後續 testcase 生成、以及哪些 testcase 被勾選提交，並輸出 seed adoption rate 與 testcase adoption rate。
- 新版 QA AI Agent 前端實作必須依 `tcrt-ui-style` 延續既有 TCRT/TestRail 視覺與 i18n 慣例，使用 `base.html`、`--tr-*` / `--btn-*` token 與既有 card/split-workspace pattern。
- 新版 QA AI Agent 必須維持獨立 UI 與獨立資料表，不共用舊 helper 的 session / draft / modal contract；資料表需與 `database_init.py`、Alembic、`scripts/db_cross_migrate.py` 相容，且沿用 `qa_ai_helper_*` 命名空間但改用 V3 語意表名。
- V1 / V2 舊 helper 的 session、draft、telemetry、統計與 adoption 歷史不做遷移或保留；新版 rollout 時應先做 DB snapshot，再以一次性 migration purge legacy helper rows，legacy tables 不再作為 bootstrap required tables 或統計來源，V3 指標自新版上線後重新起算。

## Requirements

### Requirement: Session creation MUST happen only after ticket submission

- **GIVEN** 使用者打開 QA AI Agent 入口或按下重新開始 / the user opens the QA AI Agent entry or requests restart
- **WHEN** 使用者尚未在畫面一送出 Ticket Number / the user has not yet submitted the ticket key on screen 1
- **THEN** 系統 SHALL 不建立 persisted session；只有送出 Ticket Number 後才建立新 session

### Requirement: Screen 2 MUST be a read-only ticket confirmation gate

- **GIVEN** 使用者已在畫面一送出 Ticket Number / the user has submitted a ticket key on screen 1
- **WHEN** 系統載入畫面二 / the system renders screen 2
- **THEN** 系統 SHALL 顯示 Jira 原始 ticket 內容轉成 markdown 的唯讀結果，並在通過格式檢查前阻擋進入畫面三

### Requirement: Screen 2 parser gate MUST validate field completeness, not only section existence

- **GIVEN** 系統已依 `qa_ai_helper_preclean.py` 解析 ticket / the system has parsed the ticket with the preclean-compatible parser
- **WHEN** 系統評估畫面二是否可進入畫面三 / the system evaluates whether screen 3 is allowed
- **THEN** 系統 SHALL 驗證 `User Story Narrative` 的 `As a / I want / So that`、`Criteria` 至少一筆有效內容、以及每個 Acceptance Criteria scenario 都有有效名稱與 `Given / When / Then`

### Requirement: Screen 3 MUST be an Acceptance-Criteria-driven verification workspace

- **GIVEN** 畫面二格式驗證通過 / screen 2 validation has passed
- **WHEN** 使用者進入畫面三 / the user enters screen 3
- **THEN** 系統 SHALL 依 Acceptance Criteria 建立 section、讓使用者編輯驗證項目與檢查條件、並以 section lock 控制後續 seed generation

### Requirement: Seed generation MUST use a locked requirement plan

- **GIVEN** 使用者已完成畫面三的驗證項目填寫 / the user has completed the verification-plan workspace
- **WHEN** 使用者要開始產生 Test Case Seed / the user wants to generate testcase seeds
- **THEN** 系統 SHALL 要求 requirement plan 已鎖定，並以 high-tier LLM 根據鎖定內容產生 seeds

### Requirement: Seed review MUST support incremental refinement and seed lock

- **GIVEN** 系統已產生第一版 seeds / the system has generated the initial seed set
- **WHEN** 使用者新增或修改 seed 註解 / the user adds or updates seed comments
- **THEN** 系統 SHALL 只送出增量 refinement payload 更新相關 seeds，且必須再次鎖定 seed set 後才能進入 testcase generation

### Requirement: Testcase generation MUST use locked seeds and deterministic numbering

- **GIVEN** 使用者已鎖定 seed set / the seed set is locked
- **WHEN** 系統產生完整 testcase / the system expands testcases
- **THEN** 系統 SHALL 以 low-tier LLM 展開 testcase body，並由本地 allocator 套用 section 內固定流水編號規則

### Requirement: AI stage model routing MUST be configurable from `config.yaml` and `.env`

- **GIVEN** 系統需要決定畫面四 seed generation 與畫面五 testcase generation 使用的模型 / the system needs to resolve the models for seed and testcase generation
- **WHEN** 系統從 `config.yaml` 與環境變數載入設定 / the system loads settings from `config.yaml` and environment variables
- **THEN** 系統 SHALL 能解析 `seed` 與 `testcase` 的獨立 model routing，並 SHALL 允許 `.env` / process environment 覆蓋 `config.yaml` 值；若使用 `${ENV_VAR}` 佔位則必須在執行前被解析或明確報錯

### Requirement: Commit flow MUST support selected-only commit into a chosen Test Case Set

- **GIVEN** 使用者已進入 testcase review / the user is reviewing generated testcases
- **WHEN** 使用者進行 commit / the user commits results
- **THEN** 系統 SHALL 只提交勾選的 testcase，並要求使用者先選擇既有或新建的目標 Test Case Set

### Requirement: AI provenance and adoption MUST be traceable

- **GIVEN** 系統會產生 AI seeds 與 AI testcase / the system produces AI-generated seeds and testcases
- **WHEN** 使用者納入部分 seeds 進入後續 testcase 生成、勾選部分 testcase 提交、或放棄部分產物 / the user includes some seeds for downstream generation, selects some testcases for commit, or leaves artifacts unselected
- **THEN** 系統 SHALL 保留 AI 來源、模型、session、關聯 seed/reference 與採用結果，並可計算 seed adoption rate 與 testcase adoption rate

### Requirement: Independent UI and storage for the new helper

- **GIVEN** 新版 QA AI Agent 上線 / the rewritten QA AI Agent is rolled out
- **WHEN** 系統提供新版 workflow / the system exposes the new workflow
- **THEN** 系統 SHALL 使用獨立 UI 與獨立資料表保存新版 session / plan / seed / draft / telemetry 狀態，且 SHALL 隱藏或移除舊版 helper entry，避免雙入口並存

### Requirement: Legacy helper session data and legacy statistics MUST be discarded at rollout

- **GIVEN** 系統準備切換到 V3 / the system is preparing to switch to V3
- **WHEN** 新版 helper 取代 V1 / V2 成為唯一正式流程 / the rewritten helper replaces both previous implementations
- **THEN** 系統 SHALL 不遷移舊 session / 舊統計資料，並 SHALL 在 rollout migration 中先建立 DB snapshot，再 purge legacy helper 的 session、draft、telemetry 與舊版 adoption/phase 統計資料列，且不對 V3 metrics 做 backfill

### Requirement: Persistence schema must be bootstrap- and migration-compatible

- **GIVEN** 新版 helper 需要新增或調整專用資料表 / the rewritten helper introduces or changes dedicated persistence tables
- **WHEN** 系統執行 `database_init.py` 或 `scripts/db_cross_migrate.py` / the system bootstraps or cross-migrates the main database
- **THEN** 新版 helper 資料表 SHALL 由 Alembic 管理並納入 required-table verification，且 SHALL 以跨 SQLite / MySQL / PostgreSQL 可攜型別與一般反射可搬移 schema 設計

### Requirement: New helper UI must follow TCRT UI style

- **GIVEN** 新版 helper 需要新增或改版前端畫面 / the new helper introduces dedicated frontend screens
- **WHEN** 系統實作七畫面 workflow / the system implements the seven-screen workflow
- **THEN** 系統 SHALL 依既有 TCRT UI style 實作，包含 `base.html` 區塊覆寫、`--tr-*` / `--btn-*` token、既有 card/table/modal 組合與三語 i18n retranslate 生命週期

## Non-Functional Requirements

- Performance: 畫面三每五秒 autosave 不得阻塞主要編輯操作；seed/testcase 生成應保留可追蹤的非同步狀態與進度回饋。
- Reliability: 同一份畫面三鎖定內容在未變更時，重新進入畫面四/五不得漂移 section 與 testcase 編號。
- Auditability: 必須能回溯 session 起點、鎖定版 seed/testcase 與最終 commit 結果；未完成 session 若被 `重新開始` 清除，不要求保留 lineage。
- UX governance: 不符合格式的 ticket 必須在畫面二被擋下，而不是把缺漏需求交給 LLM 猜測。

## Capabilities

### Modified Capabilities

- `helper-guided-intake`: 改為畫面一與畫面二的 ticket 輸入、session 建立、唯讀 markdown 確認與格式驗證閘門。
- `helper-structured-requirement-schema`: 改為以 `qa_ai_helper_preclean.py` 相容 parser 定義 read-only structured requirement 與 AC scenario schema。
- `helper-requirement-completeness-warning`: 改為畫面二的強制格式檢查，不再允許 override 繞過缺漏段落。
- `helper-deterministic-seed-planning`: 改為畫面三的 deterministic section allocation、驗證項目編輯、coverage 標記、autosave 與 requirement lock。
- `helper-final-generation-contract`: 改為高階 seed generation + seed refinement + 低階 testcase expansion + 本地 numbering / commit selection contract。
- `helper-prompt-file-loading`: 改為分別載入 seed generation、seed refinement、testcase generation 的 prompt。
- `jira-ticket-to-test-case-poc`: 改為描述七畫面 journey、target set commit 與 AI provenance / adoption tracking 的整體行為。

## Impact

- 受影響範圍：新版 helper API / service、畫面一到畫面七的前端 UI、資料表 migration、prompt 檔案與對應測試。
- 需要新增或調整 session lifecycle、requirement plan autosave、seed set persistence、testcase numbering allocator、commit linkage 與 adoption telemetry。
- 舊版 helper entry 與舊 contract 不得直接沿用；V1 / V2 的 session 與統計資料以清除處理，不做唯讀保留或 backfill migration。
