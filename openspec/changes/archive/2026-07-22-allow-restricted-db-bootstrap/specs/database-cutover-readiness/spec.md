## MODIFIED Requirements

### Requirement: Supported target databases SHALL 有單一指令的端到端搬移 workflow
cutover workflow runner SHALL 提供 `migrate` 模式：以單一指令對指定目標依序完成 guardrails、preflight、目標 schema bootstrap（Alembic）、main/audit/usm 三庫資料搬移、逐表 row count 覆核、目標驗證（verify-target all）與應用健康檢查；任一步驟失敗 SHALL 短路中止並在 run artifacts 保留該步驟日誌。來源資料庫 SHALL 全程唯讀。對已建立的目標 databases，workflow SHALL 可使用只具三個目標 databases schema 與資料權限、但無管理 database 權限的帳號完成。

#### Scenario: SQLite 一鍵搬移至指定 MySQL server
- **WHEN** 操作者以 `--mode migrate --target mysql --source-env-file <source> --target-env-file <target>` 執行 runner，目標為已建立但無應用 tables 的 MySQL databases，且目標帳號無權存取 `mysql` database
- **THEN** workflow 依序完成 schema 建立、三庫資料搬移、逐表覆核、驗證與健康檢查，summary 標記 success 且來源資料庫內容不變

#### Scenario: 搬移中任一庫覆核不符
- **WHEN** 任一庫的任一表 source 與 target row count 不一致
- **THEN** workflow 以失敗結束，summary 的 migration 區段標示不一致的表與兩側列數
