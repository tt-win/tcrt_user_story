## 1. Test Run Set detail / API summary

- [x] 1.1 在 `app/api/test_run_sets.py` 補 `automation_suites` summary 組裝，至少含 `id` / `name` / `script_count`
- [x] 1.2 若可低成本取得，額外補 `ci_job_name` / `ref_branch`
- [x] 1.3 確認 summary 只解析同 team suites；遇到 stale / missing suite 時回應可被前端安全處理
- [x] 1.4 補 API 測試：GET detail 含 `automation_suite_ids` 與 `automation_suites` summary

## 2. Test Run Set create/edit suite picker

- [x] 2.1 在 `app/static/js/test-run-management/set-modal.js` 加入 suite list 載入與 in-memory selection state
- [x] 2.2 在 create/edit modal 加入 suite picker UI（搜尋 + checkbox + 已選摘要）
- [x] 2.3 編輯既有 set 時回填已選 suites
- [x] 2.4 儲存時送出 `automation_suite_ids`，未變更時不得把既有 suites 清空
- [x] 2.5 補對應 i18n 字串（至少 `en-US` / `zh-TW` / `zh-CN`）

## 3. Detail page Automation Suites section

- [x] 3.1 在 Test Run Set detail 渲染 suite name / script count，而不是只顯示 `Suite #id`
- [x] 3.2 補空狀態文案與 disabled CTA 顯示
- [x] 3.3 若本 change 內一併做 detail remove flow，補移除 suite 的確認與 PATCH 更新

## 4. Run as Automation UX completion

- [x] 4.1 在 `app/static/js/test-run-management/automation-trigger.js` 的確認訊息中顯示 suite summary，而不是只顯示數量
- [x] 4.2 觸發成功後自動 refresh Test Run Set detail
- [x] 4.3 Recent Runs 區塊確認能以 suite name / trigger source 呈現新 run
- [x] 4.4 補 focused tests：run-automation API 與 detail refresh 所需 response shape 不回歸

## 5. 驗證

- [x] 5.1 `openspec validate improve-test-run-set-automation-suite-management --strict`
- [x] 5.2 `uv run pytest app/testsuite/test_test_run_set_api.py app/testsuite/test_test_run_set_automation.py app/testsuite/test_test_run_set_run_automation_api.py app/testsuite/test_test_run_set_run_history_api.py -q --no-header`
- [ ] 5.3 手動驗證：create/edit Test Run Set 時可選 suite、儲存後 detail 顯示 suite name
- [ ] 5.4 手動驗證：`Run as Automation` 確認訊息可看見 suite summary，成功後 detail 與 recent runs 會 refresh

註：5.3 / 5.4 已嘗試以本機 `http://127.0.0.1:9999/test-run-management` 驗證，但目前被登入頁面攔截，未持有可用登入憑證，因此保留未勾選。
