## ADDED Requirements

### Requirement: Header Action Button Layout and Color Logic

系統 SHALL 對所有頁面 header 操作區（Jinja `page_specific_actions` 區塊）的按鈕，套用單一規範的尺寸、語意化顏色與排列順序。任何新增頁面 SHALL 遵循此規範放置其 header 按鈕。

#### Scenario: Consistent button size

- **WHEN** 任一頁面在 header 操作區渲染按鈕（含連結型 `<a class="btn">`、`<button>` 與 dropdown toggle）
- **THEN** 該按鈕 SHALL 使用 `.btn-sm`
- **AND** 圖示與文字間距 SHALL 使用 `me-1`

#### Scenario: Semantic color palette for action buttons

- **WHEN** header 操作區的「動作型」按鈕依其意圖渲染
- **THEN** 其顏色 SHALL 依語意調色盤對應：主要建立／CTA → `primary`；建設性提交（儲存、開始執行、轉換為產出）→ `success`；停止／終結性操作 → `warning`；次要功能啟動（AI Helper、圖表報表、計算票證、重新執行、匯入工具、數據與記錄選單、組織與系統設定）→ `info`；工具與導覽（重新整理／重新掃描、跳至、返回上層、首頁、橫向設定連結）→ `secondary`
- **AND** 同一語意的動作在不同頁面 SHALL 對應到相同顏色

#### Scenario: Filter and segmented controls are exempt from the action palette

- **WHEN** header 中出現篩選或分段切換控制項（如測試執行狀態篩選、日期區間選擇、團隊篩選）
- **THEN** 該控制項 SHALL 仍套用尺寸規則（`.btn-sm`）
- **AND** 其顏色 MAY 用於編碼狀態或選取（含 `active` 狀態），不受動作型語意調色盤約束

#### Scenario: Navigation cluster ordering and icons

- **WHEN** 頁面提供返回上層與／或首頁導覽
- **THEN** 導覽按鈕 SHALL 群組於 header 操作區最右側、user menu 之前，順序為「返回上層 → 首頁」
- **AND** 返回上層 SHALL 使用 `fa-arrow-left` 圖示
- **AND** 首頁按鈕 SHALL 使用 `fa-home` 圖示、`href="/"` 與 `navigation.backToHome` 文案鍵；header 內 SHALL NOT 使用 `common.home`

#### Scenario: Overall left-to-right arrangement

- **WHEN** 渲染 header 操作區
- **THEN** 排列順序 SHALL 為：頁面動作（依重要性，最重要在前）→ 工具（重新整理）→ Jump-to（若有）→ 導覽群組（返回上層 → 首頁）
- **AND** 執行類頁面 MAY 以 `ms-auto` 將狀態控制（開始／結束／重新執行）置左、報表／工具／導覽置右
