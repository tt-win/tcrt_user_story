## Why

目前 MySQL / PostgreSQL bootstrap 即使目標 database 已存在，仍先以 app 帳號連線管理 database 進行存在性檢查。正式環境常用的最小權限帳號僅能存取指定的 main、audit、usm databases，因此一鍵 cutover 會在 schema bootstrap 階段失敗，與既有權限文件及端到端搬移契約不一致。

## What Changes

- bootstrap 先直接連線已指定的目標 database；連線成功時直接進入 Alembic migration，不要求管理 database 權限。
- 只有目標 database 明確不存在時，才沿用既有管理 database 連線與自動建庫行為。
- 補上受限 MySQL app 帳號的 regression coverage，並以三庫 SQLite → MySQL 搬移、row count、revision 與 health check 驗證完整 cutover。
- 新增正式 migration runbook，從已知來源與目標 DB 位址開始，不把 disposable Docker 建置列入正式步驟。
- 相容性：既有可自動建庫的高權限帳號行為維持不變；不涉及 schema migration。回復可還原舊版 bootstrap 邏輯並將 app 四組 DB URL 切回來源。

## Capabilities

### New Capabilities

無。

### Modified Capabilities

- `system-bootstrap`: 已存在的 server database 可由僅具該 database 權限的 app 帳號直接 bootstrap，不須額外存取管理 database。
- `database-cutover-readiness`: 指定 `--target-env-file` 的端到端搬移可使用已建立目標 databases 的最小權限帳號完成 schema、資料、驗證及 health check。

## Impact

- 程式：`app/db_migrations.py` 的 server database existence / creation 路徑。
- 測試：`app/testsuite/test_database_init.py` 與 MySQL cutover 實跑驗證。
- 文件：新增正式 SQLite → MySQL migration 與切換 runbook。
- 風險：存在性錯誤分類若錯誤，可能將一般連線失敗誤判為需建庫；實作必須只在明確 missing-database error 時嘗試管理連線。
