## Why

2026-07-30 以 Super Admin 帳號在本機（port 9911）實測，發現 `base.html` 的 app chrome 在窄螢幕會讓控制項**不可及**，不只是視覺擁擠：

- 375×812 下 `.header-toolbar` 右緣位於 `x = 863px`，超出視窗 488px。因 `.app-header` 是 `position: fixed` 且內容被裁切，`document.scrollWidth` 仍為 375（沒有水平捲軸），代表溢出的部分**既看不到也捲不到**。
- 被截斷的控制項包含「顯示團隊」「重新整理」「團隊管理」「回到首頁」與整個使用者選單。使用者在手機上開統計頁後**無法登出、也無法離開該頁**。
- 同一斷點下，`{% block page_subtitle %}` 被壓成單字寬的直排文字帶掛在畫面左緣。

App chrome 另有三層底部元素互搶空間：`.app-footer`（52px）、語言切換器（`z-index: 1070 !important`）與 AI Assistant FAB。實測時 FAB 遮蔽了「系統狀態」卡片標題與「各團隊 Test Case」卡片的表頭。

全站 z-index 沒有 scale，實測值散佈於 `999999`／`999998`／`9999`／`2050`／`1200`／`1080`／`1075`／`1070`／`1060`／`1050`／`1040`／`1030`，其中 14 處以 `!important` 互相壓制。

此外 `style.css:1193-1216` 的 `.fixed-pagination-bar`／`.pagination`／`.page-link` 整段是**死 CSS**——`rg` 對 `app/templates` 與 `app/static/js` 皆零命中，實際分頁是卡片內的一般按鈕（`organization_management.html:80-81` 的 `#pm-prev`／`#pm-next`）。這段死碼含 `position: fixed`、`pointer-events: none` 與兩個 `z-index !important`，是 z-index 混亂的來源之一。

`.app-main` 與 `body.dashboard-page .app-main` 使用 `height: 100vh` / `min-height: calc(100vh - …)`；`automation-hub.css` 另有多處 `max-height: calc(100vh - 320px)`、`max-height: 48vh`。這些在 iOS Safari 位址列收合時都會裁切內容。

既有 `ui-design-system` 的 token 需求已涵蓋顏色、間距、圓角與「陰影／層級（elevation）」，但實際上沒有任何 z-index token，層級全靠硬編數字競賽。本變更以 MODIFIED 明確把 z-index scale 納入 token 契約，取代原條款中語意含糊的「層級」表述。

## What Changes

- 建立新能力 `app-chrome-layout`，規範 `base.html` 產生的固定框架（header / footer / main / overlay 層）在所有斷點的行為契約。
- **可達性**：header toolbar 在任何視窗寬度下，其全部控制項 SHALL 保持可見或可透過明確的收合機制（overflow menu／可捲動列）觸及；SHALL 不得因 fixed 容器裁切而產生不可達控制項。
- **登出與返回的最低保證**：使用者選單（含登出）與返回上一層的入口 SHALL 在所有斷點可達。
- **視窗單位**：所有依視窗高度的 `height`／`min-height`／`max-height`（含 `calc()`）改為 `vh` fallback + `dvh` 覆寫，消除 iOS Safari 位址列收合時的裁切。
- **overlay 層級**：建立 `--z-*` token scale（dropdown / sticky / chrome / modal / toast / assistant），所有固定與浮動元素 SHALL 引用 token；`z-index` SHALL 不得再以 `!important` 宣告（現況 14 處）。
- **移除死 chrome 樣式**：刪除 `style.css:1193-1216` 的 `.fixed-pagination-bar`／`.pagination`／`.page-link` 死碼（含其 `pointer-events: none` 與 `z-index !important`），而非改寫它。
- **浮動元素不遮蔽互動控制項**：語言切換器與 AI Assistant FAB 不得互相重疊，亦不得遮蔽按鈕、連結或表格列操作。FAB 覆蓋靜態內容仍為允許——`assistant-widget-ui` 與 `system-administration-dashboard` 已明訂其 overlay 行為，本變更不與之衝突。
- **窄螢幕標題區**：page title / subtitle 區塊在窄螢幕 SHALL 有明確的降級規則（副標可隱藏），SHALL 不得產生直排擠壓。
- 不改變任何頁面的資料面、權限或 API 契約；不新增前端 bundler。

## Capabilities

### New Capabilities

- `app-chrome-layout`：`base.html` 固定框架的響應式可達性、視窗單位與 overlay 層級契約。

### Modified Capabilities

- `ui-design-system`：把 z-index scale 明確納入 single source-of-truth design token 的涵蓋範圍，取代原條款中僅以「陰影／層級（elevation）」帶過的表述。

## Impact

- 模板：`app/templates/base.html`
- 樣式：`app/static/css/style.css`（`.app-header`／`.app-footer`／`.app-main`／`#language-switcher`／`:root` token；刪除 `:1193-1216` 死碼）、`app/static/css/index.css`（`100vh`）、`app/static/css/automation-hub.css`（多處 `max-height: NNvh` 與 `calc(100vh - …)`）、`app/static/css/adhoc-test-run-execution.css`、`app/static/css/system-setup-standalone.css`、`app/static/css/assistant-widget.css`（FAB 層級）
- 測試：`app/testsuite/test_component_spec.py` 補 chrome 契約檢查；responsive browser QA（1440 / 768 / 375）
- 與 `refactor-frontend-shared-components` 的協調：該 change 的 SPEC-NAV-001 在 header 新增「管理」dropdown，會增加 toolbar 寬度；本變更的 overflow 機制 SHALL 涵蓋該 dropdown。
