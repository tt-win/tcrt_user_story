## Context

TCRT 的資料視圖幾乎都是「模板放空容器 + JS 抓資料後填入」。這個模式沒有強制任何狀態處理，於是每個頁面各自決定要不要處理 loading／empty／error，結果從「完整的空狀態」（`/organization-management`）到「什麼都不做」（`/test-case-sets`）都有。

`/test-case-sets` 的失敗特別值得記錄：markup 裡**有** `#emptyState`，也就是說當初有人想過空狀態——但全檔沒有任何 `remove('d-none')`，顯示路徑根本不存在。同時 `loadTestCaseSets()` 在 `currentTeamId` 缺失時 `console.warn` 後直接 `return`。兩者疊加的結果是：任何未被明確處理的情況都掉進「維持初始空白」，而且連死碼都無法救援。這不是「忘了做空狀態」，是「狀態機沒有預設分支，且既有分支從未接線」。

## Goals / Non-Goals

**Goals**

- 資料視圖永遠有狀態，空白不再是可能的輸出。
- 空與錯誤狀態可行動（知道原因、知道下一步）。
- 選取相依的破壞性動作不可在無目標時觸發。
- 確認與通知不阻塞主執行緒。

**Non-Goals**

- 不擴大到各頁的資料取得邏輯本身。`/test-case-sets` 的根因已定位於 `test-case-set-list/main.js:191-195` 的靜默提前返回，本變更修正其呈現層與狀態分支；該頁為何取不到 `currentTeamId`（Super Admin 無 team membership vs. team 解析時序）屬該頁自身範圍。
- 不改變既有空狀態的文案語意，只統一結構與涵蓋範圍。
- 不改變 `refine-super-admin-dashboard` 已決定的 dashboard 內部狀態呈現。
- 不引入前端狀態管理函式庫。

## Decisions

### 1. 契約的單位是「區段」而非「頁面」，預設分支是 error 而非 empty

初版把契約寫成「每個視圖落在四態之一」，紅隊審查時與 `openspec/specs/personal-dashboard/spec.md:102,232` 衝突——該 spec 已定義 `partial`／`unavailable` 的**逐 section 降級**（Audit DB 不可用時，活動 section 標 `partial`，Team／assigned section 繼續可用）。整頁單一狀態的模型無法表達這種情形。

改為：契約以區段為單位，區段各自滿足四態；部分成功的區段呈現 content 並附降級說明，而非整段變 error。這與 `personal-dashboard` 相容，也不需要在四態外再發明第五態。

預設分支仍是 error 而非 empty——把「載入失敗」誤呈現為「沒有資料」會讓使用者以為資料被刪了。

### 2. Empty 與「無權限」分開

「這個團隊沒有 test case set」和「你沒有權限看這個團隊的 set」是不同訊息，混為一談會讓使用者用錯誤的方式排除問題。權限不足視為 error 分支的一種具名情況，訊息明確但不洩漏資源是否存在以外的細節。

### 3. Skeleton 只用於形狀已知的視圖

表格列、卡片列表這類版面形狀固定的視圖用 skeleton；形狀未知或單一動作的等待（例如提交中的按鈕）維持 spinner。不強制全站換掉 78 處 spinner，只要求「形狀已知者用 skeleton」。

### 4. 選取相依動作以「有無選取」為單一判準，不做部分啟用

按鈕在無選取時 disabled，有選取時 enabled；不做「刪除可用但重設密碼不可用」這類細分——那屬於權限判定，由既有的 RBAC 路徑處理，不在呈現層再疊一層規則。

### 5. `AppUtils.confirm()` 取代原生 `confirm()`，回傳 Promise

原生 `confirm()` 的同步回傳讓呼叫端寫法簡單，改為 Promise 會動到 **105 處呼叫端、橫跨 15 個檔案**（初版估計「20+ 處」低估了五倍，紅隊審查時以 `rg --pcre2` 重新計數修正）。決定提供非阻塞版本並逐處改寫，不保留原生路徑作為 fallback——保留 fallback 等於保留不一致。

改寫順序以風險排序而非數量排序：部分呼叫點是破壞性操作前的**唯一**確認關卡（`personnel_management.js:525` 刪除使用者、`test-case-cross-set-ops.js:325` 跨 set 搬移），這些先改並各自補 regression；數量最多的 `adhoc_test_run.js`（21 處）多為提示性通知，風險較低。

### 6. 元件放 `app/templates/components/`，狀態切換仍由各頁 JS 驅動

不引入前端框架，所以共用的是 markup 與樣式，切換邏輯留在各頁。契約以 rendered HTML 檢查，不檢查 JS 實作方式。

## Risks / Trade-offs

- **逐處改寫 `alert`／`confirm` 有回歸風險**：這些呼叫散在批次操作與跨 set 搬移等破壞性流程中。緩解：逐檔改寫並補對應 regression，不一次全改。
- **Skeleton 增加初次渲染的 DOM 量**：對大型表格可能反而變慢。緩解：skeleton 列數固定為視窗可見範圍，不依實際資料量產生。
- **狀態契約的自動化檢查有極限**：component spec 能驗證 markup 是否具備各狀態容器，但無法驗證 JS 是否真的會切換——`#emptyState` 正是反例（markup 齊備、無任何顯示路徑）。緩解：markup 檢查 + 關鍵頁面的 frontend regression 雙軌，並針對「有容器但無 `classList.remove` 路徑」加靜態掃描。
- **與 `refactor-frontend-shared-components` 的重疊面**：該 change 的 Phase 11 會把 `organization_management` 的 `d-none` i18n 字串遷移到 locale JSON，可能觸及本變更要改的同一批 DOM。需協調落地順序。

## Migration Plan

1. 先加共用 skeleton 與 empty state 元件（純新增，無行為變更）。
2. 修 `/test-case-sets` 的狀態機——這是最明確的缺陷，也是契約的第一個驗證案例。
3. 修選取相依按鈕的 disabled 條件。
4. 加入 `AppUtils.confirm()`，逐檔改寫原生 `alert`／`confirm`。
5. 依頁面逐一補齊各狀態，以 `/organization-management` 的使用者詳情區為結構參考。
6. 補 component spec 與三語系文案。

無資料庫變更、無 migration。回滾即還原模板與 JS。

## Open Questions

- 「無權限」是否需要與「不存在」在訊息上完全區分？區分較好懂，但可能洩漏資源存在性。需與 `assistant-data-boundary` 既有的邊界原則對齊。
- 部分成功的「降級說明」該用何種呈現（行內提示列／區段標題旁的標記／toast）？`personal-dashboard` 目前的 `partial` 呈現方式可作為基準，但尚未確認是否適用於表格類區段。
