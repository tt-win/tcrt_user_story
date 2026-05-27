## MODIFIED Requirements

### Requirement: Acceptance Criteria MUST drive section allocation
section 配置 SHALL 由 Acceptance Criteria 驅動，並支援使用者調整起始 section number。此外，使用者 SHALL 可手動新增不對應任何 AC scenario 的 section、批次刪除不需要的 sections、以及調整 section 排列順序。手動新增的 section 使用 `manual_{uuid}` 格式的 `section_key`，與 planner 產出的 `ac.scenario_XXX` 格式區隔。

#### Scenario: User edits the starting section number
- **WHEN** 使用者修改起始 section number
- **THEN** 後續 section 編號依規則重新配置

#### Scenario: User adds a manual section beyond AC-driven sections
- **WHEN** 使用者在 AC 驅動的 sections 之外手動新增 section
- **THEN** 新 section 加入 plan 尾端，section_id 依序編號，section_key 為 `manual_{uuid}` 格式

#### Scenario: User batch-deletes AC-driven sections
- **WHEN** 使用者多選並刪除 planner 自動產出的 sections
- **THEN** 被刪除的 sections 從 plan 中移除，剩餘 sections 的 section_id 重新編號

#### Scenario: User reorders sections
- **WHEN** 使用者調整 section 順序（含 planner 產出與手動新增的 sections）
- **THEN** sections 按新順序排列，section_id 依新順序重新編號

### Requirement: Requirement plan MUST support explicit lock and unlock
系統 SHALL 提供明確 lock / unlock 機制控制後續 seed generation。locked 狀態下 SHALL 禁止新增、刪除與排序 section。

#### Scenario: Locked requirement plan enables seed generation
- **WHEN** requirement plan 被鎖定
- **THEN** 使用者可進入 seed generation

#### Scenario: Unlock disables seed generation
- **WHEN** 使用者解鎖 plan
- **THEN** 需重新確認後才能進入下一階段

#### Scenario: Locked plan prevents section addition and deletion
- **WHEN** requirement plan 處於 locked 狀態
- **THEN** 新增區段按鈕為 disabled，section checkboxes 不顯示，上移/下移按鈕不顯示，section 增刪與排序操作不可用
