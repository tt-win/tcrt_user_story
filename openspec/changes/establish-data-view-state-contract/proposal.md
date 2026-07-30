## Why

2026-07-30 實測（本機 9911，Super Admin）顯示資料視圖的狀態處理沒有統一契約，最嚴重的情況是使用者看到一片空白而得不到任何解釋。

**`/test-case-sets` 渲染出空白頁，且根因是靜默的提前返回。** 不論是否帶 `?team_id=1`，實測結果一致：

```
#testCaseSetsContainer.children.length = 0
#emptyState.className                  = "row d-none"
network                                 = 完全沒有發出任何 test-case-set 相關 API 請求
```

追進程式碼後根因明確——`test-case-set-list/main.js:191-195`：

```js
async function loadTestCaseSets() {
  if (!currentTeamId) {
    console.warn('No currentTeamId set, skipping loadTestCaseSets');
    return;                                   // ← 靜默返回，畫面維持初始空白
  }
```

同一檔案中 `#emptyState` 只被引用 3 次（`:485` 取得、`:507` 與 `:512` 加上 `d-none`），**沒有任何 `remove('d-none')`**——空狀態是永遠不會顯示的死碼，不是「未被觸發」。使用者看到約 800px 高的空白，沒有 loading、沒有空狀態、沒有錯誤訊息、沒有下一步。

**需要目標的動作在無選取時仍呈現為可用。** `/organization-management` 右側顯示「請選擇使用者」時：

```
#pm-delete (刪除)      disabled: false
#pm-reset  (重設密碼)  disabled: false
```

兩顆都維持啟用外觀與完整語意色（紅／橘）。實際點擊**不會**造成資料變更——`personnel_management.js:524` 有 `if (!hasAuth() || !state.selected) return;` 的內部 guard——所以這不是資料風險，而是**靜默失敗**：按鈕看起來可用、點下去毫無反應也毫無說明。

**其他一致性缺口**：全站 78 處 `spinner-border`、1 處 skeleton 關鍵字（實際無 skeleton 實作）；原生 `alert()`／`confirm()` 共 **105 處、分佈於 15 個檔案**，最集中的是 `adhoc_test_run.js`（21）、`test-case-section-list.js`（16）、`test-case-cross-set-ops.js`（14）、`adhoc_run_manager.js`（8）、`team-management/app-tokens.js`（7）；這些呼叫阻塞主執行緒且無法套用系統樣式與 i18n 呈現規則。空狀態在 8 個 JS 檔各自實作，樣式與文案不一致。

反面對照是 `/organization-management` 的使用者詳情區：它有結構完整的空狀態（圖示 + 「請選擇使用者」+ 「從清單選擇，或點擊『新增使用者』建立帳號」），是全站最完整的一例，可作為契約的參考基準。

既有 `ui-design-system` 的「Button State Consistency」已規範 disabled 的**呈現**，但未規範**何時**該進入 disabled。本變更以 MODIFIED 補上「需要選取才可執行的動作在無選取時必須 disabled」這條規則。

## What Changes

- 建立新能力 `data-view-states`：任何呈現伺服器資料的**區段** SHALL 呈現 loading／content／empty／error 其中之一，SHALL 不得呈現無狀態的空白區域；部分成功的區段 SHALL 呈現內容並附降級說明。以區段（而非整頁）為單位，是為了與 `personal-dashboard` 既有的 `partial`／`unavailable` 逐 section 降級契約相容。
- **靜默提前返回不算狀態**：載入流程因前置條件不足而結束時，SHALL 呈現說明該前置條件的狀態，SHALL 不僅寫 console。
- **空狀態必須可行動**：空狀態 SHALL 說明為何是空的，並在使用者具備權限時提供下一步入口。
- **錯誤狀態必須可重試**：載入失敗 SHALL 呈現行內錯誤與重試入口，SHALL 不得靜默失敗或只留 console 訊息。
- **載入狀態使用骨架**：呈現既有版面形狀的資料視圖 SHALL 以 skeleton 呈現載入中，取代造成版面塌陷的置中 spinner。
- **選取相依動作的啟用規則**：需要選取目標才可執行的動作，SHALL 在無選取時為 disabled。
- **非阻塞式確認與通知**：確認與通知 SHALL 使用系統內的非阻塞式元件，SHALL 不使用 `window.alert()`／`window.confirm()`。此項涉及 15 個檔案共 105 處呼叫，其中部分是破壞性操作前的唯一確認關卡（例如 `personnel_management.js:525` 的刪除使用者確認），改寫時 SHALL 逐檔驗證確認關卡未被繞過。
- 補上 `app/templates/components/` 的共用 skeleton 與 empty state 元件，供各頁共用。
- 不改變任何資料面、權限判定或 API 契約；不改變既有空狀態的既有文案語意，只統一結構。

## Capabilities

### New Capabilities

- `data-view-states`：資料區段的狀態契約（loading／content／empty／error＋部分成功的降級呈現）、空與錯誤狀態的可行動性、選取相依動作的啟用規則與非阻塞式確認。

### Modified Capabilities

- `ui-design-system`：在「Button State Consistency」補上選取相依動作於無選取時 SHALL disabled 的規則，取代原本僅規範 disabled 呈現、未規範進入條件的表述。

## Impact

- 模板：新增 `app/templates/components/skeleton.html`、`app/templates/components/empty_state.html`；`app/templates/test_case_set_list.html` 等頁面改用共用元件
- 前端：`app/static/js/test-case-set-list/main.js`（靜默 early return 與 `#emptyState` 死碼）、`app/static/js/app.js`（新增非阻塞 confirm／notify）、`app/static/js/organization-management/personnel_management.js`（按鈕 disabled 與刪除確認）、以及其餘 14 個含原生 `alert`／`confirm` 的檔案（完整清單見 `tasks.md` 第 3 節）
- 樣式：`app/static/css/style.css`（skeleton 與 empty state 共用樣式）
- i18n：新增空狀態與錯誤狀態文案，三語系同步
- 測試：`app/testsuite/test_component_spec.py` 補狀態契約檢查；各頁 frontend regression
