## Why

在 Test Case Management 畫面中，使用者點擊右側的 section 項目時，系統未能穩定觸發跳轉到該 section 的 test case。這個問題影響使用者體驗，特別是在管理大量測試案例時，無法快速導航到目標區塊。此問題需要立即修正以恢復預期的導航功能。

In the Test Case Management interface, clicking on a section item in the right panel does not reliably trigger navigation to that section's test cases. This issue affects user experience, especially when managing large numbers of test cases, preventing quick navigation to target sections. This needs immediate fixing to restore expected navigation behavior.

## What Changes

- 修正 section 點擊事件的觸發邏輯，確保能穩定跳轉到對應的 test case 區塊
- 改善事件監聽器的綁定方式，避免事件競爭或遺失
- 確保在動態載入內容後，section 導航功能仍然正常運作

## Capabilities

### New Capabilities

無 (這是 bug fix，不涉及新功能)

### Modified Capabilities

- `test-case-management-ui`: 修正 section 導航功能的需求規格，確保點擊 section 時能穩定跳轉到對應的 test case 區塊

## Impact

**受影響的程式碼**:
- `app/static/js/test-case-management/` - 前端 JavaScript 邏輯
- `app/templates/test_case_management.html` - 相關模板檔案

**受影響的功能**:
- Test Case Management UI 的 section 導航功能

**不受影響**:
- 後端 API
- 資料庫結構
- 其他 UI 功能
