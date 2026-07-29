## 1. Regression Test Scaffold

- [x] 1.1 新增 Test Case 列表互動的 DOM-free Node 測試檔與最小 browser-global stubs。
- [x] 1.2 鎖定編號／標題 renderer 產生直接開啟與快速編輯 sibling actions，且不再產生獨立檢視按鈕。
- [x] 1.3 鎖定事件分派、重複綁定 guard、lazy row 與操作欄權限條件的行為。

## 2. Shared Field Rendering

- [x] 2.1 抽出 Test Case Number／標題共用 cell content renderer，保留描述、escaping 與既有 i18n tooltip keys。
- [x] 2.2 將編號與標題主要內容改為可鍵盤操作的語意開啟控制項，並將鉛筆改為獨立 data action。
- [x] 2.3 移除列尾獨立檢視按鈕，並以共用權限判斷同步渲染操作欄 header 與 row cell。

## 3. Interaction Lifecycle

- [x] 3.1 在 `#testCasesStack` 建立具 idempotent guard 的事件委派，分派直接開啟與快速編輯且隔離事件冒泡。
- [x] 3.2 讓快速編輯成功、取消與失敗路徑都使用共用 renderer 還原 cell，並執行局部 i18n retranslate。
- [x] 3.3 確認表頭排序、checkbox、TCG、複製與刪除事件維持既有行為。

## 4. TCRT Styling and Accessibility

- [x] 4.1 使用 `--tr-*` token 完成主要開啟控制項、hover、focus-visible 與 `:focus-within` 樣式，不新增 inline style。
- [x] 4.2 在無 hover／窄螢幕情境維持快速編輯可見與操作欄不溢位，並重用既有三語 i18n keys。

## 5. Verification and Knowledge Sync

- [x] 5.1 執行相關 JavaScript syntax checks 與新 Node targeted test。
- [x] 5.2 執行 Test Case Management component spec、frontend lint 與 i18n coverage。
- [x] 5.3 執行全 repo Ruff、OpenSpec strict validation 與差異自我審查。
- [x] 5.4 以桌面、鍵盤及窄螢幕／無 hover 情境完成列表互動 smoke QA。
- [x] 5.5 執行 `graphify update .` 並更新專案 daily worklog。

## 6. Hover Visual Regression

- [x] 6.1 還原主要開啟控制項的原始欄位配色與等寬編號字體，移除按鈕 hover chrome，並校正鉛筆定位與內容保留空間。
- [x] 6.2 擴充回歸測試，驗證主要開啟控制項與鉛筆本身的 hover、鍵盤 focus 及無 hover／窄螢幕下視覺與定位契約。

## 7. Detail Navigation Focus Regression

- [x] 7.1 將共用按鈕焦點陰影調整為僅鍵盤 `:focus-visible`，消除滑鼠啟用前後筆後的殘留外框。
- [x] 7.2 補齊回歸測試與瀏覽器驗證，並審查 Test Case Management、Test Run Execution 與其他使用同一共用規則的 Detail 導覽控制項。

## 8. Detail Header Navigation Placement

- [x] 8.1 將 Test Case Detail 的複製連結、上一個與下一個控制項移回 Modal 標頭右上角，關閉按鈕保持最右側，並移除 body 重複子工具列。
- [x] 8.2 擴充回歸測試與瀏覽器驗證，確認標頭位置、控制項順序、既有 ID 與導覽／複製行為契約未變。

## 9. Detail Navigation Focus and Performance Regression

- [x] 9.1 以共用 input-modality helper 修正 Test Case Management 與 Test Run Execution 前後筆按鈕的 pointer 焦點殘留，保留鍵盤 focus-visible。
- [x] 9.2 將 Test Case Detail 表單 change/input 與 Markdown hotkey 綁定改為 idempotent，避免重複導覽累積 listener。
- [x] 9.3 合併重複 Markdown preview 更新，並移除純 Modal 路徑對背景列表高度的強制量測。
- [x] 9.4 補齊焦點與效能生命週期回歸測試，執行 targeted gates、實機瀏覽器驗證及 OpenSpec strict validation。
