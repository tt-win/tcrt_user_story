# QA AI Helper Rewrite Runbook

## 目的

新版 QA AI Helper 採用獨立 UI、獨立資料表與 deterministic planning。這份 runbook 提供：

- 新版流程的操作順序
- canonical / planned / draft revision 的意義
- lock、regenerate、discard 的使用規則
- 舊資料與舊 helper 的唯讀相容策略
- bootstrap / cross-db-migrate / benchmark 檢查方式

## 入口與開關

- 新版入口：
  - `/qa-ai-helper`
  - `/test-case-sets`
  - `/test-case-management`
- 舊版 helper 入口預設隱藏，保留設定僅供回退：
  - `ai.jira_testcase_helper.enable = false`
- 新版 helper 預設啟用：
  - `ai.qa_ai_helper.enable = true`

## Workflow

1. 建立 session
2. 抓取 Jira ticket
   - `include_comments` 預設關閉
3. 在 Canonical Intake 確認四段 requirement
   - `User Story Narrative`
   - `Criteria`
   - `Technical Specifications`
   - `Acceptance Criteria`
4. 產生 deterministic plan
5. 在 Plan Review 調整：
   - `applicable`
   - `not_applicable`
   - `manual_exempt`
   - per-section references
   - requirement delta
6. 鎖定 planning revision
7. 產生 testcase drafts
8. 在 Draft Review 編修 testcase body
9. commit 到目標 Test Case Set

## CRUD 邊界

### Canonical Intake

允許：

- 新增 / 刪除 / 修改四段 canonical 內容
- 新增 / 刪除 / 修改 AC scenarios
- 修改 `middle` / `tail`

不允許：

- 刪除四大 required section shell

### Plan Review

允許：

- 修改 matrix applicability
- 批次套用 `not_applicable` / `manual_exempt`
- 修改 references
- 修改 counters
- 提出 `requirement_delta`

不允許：

- 直接新增 requirement
- 直接刪除 requirement
- 直接插入 planner 未推導出的 matrix row

### Draft Review

允許：

- 修改 `title`
- 修改 `priority`
- 修改 `preconditions`
- 修改 `steps`
- 修改 `expected_results`

不允許：

- 新增 testcase object
- 刪除 testcase object
- 重新分配 requirement mapping

## Revision 與 Lock 規則

- `canonical_revision` 是 requirement 唯一 source of truth
- `planned_revision` 代表某次 deterministic planning 結果
- `draft_set` 代表某次 generation / validation 結果

下列變更都會讓 lock 失效：

- canonical content 變更
- AC scenario 增刪改
- planning overrides 變更
- selected references 變更
- counter settings 變更

如果同一個 locked revision 已經有 `active draft_set`：

- 預設直接重開既有 drafts
- 若要 fresh generation，必須先 discard draft set，或建立新的 locked revision

## Requirement Delta

如果在 Plan Review 發現 canonical requirement 遺漏或誤判：

1. 建立 `requirement_delta`
2. 系統會產生新的 `canonical_revision`
3. 舊 `planned_revision` 會標成 `stale`
4. 舊 `draft_set` 會標成 `outdated`
5. 系統會重新規劃；若可定位影響範圍，優先做 scoped replanning

## 舊資料唯讀策略

- 新版 helper **不得共寫**舊 helper tables
- 若需要讀舊資料，只能使用唯讀 adapter / migration
- rollout 時只暴露新版入口；若要回退，只切回舊入口，不做新舊共寫

## Database Bootstrap / Cross Migrate

新版 helper 使用下列主庫表：

- `qa_ai_helper_sessions`
- `qa_ai_helper_canonical_revisions`
- `qa_ai_helper_planned_revisions`
- `qa_ai_helper_requirement_deltas`
- `qa_ai_helper_draft_sets`
- `qa_ai_helper_drafts`
- `qa_ai_helper_validation_runs`
- `qa_ai_helper_telemetry_events`

相容性要求：

- `database_init.py` 需將這些表納入 `MAIN_REQUIRED_TABLES`
- `scripts/db_cross_migrate.py` 需能以一般反射方式搬移，不依賴 helper 專屬 hook
- 欄位型別以 SQLite / MySQL / PostgreSQL 可攜型別為主，JSON 內容採 TEXT/JSON 可序列化格式

## 驗證指令

### 測試

```bash
uv run pytest app/testsuite/test_qa_ai_helper_api.py -q
uv run pytest app/testsuite/test_qa_ai_helper_planner.py -q
uv run pytest app/testsuite/test_qa_ai_helper_runtime.py -q
uv run pytest app/testsuite/test_db_cross_migrate_script.py -q
uv run pytest app/testsuite/test_database_init.py -q
uv run pytest app/testsuite/test_jira_testcase_helper_frontend.py -q
```

### Benchmark

```bash
uv run python scripts/qa_ai_helper_benchmark.py --iterations 10
```

### OpenSpec

```bash
uv run openspec validate rewrite-qa-ai-agent
```
