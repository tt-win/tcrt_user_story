## Context

`base.html` 的 app chrome 是全站唯一的框架來源：固定 header（64px）、固定 footer（52px）、可捲動 `main`，外加兩個獨立的浮動層（語言切換器、AI Assistant FAB）。這個結構是為桌面設計的，18 個頁面的 `page_specific_actions` 都往同一條 flex row 塞按鈕，累積出寬度失控。

實測基準（2026-07-30，`/team-statistics`，Super Admin）：

| 視窗寬 | `.header-toolbar` 右緣 | `document.scrollWidth` | 結果 |
|---|---|---|---|
| 1440 | 視窗內 | 1440 | 8 個控制項擠成一列，勉強可用 |
| 375 | **863px** | 375 | 溢出 488px，不可見且不可捲 |

## Goals / Non-Goals

**Goals**

- 任何視窗寬度下，header toolbar 的每個控制項都可達。
- 登出與返回入口在所有斷點有最低保證。
- 建立 z-index token scale，終止 `!important` 層級競賽。
- 消除 `100vh` 在 iOS Safari 的裁切。

**Non-Goals**

- 不重新設計導覽資訊架構（breadcrumb、常駐導覽列）——那是 `establish-navigation-and-data-legibility` 的範圍。本變更只保證「現有控制項可達」。
- 不改動 `refine-super-admin-dashboard` 已決定的 dashboard 內部佈局與 icon-only quick actions。
- 不調整任何頁面的 `page_specific_actions` 內容組成（哪些按鈕該留、該搬走），只處理容器行為。
- 不引入 CSS 框架或 bundler。

## Decisions

### 1. Toolbar 採「可捲動列 + overflow menu」而非純換行

純 `flex-wrap` 會讓 header 在窄螢幕長高，推擠 `--header-height` 這個被全站 `padding-top` 依賴的常數。改為：主要控制項保留在列上、其餘收進尾端的 overflow（「⋯」）選單，列本身可水平捲動作為 fallback。`--header-height` 維持固定。

### 2. 使用者選單與返回入口 pin 在右側，永不進 overflow

登出是不可失去的逃生出口。使用者選單固定貼右，overflow 觸發鈕插在它左邊，確保無論多窄都在畫面內。

### 3. z-index token scale 用 100 為級距

```
--z-dropdown: 1000;  --z-sticky: 1020;  --z-chrome: 1030;
--z-modal: 1050;     --z-toast: 1060;   --z-assistant: 1070;
```

級距留白讓後續插入不需重排（初版另有 `--z-pagination: 1040`，因分頁列確認為死碼而移除；1040 保留為未來的空位）。所有 `z-index` 宣告改為 `var(--z-*)` 且不得帶 `!important`；lint baseline 記錄尚未收斂者。

### 4. 分頁列是死碼，刪除而非改寫

初版把 `.fixed-pagination-bar` 當成「第四個固定層」並計畫改為 sticky。紅隊審查時查證：該 class 與同段的 `.pagination`／`.page-link` 在 `app/templates` 與 `app/static/js` **零命中**，實際分頁是卡片內的一般按鈕（`#pm-prev`／`#pm-next`）。

這段死碼含 `position: fixed`、`pointer-events: none` 與 `z-index: 1040` / `1039 !important`，正是層級混亂的貢獻者之一。決定直接刪除。教訓一併寫進契約：app chrome 樣式若無任何套用者，移除而非改寫。

### 5. `vh` → `dvh`，保留 `vh` 作為 fallback，且涵蓋 `max-height`

```css
min-height: calc(100vh - var(--header-height) - var(--footer-height));
min-height: calc(100dvh - var(--header-height) - var(--footer-height));
```

不支援 `dvh` 的瀏覽器讀到第一條，支援的覆寫為第二條。

初版只涵蓋 `height`／`min-height`。紅隊查證發現 `automation-hub.css` 有多處 `max-height: calc(100vh - 320px)`、`max-height: 48vh` 等宣告，同樣會在位址列收合時算錯，因此規則擴及 `max-height` 與 `calc()` 形式。

### 6. 窄螢幕隱藏 page subtitle

副標在所有頁面都是功能列舉式文案（例：「管理測試案例，支援搜尋、過濾、編輯和批次操作」），資訊量低。窄螢幕直接 `display: none`，而非壓縮成直排。

## Risks / Trade-offs

- **Overflow menu 降低發現性**：被收起的動作需要多一次點擊。緩解：每頁最多保留 2 個最高頻動作在列上，其餘進 overflow；哪些留下由各頁決定，不在本 spec 硬編。
- **z-index 大規模改寫可能造成回歸**：現況有 `999999` 這類數字，改為 token 後相對關係可能改變。緩解：以 component spec 測試逐項驗證固定層的堆疊順序，並在 browser QA 檢查 modal 開啟時的遮蔽關係。
- **`dvh` 在捲動時會改變高度**，可能造成佈局微跳。緩解：優先用於 `min-height`／`max-height` 這類上下界；需要穩定尺寸的容器改以 `--header-height` 等固定 token 推導，不依視窗高度。
- **與 `refactor-frontend-shared-components` 的時序**：該 change 會往 header 加入「管理」dropdown。若本變更先落地，需在其 Phase 14 完成後重測 toolbar 寬度。

## Migration Plan

1. 先加 token 與 `dvh`（純新增，無行為變更）。
2. 改寫既有 `z-index` 宣告為 token，逐檔驗證堆疊順序。
3. 導入 toolbar overflow 機制，先在 `/team-statistics`（控制項最多）驗證，再套用到 `base.html`。
4. 刪除 `.fixed-pagination-bar`／`.pagination`／`.page-link` 死碼，並掃描其餘無套用者的 chrome class。
5. 補 component spec 與三斷點 browser QA。

無資料庫變更、無 migration、無 API 契約變更。回滾即還原 CSS 與模板。

## Open Questions

- ~~Toolbar overflow 的觸發斷點要以固定 breakpoint（如 `<992px`）還是以容器實際寬度（container query / ResizeObserver）決定？~~ **已決：ResizeObserver + 水平捲動 fallback**（`header-toolbar.js`）。
- 語言切換器目前在 footer 右下。若 `establish-navigation-and-data-legibility` 決定把它移入使用者選單，footer 可整條移除、回收 52px；本變更暫不預設該結果。
