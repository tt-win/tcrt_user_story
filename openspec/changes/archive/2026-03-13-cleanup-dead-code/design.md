## Context

經過一系列的架構重構（包含 `refactor-db-abstraction`、`refactor-database-init` 與 `remove-lark-test-case-sync`），TCRT 的核心系統已經變得更加標準化。目前專案成功使用了 SQLAlchemy 搭配 Alembic 來進行跨資料庫（如 SQLite、MySQL 等）的操作，且完全解除了對 Lark 測試案例同步服務的依賴。
然而，專案目錄中仍殘留著這些重構發生前所遺留下來的「腳本 (Scripts)」與「變造代碼 (Workaround)」，這些未被呼叫的模組不僅成為了 Dead Code（死碼），還可能在未來造成誤導或是環境設定上的困擾（例如某些測試檔案還保留著 SQLite 特有的 PRAGMA 語法）。

## Goals / Non-Goals

**Goals:**
- 安全地刪除 `scripts/` 目錄中過時且不會再被使用的資料庫遷移腳本與工具腳本。
- 清理根目錄中過時的雛型測試與展示腳本。
- 清理生產環境代碼中無用的 Database Dialect imports。
- 修正測試案例中直接執行 SQLite 原生 SQL 語法的部分，使其能具備跨資料庫測試的彈性或至少避免在非 SQLite 下崩潰。

**Non-Goals:**
- 不對現有的核心業務邏輯（如 Test Case CRUD、User Story Map 操作）進行功能性的改變。
- 不刪除目前還有被系統排程器 (scheduler) 或 API 呼叫的任何腳本（如 ETL 腳本 `etl_to_qdrant.py` 仍需保留）。

## Decisions

1. **移除廢棄的獨立腳本 (Standalone Scripts)**
   *   **決定：** 直接刪除 `migrate_tcg_format.py`、`migrate_test_case_sets.py`、`migrate_usm_db.py`、`cleanup_usm_nodes.py`、`ai_assist_smoke_test.py`、`test_usm_parser.py` 及 `demo_usm_usage.sh`。
   *   **Rationale：** 這些腳本目前皆為孤立腳本（未被任何程式 Import），且功能（如 Migration）已被 Alembic 取代，或為過去的 PoC 測試，保留只會增加維護負擔。

2. **清理 `app/audit/database.py` 的 Import**
   *   **決定：** 刪除 `from sqlalchemy.dialects.sqlite import JSON` 以及相關未使用的變數/模組。
   *   **Rationale：** 確保跨資料庫設計的純潔性，避免靜態檢查工具 (如 linter) 報錯。

3. **重構 `app/testsuite/test_test_run_item_update_without_snapshot.py`**
   *   **決定：** 移除測試設定函式 `_prepare_schema_with_missing_backup` 裡面的 `conn.execute(text("PRAGMA foreign_keys=OFF"))`，改為使用標準 SQLAlchemy 的 `DropTable` 與 `CreateTable` 流程，或者如果非得用原生語法，加上對連線方言 (`dialect == 'sqlite'`) 的判斷。
   *   **Rationale：** 確保測試案例未來即使在 MySQL 等其他資料庫上運行，也不會因為不認得 SQLite 指令而崩潰。

## Risks / Trade-offs

- **[Risk] 誤刪正在使用中的工具腳本** → 若某些開發者依賴這些腳本進行日常維護。
  - **Mitigation：** 所有的刪除都會透過 Git 進行版控，若日後發現某腳本仍有價值，可以隨時從歷史紀錄中還原。
- **[Risk] 修改測試環境建表邏輯導致測試變慢或失敗** →
  - **Mitigation：** 變更完成後，必須完整執行 `pytest app/testsuite/test_test_run_item_update_without_snapshot.py` 確保該測試行為不變且成功通過。
