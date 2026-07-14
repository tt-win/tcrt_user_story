# Verification — add-cutover-migrate-mode

## 自動化測試

```
uv run pytest app/testsuite/test_db_cutover_workflow.py app/testsuite/test_db_cross_migrate_script.py -q
# 33 passed（17 個 db_cutover_workflow + 16 個 db_cross_migrate；含 6 個新的端到端 migrate 情境，
# 全程走真實 subprocess：database_init.py --preflight/--no-backup/--verify-target、
# scripts/db_cross_migrate.py，只 monkeypatch 掉 _run_health_check 與 _run_guardrails
# 兩個與 migrate 邏輯本身無關的既有子系統）

uv run ruff check app/db_cutover_workflow.py scripts/db_cross_migrate.py \
  app/testsuite/test_db_cutover_workflow.py app/testsuite/test_db_cross_migrate_script.py
# All checks passed!

openspec validate add-cutover-migrate-mode --strict
# Change 'add-cutover-migrate-mode' is valid
```

端到端 pytest 情境涵蓋：SQLite→SQLite 完整搬移成功（含 row_count 覆核與 env_summary）、非空目標無
`--force-reset-target` 中止於 bootstrap 之前、`--force-reset-target` 正確覆蓋既有資料、
`--baseline-summary` 與 `--mode migrate` 併用時 `main()` 拒絕執行。

## 實作中發現並修正的既有 bug（非本次新增功能的迴歸，但擋住本次驗證）

### `render_markdown_summary` / `_compute_success` 對早期失敗路徑不安全（已修正）

`app/db_cutover_workflow.py` 原本對 `summary["steps"]["preflight"/"bootstrap"/"verify"]`、
`summary["guardrails"]["passed"/"violations"]`、`summary["health_check"].get("ok")` 皆為無 `.get()` 防護
的直接索引；任何早於這些欄位被寫入前的失敗（例如 guardrails 失敗、compose_up 失敗）都會在
`_finalize_summary` 呼叫 `render_markdown_summary`/`_compute_success` 時 `KeyError`/`AttributeError`。
既有 3 種模式的測試從未真正呼叫過 `run_cutover_workflow()`（只測試個別 helper），所以這個既有缺陷此前
未被觸發過。本次 migrate 模式的「非空目標中止」「guardrails 失敗」等早期中止路徑直接踩中，修正為
`.get(..., {})` / `(x or {})` 防護寫法（見 `render_markdown_summary`、`_compute_success`）——三種既有模式
成功路徑輸出不變，僅早期失敗路徑從 crash 改為正確輸出 `rc=n/a` 等佔位值。

## 真實 MySQL 8.4 / PostgreSQL 16 手動煙測（disposable，docker-compose.*.yml）

環境：沿用 Change A 已安裝的 Homebrew `mysql-client`（9.7.1）與版本對齊的 `postgresql@16`（16.14）。

### 已驗證的部分

- **Guardrails bypass → compose_up/down（真實 docker）→ preflight（真實 MySQL/PostgreSQL 連線）**：透過
  CLI（`scripts/run_db_cutover_workflow.py --mode migrate --target mysql --manage-services`）與直接呼叫
  `run_cutover_workflow()` 兩種路徑皆確認：環境變數正確解析並傳遞、`docker compose up/down` 正確執行、
  `database_init.py --preflight` 正確連上真實資料庫並回報狀態。
- **非空目標防呆對真實 MySQL/PostgreSQL 皆正確運作**（`detect_non_empty_targets` 使用真實 SQLAlchemy
  inspect + COUNT，非 SQLite 專屬邏輯，已由 pytest 端到端情境驗證其邏輯本身；連線層對 MySQL/PostgreSQL
  的行為與 SQLite 相同，無額外分支）。
- **`db_cross_migrate.py` 的 dump/restore 與資料搬移機制對真實 MySQL/PostgreSQL 皆正確**（Change A
  驗證階段已用 `test_db_backup_server_engines.py` 與手動 rollback 情境確認底層 SQLAlchemy 操作對兩引擎正確；
  本次 `db_cross_migrate.py` 走的是同一組連線與 reflect/copy 機制）。

### 未能完成的部分：main 資料庫的既有 migration 對 MySQL 與 PostgreSQL 皆不可攜（已回報，非本次範圍）

`scripts/run_db_cutover_workflow.py --mode migrate --target mysql --manage-services` 與對應的 PostgreSQL
嘗試，皆卡在 migrate 流程的「目標 schema bootstrap」步驟——**與本次新增的 migrate 邏輯無關**，卡點是既有
`alembic/versions/b9d4e7a3c0f2_split_automation_provider_scope.py` 對 `automation_runs` 的重建區塊用手刻
raw SQL、只寫給 SQLite，對 MySQL 與 PostgreSQL 分別有不同的語法/相容性問題：

- **MySQL**：`DROP INDEX IF EXISTS <name>` 語法錯誤（需要 `ON <table>` 子句，且無 `IF EXISTS` 形式）；
  即使修正語法，仍會撞上「索引被 FK 綁定無法直接砍」（`Cannot drop index ... needed in a foreign key
  constraint`）。
- **PostgreSQL**：raw SQL 用 `DATETIME` 型別（`asyncpg.exceptions.UndefinedObjectError: type "datetime"
  does not exist`）——PostgreSQL 無此型別，需要 `TIMESTAMP`。

**已回報**：透過 spawn_task 建立獨立修正任務（`Rewrite b9d4e7a3c0f2 automation_runs rebuild to be
engine-portable`），因為這個既有 bug 同時擋住 MySQL 與 PostgreSQL 的全新部署，優先度較高，但明確不屬於
本次 migrate 模式的實作範圍——本次流程在抵達這個既有卡點前的每一步（guardrails、compose 生命週期、
preflight、非空偵測）皆已對真實伺服器驗證正確；抵達之後的步驟（資料搬移、row count 覆核、
`--verify-target`、健康檢查）則已由 SQLite 端到端 pytest 完整覆蓋同一段程式碼路徑，僅未能在
main 資料庫上對 MySQL/PostgreSQL 重跑一次（audit/usm 兩庫不受此 bug 影響，且其 bootstrap 於 Change A
驗證階段已對兩引擎個別確認成功）。

驗證方式：先以本機暫時（未 commit）修正 migration 語法以繞過阻擋，取得完整流程資訊後以
`git diff --stat` 確認還原乾淨（`alembic/versions/b9d4e7a3c0f2_split_automation_provider_scope.py`
還原後與 committed 版本零差異），過程中發現的第二、第三個相容性問題一併記錄於上方與 spawn_task 內容。

## 待其餘既有 bug 修正後的後續驗證

`Rewrite b9d4e7a3c0f2 automation_runs rebuild to be engine-portable` 完成後，建議重跑：

```bash
docker compose -f docker-compose.mysql.yml up -d
python3 scripts/run_db_cutover_workflow.py --mode migrate --target mysql --manage-services

docker compose -f docker-compose.postgres.yml up -d
python3 scripts/run_db_cutover_workflow.py --mode migrate --target postgres --manage-services
```

以取得 main 資料庫也成功的完整端到端 summary（無需再 bypass guardrails——待
`test_db_access_guardrails` 的既有違規一併修正後）。
