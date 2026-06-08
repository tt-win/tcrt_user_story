## Why

Automation execution 已經收斂到 `TestRunSet`，但目前使用者在 Test Run Set UI 內仍無法完整管理與理解 automation suite membership：建立/編輯流程缺少 suite picker，detail 頁只顯示 `Suite #id`，`Run as Automation` 也缺少 suite summary 與觸發後的可觀測回饋。這讓主規格已接受的行為只落地了一半，也讓 Test Run Set 難以真正成為 manual runs 與 automation suites 的整合容器。

## What Changes

- 補齊 Test Run Set create/edit flow 的 automation suite 管理 UX，讓使用者可直接在 modal 中搜尋、勾選、更新 suite membership，而不是只能透過 API 或保留既有值。
- 補齊 Test Run Set detail 頁的 Automation Suites section，顯示 suite name、script count 與必要的 suite summary，而不只是一串 suite ids。
- 強化 `Run as Automation` 的確認與成功回饋，讓使用者在觸發前看見即將執行的 suites，觸發後能立即在 set detail 的 run 區塊理解哪些 suite 已排入執行。
- 補齊 Automation Hub suite detail 反向顯示 linked Test Run Sets，讓使用者能從 suite 找回引用它的 Test Run Set。
- 收斂 API response shape，讓 Test Run Set detail 可選擇性攜帶 `automation_suites` summary，避免前端為了顯示 suite 名稱與摘要再額外拼接多次查詢。
- **不**改變 execution ownership：`TestRun` 仍為 manual only，automation suite 仍只由 webhook 或 `TestRunSet` 觸發。
- **不**在此 change 引入新的 normalized join table；延續 `automation_suite_ids_json` 作為 membership 儲存方式。

## Capabilities

### New Capabilities
- 無

### Modified Capabilities
- `test-run-management-ui`: 補齊已接受但尚未完整落地的 automation suite membership / detail / trigger UX 規格，並收斂 API response summary 與觸發後 refresh 契約。

## Impact

- 後端：`app/api/test_run_sets.py`、`app/services/test_run_set_automation_service.py`、可能包含 automation suite list/summary 的 API 組裝邏輯。
- 前端：`app/static/js/test-run-management/set-modal.js`、`app/static/js/test-run-management/automation-trigger.js`、Test Run Set detail template/rendering、Automation Hub suite detail rendering。
- 資料模型：延續使用既有 `test_run_sets.automation_suite_ids_json`，此 change 不新增 migration；若需要更多前端顯示欄位，優先透過 response summary 補足。
- 驗證：需補 Test Run Set create/update/detail、run automation、suite detail linked sets、以及前端互動的 focused tests；全套 smoke 應確認 manual runs 與 automation suites 在同一個 Test Run Set detail 中都可理解。
