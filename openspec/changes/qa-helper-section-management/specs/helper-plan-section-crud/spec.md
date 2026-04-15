## ADDED Requirements

### Requirement: User MUST be able to add a new empty section to the requirement plan
系統 SHALL 在 Screen 3 section rail 提供「新增區段」按鈕，點擊後建立一個空白 section 並加入 plan 尾端。新增的 section SHALL 符合既有 `PlanSection` data model，包含以下初始值：
- `section_key`: `manual_{uuid}` 格式，前端以 `crypto.randomUUID()` 產生
- `section_id`: 依 `section_start_number` 與目前 section 數量自動計算
- `section_title`: 空字串（使用者自行填入）
- `given`, `when`, `then`: 空陣列
- `verification_items`: 包含一個空白 verification item（category 預設為「功能驗證」，含一個空白 check condition）

新增後系統 SHALL 自動選中該 section 並將焦點移至標題輸入欄位。

#### Scenario: Add an empty section when plan is in draft status
- **WHEN** plan 處於 draft 狀態，使用者點擊「新增區段」按鈕
- **THEN** 系統在 section 列表尾端新增一個空白 section，自動編排 section_id，並選中該 section 進入編輯模式

#### Scenario: Add section button is disabled when plan is locked
- **WHEN** plan 處於 locked 狀態
- **THEN** 「新增區段」按鈕 SHALL 顯示為 disabled 狀態，不可點擊

#### Scenario: Newly added section triggers autosave
- **WHEN** 使用者新增一個空白 section
- **THEN** 系統 SHALL 標記 plan 為 dirty，觸發 autosave timer

### Requirement: User MUST be able to multi-select and batch delete sections
系統 SHALL 在 Screen 3 section rail 的每個 section 項目前提供 checkbox，使用者可勾選多個 sections。勾選後 rail 頂部 SHALL 顯示 batch action bar，內含已選數量與「刪除選取區段」按鈕。

#### Scenario: Select multiple sections via checkboxes
- **WHEN** 使用者在 section rail 中勾選兩個以上 section 的 checkbox
- **THEN** batch action bar 顯示「已選取 N 個區段」文字與「刪除選取區段」按鈕

#### Scenario: Deselect all sections hides batch action bar
- **WHEN** 使用者取消所有 checkbox 勾選
- **THEN** batch action bar 隱藏

#### Scenario: Batch delete selected sections with confirmation
- **WHEN** 使用者點擊「刪除選取區段」按鈕
- **THEN** 系統彈出確認對話框，列出即將刪除的 section 標題清單
- **WHEN** 使用者確認刪除
- **THEN** 系統移除所有勾選的 sections（含其 verification items 與 check conditions），剩餘 sections 的 section_id 重新編號，batch action bar 隱藏，plan 標記為 dirty 並觸發 autosave

#### Scenario: Cancel batch delete
- **WHEN** 使用者在確認對話框中取消
- **THEN** 所有 sections 保持不變，checkbox 勾選狀態維持

#### Scenario: Batch delete when currently selected section is among deleted
- **WHEN** 使用者目前選中的 section（正在編輯的）也在被刪除的列表中
- **THEN** 刪除完成後系統 SHALL 自動選中剩餘 sections 中的第一個；若無剩餘 section 則清空編輯區

#### Scenario: Checkboxes are hidden when plan is locked
- **WHEN** plan 處於 locked 狀態
- **THEN** section rail 的 checkboxes SHALL 不顯示，batch delete 功能不可用

### Requirement: Section ID MUST be recomputed after any section addition or deletion
系統 SHALL 在每次新增或刪除 section 後，呼叫 `recomputeRequirementSectionIds()` 重新計算所有 sections 的 `section_id`，確保 section_id 連續無間斷，起始值依 `section_start_number` 設定，間隔固定為 10。

#### Scenario: Section IDs are contiguous after deletion
- **WHEN** plan 有 sections 010, 020, 030，使用者刪除 020
- **THEN** 剩餘 sections 的 section_id 重新編為 010, 020

#### Scenario: Section IDs are contiguous after addition
- **WHEN** plan 有 sections 010, 020，使用者新增一個 section
- **THEN** 三個 sections 的 section_id 編為 010, 020, 030

### Requirement: Added sections MUST be fully compatible with downstream seed generation
手動新增的 section 與 planner 自動產出的 section 在 data model 層面 SHALL 完全一致。seed generation 流程 SHALL 不區分 section 的來源（planner 或手動），僅依據 `section_id`、`section_title`、`verification_items` 執行。

#### Scenario: Manual section produces seeds just like planner section
- **WHEN** 使用者手動新增一個 section 並填入 verification items 後鎖定 plan
- **THEN** seed generation 將該 section 視同 planner 產出的 section，正常產出 seeds

### Requirement: User MUST be able to reorder sections via move up and move down buttons
系統 SHALL 在 Screen 3 section rail 的每個 section 項目提供上移（▲）與下移（▼）按鈕。點擊後 SHALL 交換該 section 與相鄰 section 的位置，並呼叫 `recomputeRequirementSectionIds()` 重新編號。移動後 SHALL 維持該 section 為選中狀態。

#### Scenario: Move a section up
- **WHEN** plan 處於 draft 狀態，使用者點擊某 section（非第一個）的上移按鈕
- **THEN** 該 section 與上方相鄰 section 交換位置，所有 section_id 重新編號，該 section 維持選中狀態，plan 標記為 dirty 並觸發 autosave

#### Scenario: Move a section down
- **WHEN** plan 處於 draft 狀態，使用者點擊某 section（非最後一個）的下移按鈕
- **THEN** 該 section 與下方相鄰 section 交換位置，所有 section_id 重新編號，該 section 維持選中狀態，plan 標記為 dirty 並觸發 autosave

#### Scenario: Move up button is disabled for the first section
- **WHEN** section 為列表中的第一個
- **THEN** 上移按鈕 SHALL 顯示為 disabled 狀態，不可點擊

#### Scenario: Move down button is disabled for the last section
- **WHEN** section 為列表中的最後一個
- **THEN** 下移按鈕 SHALL 顯示為 disabled 狀態，不可點擊

#### Scenario: Move buttons are hidden when plan is locked
- **WHEN** plan 處於 locked 狀態
- **THEN** 所有 section 的上移/下移按鈕 SHALL 不顯示

### Requirement: Section ID MUST be recomputed after reordering
系統 SHALL 在每次 section 排序變更後，呼叫 `recomputeRequirementSectionIds()` 重新計算所有 sections 的 `section_id`，確保 section_id 依新排列順序連續編號。

#### Scenario: Section IDs reflect new order after move
- **WHEN** plan 有 sections A(010), B(020), C(030)，使用者將 C 上移一位
- **THEN** sections 順序變為 A, C, B，section_id 重新編為 A(010), C(020), B(030)
