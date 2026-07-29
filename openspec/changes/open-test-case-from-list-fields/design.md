## Context

Test Case Management 是以 Jinja2 shell 搭配原生 JavaScript 動態渲染的全高工作區。案例列由 `renderTestCaseRow()` 產生，並以 section 分組、分批加入 `#testCasesStack`；目前編號與標題 cell 以 hover 顯示快速編輯按鈕，列尾眼睛按鈕則呼叫既有 `viewTestCase(recordId)` 開啟 Modal。

快速編輯由 `quickEdit(recordId, field)` 暫時以 input 取代 cell 內容。現況在儲存後另外建立一套 DOM 與 click listener，與初始 row renderer 不一致，因此直接開啟行為若只加在初始 markup，第一次快速編輯後就會遺失或與快速編輯衝突。

本變更只調整前端互動。開啟案例沿用記憶體中的 `testCases` 與既有讀取 fallback；快速編輯沿用既有 `PUT /api/teams/{team_id}/testcases/{record_id}`。不新增資料持久化、API、路由、權限或 migration。

## Goals / Non-Goals

**Goals:**

- 讓每筆案例的編號與標題主要內容成為可辨識、可鍵盤操作的 Modal 開啟入口。
- 保留目前 hover 快速編輯體驗，並明確隔離「開啟」與「快速編輯」事件。
- 讓初始、lazy render 及快速編輯還原後的 cell 使用同一互動結構。
- 移除重複檢視按鈕，同時維持複製、刪除與權限行為。
- 讓重複切換 Detail 不累積 listener 或觸發與 Modal 無關的背景列表版面量測。
- 使用既有 design token、i18n lifecycle 與無新依賴的測試方式。

**Non-Goals:**

- 不改造 Test Case Modal 的資料契約、排序、篩選、section navigation、TCG 或批次操作。
- 不調整任何角色可否快速編輯、複製或刪除的授權規則。
- 不清理與本列互動無關的既有 inline style 或其他技術債。
- 不新增後端端點、資料欄位、套件或 build pipeline。

## User Journey and State Flow

1. 使用者以滑鼠移入編號或標題 cell，或以鍵盤聚焦主要內容時，cell 顯示快速編輯鉛筆。
2. 啟用編號／標題主要內容時，事件委派辨識 `open-test-case` action，呼叫 `viewTestCase(recordId)` 開啟既有 Modal。
3. 啟用鉛筆時，事件委派先攔截該 action，只呼叫 `quickEdit(recordId, field)`，不得開啟 Modal。
4. 快速編輯期間 cell 只包含 input；Enter 或 blur 走既有儲存，Escape 取消。
5. 儲存成功、取消或失敗後，cell 一律透過共用 renderer 還原主要開啟控制項與鉛筆，再執行局部 i18n retranslate。

資料邊界不變：開啟操作不寫入資料；只有既有快速編輯流程會呼叫既有更新 API。若更新失敗，仍還原本地值與 cell 顯示。

## Decisions

### 1. 使用兩個同層級的語意控制項

編號／標題主要內容使用原生 `button`，搭配符合 class order 的 `btn btn-link btn-sm` 與頁面專屬 class；快速編輯按鈕維持為同一 cell 中的 sibling。兩者以 `data-tcm-action`、`data-record-id` 與 `data-field` 描述意圖，不建立巢狀互動元素。

選擇原生 button 是因為 Enter／Space、focus 與 disabled semantics 可直接由瀏覽器提供。替代方案是在 `<td>` 加 `onclick`／`tabindex`／`role=button`，但需要自行重建鍵盤語意，且較容易讓 input 或鉛筆冒泡誤開 Modal，因此不採用。

### 2. 在穩定父層做單一事件委派

在 `#testCasesStack` 綁定一次 click listener，由最近的 `[data-tcm-action]` 分派 `open-test-case` 或 `quick-edit`。綁定函式使用 guard，避免 minimal-mode fallback 或重複初始化累積 listener。

逐列綁定不適合目前分批／lazy render；document-level listener 的作用域又過大，因此選擇持續存在且只包含案例列表的 `#testCasesStack`。

### 3. 初始 render 與快速編輯還原共用 field renderer

抽出編號／標題 cell content renderer，初始 `renderTestCaseRow()` 與 `quickEdit()` 的所有結束路徑都使用它。renderer 保留標題描述、既有 tooltip key 與必要的 escaping；還原後對該 cell 呼叫 `window.i18n.retranslate(cell)`。

不採整張表重新 render，避免破壞 scroll 位置、section 收合狀態、lazy render 進度與目前選取狀態。

### 4. 操作欄只承載仍存在的列操作

列尾移除眼睛按鈕。共用權限判斷決定 header 與 row 是否渲染操作欄：仍有複製或刪除時保留；兩者都不可用時，同時省略 header 與 cell，避免空欄與欄數不一致。

### 5. 視覺、觸控與 i18n 沿用既有系統

主要開啟控制項保持目前欄位文字視覺，不套用 toolbar chrome。它會明確覆寫全域 `.btn` 的 hover 位移、陰影、連結變色與外框；cell 本身既有的淡色 hover 仍由 `.hover-editable` 負責。Test Case Number 使用 Bootstrap 原生等寬字型，以免名稱 class 觸發廣域 condensed 字型規則後失去數字對齊感。

鉛筆沿用原本 `right: 5px`、`z-index: 10` 與垂直置中定位；主要內容保留 45px 右側空間，避免文字與鉛筆重疊。鉛筆本身的 hover／focus／active 會明確保留 `translateY(-50%)`，避免全域 `.btn:hover` 覆寫 transform 後跳離置中位置。鉛筆在 hover 與 `:focus-within` 顯示，`@media (hover: none)` 下保持可見。主要內容的 `focus-visible` 仍使用 `--tr-*` token。新 markup 重用 `tooltips.viewEdit` 與 `tooltips.quickEdit`，預期不新增 locale key。

### 6. 以無新依賴的 JavaScript 測試鎖定契約

新增 Node `node:test`／`vm` 測試，使用最小 stub 載入相關 browser-global script。測試鎖定 renderer actions、事件分派、快速編輯後還原與操作欄條件；不引入 jsdom 或第二套前端測試框架。

### 7. 依實際啟用方式釋放 pointer 焦點

實機驗證顯示，瀏覽器在滑鼠啟用前後筆按鈕後仍可能將該按鈕判定為 `:focus-visible`，因此單靠 CSS selector 無法可靠區分輸入方式。共用互動 helper 以 click event 的 `detail` 判斷啟用來源：滑鼠／觸控產生的 click 在下一個 animation frame 釋放該按鈕焦點；鍵盤產生的 click（`detail === 0`）不 blur，繼續保留符合 `--tr-primary-rgb` 的焦點提示。

此 helper 僅由 Detail 前後筆控制項呼叫，不對所有 `.btn` 做全域 blur，避免破壞 dropdown、Modal trigger 或其他依賴焦點的元件。Test Case Management 與 Test Run Execution 的 Detail Modal 共用同一 helper，防止同型問題漂移。

### 8. 回復 Detail 標頭右上角控制項群組

使用者確認 Test Case Management 的既有 Detail 操作應位於 Modal 標頭右上角。恢復原本的標頭結構：標題之後放置 `d-flex align-items-center gap-2` 群組，依序為「複製連結、上一個、下一個、關閉」。控制項保留既有 ID 與 class，故 `init.js`、`modal.js` 與 `attachments.js` 的事件綁定及 disabled 狀態更新不需改動；移除 body 中重複的導覽子工具列。

此配置刻意與 Test Run Execution Detail 的右上角操作方式一致。風險是標頭在窄寬度可能較擁擠；沿用既有寬 Modal 與緊湊 `btn-sm`，並以瀏覽器檢查控制群組仍位於標頭右側。

### 9. 讓 Detail 更新保持 idempotent 並隔離背景列表版面

`showTestCaseModal()` 會在每次前後筆切換時重用同一份 form。表單 change/input listener 改為綁在 form 父層一次，Markdown hotkey listener 亦加一次性 guard，避免每次切換都在相同節點累積 handler。

Markdown preview 由模式切換一次批次更新三個欄位，不再先更新一輪、進入 preview mode 後又更新第二輪。Modal 導覽、preview 更新與 navigation button 狀態不會再呼叫 `adjustTestCasesScrollHeight()`；該函式只負責背景列表容器，Modal-only 更新不應強迫瀏覽器重新量測整份清單。這些調整不改變資料內容、scroll order 或儲存行為。

## Risks / Trade-offs

- [Risk] 鉛筆 click 冒泡後又開啟 Modal → [Mitigation] sibling controls、action-first dispatch，以及測試確認一次互動只呼叫一個 handler。
- [Risk] 快速編輯結束後回到不同 markup → [Mitigation] 所有 terminal paths 共用 field renderer，禁止 ad-hoc listener 重建。
- [Risk] lazy rows 沒有 listener 或初始化重複 → [Mitigation] 穩定父層事件委派與 idempotent bind guard。
- [Risk] 移除眼睛後觸控或鍵盤找不到操作 → [Mitigation] native button、focus-visible／focus-within 與 no-hover media rule。
- [Trade-off] 主要內容改為 button 會增加 tab stops → 這是可存取直接操作的必要成本；每個 cell 只保留開啟與快速編輯兩個明確控制項。
- [Trade-off] 本 change 不修正既有快速編輯權限模型或其他 inline style → 保持行為範圍可審查，相關技術債另案處理。
- [Risk] 無條件在 click handler `blur()` 會讓鍵盤使用者失去焦點位置 → [Mitigation] 只在 `event.detail > 0` 的 pointer activation 釋放焦點，鍵盤 click 保持 focus-visible，並以瀏覽器驗證兩種輸入模式。
- [Risk] 將重複 listener 改成一次性委派可能漏掉動態欄位 → [Mitigation] change/input 綁在穩定 form 父層，事件由動態 input 冒泡；Markdown hotkey 則在每個 textarea 上以 guard 綁定一次。
- [Risk] 移除 Modal 更新期間的列表高度計算可能影響列表視窗 → [Mitigation] 保留頁面載入、resize、篩選與列表 render 路徑的既有高度更新，只移除純 Modal 路徑。
- [Risk] 導覽控制項移回標頭卻改變 ID 或被保留在 body 的重複元素 → [Mitigation] 還原歷史標頭順序、保留原 ID，並以 source regression test 確認不存在子工具列。

## Migration Plan

1. 先新增互動與 renderer 回歸測試。
2. 調整 row／field renderer、事件委派與快速編輯還原。
3. 套用頁面 CSS 與操作欄條件。
4. 執行 JS syntax、Node targeted test、component spec、lint、i18n coverage、Ruff 與 OpenSpec strict validation。

無資料 migration 或部署順序要求。回滾時可回復原 row markup、移除委派 handler／新增 CSS，並重新顯示既有眼睛按鈕；不需要資料修復。

## Open Questions

無。產品與實作邊界已在紅隊審查中收斂。
