## Why

主庫已經改成 Alembic 管理與顯式 legacy adoption，但 `audit` 與 `user story map` 兩套資料庫仍在啟動時使用 `create_all`、手動補欄與 SQLite 專屬修補。這讓三套資料庫的治理模式不一致，也會讓既有資料庫的 schema drift 被隱藏，特別是在 MySQL/非 SQLite 環境下風險更高。 We need the auxiliary databases to follow the same explicit migration and adoption workflow as the main database.

## What Changes

- 為 `audit` 與 `user story map` 各自建立獨立的 Alembic migration 環境與 baseline revisions。
- 擴充 migration helper，支援三套資料庫各自的 URL、metadata、baseline 驗證與 legacy adoption。
- 更新 `database_init.py` 與 `start.sh`，在啟動時先檢查並升級 `main`、`audit`、`usm`；遇到未納管 legacy DB 時直接失敗並要求顯式 adoption。
- 移除 `audit` 與 `usm` 啟動路徑中的隱式 schema 變更行為，保留連線初始化與業務層操作。

## Capabilities

### New Capabilities
- `database-migration`: Extend strict Alembic-based migration governance to audit and user story map databases, including validation and explicit legacy adoption.

### Modified Capabilities
- `database-operations`: Auxiliary database bootstrap no longer relies on runtime `create_all` or ad-hoc schema repair.

## Impact

- `app/db_migrations.py`
- `database_init.py`
- `start.sh`
- `app/audit/database.py`
- `app/models/user_story_map_db.py`
- 新增 `alembic_audit/`, `alembic_usm/`, 對應 ini/config 與 baseline revisions
- 測試與操作文件
