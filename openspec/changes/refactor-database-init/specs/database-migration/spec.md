## ADDED Requirements

### Requirement: 使用 Alembic 進行資料庫遷移
系統 SHALL 使用 Alembic 作為管理資料庫結構變更的唯一標準工具，不再使用手寫的 SQLite 遷移腳本。

#### Scenario: 執行資料庫遷移
- **WHEN** 系統啟動或管理者手動執行 `alembic upgrade head`
- **THEN** Alembic 會根據 `alembic/versions` 中的腳本，將資料庫更新到最新版本，且此過程必須能相容於環境變數指定的資料庫方言 (如 MySQL 或 SQLite)。

### Requirement: 支援 SQLite 的 Batch 遷移模式
Alembic 配置 SHALL 啟動 `render_as_batch=True`，以自動處理 SQLite 不支援的 `ALTER TABLE` 操作。

#### Scenario: 在 SQLite 上修改現有資料表欄位
- **WHEN** 開發者產生一個涉及修改欄位 (例如 DROP COLUMN) 的 Alembic 遷移腳本，並在 SQLite 環境下執行
- **THEN** Alembic 自動使用 Batch 模式 (建立暫存表、搬移資料、重命名)，不拋出 SQLite 的語法錯誤。
