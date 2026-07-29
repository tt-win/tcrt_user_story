# test-case-management-ui Delta Specification

## Purpose

定義 Test Case Management 列表中編號／標題直接開啟案例、快速編輯事件隔離、動態列一致性與重複檢視操作移除的行為。

## ADDED Requirements

### Requirement: Direct opening from Test Case list fields

Test Case Management 列表 SHALL 讓每筆資料列的 Test Case Number 與標題主要內容直接開啟該筆案例的既有檢視／編輯 Modal。此行為 MUST 僅套用於資料列內容，不得改變可排序表頭的排序行為。

#### Scenario: Open from Test Case Number
- **WHEN** 使用者啟用某筆資料列的 Test Case Number 主要內容
- **THEN** 系統開啟該筆案例的既有 Test Case Modal

#### Scenario: Open from title
- **WHEN** 使用者啟用某筆資料列的標題主要內容
- **THEN** 系統開啟同一筆案例的既有 Test Case Modal

#### Scenario: Open with keyboard
- **WHEN** 鍵盤使用者聚焦 Test Case Number 或標題主要內容並按 Enter 或 Space
- **THEN** 系統開啟對應案例的既有 Test Case Modal

#### Scenario: Sortable headers remain unchanged
- **WHEN** 使用者啟用 Test Case Number 或標題的表頭
- **THEN** 系統執行既有排序行為
- **AND** 不得開啟任何 Test Case Modal

### Requirement: Quick edit remains distinct from direct opening

Test Case Number 與標題 cell SHALL 保留既有快速編輯能力，並 MUST 將快速編輯 action 與直接開啟 action 隔離。快速編輯的權限與後端授權 SHALL 維持既有契約。

#### Scenario: Quick edit does not open Modal
- **WHEN** 使用者啟用 Test Case Number 或標題 cell 的快速編輯按鈕
- **THEN** 系統只進入該欄位的既有 inline quick edit
- **AND** 不得開啟 Test Case Modal

#### Scenario: Terminal quick-edit paths restore both actions
- **WHEN** 使用者成功儲存、取消快速編輯，或快速編輯儲存失敗
- **THEN** cell 還原可直接開啟案例的主要內容
- **AND** cell 還原可再次使用的快速編輯按鈕

#### Scenario: Quick edit remains discoverable without pointer hover
- **WHEN** 使用者以鍵盤聚焦 cell 內控制項，或裝置不支援 hover
- **THEN** 快速編輯按鈕保持可見且可操作

### Requirement: Consistent interactions for dynamically rendered Test Case rows

分批、lazy 或重新渲染加入列表的 Test Case 資料列 SHALL 具備與初始資料列相同的直接開啟與快速編輯行為，不需逐列重新綁定 listener。

#### Scenario: Lazy-rendered row supports both actions
- **WHEN** 新一批 Test Case 資料列被加入既有列表容器
- **THEN** 新資料列的 Test Case Number 與標題可直接開啟對應案例
- **AND** 新資料列的快速編輯按鈕只進入 inline quick edit

#### Scenario: Reinitialization does not duplicate actions
- **WHEN** 頁面初始化流程再次嘗試綁定列表互動
- **THEN** 單次使用者操作仍只觸發一次對應 action

### Requirement: Remove redundant row view action

當 Test Case Number 與標題可直接開啟案例後，資料列操作區 MUST 不再顯示獨立檢視按鈕。既有複製與刪除操作 SHALL 繼續依目前權限顯示；若兩者都不可用，列表 SHALL 不渲染空的操作欄。

#### Scenario: Editor retains non-view actions
- **GIVEN** 使用者具備複製或刪除權限
- **WHEN** Test Case 列表渲染資料列
- **THEN** 操作區只顯示使用者有權限的複製或刪除操作
- **AND** 不顯示獨立檢視按鈕

#### Scenario: Read-only row has no empty action column
- **GIVEN** 使用者不具備複製與刪除權限
- **WHEN** Test Case 列表渲染表頭與資料列
- **THEN** 系統省略操作欄表頭與對應資料 cell

### Requirement: Preserve existing list-field visual treatment

Test Case Number 與標題的直接開啟控制項 SHALL 保留原本欄位的文字配色與緊湊呈現。主要開啟控制項在 pointer hover 時 MUST NOT 呈現按鈕位移、陰影或外框；既有 cell hover 與快速編輯可見性 SHALL 維持。Test Case Number MUST 使用等寬字體，且快速編輯鉛筆 MUST 固定於既有右側位置並保留內容間距。

#### Scenario: Hover keeps field colors and no button chrome
- **WHEN** 使用者將 pointer 移至 Test Case Number 或標題的主要開啟控制項
- **THEN** Test Case Number 與標題分別維持其未 hover 時的欄位文字配色
- **AND** 主要開啟控制項不位移、不顯示陰影或按鈕外框
- **AND** 使用者仍可看見並操作該 cell 的快速編輯鉛筆

#### Scenario: Number remains fixed-width and pencil does not overlap content
- **WHEN** 系統渲染 Test Case Number 或標題 cell
- **THEN** Test Case Number 使用等寬字體
- **AND** 主要內容為右側鉛筆保留空間
- **AND** 鉛筆固定在 cell 右側既有定位，不覆蓋主要文字

#### Scenario: Pencil remains anchored on its own hover
- **WHEN** 使用者將 pointer 從 cell 主要內容移至快速編輯鉛筆
- **THEN** 鉛筆維持相同的垂直置中與右側定位
- **AND** 不得因按鈕 hover 樣式跳離原先位置

### Requirement: Detail navigation uses keyboard-only focus presentation

Test Case Detail Modal 的「上一個／下一個」控制項，以及使用相同全域標準按鈕樣式的 Detail 導覽控制項，SHALL 只在鍵盤焦點時顯示焦點外框。滑鼠啟用後不得殘留焦點外框或要求使用者點擊空白處才能恢復正常呈現。

#### Scenario: Mouse navigation returns to normal presentation
- **WHEN** 使用者以滑鼠啟用 Test Case Detail Modal 的「上一個」或「下一個」控制項
- **THEN** 導覽完成後控制項不顯示僅因滑鼠焦點殘留的外框
- **AND** 使用者不需要點擊空白處使按鈕恢復正常呈現

#### Scenario: Keyboard navigation retains a visible focus indicator
- **WHEN** 鍵盤使用者聚焦 Test Case Detail Modal 的「上一個」或「下一個」控制項
- **THEN** 控制項保留符合既有 design token 的可見焦點提示

#### Scenario: Test Run Execution detail follows the shared policy
- **WHEN** 使用者以滑鼠或鍵盤啟用 Test Run Execution Detail Modal 的前後筆控制項
- **THEN** 控制項遵循與 Test Case Detail 相同的焦點呈現規則

### Requirement: Repeated Detail navigation maintains stable responsiveness

Test Case Management SHALL 讓同一個 Detail Modal 的重複前後筆切換保持穩定互動成本。系統 MUST NOT 在每次切換時於既有表單或 Markdown 欄位累積重複 listener，且純 Modal 內容更新 MUST NOT 反覆重算背景 Test Case 列表的版面。

#### Scenario: Repeated navigation does not duplicate handlers
- **WHEN** 使用者在同一個 Detail Modal 中連續切換多筆 Test Case
- **THEN** 每個表單 input/change 事件只執行一次既有變更追蹤
- **AND** 每個 Markdown 快捷鍵只執行一次既有格式化動作

#### Scenario: Modal-only refresh leaves the background list alone
- **WHEN** 前後筆切換更新 Detail 欄位、Markdown preview 與導覽按鈕狀態
- **THEN** 系統只更新 Modal 相關內容
- **AND** 不重新渲染或重新量測背景 Test Case 列表容器

### Requirement: Detail header retains its right-aligned navigation controls

Test Case Management 的 Test Case Detail Modal SHALL 將「複製連結／上一個／下一個」控制項置於標頭右上角的同一控制項群組，並讓關閉控制項保持最右側。控制項位置變動不得改變既有 ID、事件綁定、導覽順序或複製連結行為。

#### Scenario: Open detail displays the historical header placement
- **WHEN** 使用者開啟既有 Test Case Detail Modal
- **THEN** 「複製連結／上一個／下一個」顯示在標頭右上角
- **AND** 關閉按鈕顯示在同一群組最右側
- **AND** Modal body 不顯示重複的導覽子工具列

#### Scenario: Header controls retain existing behavior
- **WHEN** 使用者啟用標頭右上角的複製連結、上一個或下一個控制項
- **THEN** 系統沿用既有複製與導覽行為
- **AND** 控制項 ID 與既有 JavaScript 綁定維持不變
