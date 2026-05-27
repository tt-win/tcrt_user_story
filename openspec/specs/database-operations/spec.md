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

### Requirement: 統一的多資料庫設定來源
系統 SHALL 以一致的設定模型解析 `main`、`audit`、`usm` 三套資料庫的 URL 與相關連線設定，且 `USM` SHALL NOT 再是只靠單一環境變數的特例。 Environment variable overrides MAY still exist, but they MUST follow the same resolution contract as the other managed databases.

#### Scenario: 從正式設定載入三套資料庫 URL
- **WHEN** 系統從 `config.yaml` 與環境變數載入資料庫設定
- **THEN** `main`、`audit`、`usm` 都能透過同一套設定結構被解析，且不需要在模組內硬編碼 `.db` 路徑才能運作

#### Scenario: 使用環境變數覆寫 USM 設定
- **WHEN** 管理者提供 `USM_DATABASE_URL` 覆寫設定檔中的 USM 資料庫位址
- **THEN** 系統只覆寫 USM 目標的連線設定，且解析邏輯與 `DATABASE_URL` / `AUDIT_DATABASE_URL` 一致

### Requirement: 跨資料庫的管理與診斷流程
系統 SHALL 對管理 API、同步流程與診斷路徑採用 dialect-aware 或 SQLAlchemy/DBAPI 通用錯誤處理；SQLite 專屬診斷只可在 SQLite 方言下執行。 The system MUST NOT rely on `sqlite3.OperationalError` or unconditional `PRAGMA` diagnostics in shared runtime paths.

#### Scenario: 非 SQLite 環境遇到缺表錯誤
- **WHEN** 管理 API 在 MySQL 或 PostgreSQL 環境讀取統計資料時遇到缺少資料表
- **THEN** 系統透過通用資料庫例外或錯誤訊息辨識缺表狀態，回傳既定 fallback，而不是依賴 `sqlite3.OperationalError`

#### Scenario: 非 SQLite 環境執行同步提交流程
- **WHEN** 測試案例同步流程在非 SQLite 方言下發生提交錯誤
- **THEN** 系統不會執行 SQLite 專屬的 `PRAGMA foreign_key_check`，並改以通用錯誤記錄與 rollback 行為處理

### Requirement: 測試 schema 建立 SHALL 對齊 Alembic revisions
系統 SHALL 在主要 integration/API 測試 fixture 中以 Alembic revision chain 建立 `main`、`audit`、`usm` schema，而不是直接使用 `Base.metadata.create_all()` 建表。 Model-level isolated tests MAY continue to use direct metadata setup only when they do not claim migration coverage.

#### Scenario: 建立主庫測試 fixture
- **WHEN** API 或 service 測試需要建立暫存主庫
- **THEN** fixture 透過主庫 Alembic `upgrade head` 建立 schema，且測試不直接依賴 `Base.metadata.create_all()`

#### Scenario: 建立 auxiliary 資料庫測試 fixture
- **WHEN** 測試需要建立 `audit` 或 `usm` 暫存資料庫
- **THEN** fixture 分別套用對應的 Alembic revision chain，而不是共用主庫 metadata 或直接手建表

