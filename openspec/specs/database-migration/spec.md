# database-migration Specification

## Purpose
定義主庫、audit DB 與 USM DB 的 migration、legacy adoption、driver 驗證與 preflight / rehearsal 規則。

## Requirements
### Requirement: Auxiliary databases SHALL use explicit Alembic revision chains
系統 SHALL 為 audit 與 USM 資料庫提供顯式 Alembic revision chains，而非 runtime `create_all`。

#### Scenario: 升級 audit 資料庫
- **WHEN** 執行 audit 目標的 migration
- **THEN** 只套用 audit 專屬 revisions

#### Scenario: 升級 USM 資料庫
- **WHEN** 執行 USM 目標的 migration
- **THEN** 只套用 USM 專屬 revisions

### Requirement: Legacy auxiliary databases SHALL require explicit validation before adoption
未納管的 legacy auxiliary DB SHALL 先完成 schema 驗證，只有一致時才允許 adoption / stamping。

#### Scenario: 安全納管既有 audit 資料庫
- **WHEN** 現有 audit schema 與 baseline 一致
- **THEN** 系統允許 adoption 而不重建表格

#### Scenario: 拒絕納管不一致的 USM 資料庫
- **WHEN** 現有 USM schema 與 baseline 不一致
- **THEN** 系統拒絕 adoption 並輸出 diff

### Requirement: Bootstrap SHALL fail fast on unmanaged auxiliary legacy databases
啟動流程 SHALL 在偵測到未納管 auxiliary DB 時 fail fast，不做隱式修補。

#### Scenario: 啟動時遇到未納管 audit 資料庫
- **WHEN** audit DB 有應用表但沒有有效 Alembic version
- **THEN** 啟動中止並提示 validate / adopt 指令

#### Scenario: 啟動時遇到未納管 USM 資料庫
- **WHEN** USM DB 有應用表但沒有有效 Alembic version
- **THEN** 啟動中止並提示 validate / adopt 指令

### Requirement: 支援的 server database drivers SHALL 被明確宣告與驗證
系統 SHALL 明確宣告並驗證支援的 server database drivers 與 driver mapping。

#### Scenario: MySQL driver 缺失
- **WHEN** 目標設定要求 MySQL 但缺少對應 driver
- **THEN** migration / preflight 明確失敗

#### Scenario: PostgreSQL driver 映射一致
- **WHEN** 目標設定為 PostgreSQL
- **THEN** 系統使用一致的 driver 映射與驗證邏輯

### Requirement: Migration preflight SHALL 驗證三套資料庫目標
系統 SHALL 在 migration 前驗證主庫、audit 與 USM 三套資料庫的可升級性。

#### Scenario: 三套資料庫都可安全升級
- **WHEN** preflight 驗證三套資料庫皆通過
- **THEN** migration 可進入下一步

### Requirement: Migration verification SHALL 輸出一致性摘要
系統 SHALL 在 rehearsal / verify-target 流程中輸出 migration consistency summary。

#### Scenario: 完成 rehearsal 後輸出摘要
- **WHEN** rehearsal 或 verify-target 完成
- **THEN** 系統輸出一致性摘要供切換判斷

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

