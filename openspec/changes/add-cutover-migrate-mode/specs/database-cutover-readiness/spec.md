# database-cutover-readiness Specification

## Purpose
擴充 cutover readiness：在既有 smoke / rehearsal 驗證之上，提供單一指令的端到端資料搬移 workflow。

## ADDED Requirements

### Requirement: Supported target databases SHALL 有單一指令的端到端搬移 workflow
cutover workflow runner SHALL 提供 `migrate` 模式：以單一指令對指定目標依序完成 guardrails、preflight、目標 schema bootstrap（Alembic）、main/audit/usm 三庫資料搬移、逐表 row count 覆核、目標驗證（verify-target all）與應用健康檢查；任一步驟失敗 SHALL 短路中止並在 run artifacts 保留該步驟日誌。來源資料庫 SHALL 全程唯讀。

#### Scenario: SQLite 一鍵搬移至指定 MySQL server
- **WHEN** 操作者以 `--mode migrate --target mysql --target-env-file <path>` 執行 runner，目標為空的 MySQL databases
- **THEN** workflow 依序完成 schema 建立、三庫資料搬移、逐表覆核、驗證與健康檢查，summary 標記 success 且來源資料庫內容不變

#### Scenario: 搬移中任一庫覆核不符
- **WHEN** 任一庫的任一表 source 與 target row count 不一致
- **THEN** workflow 以失敗結束，summary 的 migration 區段標示不一致的表與兩側列數

### Requirement: Migrate 模式 SHALL 對非空目標有明確防呆
workflow SHALL 在 bootstrap 目標 schema 之前偵測目標三庫是否已含業務資料（排除 migration 版控表）；非空且未帶強制旗標 SHALL 中止並列出非空表，帶強制旗標才允許清空重灌。目標與來源解析為同一資料庫 SHALL 直接拒絕執行。

#### Scenario: 目標已有資料且未帶強制旗標
- **WHEN** `--target-env-file` 指向已含業務資料的資料庫且未帶 `--force-reset-target`
- **THEN** workflow 在任何寫入發生前中止，summary 列出非空表清單

#### Scenario: 目標與來源相同
- **WHEN** 目標任一庫解析後與對應來源為同一資料庫
- **THEN** workflow 拒絕執行並說明原因

### Requirement: Migrate 模式 SHALL 輸出切換所需的環境變數摘要
搬移成功後 summary SHALL 含 env_summary 區段，列出 app 切換至目標所需的四組連線設定鍵值（`DATABASE_URL`、`SYNC_DATABASE_URL`、`AUDIT_DATABASE_URL`、`USM_DATABASE_URL`），其中密碼 SHALL 被遮蔽；summary 與日誌 SHALL NOT 含任何明文密碼。

#### Scenario: 搬移完成後查看切換資訊
- **WHEN** migrate 模式成功結束
- **THEN** summary.md 的 Env Summary 段落列出四組遮蔽密碼後的 URL，操作者據此更新 app 環境設定

### Requirement: 資料搬移工具 SHALL 回報逐表 row count 覆核
`db_cross_migrate` 於非 dry-run 搬移完成後 SHALL 對每張搬移表重新計數 source 與 target 列數，並在 JSON summary 提供逐表結果與整體一致性布林值。

#### Scenario: 單獨執行搬移工具
- **WHEN** 操作者直接以 `--json` 執行 db_cross_migrate 完成一個 job
- **THEN** summary 含 row_count_verification 逐表列數與 row_counts_match 欄位
