## MODIFIED Requirements

### Requirement: 資料庫連線的跨平台相容性
系統 SHALL 在建立資料庫連線時，根據連線方言 (`dialect`) 動態決定是否執行特定資料庫的最佳化指令（如 SQLite 的 `PRAGMA`），以避免非 SQLite 資料庫啟動時發生語法錯誤；同時 auxiliary databases 的 schema 建立與修補 SHALL NOT 在 runtime initializer 內透過 `create_all` 或 ad-hoc DDL 執行。 Auxiliary database initializers MUST limit themselves to connection/session setup and leave schema mutations to the migration layer.

#### Scenario: 啟動非 SQLite 資料庫連線
- **WHEN** 系統以非 SQLite 的設定（如 MySQL URL）啟動並觸發 `engine` 的 `connect` 事件
- **THEN** 系統不會執行任何 `PRAGMA` 指令，並能成功建立連線。

#### Scenario: 啟動 SQLite 資料庫連線
- **WHEN** 系統以 SQLite 的設定啟動並觸發 `engine` 的 `connect` 事件
- **THEN** 系統成功執行針對 SQLite 的 `PRAGMA journal_mode=WAL` 等優化指令。

#### Scenario: 初始化 auxiliary database 連線
- **WHEN** 系統執行 `init_audit_database()` 或 `init_usm_db()`
- **THEN** 初始化流程只建立 engine/session 與必要健康檢查，不會透過 runtime DDL 改動資料表結構
