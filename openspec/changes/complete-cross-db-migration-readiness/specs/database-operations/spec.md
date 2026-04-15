## ADDED Requirements

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

### Requirement: 資料庫維運工具 SHALL 支援目標資料庫
系統 SHALL 讓資料維運工具與服務透過設定後的 SQLAlchemy engine/session 操作資料庫，而不是綁定 SQLite 檔案路徑或 `sqlite3.connect()`。 Maintenance utilities MUST be target-aware so they can run against the configured main database.

#### Scenario: 執行 TCG 維護工具
- **WHEN** 維運人員在 MySQL 或 PostgreSQL 環境執行 TCG 相關維護腳本或服務
- **THEN** 工具透過設定解析出的主庫連線進行查詢與更新，而不是假設 `test_case_repo.db` 檔案存在

### Requirement: 測試 schema 建立 SHALL 對齊 Alembic revisions
系統 SHALL 在主要 integration/API 測試 fixture 中以 Alembic revision chain 建立 `main`、`audit`、`usm` schema，而不是直接使用 `Base.metadata.create_all()` 建表。 Model-level isolated tests MAY continue to use direct metadata setup only when they do not claim migration coverage.

#### Scenario: 建立主庫測試 fixture
- **WHEN** API 或 service 測試需要建立暫存主庫
- **THEN** fixture 透過主庫 Alembic `upgrade head` 建立 schema，且測試不直接依賴 `Base.metadata.create_all()`

#### Scenario: 建立 auxiliary 資料庫測試 fixture
- **WHEN** 測試需要建立 `audit` 或 `usm` 暫存資料庫
- **THEN** fixture 分別套用對應的 Alembic revision chain，而不是共用主庫 metadata 或直接手建表
