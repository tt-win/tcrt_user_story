## 1. Workflow API 與資料模型 (Workflow API and Data Model)

- [x] 1.1 建立 AI helper session/draft 資料模型與 migration 相容邏輯 (Create AI helper session/draft models with migration-safe initialization)
- [x] 1.2 新增 helper state machine schema（phase/status/payload）(Add helper state-machine schema for phase/status/payload)
- [x] 1.3 實作建立 session API（含 set 選擇/新建）(Implement session start API with set select/create support)
- [x] 1.4 實作 session 查詢/更新 API（可恢復編輯內容）(Implement session read/update APIs for recoverable edits)

## 2. Jira 與需求整理階段 (Jira and Requirement Normalization)

- [x] 2.1 實作 TCG 輸入驗證與 Jira ticket 讀取 API (Implement TCG validation and Jira fetch API)
- [x] 2.2 接入 `gemini-3-flash-preview` 需求統整服務 (Integrate `gemini-3-flash-preview` requirement normalization service)
- [x] 2.3 實作語系規則分離：需求整理用 UI locale、testcase 產出用 output locale (Implement split language policy for review locale vs output locale)
- [x] 2.4 實作需求 markdown 儲存與版本更新 (Implement requirement markdown persistence and version updates)
- [x] 2.5 新增 `config.yaml` helper 模型設定鍵與 typed config（analysis/coverage/testcase/audit）(Add helper stage model keys in `config.yaml` with typed config mapping)
- [x] 2.6 在 `config.yaml.example` 提供預設值：analysis/testcase/audit=gemini-3-flash-preview、coverage=gpt-5.2 (Add documented defaults in `config.yaml.example`)
- [x] 2.9 參考 `/Users/hideman/code/test_case_agent_poc/llm_config.yaml` 補齊四階段 prompt 模板（analysis/coverage/testcase/audit）到 `config.yaml`/typed config (Backfill four-stage prompt templates from PoC into `config.yaml` and typed config)
- [x] 2.7 實作 helper 全階段統一 OpenRouter 呼叫器 (Implement unified OpenRouter caller for all helper stages)
- [x] 2.8 Jira 連線重用 `app/services/jira_client.py`，不得新增平行 Jira client (Reuse `app/services/jira_client.py` and avoid parallel Jira clients)

## 3. Analysis/Coverage 與 Pre-TestCase 階段 (Analysis/Coverage and Pre-TestCase)

- [x] 3.1 依 `/Users/hideman/code/test_case_agent_poc` 建立 Analysis/Coverage adapter (Build Analysis/Coverage adapter based on reference PoC)
- [x] 3.2 實作分析結果結構化儲存（可回填編輯）(Implement structured analysis persistence with editable round-trip)
- [x] 3.3 實作 pre-testcase 產出與可編輯提交 API (Implement pre-testcase generation and editable submit API)
- [x] 3.4 補上重試與錯誤狀態轉移邏輯 (Add retry and error-state transitions per phase)
- [x] 3.5 串接分階段模型讀取：analysis=gemini、coverage=gpt-5.2（可由 config 覆寫）(Wire stage model resolver with config-driven analysis/coverage selection)
- [x] 3.6 OpenRouter 設定重用 `app/config.py` 的 `settings.openrouter` 管線 (Reuse `settings.openrouter` config pipeline from `app/config.py`)

## 4. Test Case 生成與模型對齊 (Generation and Model Compliance)

- [x] 4.1 建立 test case generation adapter（參考 PoC）(Implement test case generation adapter based on PoC)
- [x] 4.2 實作生成結果 schema validator（必填欄位與型別）(Implement generated payload schema validator)
- [x] 4.3 實作 `section_path -> section_id` 解析與缺失 section 自動建立 (Implement section path resolution and auto-create missing sections)
- [x] 4.4 實作 commit API，將最終內容寫入既有 Test Case model (Implement commit API to persist final items into existing model)
- [x] 4.5 串接分階段模型讀取：testcase/audit=gemini（可由 config 覆寫）(Wire config-driven testcase and audit model resolution)
- [x] 4.6 移除 helper 對獨立 LLM 設定檔的 runtime 相依 (Remove runtime dependency on standalone LLM config files for helper flow)
- [x] 4.7 實作 Test Case ID allocator（middle/tail 皆 10 遞增，支援 initial middle）(Implement 10-step ID allocator for middle and tail numbers)
- [x] 4.8 以單一交易提交 section + testcases，任一失敗全數 rollback (Commit section and testcase writes in one atomic transaction with full rollback)
- [x] 4.9 Qdrant 查詢策略沿用既有 AI 模組的設定/查詢結構（`ai/jira_to_test_case_poc.py`、`ai/llm_config.py`、`ai/etl_all_teams.py`）(Follow existing Qdrant query/config strategy from current AI modules)
- [x] 4.10 建立 `app/services/qdrant_client.py` 獨立 async client（單例、重試、timeout、pool、semaphore）(Create dedicated async Qdrant client service with singleton/retry/timeout/pool/semaphore)
- [x] 4.11 串接 app startup/shutdown 生命週期以建立與關閉 Qdrant client (Wire Qdrant client create/close into app startup/shutdown lifecycle)

## 5. 前端精靈介面與互動 (Frontend Wizard UI and Interactions)

- [x] 5.1 在 `test_case_management.html` 新增 `AI Agent - Test Case Helper` 入口按鈕 (Add helper entry button in `test_case_management.html`)
- [x] 5.2 新增 wizard modal/stepper 骨架與狀態顯示 (Add wizard modal/stepper shell with explicit phase states)
- [x] 5.3 建立 `app/static/js/test-case-management/ai-helper.js` 串接分階段 API (Create `ai-helper.js` for phase-by-phase API orchestration)
- [x] 5.4 套用 frontend design 原則調整 stepper/確認區視覺，但維持既有系統風格 (Apply frontend design principles while preserving existing design language)

## 6. Markdown 編輯與最終確認 (Markdown Editing and Final Review)

- [x] 6.1 重用既有 markdown 編輯/預覽能力於需求確認階段 (Reuse existing markdown editor/preview in requirement checkpoint)
- [x] 6.2 建立 pre-testcase 可編輯列表與差異預覽 (Build editable pre-testcase list with diff-style preview)
- [x] 6.3 建立最終 test case 審核編輯表格（含 section 調整）(Build final editable test case review grid with section remap)
- [x] 6.4 實作提交前最後確認與阻擋條件提示 (Implement final submit confirmation with validation blockers)

## 7. 權限、i18n、稽核與導頁 (Permission, i18n, Audit, Redirect)

- [x] 7.1 新增 helper API 權限檢查（team write）(Add team-write permission checks for helper APIs)
- [x] 7.2 補齊 `zh-TW/zh-CN/en-US` locale keys（wizard 全流程文案）(Add full wizard i18n keys in all locales)
- [x] 7.3 新增關鍵動作審計記錄（start/retry/commit）(Add audit logs for start/retry/commit events)
- [x] 7.4 實作成功後導向目標 set 並高亮新建 test cases (Implement redirect to target set and highlight created cases)

## 8. 測試與驗證 (Testing and Validation)

- [x] 8.1 新增 API 單元測試：session lifecycle 與 phase transitions (Add API unit tests for session lifecycle and phase transitions)
- [x] 8.2 新增 API 單元測試：schema validation 與 section auto-create/fallback (Add API unit tests for schema validation and section mapping)
- [x] 8.3 新增前端互動測試：多步驟流程與錯誤重試 (Add frontend interaction tests for multi-step flow and retries)
- [x] 8.4 執行指定回歸測試與 smoke test，確認無既有功能回歸 (Run regression targets and smoke tests to confirm no regressions)
- [x] 8.5 新增設定測試：`config.yaml` 覆寫四階段模型與預設值回退 (Add config tests for stage model overrides and default fallback)
- [x] 8.6 新增編號測試：middle/tail 10 遞增與初始號行為 (Add ID numbering tests for 10-step increments and initial middle behavior)
- [x] 8.7 新增交易測試：commit 任一失敗時無部分資料殘留 (Add transactional tests for all-or-nothing commit behavior)
- [x] 8.8 量測 helper 期間其他讀取 API 延遲，確認 DB 鎖定影響可接受 (Measure concurrent read latency during helper flow to verify lock impact)
