# test-case-management-ui Specification

## Purpose
定義 Test Case Management UI 的主要行為，包括資產分離、預設 Set 顯示與切換、共享過濾連結、impact warning 與 section navigation 穩定性。

## Requirements
### Requirement: Dedicated assets for the Test Case Management page
系統 SHALL 以獨立靜態資產載入 Test Case Management UI，而非在模板內嵌大量 CSS / JS。

#### Scenario: Page loads with external assets
- **WHEN** 使用者開啟 Test Case Management 頁面
- **THEN** 頁面使用專屬 CSS / JS 並正常渲染

### Requirement: Functional parity after asset refactor
資產分離後 SHALL 維持既有搜尋、過濾、編輯、附件與批次操作能力。

#### Scenario: Core flows remain available
- **WHEN** 使用者執行既有核心流程
- **THEN** 功能行為與改版前一致

### Requirement: Display default Test Case Set indicator
UI SHALL 清楚標示目前 team 的 default Test Case Set。

#### Scenario: Default set is visually marked
- **WHEN** 使用者查看 Test Case Set 清單
- **THEN** default set 以明確 badge 或 icon 呈現

### Requirement: Admin UI for changing default set
系統 SHALL 允許管理者在 UI 中將某個 set 設為 default，並說明不會搬動既有 test cases。

#### Scenario: Admin clicks set as default
- **WHEN** 管理者對非 default set 執行 `Set as Default`
- **THEN** UI 顯示確認訊息，確認後更新 default 狀態

#### Scenario: Non-admin cannot change default
- **WHEN** 非管理者查看同一畫面
- **THEN** 不可見或不可使用 `Set as Default` 操作

### Requirement: Impact warning before deleting Test Case Set
刪除 Test Case Set 前 SHALL 顯示 impact preview 並要求明確確認。

#### Scenario: Delete set confirmation shows impacted Test Runs
- **WHEN** 使用者嘗試刪除 Test Case Set
- **THEN** UI 顯示受影響的 Test Runs / items，並在確認前不執行刪除

### Requirement: Impact warning before moving Test Cases across sets
搬移 Test Cases 到其他 set 前 SHALL 顯示 impact preview 並要求明確確認。

#### Scenario: Move confirmation shows impacted Test Runs
- **WHEN** 使用者送出跨 set 搬移
- **THEN** UI 顯示受影響的 Test Runs / items，並在確認前不執行搬移

#### Scenario: Cancel after warning keeps data unchanged
- **WHEN** 使用者在 warning dialog 取消
- **THEN** 不套用搬移且不移除任何 Test Run items

### Requirement: Shareable filtered view link for Test Case Set
系統 SHALL 提供 `產生連結` 功能，以目前頁面的 set 與篩選條件建立可分享連結。

#### Scenario: Generate link from current filter state
- **WHEN** 使用者設定篩選條件後產生連結
- **THEN** 系統顯示可複製 URL，且可重建同一篩選結果

### Requirement: Auth-gated deep link restoration for shared filters
共享連結 SHALL 經過既有登入與授權流程，登入後回到原始連結。

#### Scenario: Unauthenticated visitor is redirected through login
- **WHEN** 未登入使用者開啟共享連結
- **THEN** 先導向登入，登入後回到原連結並套用篩選

#### Scenario: Authenticated visitor opens shared link directly
- **WHEN** 已登入且有權限的使用者開啟共享連結
- **THEN** 系統直接載入指定 set 與篩選條件

### Requirement: Reliable section navigation in Test Case Management
系統 SHALL 穩定地把右側 section 點擊導向對應區塊，處理 lazy render 與 collapsed section。

#### Scenario: Navigate to section with lazy-loaded test cases
- **WHEN** 使用者點擊尚未完成渲染的 section
- **THEN** 系統等待目標元素出現後再滾動，並在合理時間內完成

#### Scenario: Navigate to collapsed section
- **WHEN** 目標 section 處於收合狀態
- **THEN** 系統自動展開必要父層後導向該位置

### Requirement: Event delegation for section click handling
section click handling SHALL 使用事件委派，以避免重複綁定與記憶體洩漏。

#### Scenario: Dynamically added sections support click
- **WHEN** 動態新增 section item
- **THEN** 不需重新綁定即可支援點擊導航
