## ADDED Requirements

### Requirement: App Token Test Case Move Impact Preview

App-token API SHALL 提供 `POST /api/app/teams/{team_id}/test-cases/impact-preview/move-test-set`，需要 `test_case:write` 與 `test_run:read`。Typed body SHALL 拒絕 extra fields，包含 1–100 個去重保序 `record_ids` 與正整數 `target_test_set_id`；record id 解析語意 SHALL 與 `batch-operations` 相同。端點 SHALL 在任何業務寫入前驗證 team、target Set 與所有 records，並回傳 `impacted_item_count`、`impacted_test_runs`、`trigger`、`target_test_case_set_id`、canonical `case_ids`、`case_numbers`、`source_test_case_set_ids` 與 `impact_fingerprint`。Fingerprint SHALL 綁定 team、canonical cases 的 Set/Section、target Set、相關 Run scope，以及每個 impacted Run Item 與其 result-history children 的全 persisted-column deletion snapshot digest；同 id 內容更新或新增 item/history SHALL 改變 fingerprint。Response SHALL NOT 暴露 snapshot 內容。

#### Scenario: Preview a batch move with affected Run Items
- **WHEN** token 具備 `test_case:write` 與 `test_run:read` 並預覽把案例搬至其既有 Test Run scope 以外的 Set
- **THEN** response 回傳每個受影響 Test Run 與預估移除 item 數
- **AND** response 回傳可供 mutation 做 optimistic precondition 的 `impact_fingerprint`
- **AND** main/business database 不發生 mutation，但 SHALL 寫入 redacted App Token preview audit

#### Scenario: Preview rejects any missing record atomically
- **WHEN** preview 的 `record_ids` 含不存在或不屬於 team 的案例
- **THEN** API 回 validation error
- **AND** 不回傳可能被誤認為完整的部分 preview

#### Scenario: Preview does not bypass Test Run read scope
- **WHEN** token 只有 `test_case:write` 而沒有 `test_run:read`
- **THEN** API SHALL 回 403 `APP_TOKEN_SCOPE_DENIED`
- **AND** SHALL NOT 回傳 Test Run 名稱或 impact details

### Requirement: Guarded App Token Test Case Set Move

App-token API SHALL 提供 `POST /api/app/teams/{team_id}/test-cases/move-test-set`，需要 `test_case:write` 與 `test_run:read`，body 為 preview body 加上必填 `impact_fingerprint` 與 optional `target_section_id`。Server SHALL 在同一 transaction 內以穩定順序鎖定相關 rows、重算 fingerprint；不符 SHALL 回 409 `APP_TOKEN_IMPACT_CHANGED` 且零寫入。符合時 SHALL 原子更新 Set/Section 與刪除 out-of-scope Run Items。Response SHALL 包含 `success=true`、`processed_count`、`moved_count`、`unchanged_count`、canonical `case_ids`/`case_numbers`、`target_test_case_set_id`、ordered `placements[]` 與 final `cleanup_summary`。每個 placement SHALL 包含 `case_id`、`previous_test_case_set_id`、`previous_section_id`、`target_test_case_set_id`、final `target_section_id` 與 `changed`。已在 target Set 的案例 SHALL 為 unchanged，保留現有 Section 且不 cleanup。

Guarded move 與所有 production Run Item create paths SHALL 共用 config-scope concurrency protocol。MySQL/PostgreSQL SHALL 在 scope validation 前以穩定順序鎖定 TestRunConfig parent rows；SQLite SHALL 在任何 snapshot read 前取得 `BEGIN IMMEDIATE` 或等價跨 process writer serialization。Item create SHALL 在取得鎖後重讀 config scope/case Set 再 insert，guarded move SHALL 在取得鎖後重讀 items/history 再比對 fingerprint。

#### Scenario: Guarded mutation does not bypass Test Run read scope
- **WHEN** token 有 `test_case:write` 但沒有 `test_run:read`
- **THEN** mutation SHALL 回 403 `APP_TOKEN_SCOPE_DENIED`
- **AND** SHALL NOT 移動 case 或回傳 cleanup Run names

#### Scenario: Previewed state changed before mutation
- **WHEN** preview 後任一 canonical case、其 Set/Section、相關 Run scope 或 impacted items 改變
- **THEN** 使用舊 fingerprint 的 mutation SHALL 回 409 `APP_TOKEN_IMPACT_CHANGED`
- **AND** cases、Sections 與 Run Items SHALL 全部保持不變

#### Scenario: Existing impacted item gains execution data
- **WHEN** preview 後同一 item id 的 result、assignee、comment/history 或 attachment metadata 被新增或更新
- **THEN** 舊 fingerprint SHALL 回 409 `APP_TOKEN_IMPACT_CHANGED`
- **AND** SHALL NOT 刪除剛寫入的 execution data

#### Scenario: New impacted item appears after preview
- **WHEN** preview 後相關 Test Run 新增同 case 的 Run Item
- **THEN** transaction 內 parent/item locks 與重查 SHALL 使舊 fingerprint 回 409
- **AND** SHALL NOT 搬移案例或刪除任何 Run Item

#### Scenario: Move wins a concurrent item-create race
- **WHEN** guarded move 先取得 config-scope lock，item create 後等待
- **THEN** move SHALL 完成，create SHALL 在取得鎖後重驗 scope 並拒絕 out-of-scope insert

#### Scenario: Item create wins a concurrent guarded-move race
- **WHEN** item create 先取得 lock 並 insert，guarded move 後等待
- **THEN** move SHALL 重查 deletion snapshot 並回 409 `APP_TOKEN_IMPACT_CHANGED`
- **AND** new Run Item SHALL 保持不變

#### Scenario: Guarded batch move succeeds atomically
- **WHEN** fingerprint 仍符合且所有 canonical records 仍有效
- **THEN** 所有 changed cases SHALL 移至 target root `Unassigned`
- **AND** cleanup SHALL 在同一 transaction 執行並回傳 final summary

#### Scenario: Guarded single move targets a Section
- **WHEN** request 只含一個 case 並提供屬於 target Set 的 `target_section_id`
- **THEN** case SHALL 原子搬到該 target Section

#### Scenario: Legacy generic cross-Set writes are redirected
- **WHEN** App Token generic `PUT` 或 `batch-operations:update_test_set` 要改變 case Set
- **THEN** API SHALL 回 400 `APP_TOKEN_VALIDATION_ERROR` 並指示使用 guarded preview/move endpoint
- **AND** SHALL NOT 執行 partial mutation

## MODIFIED Requirements

### Requirement: Test Case Batch Operations
App-token API SHALL 提供 `POST /api/app/teams/{team_id}/test-cases/batch-operations`，支援 `delete`、`update_priority`、`update_tcg` 與同 Set `update_section`；`update_test_set` 名稱可維持解析相容，但 App Token route SHALL 以 400 `APP_TOKEN_VALIDATION_ERROR` 導向 guarded move endpoint，不執行寫入。`delete` SHALL 要求 `test_case:admin`，其餘可執行操作 SHALL 要求 `test_case:write`。`record_ids` SHALL 接受本地 id、`lark_record_id` 或 test case number。找不到的記錄 SHALL 在非 guarded 操作中逐項回報錯誤而不使整批失敗。

`update_section` SHALL 使用 `update_data.section_id` 且只允許目標 Section 與案例目前 Set 相同。Guarded move SHALL 使用 top-level `target_test_set_id`、`record_ids` 與 `impact_fingerprint`，不再將 `update_data.test_set_id` 文件化為 Agent mutation recipe。

#### Scenario: 批次更新優先級
- **WHEN** token 具備 `test_case:write` 並以 `update_priority` 批次更新多筆案例
- **THEN** 系統 SHALL 更新所有可解析的案例並回報 success/error counts

#### Scenario: 批次刪除需要 admin scope
- **WHEN** token 只有 `test_case:write` 並提交 `delete` 批次操作
- **THEN** 系統 SHALL 回 403 `APP_TOKEN_SCOPE_DENIED` 且不刪除任何案例

#### Scenario: 不支援的操作
- **WHEN** 提交未定義的 operation 名稱
- **THEN** 系統 SHALL 回 400

#### Scenario: 部分記錄不存在
- **WHEN** `record_ids` 混合存在與不存在的記錄
- **THEN** 存在的記錄 SHALL 被處理，且不存在的 SHALL 逐項列於 error messages

#### Scenario: 批次 Section 搬移拒絕 cross-Set target
- **WHEN** `update_section` 的目標 Section 不屬於案例目前 Set
- **THEN** 該案例 SHALL 回報 item-level error 且不改變 Set 或 Section

### Requirement: Test Case Create and Update Operations
App-token API SHALL 支援建立與更新 test case，並沿用本地 test case 管理的驗證規則、default set 規則、section scope 規則與 local-only persistence。外部 app token mutation SHALL 不觸發 Lark 或其他外部 test case sync。

單筆 generic update SHALL 繼續支援非 Set 欄位與同 Set Section 變更。若 request 實際改變 `test_case_set_id`，SHALL 回 400 `APP_TOKEN_VALIDATION_ERROR` 並要求使用 guarded move endpoint；重送相同 Set SHALL 是 no-op 並保留現有 Section。

#### Scenario: 建立 test case
- **WHEN** token 具備 `test_case:write` 並提交有效 test case payload
- **THEN** 系統 SHALL 在指定 team 建立本地 test case
- **AND** 若 payload 未指定 set，系統 SHALL 使用該 team default test case set

#### Scenario: 更新 test case
- **WHEN** token 具備 `test_case:write` 並更新同 team 的 test case
- **THEN** 系統 SHALL 更新本地 DB
- **AND** SHALL NOT 呼叫外部同步 API

#### Scenario: 拒絕跨 team section 或 set
- **WHEN** payload 指向不屬於該 team 的 test case set 或 section
- **THEN** 系統 SHALL 回 400 `APP_TOKEN_VALIDATION_ERROR`
- **AND** mutation SHALL NOT 執行

#### Scenario: Generic update does not bypass guarded move
- **WHEN** update 提供與現有值不同的 `test_case_set_id`
- **THEN** API SHALL 回 400 `APP_TOKEN_VALIDATION_ERROR` 且零寫入
