## Context

TCRT header 固定顯示在所有頁面頂端（`base.html`），其中 `#team-name-badge` 目前是一個純展示的 `<span>`，由各頁面的 JS 透過 `AppUtils.setCurrentTeam()` 設定文字。所有頁面均共用此元件，因此只需修改 `base.html` 與全域 JS 即可影響全部頁面。

目前 team 資訊存在 `localStorage['currentTeam']`（由 `AppUtils` 管理），包含 `id`、`name` 等欄位，不需任何後端 API 異動。

## Goals / Non-Goals

**Goals**
- Team badge 可點擊，展示同 team 頁面的下拉選單
- 選單清單由單一 config 管理（single source of truth）
- 當前頁面在選單中以 active 狀態標示
- 支援 i18n 與 Automation Hub 入口開關
- 往後新增 team-scoped 頁面只需在 config 新增一筆記錄

**Non-Goals**
- 不改動頁面的側邊欄或主導覽結構
- 不增加後端 API
- 不對非 team-scoped 頁面（login、setup、profile）顯示此選單

## Decisions

### Decision 1：Config-driven page registry

採用 `team-nav-config.js` 作為 team-scoped 頁面清單的 single source of truth。每筆記錄包含：

```js
{ key, iconClass, i18nKey, pathTemplate, condition }
```

`pathTemplate` 支援 `{team_id}` 佔位符（User Story Map 需要）。`condition` 為可選 async function，允許條件性顯示（如 Automation Hub 開關）。

**Alternative considered**: 在 HTML template 以 `{% block %}` 方式讓各頁面自己宣告——缺點是各頁面各自維護，無法保證一致性，也無法在任何頁面看到完整清單。

### Decision 2：Dropdown 實作方式

使用 Bootstrap 5 原生 Dropdown 元件，將 `#team-name-badge` 包在 `<div class="dropdown">` 中，button 設定 `data-bs-toggle="dropdown"`。這樣不需引入額外依賴，且與現有 Bootstrap 5 dropdown 行為（語言切換器等）完全一致。

**Alternative considered**: 自製 popover — 無必要，增加維護負擔。

### Decision 3：Active page 偵測

使用 `window.location.pathname` 比對 `pathTemplate`（將 `{team_id}` 替換為萬用字元後做前綴比對），不依賴伺服器端 render，確保在所有頁面一致運作。

### Decision 4：Badge 無 team 時隱藏

若 `AppUtils.getCurrentTeam()` 回傳 null（如在 login 或 setup 頁面），則整個 dropdown 保持隱藏（維持現有 `d-none` 行為）。

### Decision 5：全域變數存取慣例（bare global，非 `window.*`）

`app.js` 以 `const AppUtils = {...}` 宣告。在 classic script 中，頂層 `const` 會建立跨檔案可存取的 bare global，但**不會**成為 `window` 的屬性，因此 `window.AppUtils` 為 `undefined`。`team-nav.js`/`team-nav-config.js` 內存取 team 必須用 bare `AppUtils`（以 `typeof AppUtils !== 'undefined'` 防護），不可用 `window.AppUtils`。反之，`TeamNav` 本身以 `window.TeamNav = TeamNav` 明確掛上 `window`，讓各頁面既有的 `if (window.TeamNav)` 委派守衛能正確觸發，將 badge 狀態統一交給 `TeamNav.refresh()`。

### Decision 6：非同步渲染需先解析條件再動 DOM

`renderItems` 因 `condition`（Automation Hub 開關）為 async，若在多次 `refresh()`（DOMContentLoaded / teamChanged / i18nReady 連續觸發）下於 `await` 後才 append，會在單次 `innerHTML=''` 清空後彼此交錯 append，造成選單項目重複。解法：先 `await` 解析所有頁面的顯示條件，再以**同步**方式一次清空＋append；並以 generation counter 讓較舊的 render 在偵測到有更新的 render 開始時放棄，避免覆蓋。

## Risks / Trade-offs

- **[Risk] badge 被多處 JS 直接操作** → 現有 4 個檔案直接更新 `#team-name-badge` 和 `#team-name-text`。改為 dropdown 後，這些檔案只需更新文字節點，dropdown 結構不受影響；但若未來有人新增第 5 個直接更新的地方，可能破壞結構。Mitigation：在 `team-nav.js` 初始化時統一監聽 `teamChanged` / `teamCleared` 事件（AppUtils 已觸發），讓 badge 狀態由事件驅動，減少各頁面直接操作。
- **[Risk] User Story Map team_id 不存在** → 若 localStorage 無 team，URL 無法構建。Mitigation：team 不存在時，USM 連結 disable。
- **[Risk] Automation Hub 開關 async 查詢延遲** → dropdown 開啟瞬間可能尚未取得開關狀態。Mitigation：預設顯示（fallback true），與現有邏輯一致；開關載入後動態更新 DOM。

## Migration Plan

1. 修改 `base.html`：team badge span → dropdown wrapper
2. 新增 `team-nav-config.js`（頁面清單）
3. 新增 `team-nav.js`（dropdown 初始化、事件監聽）
4. `base.html` 引入兩個新 JS 檔
5. 三語系 locale 新增 i18n key
6. 無需資料庫 migration，無需 rollback 計畫

Rollback：刪除新增 JS 檔並還原 `base.html` 即可回到純展示狀態。

## Open Questions

- 未來是否需要對部分頁面根據使用者權限隱藏（如非 admin 不顯示某頁面）？目前 config 的 `condition` 欄位可擴充，但此次不實作。
