## Why

目前 QA AI Helper 的「需求驗證項目分類與填充」(VERIFICATION_PLANNING) 畫面完全依賴使用者手動填寫驗證項目與檢查條件。
PoC (`scripts/ac_inspection_poc.py`) 已驗證「多低階模型角色分工並行 extraction + 高階模型統合」的架構可行——三個低階模型各自專注不同面向（Happy Path + Permission / Edge Cases + Performance / Error Handling + Abuse），由高階模型統合去重並補遺，能在數秒內產出高品質的檢驗項目清單。

此變更將 PoC 成果整合進正式的 QA AI Helper 工作流，讓使用者在確認需求後可一鍵產生 AI 建議的驗證項目，再於畫面上自行增刪修改，大幅降低手動規劃的工作量。

同時，因為多模型協作流程較長（3N 次低階呼叫 + 1 次高階呼叫），需要在前端加入仿 Evangelion MAGI 系統的過場動畫，讓使用者清楚當前階段進度；後續 seed 產生與 testcase 產生也需加入「AI 思考中...」動畫，避免使用者以為系統無反應。

## What Changes

- **新增 MAGI 多模型 inspection 流程**：在 TICKET_CONFIRMATION → VERIFICATION_PLANNING 之間，新增 AI 自動產生驗證項目的能力
  - Phase 1：三個低階角色模型，**每個 AC Scenario 獨立呼叫**，並行 extraction（3 models × N scenarios = 3N 呼叫）
  - Phase 2：一個高階模型統合所有 Scenario 的三模型結果，產出結構化的驗證項目（非 markdown，而是可直接 parse 為 PlanSection / VerificationItem / CheckCondition 的格式）
  - 統合結果自動填充進 VERIFICATION_PLANNING 畫面的資料結構
  - 使用者保留完整的增刪修改能力（AI 僅為初始填充）
- **中間層資料壓縮**：低階模型的 extraction 輸出與高階模型的統合輸出均採壓縮格式（pipe-delimited 或 compact JSON），不做易讀排版，降低 token 消耗
- **模型可配置化**：三個低階模型 ID 與高階統合模型 ID 均可透過 `config.yaml` 及環境變數指定
- **MAGI 過場動畫**：前端新增仿 Evangelion MAGI 系統風格的動畫元件，在多模型 inspection 流程中顯示：
  - 三個低階模型的即時狀態（呼叫中 / 完成 / 失敗）
  - 高階模型統合階段
  - 當前所在階段的視覺指示
- **AI 思考動畫**：seed 產生與 testcase 產生流程中新增簡易「AI 思考中...」動畫
- **新增 inspection prompt 模板**：`prompts/jira_testcase_helper/inspection_extraction.md` 與 `prompts/jira_testcase_helper/inspection_consolidation.md`

## Capabilities

### New Capabilities
- `helper-magi-inspection`: MAGI 多模型協作 inspection 流程——從結構化需求自動產生驗證項目並填充至 VERIFICATION_PLANNING，含模型配置、角色分工、結構化輸出、結果 parse 與填充邏輯
- `helper-ai-progress-animation`: QA AI Helper 各 LLM 呼叫階段的前端進度動畫——MAGI 過場（inspection）、AI 思考中（seed / testcase）

### Modified Capabilities
- `helper-guided-intake`: 在 TICKET_CONFIRMATION 確認後新增「AI 產生驗證項目」觸發點，VERIFICATION_PLANNING 初始化邏輯需支援 AI 填充結果的匯入

## Impact

- **後端**：
  - `app/services/qa_ai_helper_service.py`：新增 inspection 流程編排（Phase 1 並行 + Phase 2 統合 + 結果填充）
  - `app/services/qa_ai_helper_llm_service.py`：新增 `inspection_extraction` 與 `inspection_consolidation` 兩個 LLM stage
  - `app/services/qa_ai_helper_prompt_service.py`：新增 inspection prompt 載入
  - `app/api/qa_ai_helper.py`：新增 inspection 觸發 API endpoint（可能為 SSE 以回報即時進度）
  - `app/config.py`：新增 inspection model 設定（`models.inspection_extraction_a/b/c` + `models.inspection_consolidation`）
- **前端**：
  - `app/static/js/qa-ai-helper/main.js`：整合 inspection 觸發流程、MAGI 動畫、AI 思考動畫
  - `app/static/css/qa-ai-helper.css`：MAGI 動畫與 AI 思考動畫樣式
- **Prompt**：
  - 新增 `prompts/jira_testcase_helper/inspection_extraction.md`
  - 新增 `prompts/jira_testcase_helper/inspection_consolidation.md`
- **Config**：`config.yaml` 新增 inspection 相關模型設定區塊，支援環境變數覆蓋
- **Migration**：無 DB schema 變更（inspection 結果直接寫入現有的 RequirementPlan / PlanSection / VerificationItem / CheckCondition 資料結構）
- **Rollback**：inspection 功能為可選觸發（使用者仍可手動填寫），停用只需移除觸發入口，無破壞性影響
