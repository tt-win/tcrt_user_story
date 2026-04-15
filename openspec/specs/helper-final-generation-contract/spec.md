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
