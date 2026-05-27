# database-cutover-readiness Specification

## Purpose
定義「可無痛切換 DB」所需的工程門檻、靜態守門、smoke workflow、rehearsal 與 rollback 要求，讓資料庫切換 readiness 成為可重複驗證的標準，而不是倚賴口頭判斷。

## Requirements
### Requirement: Supported target databases SHALL 有可執行的 smoke workflow
系統 SHALL 為每一種支援的 server database target 提供可執行且文件化的 smoke workflow，涵蓋 `main`、`audit`、`usm` 三套資料庫的 URL 設定、migration/bootstrap、應用啟動與健康檢查。 The workflow MUST be runnable without modifying application code.

#### Scenario: MySQL smoke workflow
- **WHEN** 開發者依照專案提供的 MySQL smoke workflow 啟動環境並執行 bootstrap
- **THEN** `main`、`audit`、`usm` 三套資料庫都能完成 migration/bootstrap，且應用程式健康檢查可通過

#### Scenario: PostgreSQL smoke workflow
- **WHEN** 開發者依照專案提供的 PostgreSQL smoke workflow 啟動環境並執行 preflight 或 bootstrap
- **THEN** 系統能驗證 PostgreSQL 目標的 driver、URL 與 migration 路徑，且不需要修改程式碼才能完成 smoke

### Requirement: Direct DB access regressions SHALL 被工程守門阻擋
系統 SHALL 提供 pre-merge guardrail，以阻擋新的 runtime direct DB access 進入非受管模組。 The guardrail MUST cover `app/api/`、`app/services/`、`app/auth/`、`scripts/`、`ai/` 等共享執行路徑，並要求允許例外被明確列出。

#### Scenario: 新的 handler 直接建立 session
- **WHEN** 開發者在 API handler 或 service 中新增 `SessionLocal()`、直接 `commit()` 或直接 `execute(text(...))`
- **THEN** 靜態檢查失敗，並指出該存取必須搬移到受管 boundary

#### Scenario: 受管 boundary 模組使用核准的資料存取模式
- **WHEN** 開發者在受管 boundary/infra 模組內實作經核准的 ORM 或 raw SQL 邏輯
- **THEN** guardrail 不會誤判該實作為違規，且例外範圍可被追蹤與審查

### Requirement: Cutover rehearsal SHALL 包含資料驗證與一致性摘要
系統 SHALL 提供 cutover rehearsal 的資料驗證步驟，至少包含重要資料表 row count、必要資料存在性、migration 完成狀態與跨資料庫 target 的驗證摘要。 The rehearsal MUST produce operator-readable results instead of relying on ad-hoc manual SQL checks.

#### Scenario: 執行 cutover rehearsal
- **WHEN** 維運人員對目標資料庫執行 rehearsal
- **THEN** 系統或文件輸出重要檢查項目、migration/revision 狀態與關鍵資料驗證結果，使維運人員能確認資料已成功遷移並且 access boundary 已對齊目標資料庫

### Requirement: Cutover readiness SHALL 定義 rollback 準備
系統 SHALL 在 cutover readiness 文件或工具中定義 rollback 前提、回退步驟、必要備份與重新驗證方式。 Rollback guidance MUST 明確對應 `main`、`audit`、`usm` 的 managed migration 與 boundary 流程。

#### Scenario: Rehearsal 或 smoke 驗證失敗
- **WHEN** smoke workflow 或 rehearsal 驗證未通過
- **THEN** 文件或工具明確指出應保留的來源資料庫狀態、回退步驟與重新驗證方式，避免在不一致狀態下繼續切換
