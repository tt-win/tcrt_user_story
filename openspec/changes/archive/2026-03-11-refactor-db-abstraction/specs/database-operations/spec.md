## ADDED Requirements

### Requirement: 資料庫連線的跨平台相容性
系統 SHALL 在建立資料庫連線時，根據連線方言 (`dialect`) 動態決定是否執行特定資料庫的最佳化指令（如 SQLite 的 `PRAGMA`），以避免非 SQLite 資料庫啟動時發生語法錯誤。

#### Scenario: 啟動非 SQLite 資料庫連線
- **WHEN** 系統以非 SQLite 的設定（如 MySQL URL）啟動並觸發 `engine` 的 `connect` 事件
- **THEN** 系統不會執行任何 `PRAGMA` 指令，並能成功建立連線。

#### Scenario: 啟動 SQLite 資料庫連線
- **WHEN** 系統以 SQLite 的設定啟動並觸發 `engine` 的 `connect` 事件
- **THEN** 系統成功執行針對 SQLite 的 `PRAGMA journal_mode=WAL` 等優化指令。

### Requirement: 跨資料庫的 JSON 陣列查詢
系統 SHALL 提供能相容於多種關聯式資料庫的 JSON 陣列內容查詢方式，取代直接寫死的 SQLite `json_each` 語法。

#### Scenario: 查詢包含特定 Tag 的 Test Case
- **WHEN** 呼叫 `TestCaseRepoService` 中依賴 JSON 查詢的功能（如透過 TCG tag 篩選 test_cases）
- **THEN** 系統透過 SQLAlchemy ORM、Dialect 動態生成或是應用層過濾的方式取得結果，且不產生 SQL 語法錯誤。

### Requirement: 跨資料庫的 Upsert 實作
系統 SHALL 在處理 `tcg_converter.py` 的資料更新時，使用跨資料庫支援的 Upsert 模式或 SQLAlchemy 的原生語法，不再依賴 SQLite 特有的 `INSERT OR REPLACE`。

#### Scenario: 更新 TCG Records
- **WHEN** 系統接收到 TCG 資料匯入，需要對 `tcg_records` 進行「不存在則新增，存在則更新」操作
- **THEN** 系統成功執行資料的 Upsert 操作，且過程不發生 SQL 語法例外。

### Requirement: 移除 SQLite 專屬的模型定義
系統 SHALL 在所有的 SQLAlchemy 模型（Models）定義中，僅使用標準的定義方式，移除如 `sqlite_autoincrement` 等受限於單一資料庫的參數。

#### Scenario: 建立資料表結構
- **WHEN** 系統或 Migration 工具讀取 `database_models.py` 以建立或同步 Table Schema 時
- **THEN** 產生的 DDL 不依賴 SQLite 特有屬性，且能正確在不同關聯式資料庫建立出主鍵與遞增欄位。
