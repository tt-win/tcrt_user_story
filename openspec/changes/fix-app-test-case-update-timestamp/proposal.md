## Why

App Token 的單筆 Test Case 更新會修改內容，卻不會刷新本地 `updated_at`，因此依該欄位計算的團隊「更新數」與其他更新時間消費者無法反映 API／`tcrt-app` skill 的實際異動。這也使 App Token 路徑與既有 JWT、批次更新路徑的時間戳行為不一致。

## What Changes

- 成功且實際改變至少一個 Test Case 持久化欄位的 App Token generic update SHALL 刷新該案例的本地 `updated_at`。
- 被拒絕、失敗或實際無變化的 update SHALL 不刷新 `updated_at`。
- 新增回歸測試，驗證內容更新會推進時間戳，並可被既有 Test Case trend `Updated` 統計納入。
- 不改變 `Updated` 的既有統計定義、不回填歷史資料，也不擴張至其他 mutation endpoint。

## Capabilities

### New Capabilities

無。

### Modified Capabilities

- `app-token-test-case-api`: 明確規範 App Token 單筆 Test Case generic update 對本地 `updated_at` 的維護語意。

## Impact

- API：`PUT /api/app/teams/{team_id}/test-cases/{case_id}` 的成功 mutation 行為。
- 資料與統計：既有 `test_cases.updated_at` 會在後續有效更新時刷新；團隊 Test Case trend 將沿用現有查詢自然反映該更新。
- 測試：App Token Test Case mutation 與 team statistics focused regression tests。
- 相容性：無 endpoint、request／response shape、scope、schema 或 dependency 變更；無 Alembic migration。
- 回復：可回退程式碼以停止未來時間戳刷新；既有已寫入時間戳不做破壞性回復，亦不需資料 migration。
