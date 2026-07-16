## Why

SQLite → MySQL 8.0 正式演練揭露五項跨引擎落差：Automation Hub background sync 產生 MySQL 不支援的 `NULLS FIRST`、刻意過濾孤兒歷史列卻被 row-count gate 判定失敗、legacy attachment 欄位與 functional index 反射產生誤導警告，以及六組重複單欄索引。這些問題會讓 background sync 持續失敗或讓可解釋的資料清理阻斷 cutover，必須在正式切換前收斂。

## What Changes

- 將 pending automation runs 的 NULL-first 排序改成跨 SQLite / MySQL / PostgreSQL 可編譯且語意一致的 `CASE` 排序。
- 搬移工具將刻意過濾的孤兒列記錄為 structured repair / filtered rows，row-count 以 `source_rows - filtered_rows` 作為 expected target；任何其他未解釋落差仍失敗。
- 將 `test_cases.attachment_count` / `has_attachments` 視為已知 legacy source-only computed 欄位，在 summary 明確列出，但不再報未知 schema drift warning。
- 只抑制 SQLite functional-index reflection 的特定 SQLAlchemy warning；target index 仍由 Alembic head 建立與驗證。
- 新增 migration 移除六個與 custom indexes 重複的 auto-named indexes，並從 models 移除相同欄位的 `index=True`；不修改已發布的 initial migration。
- 更新 MySQL migration runbook，說明 filtered-row、known source-only fields、historical duplicate-index warning 與最終 schema 驗證。

## Capabilities

### New Capabilities

無。

### Modified Capabilities

- `automation-hub-run-orchestration`: 非終態 run 的背景同步排序 SHALL 在所有支援 DB 引擎可執行，並維持未同步列優先。
- `database-cutover-readiness`: row-count verification SHALL 區分可稽核的刻意 filtered rows 與非預期資料遺失。
- `schema-engine-portability`: Alembic head 與 model metadata SHALL 不保留語意相同的重複單欄 indexes，known legacy source-only 欄位與 functional-index reflection SHALL 有明確處理。

## Impact

- Runtime：Automation Hub background sync query。
- 搬移：`scripts/db_cross_migrate.py` JSON summary、row-count gate 與 reflection logging。
- Schema：main DB 新增非破壞性 Alembic revision，只移除冗餘 indexes；不刪除欄位或資料。
- 相容性：SQLite、MySQL 8、PostgreSQL 16 都需通過；既有 published migrations 不修改。
- Rollback：downgrade 會重建六個 auto-named indexes；runtime / 搬移修正可隨程式版本回退，來源資料不受影響。
