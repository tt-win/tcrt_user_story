## 1. UI 與互動入口 / UI Entry and Interaction

- [x] 1.1 在 Test Case Set 案例管理畫面 `套用篩選` 旁新增 `產生連結` 按鍵 / Add `Generate Link` button next to `Apply Filter` on Test Case Set case management page
- [x] 1.2 建立顯示分享連結的 modal（含 readonly 欄位與複製動作）/ Build modal to show share URL with readonly field and copy action
- [x] 1.3 新增並串接 i18n 文案鍵值（按鍵、modal 標題、複製提示）/ Add and wire i18n keys for button, modal title, and copy feedback

## 2. 連結生成與狀態還原 / Link Generation and State Restoration

- [x] 2.1 實作目前篩選條件到 query string 的序列化邏輯 / Implement serialization from current filters to query string
- [x] 2.2 實作頁面初始化時從 query string 還原篩選條件並自動套用 / Implement query-string-based filter restoration on page init
- [x] 2.3 對齊並補強登入回跳流程，確保未登入使用共享連結後可回到原 URL / Align and harden login redirect to preserve full shared URL for unauthenticated users

## 3. 權限與邊界條件 / Authorization and Edge Cases

- [x] 3.1 驗證無權限使用者開啟共享連結時維持既有拒絕行為 / Verify forbidden users opening shared links still receive existing access-denied behavior
- [x] 3.2 限制共享連結僅包含必要篩選參數並排除 UI-only 狀態 / Restrict shared URL to required filter params and exclude UI-only state

## 4. 測試與驗證 / Tests and Validation

- [x] 4.1 新增前端/整合測試：已登入開啟共享連結可直接看到正確篩選結果 / Add tests for authenticated direct-open shared link behavior
- [x] 4.2 新增前端/整合測試：未登入開啟共享連結會登入後回跳並還原篩選 / Add tests for unauthenticated open -> login -> return with restored filters
- [x] 4.3 新增 round-trip 測試：filter state 序列化與反序列化一致 / Add round-trip tests for filter state serialization/deserialization consistency
- [x] 4.4 執行目標測試並記錄結果（含失敗案例與修正）/ Run target test suites and record outcomes including failures and fixes
