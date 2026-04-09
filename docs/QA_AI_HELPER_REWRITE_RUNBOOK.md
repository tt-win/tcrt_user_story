# QA AI Helper V3 Runbook

## 目的

這份文件描述新版 QA AI Helper V3 的正式操作與 rollout 邊界。V3 已不再使用 `canonical_revision -> planned_revision -> draft_set` 的舊 phase 流程，而是改成固定七畫面、兩段鎖定、兩段模型分工。

本文件涵蓋：

- 七畫面流程與 guard
- 畫面二 parser gate 規則
- 畫面三到畫面五的 lock / unlock 邊界
- `config.yaml` / `.env` stage model 設定方式
- TCRT UI 依循方式
- legacy helper purge 與 no-backfill rollout 策略

## 入口與開關

- 新版入口：
  - `/qa-ai-helper`
  - `/test-case-sets`
  - `/test-case-management`
- 新版 helper 開關：
  - `ai.qa_ai_helper.enable = true`
- 舊 modal 與舊 helper 統計已退役：
  - `/test-case-sets`、`/test-case-management` 不再載入舊 modal partial
  - `/api/admin/team_statistics/helper_ai_analytics` 固定回傳 `410 legacy_helper_statistics_retired`

## 七畫面流程

### 畫面一：載入需求單

- 使用者輸入 `Ticket Number`
- 只有按下 `載入需求單內容` 才建立 `qa_ai_helper_sessions`
- 此畫面本身是 sessionless

### 畫面二：需求單內容確認

- 左側以 markdown 唯讀顯示 Jira 原始 ticket
- 右側顯示 parser gate 結果、錯誤、警告與 CTA
- 桌面版採 `8 + 4` split layout
- parser 以 `scripts/qa_ai_helper_preclean.py` 為基底

#### parser gate

必填區塊：

- `User Story Narrative`
- `Criteria`
- `Acceptance Criteria`

warning-only：

- `Technical Specifications`

欄位級檢查：

- `As a`
- `I want`
- `So that`
- `Criteria` 至少一筆有效 item
- 每個 Acceptance Criteria scenario 都必須有：
  - 有效名稱
  - `Given`
  - `When`
  - `Then`

以下情況會直接阻擋進入畫面三：

- 缺少必要區塊
- `Acceptance Criteria` 不是非空 list
- `Unnamed Scenario`
- 缺少 `Given / When / Then`

### 畫面三：需求驗證項目分類與填充

- 依 Acceptance Criteria 建立 section
- 預設 section 編號：
  - `ticket_key.010`
  - `ticket_key.020`
  - `ticket_key.030`
- 左側為 section rail
- 右側為 section editor
- 下方保留 `Criteria` 與 `Technical Specifications` 唯讀參考區
- 依 `tcrt-ui-style` 沿用 `base.html`、既有 card/workspace pattern 與 i18n lifecycle

驗證項目分類固定為：

- `API`
- `UI`
- `功能驗證`
- `其他`

每筆檢查條件都必須填寫：

- 自然語言描述
- `coverage`

coverage 由使用者自行負責填寫：

- `Happy Path`
- `Error Handling`
- `Edge Test Case`
- `Permission`

儲存規則：

- 每 5 秒 autosave
- 支援手動 `儲存`

鎖定規則：

- 只有 `鎖定需求` 後才能進畫面四
- `解開鎖定` 後，下游 seed/testcase 立即失效

### 畫面四：Test Case 種子確認

- 由 high-tier model 根據「已鎖定 requirement plan」生成第一版 seed set
- seed 生成改為最多 5 個 worker 併發執行，每個 worker 都會攜帶完整 requirement plan 與 section summary 參考資料
- 每筆 seed 預設為 `納入`
- 支援 per-seed `納入 / 排除`
- 支援 section-level `全部納入 / 全部排除`
- 不提供手動新增 / 刪除 seed

refinement 規則：

- 只允許以註解驅動 refinement
- refinement payload 只送出「新增或修改過的 seed 註解」
- 不重跑整批 seed

鎖定規則：

- 任一註解修改或 include/exclude 變更，都會使 seed set 回到 draft
- 只有 `鎖定 Seeds` 後，才可進入畫面五

adoption 口徑：

- `seed_adoption_rate = included_seed_count / generated_seed_count`

### 畫面五：Test Case 確認

- 只處理由畫面四「已鎖定且已納入」的 seeds 產生出的 testcase drafts
- 由 low-tier model 生成 testcase body
- model 不負責編號，編號由本地 allocator 套用

編號規則：

- 同一 section 內依固定流水號配置：`010, 020, 030...`
- 不再依 verification item 切換 `100, 200, 300...` block

畫面五僅允許編修：

- `title`
- `priority`
- `preconditions`
- `steps`
- `expected_results`

不可編修：

- testcase 編號
- seed/reference
- source section / verification item

勾選規則：

- `selected_for_commit` 預設不全選
- invalid draft 不可勾選
- 支援 section-level 全選 / 清除選取
- 至少一筆有效且被勾選的 draft 才能進畫面六

若畫面四 seed set 再次變更：

- 既有 `testcase_draft_set` 標記為 `superseded`
- 必須重新生成 testcase drafts

adoption 口徑：

- `testcase_adoption_rate = selected_for_commit_count / generated_testcase_count`

### 畫面六：Test Case Set 選擇

- 只能選一個 target set
- 模式互斥：
  - 使用既有 Test Case Set
  - 建立新 Test Case Set
- 新建模式需先通過必要欄位驗證

### 畫面七：新增結果

- 顯示：
  - target set
  - created / failed / skipped 數量
  - per-draft 結果摘要
- 已建立 `commit_links` 的 draft 可追到實際 testcase
- 畫面七不提供 destructive `重新開始`，只提供開始新流程或回目標 set

## Stage Model 設定

`qa_ai_helper` 的 stage model 由設定驅動，不可寫死在程式內。

`config.yaml`：

```yaml
ai:
  qa_ai_helper:
    models:
      seed:
        model: ${QA_AI_HELPER_MODEL_SEED}
        temperature: 0.1
      seed_refine:
        model: ${QA_AI_HELPER_MODEL_SEED_REFINE}
        temperature: 0.0
      testcase:
        model: ${QA_AI_HELPER_MODEL_TESTCASE}
        temperature: 0.0
```

對應環境變數：

- `QA_AI_HELPER_MODEL_SEED`
- `QA_AI_HELPER_MODEL_SEED_TEMPERATURE`
- `QA_AI_HELPER_MODEL_SEED_REFINE`
- `QA_AI_HELPER_MODEL_SEED_REFINE_TEMPERATURE`
- `QA_AI_HELPER_MODEL_TESTCASE`
- `QA_AI_HELPER_MODEL_TESTCASE_TEMPERATURE`

規則：

- `seed_refine` 未設定時 fallback 到 `seed`
- `${ENV_VAR}` 若未被解析，settings load 直接 fail-fast
- 預設溫度：
  - `seed = 0.1`
  - `seed_refine = 0.0`
  - `testcase = 0.0`

## Persistence 與 Metrics

V3 使用 `qa_ai_helper_*` 命名空間，但只以 V3 語意表做 bootstrap required tables：

- `qa_ai_helper_sessions`
- `qa_ai_helper_ticket_snapshots`
- `qa_ai_helper_requirement_plans`
- `qa_ai_helper_plan_sections`
- `qa_ai_helper_verification_items`
- `qa_ai_helper_check_conditions`
- `qa_ai_helper_seed_sets`
- `qa_ai_helper_seed_items`
- `qa_ai_helper_testcase_draft_sets`
- `qa_ai_helper_testcase_drafts`
- `qa_ai_helper_telemetry_events`
- `qa_ai_helper_commit_links`

legacy tables 若仍存在：

- 不再是 bootstrap required tables
- 不再是統計或 adoption 的讀取來源
- rollout 後僅視為 legacy compatibility schema

## Legacy Purge 與 Rollout

### 原則

- 不遷移 V1 / V2 session、draft、telemetry、phase 統計
- 不對 V3 adoption / telemetry 做 backfill
- V3 metrics 起算點固定為：
  - `first_v3_session_after_purge`

### 建議步驟

1. 進 maintenance window，停止舊 helper 寫入
2. 先建立主庫 snapshot
3. 執行 helper runtime purge
4. 驗證 purge 結果為 clean
5. 切換入口，只暴露 V3 UI

### 參考腳本

`scripts/db_cross_migrate.py` 已提供：

- `create_sqlite_snapshot(engine, label="helper-purge")`
- `purge_legacy_helper_runtime(target_url, logger=None)`
- `verify_legacy_helper_purge(target_url)`

purge 目標至少包含：

- `ai_tc_helper_sessions`
- `ai_tc_helper_drafts`
- `ai_tc_helper_stage_metrics`
- `qa_ai_helper_sessions`
- `qa_ai_helper_canonical_revisions`
- `qa_ai_helper_planned_revisions`
- `qa_ai_helper_requirement_deltas`
- `qa_ai_helper_draft_sets`
- `qa_ai_helper_drafts`
- `qa_ai_helper_validation_runs`
- `qa_ai_helper_telemetry_events`
- `qa_ai_helper_ticket_snapshots`
- `qa_ai_helper_requirement_plans`
- `qa_ai_helper_plan_sections`
- `qa_ai_helper_verification_items`
- `qa_ai_helper_check_conditions`
- `qa_ai_helper_seed_sets`
- `qa_ai_helper_seed_items`
- `qa_ai_helper_testcase_draft_sets`
- `qa_ai_helper_testcase_drafts`
- `qa_ai_helper_commit_links`

## 驗證指令

```bash
PYTHONPATH=/Users/hideman/code/tcrt_user_story pytest app/testsuite/test_qa_ai_helper_preclean.py -q
PYTHONPATH=/Users/hideman/code/tcrt_user_story pytest app/testsuite/test_qa_ai_helper_api.py -q
PYTHONPATH=/Users/hideman/code/tcrt_user_story pytest app/testsuite/test_jira_testcase_helper_frontend.py -q
PYTHONPATH=/Users/hideman/code/tcrt_user_story pytest app/testsuite/test_team_statistics_helper_frontend.py -q
PYTHONPATH=/Users/hideman/code/tcrt_user_story pytest app/testsuite/test_team_statistics_helper_ai_api.py -q
PYTHONPATH=/Users/hideman/code/tcrt_user_story pytest app/testsuite/test_db_cross_migrate_script.py -q
node --check app/static/js/team_statistics.js
python -m py_compile scripts/db_cross_migrate.py database_init.py app/api/team_statistics.py
openspec validate rewrite-qa-ai-agent --strict --json
```
