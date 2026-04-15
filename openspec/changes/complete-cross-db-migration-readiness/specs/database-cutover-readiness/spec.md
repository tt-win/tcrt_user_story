# database-cutover-readiness Specification

## Purpose
定義跨資料庫切換前的 readiness 驗證、smoke rehearsal 與 rollback 準備要求，確保系統在切換到 server database 前有可重複執行的操作標準。

## Requirements
### Requirement: Supported target databases SHALL 有可執行的 smoke workflow
系統 SHALL 為每一種支援的 server database target 提供可執行且文件化的 smoke workflow，涵蓋三套資料庫 URL 設定、migration/bootstrap 與基本健康檢查。 The workflow MUST be runnable by developers locally without modifying application code.

#### Scenario: MySQL smoke workflow
- **WHEN** 開發者依照專案提供的 MySQL smoke workflow 啟動環境並執行 bootstrap
- **THEN** `main`、`audit`、`usm` 三套資料庫都能完成 migration/bootstrap，且應用程式健康檢查可通過

#### Scenario: PostgreSQL smoke workflow
- **WHEN** 開發者依照專案提供的 PostgreSQL smoke workflow 啟動環境並執行 bootstrap 或 preflight
- **THEN** 系統能驗證 PostgreSQL 目標的 driver、URL 與 migration 路徑，且不需要修改程式碼才能啟動 smoke

### Requirement: Cutover rehearsal SHALL 包含資料驗證
系統 SHALL 提供 cutover rehearsal 的資料驗證步驟，至少包含重要資料表 row count、必要資料存在性與 migration 完成狀態。 The rehearsal MUST produce operator-readable results instead of relying on ad-hoc manual SQL checks.

#### Scenario: 執行 cutover rehearsal
- **WHEN** 維運人員對目標資料庫執行 rehearsal
- **THEN** 系統或文件輸出重要表的檢查項目與結果，使維運人員能確認資料已成功遷移到目標資料庫

### Requirement: Cutover readiness SHALL 定義 rollback 準備
系統 SHALL 在 cutover readiness 文件或腳本中定義 rollback 前提、回退步驟與需要保留的備份/驗證資訊。 Rollback guidance MUST be specific to the managed databases and their migration flow.

#### Scenario: Rehearsal 驗證失敗
- **WHEN** smoke 或 rehearsal 驗證未通過
- **THEN** 文件或工具明確指出應保留的來源資料庫狀態、回退步驟與重新驗證方式，避免直接在不一致狀態下切換
