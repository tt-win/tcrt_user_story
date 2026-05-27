## Why

在前一次的重構 (`refactor-db-abstraction`) 中，我們已經成功將業務邏輯 (CRUD、查詢、Upsert) 以及資料庫連線從對 SQLite 的硬依賴中抽離，使其具備了跨資料庫（如 MySQL）的能力。

然而，目前系統的啟動與資料庫初始化機制（特別是 `database_init.py`）仍然包含大量為了解決 SQLite 限制（例如不支援 `ALTER TABLE DROP COLUMN`）而手刻的 Table 重建、資料複製與遷移腳本。這導致：
1. **跨資料庫阻礙**：當使用 MySQL 時，這些手刻的 SQLite 遷移語法會直接報錯，阻止系統啟動。
2. **維護成本高昂**：每次修改 Database Model，都必須手動編寫極度複雜的 Workaround 腳本。

為了解決這個問題並完成跨資料庫支援的「最後一哩路」，我們需要引入標準的資料庫遷移工具（**Alembic**），並重構 `database_init.py` 以及系統的啟動流程 (`start.sh` 等)，讓系統具備標準化、自動化且跨平台的 Schema 管理能力。

## What Changes

- **BREAKING**: 移除 `database_init.py` 中所有手刻的「建暫存表 -> 搬資料 -> 刪舊表 -> 改名」的 SQLite 專屬遷移邏輯。
- 引入 `Alembic` 作為官方的資料庫遷移與版本控制工具。
- 建立初始的 Alembic Migration Script，將現有的 Schema 定義為 Baseline。
- 修改 `database_init.py`：使其不再負責複雜的 Schema 更新，而是負責觸發 Alembic 的 `upgrade head` 指令，或僅處理基礎資料（如 Default Admin 帳號）的寫入。
- 修改系統啟動流程（包含 Dockerfile 或 `start.sh`），確保在啟動 FastAPI 服務前，會先正確執行資料庫遷移。

## Capabilities

### New Capabilities
- `database-migration`: 系統使用 Alembic 管理資料庫結構的變更，並支援跨資料庫的 Schema 升級與降級。

### Modified Capabilities
- `system-bootstrap`: 修改系統啟動時的資料庫檢查與初始化行為，整合自動化的遷移指令。

## Impact

- `database_init.py` (大幅重構)
- 新增 `alembic.ini` 與 `alembic/` 目錄
- `requirements.txt` (新增 `alembic` 套件)
- `start.sh` / 啟動腳本
- 開發者與部署流程（未來修改 Model 需要產出 Alembic revision）
