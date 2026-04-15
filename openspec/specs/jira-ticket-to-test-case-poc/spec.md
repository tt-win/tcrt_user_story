# Capability: JIRA Ticket to Test Case PoC

## Purpose

定義目前已上線的 QA AI Agent / Jira-to-testcase 工作流。現行流程不再是舊版 TUI PoC，而是以 TCRT 內的七畫面互動流程、獨立 persistence、session lifecycle 與 telemetry 為核心。

## Requirements

### Requirement: QA AI Agent MUST follow a seven-screen workflow
系統 SHALL 以固定七畫面流程帶使用者完成從載入需求單到建立 testcase 的旅程。

#### Scenario: User advances through the full journey
- **WHEN** 使用者依序完成每個畫面的必要操作
- **THEN** 系統按順序流轉，不回退到舊版 helper flow

### Requirement: New helper MUST use independent UI and storage
新版 helper SHALL 使用獨立 UI 與資料持久化結構，不以 legacy helper session / draft tables 作為主要資料來源。

#### Scenario: New helper persists to dedicated tables
- **WHEN** 使用者建立或編輯 session、plan、seed、testcase draft 或 telemetry
- **THEN** 系統寫入新版 helper 專用資料結構

#### Scenario: Legacy helper entry is hidden at rollout
- **WHEN** 新版 helper 啟用
- **THEN** 舊版 helper 的使用者入口被隱藏或移除

### Requirement: Session display naming uses timestamp labels
helper session 清單與恢復流程 SHALL 使用 ticket-aware、timestamp-based label 呈現。

#### Scenario: Session labels are timestamp-based
- **WHEN** UI 顯示既有 helper sessions
- **THEN** 每筆 session 以 ticket 與時間資訊命名，便於辨識與恢復

### Requirement: Session management APIs for lifecycle control
系統 SHALL 提供 helper session 的恢復、刪除與清理等 lifecycle APIs。

#### Scenario: Client performs lifecycle operations
- **WHEN** 前端對某 session 執行 resume / delete / clear 等操作
- **THEN** 後端提供一致且可預測的 lifecycle 行為

### Requirement: Requirement lock MUST gate screen-4 seed generation
screen 4 的 seed generation SHALL 受 requirement plan lock 控制。

#### Scenario: Unlocked plan cannot open seed generation
- **WHEN** requirement plan 尚未 lock
- **THEN** `開始產生 Test Case 種子` 動作不可用

### Requirement: Seed lock MUST gate screen-5 testcase generation
screen 5 的 testcase generation SHALL 受 seed set lock 控制。

#### Scenario: Seed changes require relock
- **WHEN** 使用者在 screen 4 修改 seed comment、include / exclude 或其他 seed 狀態
- **THEN** 必須重新 lock 後才能產生 testcase drafts

### Requirement: Screen 5 MUST only advance with valid selected testcase drafts
screen 5 SHALL 僅在至少一筆有效且被選取的 testcase draft 存在時，允許進入 screen 6。

#### Scenario: Invalid or empty selection blocks screen 6
- **WHEN** 沒有有效選取項或所有選取項均驗證失敗
- **THEN** 流程停留在 screen 5 並顯示阻擋原因

### Requirement: Screen 6 MUST support existing or new Test Case Set selection
screen 6 SHALL 支援選擇既有 Test Case Set 或建立新的 Test Case Set 作為 commit 目標。

#### Scenario: Exactly one target mode is active
- **WHEN** 使用者位於 screen 6
- **THEN** UI 一次只允許 existing-set 或 new-set 其中一種模式生效

#### Scenario: User creates a new target set
- **WHEN** 使用者選擇建立新 set
- **THEN** helper 建立該 set 並將其作為 commit target

### Requirement: Screen 7 MUST summarize commit results and redirect to the target set
screen 7 SHALL 顯示 commit 結果摘要並導向最終 target set。

#### Scenario: Commit success opens target set context
- **WHEN** testcase drafts 成功提交
- **THEN** 畫面顯示建立數量並導向目標 set

#### Scenario: Partial failure still produces a structured result summary
- **WHEN** 部分 testcase drafts 成功、部分失敗
- **THEN** 畫面仍顯示逐筆結果、失敗原因與 target set 連結

### Requirement: Test Case ID Naming Rules
系統 SHALL 依 section / verification-item block allocation 與既有 TCRT 命名規則產生 testcase 編號，而非由模型直接指派最終 ID。

#### Scenario: Local numbering stays sequential across generated testcases
- **WHEN** 多筆 testcase drafts 自同一批 seeds 產生
- **THEN** 系統以本地編號規則保持 section 內與跨項目的順序一致

### Requirement: Helper workflow SHALL persist stage-level telemetry for analytics
系統 SHALL 持久化 helper 各 stage 的 telemetry，供後續 analytics 查詢。

#### Scenario: Record telemetry when helper stage completes
- **WHEN** helper 某 stage 成功完成
- **THEN** 系統記錄該 stage 的耗時、token 與必要統計

#### Scenario: Record telemetry when helper stage fails
- **WHEN** helper stage 失敗
- **THEN** 系統仍保留可查詢的失敗 telemetry

### Requirement: Helper telemetry SHALL include output cardinality for generation stages
generation 相關 stage 的 telemetry SHALL 記錄輸出數量。

#### Scenario: Store output counts after generation stage
- **WHEN** seed 或 testcase generation 完成
- **THEN** 系統保存輸出筆數供 analytics 與 adoption metrics 使用

### Requirement: Helper telemetry SHALL be backward compatible with existing session APIs
新增 telemetry 與 analytics 不得破壞既有 helper session API。

#### Scenario: Existing helper session operations remain available
- **WHEN** 前端仍使用既有 session list / resume / delete flows
- **THEN** API 契約維持可用

### Requirement: AI provenance and adoption metrics MUST be queryable
系統 SHALL 保留足夠 metadata 來查詢 seeds / testcases 的 AI provenance 與 adoption rates。

#### Scenario: Seed adoption rate is computed from generated versus included seeds
- **WHEN** 使用者只包含部分 generated seeds 進入後續流程
- **THEN** 系統可計算 seed adoption rate

#### Scenario: Testcase adoption rate is computed from generated versus committed selections
- **WHEN** 只提交部分 testcase drafts
- **THEN** 系統可計算 testcase adoption rate

### Requirement: New helper UI MUST follow existing TCRT visual and i18n patterns
新版 helper UI SHALL 沿用既有 `base.html`、TCRT 設計 token、常用元件樣式與 i18n retranslate lifecycle。

#### Scenario: New helper dynamic content remains translatable
- **WHEN** helper 動態建立或更新 plan / seed / testcase 節點
- **THEN** 仍可被既有 `window.i18n.retranslate(...)` 正確翻譯

### Requirement: New helper persistence MUST remain bootstrap- and migration-compatible
新版 helper tables SHALL 受主庫 bootstrap / migration / cross-db migration 流程管理。

#### Scenario: Database bootstrap verifies new helper tables
- **WHEN** 執行 `database_init.py` 或 verify-target
- **THEN** 新版 helper tables 被納入必要驗證範圍

#### Scenario: Cross-database migration copies helper tables without custom handling
- **WHEN** 執行 `scripts/db_cross_migrate.py`
- **THEN** 新版 helper tables 以跨資料庫相容 schema / row format 被遷移
