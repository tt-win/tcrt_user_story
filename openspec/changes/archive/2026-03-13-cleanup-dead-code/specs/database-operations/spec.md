## MODIFIED Requirements

### Requirement: 資料庫連線的跨平台相容性
系統 SHALL 在建立資料庫連線時，根據連線方言 (`dialect`) 動態決定是否執行特定資料庫的最佳化指令（如 SQLite 的 `PRAGMA`），以避免非 SQLite 資料庫啟動時發生語法錯誤。

#### Scenario: 啟動非 SQLite 資料庫連線
- **WHEN** 系統以非 SQLite 的設定（如 MySQL URL）啟動並觸發 `engine` 的 `connect` 事件
- **THEN** 系統不會執行任何 `PRAGMA` 指令，並能成功建立連線。

#### Scenario: 啟動 SQLite 資料庫連線
- **WHEN** 系統以 SQLite 的設定啟動並觸發 `engine` 的 `connect` 事件
- **THEN** 系統成功執行針對 SQLite 的 `PRAGMA journal_mode=WAL` 等優化指令。

#### Scenario: 執行自動化測試 (Test Suite)
- **WHEN** 系統執行基於 pytest 的測試案例 (如 `test_test_run_item_update_without_snapshot`)
- **THEN** 測試準備環境的建表與資料庫設定指令，不會包含無條件寫死的 `PRAGMA` 語句，並能安全地跨資料庫方言執行。
