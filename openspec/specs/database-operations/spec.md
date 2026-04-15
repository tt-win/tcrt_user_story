# database-operations Specification

## Purpose
將資料庫操作從 SQLite-only 實作收斂為可支援多資料庫的 SQLAlchemy / boundary 抽象，並規範維運工具與 shared runtime path。

## Requirements
### Requirement: 資料庫連線的跨平台相容性
系統 SHALL 依資料庫方言動態套用必要設定，例如 SQLite PRAGMA，避免非 SQLite 環境出現語法錯誤。

#### Scenario: 啟動非 SQLite 資料庫連線
- **WHEN** 使用 MySQL 或 PostgreSQL 等非 SQLite 連線
- **THEN** 系統不執行 SQLite 專屬 PRAGMA，且能成功建立連線

#### Scenario: 啟動 SQLite 資料庫連線
- **WHEN** 使用 SQLite 啟動
- **THEN** 系統正確套用 SQLite 最佳化設定

#### Scenario: 非 SQLite 環境執行共享診斷流程
- **WHEN** 執行共享 runtime path 的統計或管理邏輯
- **THEN** 行為不依賴 SQLite-only 寫法

### Requirement: 跨資料庫的 JSON 陣列查詢
系統 SHALL 提供可跨資料庫工作的 JSON / tag 查詢策略，而非寫死 SQLite `json_each`。

#### Scenario: 查詢包含特定 Tag 的 Test Case
- **WHEN** 使用 tag、TCG 或類似條件查詢 test cases
- **THEN** 系統以相容的 ORM / dialect / 應用層策略回傳結果

### Requirement: 移除 SQLite 專屬的模型定義
SQLAlchemy models SHALL 避免依賴 SQLite-only schema 定義。

#### Scenario: 建立資料表結構
- **WHEN** migration 或 schema 建立流程讀取 models
- **THEN** 產生的 DDL 不依賴 SQLite-only 參數

### Requirement: 共享 runtime path 的 raw SQL 與方言行為 SHALL 被集中治理
shared runtime path 若仍需 raw SQL，SHALL 集中在受管 boundary 中治理。

#### Scenario: 非 SQLite 環境執行統計或管理查詢
- **WHEN** runtime 執行跨資料庫統計 / 管理查詢
- **THEN** 方言差異由受管 boundary 統一處理

### Requirement: 資料庫維運工具 SHALL 支援目標資料庫
維護腳本與跨庫工具 SHALL 支援既定 target databases。

#### Scenario: 執行維護腳本
- **WHEN** 執行 migration / repair / maintenance script
- **THEN** 工具使用與目標資料庫相容的存取方式

### Requirement: 測試 schema 建立 SHALL 對齊受管 migration 與 target database
測試環境 schema 建立 SHALL 對齊正式 migration 與 target database 規則。

#### Scenario: 建立跨資料庫 smoke 測試 fixture
- **WHEN** 建立 smoke / regression fixture
- **THEN** schema 建立策略與目標資料庫相容
