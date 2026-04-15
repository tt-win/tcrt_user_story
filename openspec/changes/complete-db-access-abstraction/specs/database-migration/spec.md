## ADDED Requirements

### Requirement: 支援的 server database drivers SHALL 被明確宣告與驗證
系統 SHALL 為支援的 server databases 明確宣告 sync/async driver 組合，並在 migration/bootstrap preflight 階段驗證 driver 是否可用。 The system MUST fail with actionable guidance when a configured target database cannot be initialized because the required drivers are missing or mismatched.

#### Scenario: MySQL driver 缺失
- **WHEN** 管理者以 MySQL URL 執行 migration/bootstrap，但執行環境缺少必要的 MySQL sync 或 async driver
- **THEN** 系統在 preflight 階段即失敗，並指出缺少的 driver 與對應安裝方式

#### Scenario: PostgreSQL driver 映射一致
- **WHEN** 管理者以 PostgreSQL URL 執行 migration/bootstrap
- **THEN** 系統對 async 與 sync engine 使用一致且受支援的 driver 映射，避免不同模組各自推導不同 driver

### Requirement: Migration preflight SHALL 驗證三套資料庫目標
系統 SHALL 提供在正式 cutover 前可重複執行的 preflight/rehearsal 步驟，對 `main`、`audit`、`usm` 分別驗證 URL resolution、driver 可用性、Alembic 狀態、legacy adoption 狀態與 access boundary 對齊情況。 The preflight MUST stop on the first unsafe target and report target-specific remediation.

#### Scenario: 未納管 legacy auxiliary database
- **WHEN** 管理者執行 preflight，而 `audit` 或 `usm` 為既有但未納入 Alembic 管理的資料庫
- **THEN** preflight 明確標示失敗的 target，並提示相對應的 validation/adoption 指令

#### Scenario: 三套資料庫都可安全升級
- **WHEN** 管理者執行 preflight，且三套資料庫的 driver、URL、Alembic 狀態與 access boundary 對齊皆符合要求
- **THEN** 系統回報所有 targets ready，允許後續執行 migration、smoke 與 rehearsal

### Requirement: Migration verification SHALL 輸出一致性摘要
系統 SHALL 在 migration rehearsal、bootstrap 驗證或 target migration 完成後輸出一致性的驗證摘要，至少包含 revision、重要表存在狀態、關鍵資料檢查結果與受管 target 的驗證結論。 Verification output MUST be deterministic enough to support operator review and rollback decisions.

#### Scenario: 完成 rehearsal 後輸出摘要
- **WHEN** 管理者完成某一 target database 的 rehearsal 或 bootstrap 驗證
- **THEN** 系統輸出該 target 的 current revision、required tables 檢查結果與關鍵資料表的一致性資訊
