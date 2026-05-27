## 1. Session Lifecycle and Routing

- [x] 1.1 實作畫面一 sessionless 入口，只有送出 Ticket Number 後才建立 `qa_ai_helper_session`
- [x] 1.2 實作「重新開始」流程：刪除當前未完成 session 與下游資料，回到畫面一，下一次 submit 建立全新 session
- [x] 1.3 定義七畫面對應的 session `current_screen` / `status` 狀態與前後跳轉 guard

## 1A. Legacy Retirement and Data Purge

- [x] 1A.1 封存並隱藏 V1 / V2 helper 入口，不再讓使用者進入舊 modal 或舊 phase-based 頁面
- [x] 1A.2 設計並執行 rollout migration：先建立 DB snapshot，再 purge legacy helper rows，清除 `ai_tc_helper_*` 與舊 V2/V3 helper runtime data
- [x] 1A.3 移除或停用舊 helper phase 統計、舊 adoption/telemetry 聚合與相關查詢，不做資料 backfill
- [x] 1A.4 明確定義 V3 rollout 後的統計起算點，讓 seed/testcase adoption metrics 自新版上線後重新累積

## 2. Ticket Loading and Format Gate

- [x] 2.1 以 Jira 原始內容轉 markdown 的方式實作畫面二唯讀票單確認畫面
- [x] 2.2 將 `scripts/qa_ai_helper_preclean.py` 封裝為新版 helper 的 parser/normalizer，輸出畫面三所需 schema
- [x] 2.3 實作畫面二格式檢查，至少驗證 `User Story Narrative`、`Criteria`、`Acceptance Criteria`，並將 `Technical Specifications` 視為 warning-only 參考區
- [x] 2.4 補上欄位級驗證：`As a / I want / So that`、有效 Criteria items、以及 AC scenario 名稱與 `Given / When / Then`
- [x] 2.5 對 `Unnamed Scenario`、缺 clause、缺欄位等 parser gate 問題輸出明確錯誤碼與訊息，格式不通過時阻擋進入畫面三
- [x] 2.6 以 `tcrt-ui-style` 規劃畫面二 `8 + 4` split layout：左側唯讀 markdown，右側驗證結果 / 警告 / CTA

## 3. Requirement Verification Workspace

- [x] 3.1 依 Acceptance Criteria 產生 section 清單與預設 `ticket_key.010/020/030...` 編號，支援調整起始 section 號碼
- [x] 3.2 依 `tcrt-ui-style` 實作左側 section rail、右側 section 編輯區、Given/When/Then 摘要、下方 Criteria / Technical Specifications 參考區與 sticky action bar
- [x] 3.3 實作四種驗證項目分類：`API`、`UI`、`功能驗證`、`其他`，並定義對應必填欄位
- [x] 3.4 實作檢查條件編輯器，要求每條件填寫自然語言描述與 coverage 類型：`Happy Path`、`Error Handling`、`Edge Test Case`、`Permission`
- [x] 3.5 實作每五秒 autosave 與手動「儲存」按鈕
- [x] 3.6 實作 requirement lock / unlock，未鎖定不得產生 seeds；unlock 後需失效 downstream seed/testcase 狀態

## 4. Seed Generation and Seed Review

- [x] 4.1 定義 `ai.qa_ai_helper.models.seed / seed_refine / testcase` 的 settings contract，支援 `config.yaml` 與 `.env` / process environment override
- [x] 4.2 更新 `app/config.py`、`config.yaml.example` 與 loader，支援 `${ENV_VAR}` placeholder 解析、stage model env key mapping 與 unresolved placeholder fail-fast
- [x] 4.3 定義 high-tier seed generation prompt / model contract，輸入為鎖定 requirement plan
- [x] 4.4 設計 `qa_ai_helper_seed_sets` / `qa_ai_helper_seed_items` 或等效 persistence 結構
- [x] 4.5 在畫面四顯示 seed cards：包含 reference、來源 section/item 摘要、AI 標記、註解入口與 hover 預覽
- [x] 4.6 實作每筆 seed 的納入/排除開關，預設全納入，並提供 section-level 全部納入 / 全部排除操作
- [x] 4.7 實作註解驅動的 diff-only refinement，只送出新增或修改過的 seed 註解，不重跑全量 seeds；無 dirty comment 時不觸發
- [x] 4.8 實作 seed lock / unlock，未鎖定 seed set 不得進入 testcase generation
- [x] 4.9 確保畫面四不提供手動新增 seed / 刪除 seed 的 UI 或 API，維持 seed traceability

## 5. Testcase Generation and Review

- [x] 5.1 定義 low-tier testcase generation prompt / model contract，要求模型回傳 body fields 與 seed/reference key，不負責編號
- [x] 5.2 實作本地 testcase numbering allocator，支援 section + 驗證項目 block (`010`, `100`, `200`...) 的遞延規則
- [x] 5.3 在畫面五顯示 testcase draft cards，僅允許編修 `title / priority / preconditions / steps / expected results`，並將 testcase ID 與 seed/reference 欄位維持唯讀
- [x] 5.4 實作「勾選要 commit 的 testcase」機制，預設不自動全選，支援 section-level 全選 / 清除選取，未勾選不得進入 commit payload
- [x] 5.5 實作 testcase validation 與 seed-reference 對應檢查：`title`、`steps`、`expected results` 缺漏時不可勾選，且至少一筆有效勾選後才能進入畫面六
- [x] 5.6 實作 upstream seed 變更後的 testcase draft supersede 規則，要求畫面五重新生成
- [x] 5.7 確保畫面五不提供手動新增 testcase draft / 刪除 testcase draft 的 UI 或 API，維持 traceability

## 6. Test Case Set Selection and Commit Result

- [x] 6.1 實作畫面六的既有 Test Case Set 選擇與新建 Test Case Set 流程，兩種模式互斥，且新建模式需先通過必要欄位驗證
- [x] 6.2 實作 commit，只提交勾選且通過 validation 的 testcase 到唯一目標 Test Case Set
- [x] 6.3 實作 per-draft commit result 收斂：建立成功項目的 `commit_links`，保留 failed/skipped 結果與原因
- [x] 6.4 實作畫面七的新增結果摘要與導向目標 Test Case Set 畫面，顯示 created / failed / skipped 數量與明細

## 7. Persistence, Provenance, and Adoption Metrics

- [x] 7.1 以 `qa_ai_helper_*` 命名空間建立 V3 語意資料表：`sessions`、`ticket_snapshots`、`requirement_plans`、`plan_sections`、`verification_items`、`check_conditions`、`seed_sets`、`seed_items`、`testcase_draft_sets`、`testcase_drafts`、`commit_links`、`events`
- [x] 7.2 新增 seed persistence、commit linkage 與 AI provenance 欄位，能標示哪些 seed / testcase 為 AI 產生
- [x] 7.3 定義並實作 seed adoption rate 與 testcase adoption rate 的計算、儲存與查詢方式，其中 seed adoption 以 `included_seed_count / generated_seed_count` 為準，testcase adoption 以 `selected_for_commit_count / generated_testcase_count` 為準
- [x] 7.4 補齊 `database_init.py` required-table verification、Alembic migration 與 `scripts/db_cross_migrate.py` 相容性
- [x] 7.5 將 legacy helper 的 session / telemetry / phase 統計刪除策略納入 migration 與 rollout runbook，確認 purge 後不影響 V3 schema bootstrap

## 8. Tests and Documentation

- [x] 8.1 補齊 parser / format-gate 測試，覆蓋必要段落缺漏與 markdown render case
- [x] 8.2 補齊畫面三 autosave、manual save、lock / unlock workflow 測試
- [x] 8.3 補齊 settings loader / `.env` override / unresolved placeholder fail-fast 測試，覆蓋 seed / seed_refine / testcase stage model routing
- [x] 8.4 補齊 seed generation / seed refinement / include-exclude / seed lock contract tests
- [x] 8.5 補齊 testcase numbering allocator、commit selection 與 adoption metrics tests
- [x] 8.6 補齊 legacy purge / no-backfill 決策測試與驗證腳本，確認舊 session / 舊統計不再被讀取
- [x] 8.7 更新 runbook、操作文件與 OpenSpec 關聯文件，說明七畫面流程、parser gate、TCRT UI 依循方式、stage model env 設定方式與 legacy 資料清除策略
