## 1. UI Entry Removal / UI 入口移除

- [x] 1.1 盤點並移除 Test Case 編輯頁所有可見 AI 改寫入口（按鈕/toolbar action） / Audit and remove all visible AI rewrite entry controls in the test case editor.
- [x] 1.2 清理或調整入口相關 DOM selector 與綁定點，避免殘留可見觸發元件 / Clean up entry-related selectors and bindings to avoid leftover visible triggers.
- [x] 1.3 檢查 i18n 文案策略（暫留或註記）並確保 UI 不再呈現 AI 改寫文字 / Verify i18n retention strategy while ensuring no AI rewrite label is rendered in UI.

## 2. Frontend Flow Guardrails / 前端流程防呆

- [x] 2.1 更新 `ai-assist.js` 初始化條件，無入口元素時直接 no-op / Update `ai-assist.js` initialization to no-op when trigger elements are absent.
- [x] 2.2 移除或封鎖可從一般使用流程觸發 AI assist modal 的前端路徑 / Remove or block standard user-flow paths that can open AI assist modal.
- [x] 2.3 驗證非 AI 編輯流程（儲存、欄位編輯、切換）不受影響 / Verify non-AI editor workflows remain unaffected.

## 3. Capability Retention Verification / 能力保留驗證

- [x] 3.1 以既有 request payload 驗證 `/api/teams/{team_id}/testcases/ai-assist` 仍可回應 / Validate existing `/ai-assist` endpoint still responds with current payload contract.
- [x] 3.2 確認 `app/api/test_cases.py` 的 AI assist contract 無破壞性變更 / Confirm no breaking contract changes in `app/api/test_cases.py`.
- [x] 3.3 記錄未來恢復 UI 入口的最小回復步驟 / Document minimal rollback steps for future UI re-enable.

## 4. Regression and Documentation / 回歸與文件

- [x] 4.1 新增或更新測試，覆蓋「UI 無 AI 入口」與「後端能力仍可用」兩類驗證 / Add or update tests for hidden UI entry and retained backend capability.
- [x] 4.2 執行手動回歸，確認一般使用者看不到 AI 改寫入口 / Run manual regression to confirm AI rewrite entry is not visible to standard users.
- [x] 4.3 更新對應文件或變更說明，明確標示 capability retained, UI hidden / Update docs or change notes to state capability retained and UI hidden.
