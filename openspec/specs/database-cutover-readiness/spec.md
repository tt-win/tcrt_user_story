# database-cutover-readiness Specification

## Purpose
定義 TCRT 在跨資料庫切換前的 smoke workflow、rehearsal 驗證與 rollback 準備要求。

## Requirements
### Requirement: Supported target databases SHALL 有可執行的 smoke workflow
系統 SHALL 為支援的目標資料庫提供可執行的 smoke workflow。

#### Scenario: MySQL smoke workflow
- **WHEN** 目標資料庫為 MySQL
- **THEN** 系統可執行對應的 smoke workflow

#### Scenario: PostgreSQL smoke workflow
- **WHEN** 目標資料庫為 PostgreSQL
- **THEN** 系統可執行對應的 smoke workflow

### Requirement: Direct DB access regressions SHALL 被工程守門阻擋
系統 SHALL 以 guardrail / boundary 機制阻擋新的 runtime 直接 DB access 回歸。

#### Scenario: 新的 handler 直接建立 session
- **WHEN** 新增程式碼繞過既有資料存取邊界直接建立 runtime session
- **THEN** 工程守門流程應能偵測或阻擋此回歸

### Requirement: Cutover rehearsal SHALL 包含資料驗證與一致性摘要
系統 SHALL 在 cutover rehearsal 中產出資料驗證結果與一致性摘要。

#### Scenario: 執行 cutover rehearsal
- **WHEN** 團隊執行 cutover rehearsal
- **THEN** 系統輸出驗證結果與一致性摘要

### Requirement: Cutover readiness SHALL 定義 rollback 準備
系統 SHALL 在 cutover readiness 文件與流程中定義 rollback 準備。

#### Scenario: Rehearsal 或 smoke 驗證失敗
- **WHEN** rehearsal 或 smoke workflow 失敗
- **THEN** 團隊可依既定 rollback 準備中止切換並回復
