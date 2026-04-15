## 1. Auxiliary Alembic Setup

- [x] 1.1 建立 `audit` 專用 Alembic 環境與 baseline revision (Create dedicated Alembic environment and baseline revision for audit DB)
- [x] 1.2 建立 `usm` 專用 Alembic 環境與 baseline revision (Create dedicated Alembic environment and baseline revision for USM DB)

## 2. Shared Migration Abstraction

- [x] 2.1 抽象化 migration target 定義，支援 `main`、`audit`、`usm` 的 URL、metadata、baseline 與額外允許表 (Refactor migration targets for main, audit, and usm databases)
- [x] 2.2 為 `audit` 與 `usm` 補上 `validate legacy`, `adopt legacy`, `upgrade` 共用流程 (Add shared validate/adopt/upgrade flow for auxiliary databases)

## 3. Bootstrap Integration

- [x] 3.1 更新 `database_init.py`，加入 `--validate-legacy-audit-db`, `--adopt-legacy-audit-db`, `--validate-legacy-usm-db`, `--adopt-legacy-usm-db` 指令 (Extend database_init.py with strict auxiliary adoption commands)
- [x] 3.2 更新啟動 bootstrap，依序檢查並升級 `main`, `audit`, `usm`，遇到未納管 legacy DB 時 fail fast (Update bootstrap to upgrade all managed DBs and fail fast on unmanaged legacy DBs)

## 4. Remove Runtime Schema Mutation

- [x] 4.1 移除 `audit` 初始化流程中的 `create_all` / 手動補欄 schema repair (Remove runtime schema mutation from audit DB initializer)
- [x] 4.2 移除 `usm` 初始化流程中的 `create_all` / SQLite 修表邏輯 (Remove runtime schema mutation from USM DB initializer)

## 5. Verification

- [x] 5.1 補上 auxiliary DB migration/adoption 的自動化測試或 smoke tests (Add automated tests or smoke tests for auxiliary DB migration and adoption)
- [x] 5.2 執行 targeted 與全量驗證，確認 `start.sh`、legacy adoption、pytest 都可正常通過 (Run targeted and full verification for bootstrap and pytest)
