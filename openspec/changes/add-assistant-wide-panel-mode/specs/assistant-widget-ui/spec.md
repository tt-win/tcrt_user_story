## MODIFIED Requirements

### Requirement: 面板尺寸切換

面板 SHALL 在標題列提供三個可直接選取的尺寸按鈕，支援 `narrow`、`medium` 與 `wide` 三種模式。`narrow` 為既有 390px 小窗；`medium` 保留既有右下角大窗，寬度為 `min(50vw, calc(100vw - 40px))`，高度為 `min(80vh, calc(100vh - var(--header-height) - var(--footer-height) - 96px))` 與等價的 `dvh` fallback；`wide` 為桌面中央寬度 `min(80vw, calc(100vw - 32px))`，高度以 `min(80vh, calc(100vh - var(--header-height) - var(--footer-height) - 32px))` 與等價的 `dvh` fallback 為上限。尺寸按鈕 SHALL 使用原生 `button` 鍵盤互動，並以 `aria-pressed` 明確標示唯一 active mode；點擊任一按鈕 MUST 直接套用該按鈕代表的模式，不得依賴循環或隱藏的下一步狀態。

canonical mode SHALL 以 localStorage key `tcrt_assistant_panel_size_mode` 跨頁面保留；有效值為 `narrow`、`medium`、`wide`，未知或損壞值 MUST fail-closed 回到 `narrow`。既有 `tcrt_assistant_panel_size` 的 `compact`/`expanded` 值 MUST 在升級時分別正規化為 `narrow`/`medium`，並可維持 legacy mirror 以避免舊版頁面遺失偏好。`narrow` 與 `medium` MUST 保留右下角定位；`wide` MUST 明確重置 `right`/`bottom`，使用 `left: 50%`、`top: 50%` 與 centered transform。三種模式切換只改變面板 class、位置與尺寸，不得清除或重建對話狀態。

#### Scenario: 關閉面板不可進入鍵盤與輔助技術

- **WHEN** Assistant panel 處於 closed 狀態
- **THEN** panel 使用 `aria-hidden="true"` 與 `inert`（或等價機制）移出 accessibility tree 與 sequential keyboard focus；開啟時解除，關閉時 focus 回到 FAB

#### Scenario: 三個尺寸按鈕直接切換

- **WHEN** 使用者點擊標題列的 narrow、medium 或 wide 按鈕
- **THEN** 面板直接套用被點擊的模式，每個按鈕以 `aria-pressed` 顯示目前唯一 active mode，且不依賴 `narrow → medium → wide` 的循環

#### Scenario: Narrow 模式保留既有幾何

- **WHEN** viewport 寬度大於 575.98px 且 panelSizeMode 為 narrow
- **THEN** 面板維持既有右下角定位、390px 寬度與 header/footer-aware 的既有高度上限

#### Scenario: Medium 模式保留既有 expanded 幾何

- **WHEN** viewport 寬度大於 575.98px 且 panelSizeMode 為 medium
- **THEN** 面板維持右下角定位，寬度為 `min(50vw, calc(100vw - 40px))`，高度為既有 header/footer-aware 的 `min(80vh, calc(100vh - var(--header-height) - var(--footer-height) - 96px))` 與 `dvh` fallback

#### Scenario: Wide 模式置中並擴大資訊區域

- **WHEN** viewport 寬度大於 575.98px 且 panelSizeMode 為 wide
- **THEN** 面板使用約 80vw 寬度與約 80vh/80dvh 高度，水平與垂直置中，並明確不使用 narrow/medium 的 right/bottom 定位

#### Scenario: Wide 模式突顯並保留非 modal 邊界

- **WHEN** 使用者在 viewport 寬度大於 575.98px 時開啟 wide 面板
- **THEN** 頁面背景顯示固定暗化/模糊遮罩，遮罩位於面板下方、標記為 `aria-hidden="true"` 且不攔截底層 pointer events；關閉面板或離開 wide 模式後遮罩不可見

#### Scenario: 尺寸模式跨頁面保留與 legacy migration

- **WHEN** 使用者選擇 medium 或 wide 後導航至另一頁面，或瀏覽器只剩舊版 `compact`/`expanded` preference
- **THEN** 新頁面的助手面板以相同 canonical mode 初始化；舊版值分別初始化為 narrow/medium，其他值初始化為 narrow，且 canonical preference 被寫回

#### Scenario: Mobile 不受 wide 定位影響

- **WHEN** 螢幕寬度 ≤575.98px 且 panelSizeMode 為 wide、medium 或 narrow
- **THEN** 面板維持全螢幕 `inset: 0`、不使用 centered `translate(-50%, -50%)`，且不因 desktop 尺寸規則產生水平捲軸；三個原生尺寸按鈕仍可操作

#### Scenario: 調整尺寸不改變對話狀態

- **WHEN** 使用者在有訊息、串流回覆、待確認卡或附件狀態的對話中切換尺寸
- **THEN** 面板只改變外框尺寸與位置，既有訊息、streaming/confirmation/attachment 狀態與目前回合不得被清除、重建或取消

#### Scenario: 尺寸 label 隨模式與語言同步

- **WHEN** 使用者處於任一尺寸模式，或切換介面語言
- **THEN** mode group label、各尺寸按鈕 title/aria-label、目前 mode 的可見 label 與 `aria-pressed` 狀態使用目前語系同步更新
