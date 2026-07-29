## MODIFIED Requirements

### Requirement: Test Run Set CRUD and Membership
App-token API SHALL 支援 test run set 的建立、讀取、更新、刪除、archive、membership attach/detach/move、最多 100 個 config 的 batch move/detach，以及 automation suite membership。所有 suite、config 與 case references SHALL 限制在同 team。建立、更新與 membership 變更需要 `test_run:write`；刪除與 archive 為破壞性操作，需要 `test_run:admin`。

系統 SHALL 提供 `POST /api/app/teams/{team_id}/test-run-sets/members/batch-move`。Typed body SHALL 拒絕 extra fields，並包含 1–100 個正整數、去重保序 `config_ids`；必填但可 null 的 `target_set_id`；以及對每個 canonical config 各有一筆、`set_id` 必填可 null 的 `expected_memberships`。缺欄、typo、type/range/extra-field error SHALL 回 422，不得誤當 detach。Body 中 missing/cross-team reference SHALL 回 400 `APP_TOKEN_VALIDATION_ERROR`；missing path resource SHALL 回 404 `APP_TOKEN_RESOURCE_NOT_FOUND`；transaction 內實際 membership 不符 precondition SHALL 回 409 `APP_TOKEN_STATE_CHANGED`。所有失敗在 mutation 前發生且零寫入。Archived Set SHALL 保持既有相容行為，可作為 target。

Batch response SHALL 固定包含 `success=true`、`processed_count`、`moved_count`、`unchanged_count`、`target_set_id`、canonical `config_ids`、`affected_set_ids` 與 `movements[]`。Counts 以 canonical IDs 計算；`affected_set_ids` 僅含實際改變 membership 的 non-null previous/target IDs，sorted unique，全批 no-op 為 `[]`；`movements[]` 以 request 順序回傳 `config_id`、`previous_set_id`、`target_set_id`、`changed`。只重算 `affected_set_ids` 各正好一次。

`/{set_id}/members` exact body SHALL 為 `{"config_ids":[12,13],"expected_memberships":[{"config_id":12,"set_id":null},{"config_id":13,"set_id":null}]}`，且僅允許 expected 與當下狀態均為 unassigned/already-target。Expected source 指向其他 Set SHALL 回 400 `APP_TOKEN_VALIDATION_ERROR` 並要求 batch-move；當下狀態與 expected 不符 SHALL 回 409 `APP_TOKEN_STATE_CHANGED`。單筆 `/move` exact body SHALL 為 `{"target_set_id":7,"expected_source_set_id":5}`，detach SHALL 明確使用 `{"target_set_id":null,"expected_source_set_id":5}`；兩欄必填可 null，typed model SHALL 拒絕 extra fields。Test Run Set create 的 `initial_config_ids` 隱含 expected source 皆為 null；transaction 內任一 config 已 assigned SHALL 回 409 `APP_TOKEN_STATE_CHANGED` 並 rollback 整個 create，不留下空 Set。

Create 與 add-members response SHALL 永遠 additive 包含 `membership_summary`，其 schema 與 batch response 共用 `MembershipMutationSummary`：`success`、`processed_count`、`moved_count`、`unchanged_count`、`target_set_id`、canonical `config_ids`、sorted `affected_set_ids`、ordered `movements[]`。Omitted/empty `initial_config_ids` SHALL 回傳 `target_set_id=<new set id>`、三個 count 均 0 且三個 arrays 均 `[]`；already-target add-members SHALL 計入 unchanged。

#### Scenario: 建立 test run set
- **WHEN** token 具備 `test_run:write` 並建立 test run set
- **THEN** 系統 SHALL 建立 set 並保存 initial config ids 與 automation suite ids
- **AND** initial configs 的 previous/target Set status SHALL 正確重算

#### Scenario: 更新 membership
- **WHEN** token 移動 config 到另一個 test run set
- **THEN** 系統 SHALL 驗證 source 與 target set 屬於同 team
- **AND** response SHALL 反映最新 membership 或 movement summary

#### Scenario: 批次搬移多個 configs
- **WHEN** token 提供多個有效 config ids 與同 team target Set
- **THEN** 系統 SHALL 在單一 transaction 搬移所有 configs
- **AND** response SHALL 區分 moved 與 unchanged
- **AND** `movements[]` SHALL 回傳每個 previous→target mapping
- **AND** 只有實際改變的 previous/target Set status SHALL 各重算一次

#### Scenario: 批次移出成 unassigned
- **WHEN** batch-move 的 `target_set_id` 為 null
- **THEN** 所有有效 configs SHALL 移除 membership
- **AND** 所有 previous Set status SHALL 重算

#### Scenario: Missing nullable target is not detach
- **WHEN** batch 或單筆 move body 遺漏 `target_set_id` 或拼錯欄位
- **THEN** API SHALL 回 422
- **AND** 任何 config SHALL NOT 被 detach

#### Scenario: 批次搬移 validation 失敗零寫入
- **WHEN** 任一 config 或 non-null target Set 不存在或不屬於 team
- **THEN** API SHALL 拒絕整批
- **AND** 所有既有 membership SHALL 保持不變

#### Scenario: 重送相同 batch move 是 no-op
- **WHEN** 所有 configs 已位於 target Set，或都已在 target null 狀態
- **THEN** response SHALL 回 `moved_count=0` 並將其計入 `unchanged_count`
- **AND** 不產生重複 membership
- **AND** `affected_set_ids` SHALL 為 `[]`

#### Scenario: Membership changed after read-back
- **WHEN** request 的 `expected_memberships` 與 transaction 內實際 membership 不符
- **THEN** API SHALL 回 409 `APP_TOKEN_STATE_CHANGED`
- **AND** SHALL NOT 覆寫並行變更

#### Scenario: Add-members cannot implicitly relocate
- **WHEN** `/{set_id}/members` 的任一 config 當下屬於另一個 Set
- **THEN** 若 request 也明示該 source，API SHALL 回 400 `APP_TOKEN_VALIDATION_ERROR`；若與 expected 不符，SHALL 回 409 `APP_TOKEN_STATE_CHANGED`
- **AND** mutation SHALL 零寫入
- **AND** response SHALL 指示使用 explicit batch-move

#### Scenario: Initial membership race rolls back Set creation
- **WHEN** Set create 的任一 `initial_config_ids` 在 transaction 內已歸組
- **THEN** API SHALL 回 409 `APP_TOKEN_STATE_CHANGED`
- **AND** new Set 與所有 membership SHALL NOT 被建立

#### Scenario: 刪除或 archive set
- **WHEN** token 具備 `test_run:admin` 並刪除或 archive test run set
- **THEN** 系統 SHALL 套用既有 cleanup 與 audit 行為

#### Scenario: 只有 write scope 不可刪除 set
- **WHEN** token 只有 `test_run:write` 卻刪除或 archive test run set
- **THEN** 系統 SHALL 回 403 `APP_TOKEN_SCOPE_DENIED`
- **AND** mutation SHALL NOT 執行
