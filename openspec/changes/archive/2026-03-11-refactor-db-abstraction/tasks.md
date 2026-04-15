## 1. 資料庫連線初始化重構 (Database Connection Setup)

- [x] 1.1 修改 `app/database.py` 中的 `set_sqlite_pragma` 邏輯，增加連線方言 (`dialect`) 判斷，僅在 `sqlite` 時執行 `PRAGMA`。(Modify `set_sqlite_pragma` in `app/database.py` to check dialect before execution)
- [x] 1.2 修改 `app/database.py` 中的 `set_sync_sqlite_pragma` 同步版連線邏輯，同樣增加方言判斷。(Modify `set_sync_sqlite_pragma` in `app/database.py` to check dialect)
- [x] 1.3 尋找並修改其他連線初始化的部分（如 `app/audit/database.py`、`app/models/user_story_map_db.py` 等），確保跨資料庫相容。(Update other DB initialization scripts to be dialect-aware)

## 2. 移除模型定義的 SQLite 特有屬性 (Remove SQLite-specific Model Attributes)

- [x] 2.1 修改 `app/models/database_models.py`，全域搜尋並移除所有 `sqlite_autoincrement=True` 參數。(Remove `sqlite_autoincrement=True` from `app/models/database_models.py`)
- [x] 2.2 檢查 `database_models.py` 中的其他欄位定義，確保沒有其他違反標準 ORM 抽象化的特例（例如寫死 SQLite 的 Column Type）。(Review models for any other non-standard dialect attributes)

## 3. 重構 JSON 查詢邏輯 (Refactor JSON Queries)

- [x] 3.1 審查 `app/services/test_case_repo_service.py` 找到使用 `json_each` 的查詢片段。(Identify `json_each` usages in `app/services/test_case_repo_service.py`)
- [x] 3.2 將 `json_each` 的查詢改寫為應用層過濾、或是針對目前資料庫動態產生通用 SQL（如使用 `LIKE` 或是 SQLAlchemy 原生的寫法）。(Refactor `json_each` into standard SQLAlchemy or application-level filtering)
- [x] 3.3 執行與 Test Case 查詢相關的 Unit/Integration Tests，確保重構後功能與效能符合預期。(Run test cases to ensure query refactoring works as expected)

## 4. 重構 Upsert 邏輯 (Refactor Upsert Logic)

- [x] 4.1 審查 `app/services/tcg_converter.py` 找到使用 `INSERT OR REPLACE` 的 SQL。(Identify `INSERT OR REPLACE` usages in `app/services/tcg_converter.py`)
- [x] 4.2 將 `INSERT OR REPLACE` 重構為標準的先 `SELECT` 後 `INSERT`/`UPDATE` 邏輯，或採用支援多方言的 SQLAlchemy Upsert 封裝。(Refactor into a dialect-agnostic upsert logic)
- [x] 4.3 執行與 TCG 匯入相關的測試，確保資料同步正確且無重複。(Run TCG import tests to verify the upsert behavior)

## 5. 系統測試與驗證 (System Testing and Verification)

- [x] 5.1 執行全專案的 Pytest 測試，確保所有基於 SQLite 的測試都能通過。(Run all Pytest test cases against SQLite to ensure no regressions)
- [x] 5.2 建立或準備一組基本的 MySQL 環境變數或 Docker 容器配置（可選，作為文件紀錄與驗證用），證明程式碼可以順利啟動連線。(Optional: Spin up a MySQL instance to verify connection initialization passes without syntax errors)
