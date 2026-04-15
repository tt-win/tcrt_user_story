## 1. 刪除過時的獨立腳本 (Remove obsolete standalone scripts)

- [x] 1.1 刪除 `scripts/` 目錄下的過期腳本：`migrate_tcg_format.py`, `migrate_test_case_sets.py`, `migrate_usm_db.py`, `cleanup_usm_nodes.py`, `ai_assist_smoke_test.py`。(Delete obsolete migration and utility scripts from the scripts directory)
- [x] 1.2 刪除根目錄下的除錯與展示腳本：`test_usm_parser.py`, `demo_usm_usage.sh`。(Delete obsolete debugging and demo scripts from the project root)

## 2. 清理與修復程式碼 (Clean up and fix code)

- [x] 2.1 編輯 `app/audit/database.py`，刪除未使用的 `from sqlalchemy.dialects.sqlite import JSON` 匯入，確保程式碼整潔。(Remove unused SQLite dialect import from app/audit/database.py)
- [x] 2.2 編輯 `app/testsuite/test_test_run_item_update_without_snapshot.py`，將 `conn.execute(text("PRAGMA foreign_keys=OFF"))` 等直接寫死的 SQLite 語法加入 dialect 判斷，或改用通用的測試前置準備邏輯。(Refactor test setup in test_test_run_item_update_without_snapshot.py to use standard SQLAlchemy or add dialect checks to avoid SQLite PRAGMA errors on other databases)

## 3. 測試與驗證 (Testing and Verification)

- [x] 3.1 執行 `pytest app/testsuite/test_test_run_item_update_without_snapshot.py`，確保該測試案例的修改沒有破壞原本的測試邏輯且能順利通過。(Run the modified test case to ensure it still passes)
- [x] 3.2 執行全專案的 Pytest，確保刪除這些檔案並沒有無意中影響任何還在依賴它們的模組。(Run the entire test suite to guarantee no accidental dependencies were broken)
