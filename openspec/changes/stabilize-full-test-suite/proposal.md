## Why

`uv run pytest app/testsuite -q` 目前有 8 個失敗，使共享 runtime 變更無法用全套測試可靠驗收；其中同時混有真實契約落差、測試對環境與執行順序的依賴，以及已演進 registry 的脆弱斷言。現在需要先把產品契約與測試前提收斂，恢復可重複、可判讀的綠色 baseline。

## What Changes

- 收斂 QA AI Helper team analytics 的退役契約：移除 legacy tab marker／載入管線但保留現行 V3 dashboard，並保留受管理員權限保護的 legacy 相容端點；授權管理員收到明確 `410 Gone`，未授權使用者仍收到 `403 Forbidden`。
- 清除 runtime service 與維護腳本中未經審查的 DB access guardrail 違規；runtime transaction 必須移入受管 boundary，離線腳本只有在明確記錄理由且符合 policy 時才能列為例外。
- 讓回歸測試不受開發機既有 leader lock、ambient QA model 環境變數或其他測試留下的全域狀態影響，且隔離不得削弱正式 runtime 的 lock、設定優先序或權限行為。
- 將 scheduled-service 清單測試改為驗證 registry 契約與必要 service membership，不再把可擴充 registry 寫死為恰好一筆。
- 完成後以相同環境連續執行目標測試與全套測試，確認失敗不是靠跳過、放寬斷言或停止使用者既有服務消失。
- **非目標**：不新增資料表或 migration、不改 scheduler registry 的產品功能、不恢復已退役的 Helper analytics 資料管線、不停用或終止開發機上既有的 TCRT server。

## Capabilities

### New Capabilities

- `test-suite-reliability`: 定義回歸測試對 process lock、環境變數、全域 app state 與可擴充 registry 的隔離及判讀契約。

### Modified Capabilities

- `helper-team-analytics`: 將既有 legacy analytics tab/API 契約改為 V3 dashboard 接替、舊 marker／pipeline 移除，以及受權限保護的 `410 Gone` 退役相容行為。
- `database-access-boundaries`: 強化 guardrail 驗收，要求 runtime 違規歸零，離線工具例外必須是最小範圍且經 policy 明確核准。

## Impact

- 影響 QA AI Helper team statistics template 的 legacy marker、舊 admin API、DB access boundary 與 guardrail policy、scheduled-service 與設定載入相關測試，以及 leader-lock 測試 fixture；現行 V3 dashboard 與 `/qa-ai-helper/*` API 不移除。
- API compatibility：legacy Helper analytics endpoint 對授權管理員明確回 `410`，屬既有 API 的退役相容回應；未授權請求維持 `403`。不新增替代 analytics API。
- Database / migration：不變更 schema、不新增 Alembic revision，也不搬移資料；transaction ownership 的程式調整須保留既有 commit／rollback 語意。
- Rollback：可逐項還原測試隔離與 boundary 重構；Helper analytics 若需恢復，必須連同主 spec、UI 與資料 API 另案恢復，不能只移除 `410` route。
- 主要風險是為了全綠而誤改正確產品行為；以主 spec、現有退役測試與目標負向驗證作為判定依據，禁止 skip、xfail 或寬鬆吞錯。
