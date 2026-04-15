## 1. Driver And Config Hardening

- [x] 1.1 補上 MySQL / PostgreSQL 所需 sync+async drivers 與版本說明 (Add supported MySQL/PostgreSQL sync and async drivers plus version notes)
- [x] 1.2 將 USM 資料庫設定正式納入 `app/config.py` 與 `config.yaml.example` (Add formal USM database config to settings and example config)
- [x] 1.3 統一 `main`、`audit`、`usm` 的 URL normalization 與 PostgreSQL sync driver mapping (Unify URL normalization and PostgreSQL sync driver mapping across all managed databases)

## 2. Runtime And Tooling Cleanup

- [x] 2.1 移除 `app/api/admin.py` 對 `sqlite3.OperationalError` 的依賴，改成方言安全的缺表 fallback (Replace sqlite3-specific admin error handling with dialect-safe missing-table fallback)
- [x] 2.2 將 `app/services/test_case_sync_service.py` 的外鍵診斷改為只在 SQLite 執行或提供通用 fallback (Scope foreign-key diagnostics to SQLite or provide a generic fallback)
- [x] 2.3 重構 `app/services/tcg_converter.py` 與 `scripts/migrate_tcg_format.py`，改用設定導向的 SQLAlchemy 連線 (Refactor TCG maintenance code to use configured SQLAlchemy connections instead of SQLite file paths)

## 3. Migration-Based Test Fixtures

- [x] 3.1 建立可重用的 Alembic test helper，支援 `main`、`audit`、`usm` 暫存資料庫初始化 (Create reusable Alembic test helpers for temporary main/audit/usm databases)
- [x] 3.2 將主要 API/service 測試 fixture 從 `Base.metadata.create_all()` 切換為 migration-based setup (Migrate primary API/service fixtures from `create_all()` to Alembic-based setup)
- [x] 3.3 補 driver mapping、設定解析與 dialect-safe 診斷的回歸測試 (Add regression tests for driver mapping, config resolution, and dialect-safe diagnostics)

## 4. Cutover Readiness Workflow

- [x] 4.1 新增 target-aware preflight，檢查 driver、URL resolution、Alembic 狀態與 legacy adoption 狀態 (Add target-aware preflight for driver, URL resolution, Alembic status, and legacy adoption checks)
- [x] 4.2 為 migration/bootstrap 補 revision、required tables 與關鍵 row count 的驗證摘要輸出 (Add migration/bootstrap verification summaries for revision, required tables, and critical row counts)
- [x] 4.3 補齊 MySQL 與 PostgreSQL 的 smoke / rehearsal 文件或腳本入口 (Add MySQL and PostgreSQL smoke/rehearsal documentation or script entry points)
- [x] 4.4 文件化 rollback 前提、回退步驟與重新驗證方式 (Document rollback prerequisites, rollback steps, and re-verification flow)

## 5. Verification

- [x] 5.1 執行 SQLite 回歸驗證，確認 fixture 重構後既有測試仍可通過 (Run SQLite regression validation after fixture refactor)
- [x] 5.2 執行 MySQL bootstrap / smoke rehearsal，驗證三套資料庫 migration 與健康檢查 (Run MySQL bootstrap and smoke rehearsal for all three managed databases)
- [x] 5.3 執行 PostgreSQL preflight / smoke rehearsal，確認 driver 與 migration 路徑可用 (Run PostgreSQL preflight and smoke rehearsal to validate driver and migration path readiness)
