## Context

全域 AI Assistant widget 由 `app/static/js/assistant-widget.js` 動態注入，樣式集中於 `app/static/css/assistant-widget.css`。面板目前提供 `narrow` 小窗、`medium` 右下角大窗與 `wide` 中央寬版三種模式；`tcrt_assistant_panel_size_mode` 是 canonical preference，`tcrt_assistant_panel_size` 保留為舊版 preference 的相容 mirror。尺寸控制必須讓使用者直接選取目標模式，不再把一個按鈕當成循環切換器。

這是純前端 UX 變更。對話資料、streaming、confirmation、附件、API routing 與權限邊界都不應因面板尺寸變更而改變。wide 的中央 transform 必須在 mobile 規則中重置；每個 mode button 必須有明確的 active indicator、鍵盤語意與即時 i18n label。

## Goals / Non-Goals

**Goals:**

- 在桌面提供約 80vw × 80vh 的 `wide` 面板，水平與垂直置中。
- 保留 `narrow` 390px 小窗與 `medium` 既有 50vw 右下角幾何。
- 在標題列提供三個原生 button，直接選取 `narrow`、`medium` 或 `wide`，並以 `aria-pressed` 標示唯一 active mode。
- 讓尺寸偏好跨頁面與重新載入持續有效；canonical key 優先，舊版 `compact`/`expanded` 值正規化為 `narrow`/`medium`，未知值 fail-closed。
- 讓 wide 模式支援既有訊息、Markdown table/code、歷史清單、confirmation 與附件內容，不改變其資料流程。
- 維持三語系、動態 accessibility label、keyboard controls 與既有 mobile 全螢幕行為；mobile 仍可直接使用三個 mode buttons。
- 在 wide 開啟時以頁面級暗化/模糊 backdrop 突顯中央面板，但不攔截底層 pointer events、不建立 focus trap、不鎖定 body scroll。

**Non-Goals:**

- 不新增後端 endpoint、資料表、migration、conversation 欄位或 SSE event。
- 不改變 Assistant 的 global/team scope、工具權限、confirmation safety 或 streaming lifecycle。
- 不新增會攔截互動的 modal backdrop、focus trap、body scroll lock 或獨立的 mode picker menu；wide 的 backdrop 僅提供視覺暗化/模糊。
- 不把 `medium` 重新定義為中央模式；`medium` 仍留在右下角。

## Decisions

### D1: 使用三個 direct mode buttons，不使用循環狀態機

`panelSizeMode` 的 canonical 有效值固定為 `narrow`、`medium`、`wide`。標題列以三個 `type="button"` 控制代表模式，點擊只套用被點擊的 mode；不保留 `nextSizeMode()`、下一步 icon 或隱藏的 cycle state。每次套用模式時，`medium`/`wide` class 與 `data-assistant-size-mode` 由同一個 setter 更新，避免多個尺寸 class 同時存在；narrow 以沒有 medium/wide class 表示。

每個 button 以 `aria-pressed` 明確標示是否為 active，group 與目前 mode label 同步更新。這讓滑鼠、鍵盤與輔助技術都能直接理解三個選項，而不必推斷下一個狀態。

### D2: wide 以 viewport 中心定位，保留安全邊界

wide 以 `left: 50%`、`top: 50%`、`right: auto`、`bottom: auto` 與 `translate(-50%, -50%)` 定位。寬度使用 `min(80vw, calc(100vw - 32px))`；高度以 80vh/80dvh 為目標，並以 header/footer 高度與 32px 安全邊界作為矮螢幕上限。這保留「中央 80%」的主體意圖，又避免短 viewport 的面板超出固定 chrome。

現有 `.tcrt-assistant-panel.tcrt-assistant-is-open` 會把 transform 設為 `none`，因此 wide 必須提供更高 specificity 的 open 與 closed selector。mobile media query 置於 wide 規則之後，使用 `inset: 0` 覆蓋 desktop anchors，並明確以 `transform: none` reset wide 的 centered transform。

### D3: 使用 canonical preference 並相容舊版 key

讀取時優先使用 `tcrt_assistant_panel_size_mode`：key 不存在時才讀取既有 `tcrt_assistant_panel_size`，將 `compact`→`narrow`、`expanded`→`medium`；canonical key 存在但值無效時直接 fail-closed 為 `narrow`。每次初始化與有效切換都寫回 canonical key，並以 `compact`/`expanded`/`wide` mirror 舊 key，讓舊版讀到新 wide 時安全回退到 compact，而不載入無效 CSS 狀態。

### D4: 由 JS 統一同步 mode label 與 accessibility state

三個 mode button 的 title/aria-label、group label、目前 mode label 與 `aria-pressed` 由 `syncPanelSizeControls()` 統一更新。按鈕不使用 `data-i18n-title` 或 `data-i18n-aria-label`，避免靜態 retranslate 覆蓋動態狀態；`i18nReady` 與 `languageChanged` 後重新同步。三語系提供 `assistant.sizeModeLabel`、`assistant.sizeNarrow`、`assistant.sizeMedium`、`assistant.sizeWide`。

### D5: 背景突顯但保持非 modal 邊界

wide 只改 panel 的外框幾何；`.tcrt-assistant-messages` 維持 flex child、內部垂直捲動，既有 table wrapper/code block overflow 繼續承擔寬內容。wide 面板開啟時，JS 顯示 `.tcrt-assistant-wide-backdrop` 固定元素，置於頁面之上、面板與 FAB 之下；CSS 使用暗色半透明背景與 `backdrop-filter: blur(...)`（瀏覽器不支援 blur 時仍保留暗化 fallback）。backdrop 設為 `aria-hidden="true"`、`pointer-events: none`，不改變 `aria-modal="false"`，不啟用 focus trap 或 body scroll lock，避免把尺寸擴展誤變成阻塞式 modal 或改變底層頁面操作。

### D6: Mobile 維持全螢幕但保留 direct controls

≤575.98px 時三種模式都呈現全螢幕，因此 CSS 對 panel 使用 `inset: 0` 並 reset wide transform；三個原生 mode buttons 仍可操作，讓使用者可以先選好回到 desktop 後要使用的偏好。mobile 選擇不得清除 canonical 或 legacy localStorage preference。

### D7: Closed panel is inert and hidden from assistive technology

The panel is rendered with `aria-hidden="true"` and `inert` while closed. `openPanel()` removes both states before focusing the composer; `closePanel()` restores them before returning focus to the FAB. CSS opacity and pointer-events remain visual behavior only and are not treated as keyboard/accessibility isolation.

## Risks / Trade-offs

- **[Risk] 三個控制項增加 header 密度。** → 使用 compact icon-only buttons、固定 group layout 與目前 mode label；原生 button 保持明確鍵盤 focus 與 `aria-pressed` 語意。
- **[Risk] centered transform 與現有 open/mobile selector 衝突。** → wide open/closed selector 明確覆蓋 transform，mobile selector 明確 reset 所有定位與 transform，並以 CSS regression test 守門。
- **[Risk] 極窄或極矮 viewport 可能無法實現完整 80%。** → 使用 `min()` 安全邊界；≤575.98px 直接沿用 full-screen mobile layout。
- **[Risk] 80vw 讓長段落單行過長。** → 不改動既有 Markdown table wrapper、code overflow 與訊息 bubble wrapping；wide 的目標是增加資訊容量，不引入新的 content renderer。
- **[Risk] backdrop-filter 在部分瀏覽器不可用。** → 以半透明暗色背景作為必要 fallback；模糊只在瀏覽器支援時增強視覺層次。
- **[Risk] localStorage 中存在舊版或損壞值。** → canonical/legacy 讀取與 transition 都經過有效值正規化，未知值 fail-closed 至 narrow。

## Migration Plan

1. 在同一個 frontend/OpenSpec change 內更新 CSS、JS、三語系、focused tests 與 spec delta。
2. 不需資料庫 migration、bootstrap 或 API rollout；部署後新版本優先使用 canonical mode key，並接受既有 compact/expanded preference。
3. 初始化時將舊版 preference 寫回 `tcrt_assistant_panel_size_mode`；每次切換同步維持 legacy mirror。
4. Rollback 時舊版讀到 legacy `wide` 會依舊有的二態讀取邏輯回到 compact；不需清除 localStorage，也不復活任何後端狀態。

## Open Questions

無。direct mode controls、OpenSpec 契約、mobile transform reset、i18n accessibility state 與 right/bottom reset 已固定。
