# Tasks: stabilize-full-test-suite

> 實作前先讀 `design.md` 的 D1 分類表與 D2–D6。不得以 skip／xfail、放寬安全斷言、目錄級 DB policy 例外，或停止 port 9999 既有 server 來取得全綠。

## 1. 固定 baseline 與 order-only reproduction

- [x] 1.1 以目前六個可獨立重現案例建立目標 gate：DB guardrail、QA model placeholder、scheduled-service list、兩個 Helper analytics API 案例與 Helper analytics template 案例；保存每個失敗的實際 contract 差異。 → verify: `uv run pytest -q app/testsuite/test_db_access_guardrails.py::test_db_access_guardrails_have_no_unexpected_violations app/testsuite/test_qa_ai_helper_models.py::test_settings_loader_expands_qa_ai_helper_model_placeholders app/testsuite/test_scheduled_services_api.py::test_super_admin_can_list_scheduled_services app/testsuite/test_team_statistics_helper_ai_api.py app/testsuite/test_team_statistics_helper_frontend.py::test_team_statistics_template_no_longer_exposes_helper_tab_or_sections` 在修改前穩定重現 6 failures
- [x] 1.2 依完整 suite 的原始收集順序縮小 `test_settings_warns_when_container_runtime_uses_localhost_services` 的污染來源，確認是 env、logger、dependency override 或其他 module-global state；將最小重現與根因記入實作摘要後才修改 fixture。 → verify: root-cause 最小 pytest 指令修改前可重現、修改後連跑兩次皆通過
- [x] 1.3 確認現有開發 server／production leader lock 僅作為環境前提，不停止或重啟該程序；記錄 leader test 目前因共享 lock identity 失敗。 → verify: `uv run pytest -q app/testsuite/test_container_deployment_p1.py::test_leader_lock_is_exclusive_across_processes` 修改前重現 holder 未取得 leadership

  根因紀錄（1.2）：`create_managed_test_database()` 觸發 Alembic env 的 `logging.config.fileConfig()`；其預設 `disable_existing_loggers=True` 會停用已載入的 `app.config` logger。最小重現為 scheduled-service list 測試後接 container warning 測試，後者 `caplog.text == ""`。

## 2. 完成 Helper analytics 退役契約

- [x] 2.1 在既有 admin team-statistics router 新增 legacy `helper_ai_analytics` tombstone，沿用 current-user 與 admin permission check；未授權回 `403`，授權管理員回結構化 `410`（`legacy_helper_statistics_retired`），且不查詢 telemetry DB。 → verify: `uv run pytest -q app/testsuite/test_team_statistics_helper_ai_api.py` 全綠
- [x] 2.2 從 `team_statistics.html`／`team_statistics.js` 清除 legacy `helper-ai-*` marker 與 `helper_ai_analytics` pipeline（包含 commented markup），但保留 `qa-ai-helper-tab`、V3 pane、`loadQaAiHelperDashboard()` 與 helperDash renderers。 → verify: `uv run pytest -q app/testsuite/test_team_statistics_helper_frontend.py`，並以 `rg` 確認 V3 markers 仍存在
- [x] 2.3 將 V3 tab 從 legacy `teamStats.tabs.helperAi` 改用新的專用 key並同步三個 locale，確認其他 V3 helperDash 文案仍完整且 JavaScript 可解析。 → verify: `node --check app/static/js/team_statistics.js && node scripts/check-i18n-coverage.mjs && npm run lint`

## 3. 收斂 DB access boundary 與 policy

- [x] 3.1 追蹤 `AutomationEnvironmentService` create/update 的呼叫端與 transaction owner，讓兩個 `IntegrityError` 分支由現有 MainAccessBoundary（或等價受管 write wrapper）rollback；service 保留既有 409 error code/message，不直接呼叫 `session.rollback()`。 → verify: automation environment create/update duplicate 測試同時證明 409、rollback 後 session 可再使用
- [x] 3.2 逐檔 review `cleanup_manual_automation_links.py` 與 `migrate_attachment_metadata_paths.py` 的執行入口、引擎範圍與 transaction recovery；能重用 boundary 者改用 boundary，確屬獨立 maintenance CLI 者只以精確檔案路徑加入 `offline_maintenance` policy，禁止放行整個 `scripts/`。 → verify: 兩支腳本的 dry-run／write 或現有目標測試通過，policy diff 僅含經 review 路徑
- [x] 3.3 保留 guardrail 對任何未核准新違規的偵測能力，確認掃描結果歸零。 → verify: `uv run pytest -q app/testsuite/test_db_access_guardrails.py`

## 4. 修正 hermetic test fixtures

- [x] 4.1 在 QA model placeholder 測試中先清除會覆蓋 YAML 的 `QA_AI_HELPER_MODEL_SEED*`、`SEED_REFINE*`、`TESTCASE*` process env，再設定案例 placeholder env；保留 production「process env 優先」與 unresolved placeholder fail-fast 測試。 → verify: 以外部 stage model override 執行該測試仍全綠，且 `test_settings_loader_rejects_unresolved_placeholders` 通過
- [x] 4.2 讓 leader holder、contender 與 release-check 三個子行程共享同一個 per-test temp lock namespace，production 未設定 override 時仍使用原固定 lock identity。 → verify: 既有 server 持 production lock 時 `uv run pytest -q app/testsuite/test_container_deployment_p1.py::test_leader_lock_is_exclusive_across_processes` 全綠，且測試仍驗證競爭者失敗與釋放後可重取
- [x] 4.3 依 1.2 根因在污染來源 teardown 還原其 env／logger／FastAPI dependency override／singleton state，不在被害測試做不分來源的 global reset。 → verify: 1.2 最小順序重現與 `uv run pytest -q app/testsuite/test_settings_container_runtime.py` 連跑兩次全綠
- [x] 4.4 將 scheduled-service list 測試改為比對 fixture scheduler registry 的 service key set，並以 key 定位 `lark_org_sync` 驗證欄位；不改 registry 產品內容或 API payload。 → verify: `uv run pytest -q app/testsuite/test_scheduled_services_api.py`

## 5. 收尾驗證

- [x] 5.1 先執行本 change 全部目標測試，確認 Helper auth、DB rollback、placeholder fail-fast、leader 互斥與 registry membership 等負向／正向案例均保留，且沒有新增 skip/xfail。 → verify: 2.1–4.4 所列 pytest 指令合併執行全綠
- [x] 5.2 執行相關 lint、JavaScript syntax、i18n coverage 與 template guard；只修本 change 引入的問題。 → verify: `uv run ruff check <本 change 修改的 Python 檔>`, `node --check app/static/js/team_statistics.js`, `node scripts/check-i18n-coverage.mjs`, `npm run lint`
- [x] 5.3 執行完整後端測試至少一次，結果必須全綠；若仍有 order-only failure，回到污染來源修復，不新增 skip/xfail。 → verify: `uv run pytest app/testsuite -q`
- [x] 5.4 自我 review diff，確認無 migration、無 telemetry 資料刪除、無外部程序操作，並嚴格驗證 OpenSpec change。 → verify: `git diff --check && openspec validate stabilize-full-test-suite --strict`
- [x] 5.5 依 repo 規範更新 Graphify 與當日 Obsidian worklog，記錄最終測試證據與任何仍待處理事項。 → verify: `graphify update .` 成功，且 `2026-07-16.md`／`INDEX.md` 已更新
