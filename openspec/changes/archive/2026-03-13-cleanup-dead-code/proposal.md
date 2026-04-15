## Why

隨著專案經歷了數次重大重構（包含引入 Alembic 作為資料庫遷移工具，以及移除對 Lark 測試案例的同步依賴），系統中遺留了許多不再使用的一次性遷移腳本、開發測試用檔案，以及過去針對 SQLite 特製但現在已不需要的 Workaround 與未使用 Import。
清理這些冗餘的死碼（Dead Code）可以大幅降低專案目錄的雜亂度，減少新進開發者的認知負擔，並確保在未來的跨資料庫執行（如 MySQL 或 PostgreSQL）與自動化測試中，不會因為這些殘留的 SQLite 語法而發生預期外的錯誤。

## What Changes

- 刪除 `scripts/` 目錄下的過期遷移與維護腳本，包含：`migrate_tcg_format.py`、`migrate_test_case_sets.py`、`migrate_usm_db.py`、`cleanup_usm_nodes.py`、`ai_assist_smoke_test.py`。
- 刪除專案根目錄下不再維護的除錯/展示用腳本：`test_usm_parser.py` 與 `demo_usm_usage.sh`。
- 修復 `app/audit/database.py` 中未使用的 SQLite 方言 Import。
- 修復 `app/testsuite/test_test_run_item_update_without_snapshot.py` 測試案例，將直接寫死的 `PRAGMA foreign_keys` 修改為僅在 SQLite 環境下執行，或將其重構以符合跨資料庫標準。

## Capabilities

### Modified Capabilities
- `database-operations`: 徹底清理所有殘留的特定資料庫 (SQLite) 相依邏輯與無用的手動腳本。

## Impact

- `scripts/` (多個檔案將被刪除)
- 專案根目錄 (2 個檔案將被刪除)
- `app/audit/database.py`
- `app/testsuite/test_test_run_item_update_without_snapshot.py`
