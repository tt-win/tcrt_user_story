## MODIFIED Requirements

### Requirement: 資料庫連線的跨平台相容性
系統 SHALL 在建立資料庫連線、執行連線診斷或方言特化初始化時，根據連線方言 (`dialect`) 動態決定是否執行特定資料庫的最佳化與診斷指令（如 SQLite 的 `PRAGMA`），以避免非 SQLite 資料庫在 shared runtime path 上發生語法錯誤或錯誤判斷。

#### Scenario: 啟動非 SQLite 資料庫連線
- **WHEN** 系統以非 SQLite 的設定（如 MySQL URL）啟動並觸發 `engine` 的 `connect` 事件
- **THEN** 系統不會執行任何 SQLite 專屬 `PRAGMA` 指令，並能成功建立連線

#### Scenario: 啟動 SQLite 資料庫連線
- **WHEN** 系統以 SQLite 的設定啟動並觸發 `engine` 的 `connect` 事件
- **THEN** 系統成功執行針對 SQLite 的最佳化指令，如 `PRAGMA journal_mode=WAL`

#### Scenario: 非 SQLite 環境執行共享診斷流程
- **WHEN** 管理 API、同步流程或診斷路徑在 MySQL 或 PostgreSQL 環境執行
- **THEN** 系統不會執行 SQLite 專屬 `PRAGMA` 或依賴 `sqlite3.OperationalError` 才能判斷失敗原因

## ADDED Requirements

### Requirement: 共享 runtime path 的 raw SQL 與方言行為 SHALL 被集中治理
系統 SHALL 將共享 runtime path 上的 raw SQL、dialect branching 與方言專屬錯誤處理集中到受管 boundary/infra 模組。 API handler、service、auth flow 與 background task MUST NOT 散落直接依賴單一資料庫方言的 SQL 或例外型別。

#### Scenario: 非 SQLite 環境執行統計或管理查詢
- **WHEN** 共享 runtime path 在 MySQL 或 PostgreSQL 環境執行需要 raw SQL 的查詢
- **THEN** 該查詢透過受管 boundary/adapter 以 dialect-aware 方式執行，且不因 SQLite-specific SQL 導致語法錯誤

#### Scenario: 受管 boundary 內保留必要 raw SQL
- **WHEN** 某個受管 boundary 因效能或語意需求必須保留 raw SQL
- **THEN** SQL 被限制在受管模組內，並附帶對應方言處理與測試覆蓋

### Requirement: 資料庫維運工具 SHALL 支援目標資料庫
系統 SHALL 讓資料維運工具、離線作業與整合流程透過設定後的 SQLAlchemy engine/session 與受管 boundary 操作資料庫，而不是綁定 SQLite 檔案路徑或隱式 `sqlite3.connect()`。 Maintenance utilities MUST be target-aware so they can run against the configured main database.

#### Scenario: 執行維護腳本
- **WHEN** 維運人員在 MySQL 或 PostgreSQL 環境執行資料維護腳本或服務
- **THEN** 工具透過設定解析出的 target database 連線進行查詢與更新，而不是假設本機 `.db` 檔案存在

### Requirement: 測試 schema 建立 SHALL 對齊受管 migration 與 target database
系統 SHALL 在主要 integration/API 測試 fixture 中以受管 migration 與 target-aware schema setup 建立 `main`、`audit`、`usm` 測試資料庫，而不是在聲稱驗證跨資料庫行為的測試裡依賴寫死 SQLite-only schema setup。 Model-level isolated tests MAY continue to use direct metadata setup only when they do not claim portability or migration coverage.

#### Scenario: 建立跨資料庫 smoke 測試 fixture
- **WHEN** 測試需要驗證 MySQL 或 PostgreSQL target 的 API / service 流程
- **THEN** fixture 透過受管 migration/schema setup 建立對應資料庫，而不是直接寫死 SQLite 測試初始化
