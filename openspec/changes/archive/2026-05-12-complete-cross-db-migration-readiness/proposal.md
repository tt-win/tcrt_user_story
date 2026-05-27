## Why

目前三套資料庫已納入 Alembic 與顯式 adoption，但專案仍殘留 SQLite 專屬的 runtime 例外處理、腳本、測試 fixture 與設定缺口，實際上還不能稱為可無痛切換到其他關聯式資料庫。We need one more hardening pass so that migration readiness is verified end-to-end instead of assumed from partial abstraction.

## What Changes

- 補齊目標資料庫 driver 與設定模型，讓 `main`、`audit`、`usm` 都能透過一致的設定來源切換到 MySQL 或 PostgreSQL。
- 清除剩餘 SQLite 專屬 runtime / script 路徑，將 `sqlite3` 例外、`PRAGMA` 診斷與硬編碼 `.db` 預設改為方言感知或設定導向實作。
- 將測試基底改為以 Alembic 建立 schema，而不是在 fixture 內直接 `create_all`，並補跨資料庫 smoke coverage。
- 建立正式的 cutover readiness 流程，包含 preflight、資料驗證、rehearsal 與 rollback 輸出，讓資料遷移有可重複執行的操作標準。

## Capabilities

### New Capabilities
- `database-cutover-readiness`: 定義跨資料庫切換前的 smoke、rehearsal、資料驗證與 rollback 準備要求。

### Modified Capabilities
- `database-operations`: 收斂剩餘 SQLite 專屬 runtime、script 與設定特例，並要求測試/工具鏈可在不同 SQL dialect 下運作。
- `database-migration`: 擴充 migration 治理到驅動安裝、target database preflight 與正式 adoption/cutover 驗證流程。

## Impact

- `requirements.txt`
- `app/config.py`
- `config.yaml.example`
- `app/database.py`
- `app/audit/database.py`
- `app/models/user_story_map_db.py`
- `app/services/test_case_sync_service.py`
- `app/api/admin.py`
- `app/services/tcg_converter.py`
- `scripts/migrate_tcg_format.py`
- `app/testsuite/` fixtures 與 migration/smoke tests
- MySQL/PostgreSQL smoke 文件與自動驗證流程
