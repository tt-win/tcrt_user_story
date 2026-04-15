## 1. Backend Service & API

- [x] 1.1 `app/services/test_case_set_service.py`: 實作統一取得/更新 default set 邏輯 (Implement unified default resolution logic)
- [x] 1.2 `app/api/test_cases.py` & `app/api/adhoc.py`: 重構現有建立流程，改用新的 unified default logic (Refactor creation flows to use unified logic)
- [x] 1.3 `app/api/test_case_sets.py`: 實作切換 default set 的 API (Admin-only)，包含確保有 `Unassigned` section (Implement set-as-default API with Unassigned section check)

## 2. Frontend UI (Managed by frontend design skill)

- [x] 2.1 UI 設計：使用 `frontend-design` skill 設計 Test Case Set 列表中的 Default 標籤與 Admin 切換操作 (Design UI with frontend-design skill for default badge and admin action)
- [x] 2.2 `app/static/js/test-case-set-list/main.js` (或新架構): 實作 Default 標籤顯示邏輯 (Implement Default badge display)
- [x] 2.3 `app/static/js/test-case-set-list/main.js` (或新架構): 實作 Admin 的「設為預設」按鈕、確認對話框與 API 串接 (Implement Set as Default button, confirmation modal, and API integration)

## 3. Testing & Validation

- [x] 3.1 撰寫後端 API 單元測試，確保權限檢查與資料一致性 (Write backend unit tests for permission and atomicity)
- [x] 3.2 驗證既有 Test Run impact preview 行為是否維持正常 (Validate Test Run impact preview behavior remains intact)
