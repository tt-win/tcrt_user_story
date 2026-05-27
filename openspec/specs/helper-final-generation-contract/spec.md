# helper-final-generation-contract Specification

## Purpose
定義 QA AI Agent 從 seed generation、seed review 到 testcase generation 與 commit 的最終契約。

## Requirements
### Requirement: Seed generation MUST use a locked requirement plan and a high-tier model
系統 SHALL 只在 requirement plan 鎖定後，以高階模型產生第一批 seeds。

#### Scenario: Locked plan produces the first seed set
- **WHEN** requirement plan 已鎖定且使用者開始產生 seeds
- **THEN** 系統以鎖定內容產出第一批 seed set

### Requirement: Each seed MUST remain traceable to section and verification-item context
每個 seed SHALL 可追溯到 section 與 verification item。

#### Scenario: Seed references its originating verification item
- **WHEN** 使用者檢視某 seed
- **THEN** 可查到其來源 verification item 與 section context

### Requirement: Seed review MUST support per-seed comments and diff-only refinement
seed review SHALL 支援逐筆評論與局部 refine。

#### Scenario: User comment updates only one affected seed
- **WHEN** 使用者只評論單一 seed
- **THEN** refine 結果只影響該 seed 或必要範圍

### Requirement: Seed set MUST support explicit lock before testcase generation
在 testcase generation 前，seed set SHALL 需要顯式 lock。

#### Scenario: Unlocked seed set blocks testcase generation
- **WHEN** seed set 尚未 lock
- **THEN** 系統不允許進行 testcase generation

### Requirement: Seed review MUST support explicit include or exclude decisions for downstream generation
系統 SHALL 支援使用者明確包含或排除特定 seeds。

#### Scenario: Excluded seed is not expanded into a testcase draft
- **WHEN** 某 seed 被標記為 exclude
- **THEN** 它不會被展開為 testcase draft

### Requirement: Testcase generation MUST use locked seeds and a lower-tier model
testcase generation SHALL 使用已 lock 的 seeds 與較低階模型。

#### Scenario: Locked seeds produce testcase drafts
- **WHEN** 使用者在已 lock 的 seed set 上執行 testcase generation
- **THEN** 系統產生 testcase drafts

### Requirement: Screen 5 MUST support testcase editing and selected-only commit
screen 5 SHALL 支援編輯 testcase drafts，並只提交被選取的有效草稿。

#### Scenario: Only valid selected drafts enter commit
- **WHEN** 使用者提交 screen 5 結果
- **THEN** 只有有效且被勾選的 drafts 會進入 commit

### Requirement: Testcase drafts MUST be superseded when the upstream seed set changes
上游 seed set 改變後，既有 testcase drafts SHALL 被視為過期並重新生成。

#### Scenario: Seed change invalidates existing testcase drafts
- **WHEN** 使用者變更 seed set
- **THEN** 現有 testcase drafts 失效或需重建

### Requirement: Commit execution MUST preserve per-draft outcomes
commit 結果 SHALL 保留每筆 testcase draft 的成功 / 失敗狀態。

#### Scenario: Partial commit retains per-draft status
- **WHEN** commit 部分成功、部分失敗
- **THEN** 系統保留逐筆結果與失敗原因

### Requirement: Screen 4 MUST not support manual seed creation or deletion

The system SHALL preserve screen-4 seed traceability by disallowing manual seed creation or deletion in V3.

#### Scenario: User cannot manually add or delete a seed
- **WHEN** the user reviews the seed list on screen 4
- **THEN** the UI provides comment editing and include/exclude controls, but does not provide manual add-seed or delete-seed actions

### Requirement: Model output MUST carry seed references but MUST NOT assign final IDs

The system SHALL require the testcase-generation model to return testcase body fields together with the originating seed reference, and MUST assign final testcase IDs locally after model output is received.

#### Scenario: Model returns reference keys only
- **WHEN** the testcase-generation model responds
- **THEN** the response contains seed or item references for local merge, and the model does not decide the final testcase numbering

### Requirement: Local numbering MUST use section and verification-item block allocation

The system SHALL assign testcase IDs with the pattern `[ticket_key].[section].[tail]`, where:
- section numbers come from screen-3 section allocation
- the first testcase in a section starts tail allocation at `010`
- each subsequent testcase in the same section increments by `10`
- verification items do not create separate numbering blocks

#### Scenario: Later verification items continue the same sequence
- **WHEN** section `TCG-93178.010` has two verification items and the first item uses tails `010` and `020`
- **THEN** the first seed of the second verification item becomes `TCG-93178.010.030`

#### Scenario: Numbering stays sequential across many generated testcases
- **WHEN** a section already has generated testcase tails through `110`
- **THEN** the next testcase tail becomes `120`

### Requirement: Screen 5 selection MUST be blocked by validation failures

The system SHALL validate testcase drafts before they can be selected for commit or moved to screen 6.

#### Scenario: Invalid draft cannot be selected
- **WHEN** one testcase draft has an empty title, no steps, or no expected results
- **THEN** that draft cannot be selected for commit until the validation issue is fixed

#### Scenario: No valid selections blocks screen-6 progression
- **WHEN** the user has not selected any valid testcase draft
- **THEN** the flow cannot advance to screen 6

### Requirement: Screen 5 MUST not support manual testcase-draft creation or deletion

The system SHALL preserve traceability by disallowing manual testcase-draft add/delete operations in V3.

#### Scenario: User cannot manually add or delete a testcase draft
- **WHEN** the user reviews testcase drafts on screen 5
- **THEN** the UI provides edit and selection controls only, without manual add-draft or delete-draft actions

### Requirement: Final generation contracts MUST be split by responsibility
**Reason**: The new design still separates responsibilities, but the primary contract boundary is now `seed generation -> seed refinement -> testcase generation -> local numbering/commit`, not the prior internal/model/post-merge structure.
**Migration**: Keep internal traceability data, but express the contract around the two explicit model stages and their lock gates.

### Requirement: Runtime MUST downshift batch size when consistency risk is high
**Reason**: Batch downshifting and complexity scoring are not part of the currently requested redesign.
**Migration**: If batching controls are needed later, they can be reintroduced as an operational enhancement without changing the screen flow.

