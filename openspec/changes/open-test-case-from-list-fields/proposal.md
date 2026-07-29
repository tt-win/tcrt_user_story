## Why

Test Case Management 列表目前只有列尾的眼睛按鈕能開啟案例，編號與標題儲存格雖會在 hover 時顯示快速編輯按鈕，主要內容本身卻不可開啟案例，造成互動提示與實際行為不一致。讓編號與標題成為直接開啟入口後，可移除重複的檢視按鈕並保留既有快速編輯效率。

## What Changes

- Test Case 列表的編號與標題內容可直接開啟既有 Test Case 檢視／編輯 Modal；可排序表頭維持原行為。
- hover、鍵盤 focus 與無 hover 裝置仍可操作快速編輯按鈕；點擊快速編輯不得連帶開啟 Modal。
- 編號與標題在直接開啟控制項的 hover 下維持原本欄位配色；不呈現按鈕位移、陰影或外框。Test Case Number 維持等寬字體，鉛筆維持原本右側定位且不覆蓋內容。
- Test Case Detail 的「上一個／下一個」按鈕在滑鼠或觸控啟用後主動釋放殘留焦點；鍵盤操作仍保留可見焦點提示，並讓 Test Run Execution 等同型 Detail 導覽遵循相同規則。
- Detail 前後筆切換不得重複累積表單／Markdown listener，也不得因 Modal 內部更新反覆重算背景 Test Case 列表版面，避免瀏覽越久反應越慢。
- Test Case Detail 的「複製連結／上一個／下一個」恢復位於 Modal 標頭右上角，保留原有順序並讓關閉按鈕維持最右側。
- 列表互動使用支援 lazy render 的事件委派，確保後續動態渲染列具有相同行為。
- 快速編輯成功、取消或失敗後，以同一套 cell renderer 還原開啟與編輯控制項，避免互動漂移。
- 移除每列重複的檢視按鈕，保留既有複製與刪除操作；若使用者沒有其他列操作權限，省略空的操作欄。
- 補充自動化回歸測試，涵蓋開啟、快速編輯事件隔離、動態列與操作欄行為。

## Capabilities

### New Capabilities

- 無。

### Modified Capabilities

- `test-case-management-ui`: 增加列表編號／標題直接開啟案例、快速編輯事件隔離，以及移除重複檢視操作的可觀察行為。

## Non-Goals

- 不改變 Test Case Modal 的內容、檢視／編輯模式或前後筆導覽順序；僅修正前後筆控制項的輸入模式焦點呈現、互動生命週期效能及回復原本的標頭位置。
- 不改變快速編輯、複製、刪除的既有權限與後端授權契約。
- 不新增或修改 API、資料模型、資料庫 migration、路由或套件依賴。
- 不重構與本列表互動無關的 inline style、TCG、篩選、排序或批次操作程式碼。

## Risks

- 主要風險是事件冒泡讓鉛筆同時觸發 Modal，以及快速編輯後重新建立 DOM 時遺失直接開啟行為；設計與測試需明確隔離兩種 action 並共用 renderer。
- 動態／分批渲染若逐列綁定事件可能遺漏後續列或累積 listener；必須綁定在穩定父層。
- 移除檢視按鈕後需維持鍵盤與觸控可達性，避免只依賴 hover。
- Detail 每次切換若重新綁定既有欄位 listener 或強制量測背景列表，成本會隨導覽次數與列表大小放大；Modal 內事件必須可重入且版面更新限於 Modal。

## Impact

- 前端：Test Case 列表 row renderer、事件初始化、快速編輯 DOM 還原、Detail Modal 標頭控制項配置、Modal 互動生命週期、頁面專屬 CSS，以及共用 pointer／keyboard focus 規則。
- 測試：新增 DOM-free JavaScript 回歸測試，必要時補充既有 component contract 與瀏覽器焦點檢查。
- 相容性：沿用既有 `viewTestCase(recordId)` 與 i18n lifecycle；無 API、資料或部署相容性影響。
