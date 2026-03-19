# SQLite Smoke Setup

此文件提供本專案在本機對 SQLite 執行三套資料庫 `main`、`audit`、`usm` 的 smoke / rehearsal 標準流程。

## 1. 執行 SQLite smoke

```bash
python3 scripts/run_db_cutover_workflow.py --target sqlite --mode smoke
```

此流程會：

- 在 `.tmp/db-cutover/` 建立隔離的 SQLite `main` / `audit` / `usm` 檔案
- 執行 DB access guardrails
- 執行 `python3 database_init.py --preflight`
- 執行 `python3 database_init.py`
- 執行 `python3 database_init.py --verify-target all`
- 啟動應用程式並檢查 `GET /health`

## 2. 執行 SQLite baseline / rehearsal

若要產生後續 MySQL 或 PostgreSQL rehearsal 的 baseline summary：

```bash
python3 scripts/run_db_cutover_workflow.py --target sqlite --mode rehearsal
```

輸出會寫入最新的 `.tmp/db-cutover/<timestamp>-sqlite-rehearsal/summary.json` 與 `summary.md`。

## 3. 驗證輸出

每次 run 至少會留下：

- `summary.json`
- `summary.md`
- `logs/preflight.log`
- `logs/bootstrap.log`
- `logs/verify.log`
- `logs/start.log`

若 smoke 或 rehearsal 失敗，請依 [database-cutover-readiness.md](database-cutover-readiness.md) 執行 rollback 與 re-verification。
