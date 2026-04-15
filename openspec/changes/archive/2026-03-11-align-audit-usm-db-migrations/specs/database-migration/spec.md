## ADDED Requirements

### Requirement: Auxiliary databases SHALL use explicit Alembic revision chains
系統 SHALL 為 `audit` 與 `user story map` 資料庫提供各自獨立的 Alembic migration 環境與 baseline revision，並以其各自的 metadata 作為 schema 來源。 The audit database and the user story map database MUST be managed by their own explicit revision chains instead of runtime `create_all`.

#### Scenario: 升級 audit 資料庫
- **WHEN** 系統執行 auxiliary database migration 流程並指定 `audit` 目標
- **THEN** 只會套用 `audit` 的 Alembic revisions 到 `audit` 資料庫，且不會混用主庫或 USM 的 metadata

#### Scenario: 升級 USM 資料庫
- **WHEN** 系統執行 auxiliary database migration 流程並指定 `usm` 目標
- **THEN** 只會套用 `usm` 的 Alembic revisions 到 `user story map` 資料庫，且不會混用主庫或 audit 的 metadata

### Requirement: Legacy auxiliary databases SHALL require explicit validation before adoption
系統 SHALL 在 `audit` 或 `usm` 資料庫缺少有效 Alembic version 時，先比較 live schema 與 baseline metadata，只有在完全一致時才允許 adoption。 The system MUST reject automatic stamping when schema differences are detected.

#### Scenario: 安全納管既有 audit 資料庫
- **WHEN** 管理者執行 `python3 database_init.py --adopt-legacy-audit-db`，且現有 `audit` schema 與 baseline 完全一致
- **THEN** 系統先完成驗證，再寫入 `audit` 資料庫的 baseline revision，且不重建既有表格

#### Scenario: 拒絕納管不一致的 USM 資料庫
- **WHEN** 管理者執行 `python3 database_init.py --adopt-legacy-usm-db`，但 live USM schema 與 baseline 有差異
- **THEN** 系統拒絕 adoption，列出 schema diff，且不寫入任何 Alembic version

### Requirement: Bootstrap SHALL fail fast on unmanaged auxiliary legacy databases
系統啟動流程 SHALL 在偵測到 `audit` 或 `usm` 為既有但未納入 Alembic 管理的資料庫時立即中止，並提示對應的 validation/adoption 指令。 The bootstrap flow MUST NOT repair or mutate these schemas implicitly at runtime.

#### Scenario: 啟動時遇到未納管 audit 資料庫
- **WHEN** 執行 `./start.sh` 或 `python3 database_init.py`，且 `audit` 資料庫已有應用表但沒有有效 Alembic version
- **THEN** 啟動流程中止，並提示先執行 `--validate-legacy-audit-db` / `--adopt-legacy-audit-db`

#### Scenario: 啟動時遇到未納管 USM 資料庫
- **WHEN** 執行 `./start.sh` 或 `python3 database_init.py`，且 `usm` 資料庫已有應用表但沒有有效 Alembic version
- **THEN** 啟動流程中止，並提示先執行 `--validate-legacy-usm-db` / `--adopt-legacy-usm-db`
