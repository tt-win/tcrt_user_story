## 1. Config 與基礎設施擴展

- [x] 1.1 在 `QAAIHelperModelsConfig` 新增 `inspection_extraction_a`、`inspection_extraction_b`、`inspection_extraction_c`、`inspection_consolidation` 四個 stage model 欄位，含預設模型與 temperature
- [x] 1.2 在 `QAAIHelperModelsConfig.from_env` 新增四個 inspection stage 的環境變數覆蓋（`QA_AI_HELPER_MODEL_INSPECTION_EXTRACTION_A` 等）
- [x] 1.3 更新 `config.yaml.example` 新增 inspection 模型設定區塊與註解
- [x] 1.4 定義 `InspectionRoleConfig` pydantic model 並在 config.yaml 新增 `inspection.roles` 區塊（label、role_name、role_focus），含合理預設值
- [x] 1.5 在 config.yaml 新增 `inspection.max_scenarios_warning` 設定（預設 5），超過此值時前端提醒使用者

## 2. Prompt 模板

- [x] 2.1 擴展 `QAAIHelperPromptStage` 加入 `inspection_extraction` 與 `inspection_consolidation`
- [x] 2.2 在 `PROMPT_FILE_MAP` 加入對應的 prompt 檔案名稱
- [x] 2.3 將 PoC 的 `prompts/ac_inspection/extraction.md` 移至 `prompts/jira_testcase_helper/inspection_extraction.md`，調整 placeholder 與現有機制一致
- [x] 2.4 將 PoC 的 `prompts/ac_inspection/consolidation.md` 移至 `prompts/jira_testcase_helper/inspection_consolidation.md`，修改輸出格式要求為結構化 JSON schema
- [x] 2.5 驗證 `render_stage_prompt` 對新 stage 的 placeholder 替換正確運作

## 3. LLM 呼叫層擴展

- [x] 3.1 擴展 `QAAIHelperLLMStage` type alias 加入 inspection 相關 stage
- [x] 3.2 擴展 `_stage_config` 方法支援 inspection stage 的模型設定解析（含 fallback 邏輯）
- [x] 3.3 新增 `call_inspection_extraction(role_label: str, prompt: str)` 方法，根據 role_label 選擇對應模型
- [x] 3.4 新增 `call_inspection_consolidation(prompt: str)` 方法，強制使用 `response_format: {"type": "json_object"}`
- [x] 3.5 確保 inspection 呼叫共用現有的 `max_concurrent_llm_calls` semaphore

## 4. 狀態機與核心流程

- [x] 4.1 在 `_SESSION_SCREEN_TRANSITIONS` 新增 `magi_inspection` screen 狀態（ticket_confirmation → magi_inspection → verification_planning）
- [x] 4.2 新增 `run_magi_inspection` async 方法，編排 Phase 1 並行 extraction + Phase 2 consolidation
- [x] 4.3 實作 Phase 1 邏輯：從 ticket_snapshot 取出 AC Scenarios，為每個 scenario × 每個 role 建立 extraction 呼叫，以 `asyncio.gather` 並行執行
- [x] 4.4 實作 Phase 2 邏輯：收集 Phase 1 結果，組裝 consolidation prompt，呼叫高階模型產出 JSON
- [x] 4.5 實作 `_transform_inspection_to_sections_payload` 轉換函式，將 consolidation JSON 轉為 `_replace_requirement_plan_sections_sync` 期望的格式
- [x] 4.6 實作結果填充：呼叫 `_replace_requirement_plan_sections_sync` 將 inspection 結果寫入 requirement plan
- [x] 4.7 實作 partial failure 容錯：Phase 1 至少一個模型成功即繼續，全部失敗則 fallback
- [x] 4.8 實作 consolidation JSON schema 驗證，驗證失敗時嘗試一次 repair call

## 5. SSE Endpoint 與進度推送

- [x] 5.1 新增 API endpoint `POST /teams/{team_id}/qa-ai-helper/sessions/{session_id}/magi-inspection`，回傳 `StreamingResponse (text/event-stream)`
- [x] 5.2 定義 SSE 事件格式：`extraction_complete`、`extraction_error`、`phase_change`、`consolidation_complete`、`consolidation_error`、`done`
- [x] 5.3 在 `run_magi_inspection` 中注入 callback 機制，每個步驟完成時推送對應 SSE 事件
- [x] 5.4 實作 SSE 連線的 timeout 與 client disconnect 偵測

## 6. 前端 - MAGI 過場動畫

- [x] 6.1 建立 `app/static/js/qa-ai-helper/magi-animation.js` 模組，封裝 MAGI 動畫邏輯
- [x] 6.2 實作三面板佈局（MELCHIOR / BALTHASAR / CASPER 對應三個角色模型），含狀態指示燈
- [x] 6.3 實作 SSE 事件監聽，即時更新各模型面板狀態（呼叫中 / 完成 / 失敗）
- [x] 6.4 實作 Phase 1 → Phase 2 階段過渡動畫
- [x] 6.5 新增 MAGI 動畫 CSS 樣式至 `app/static/css/qa-ai-helper.css`（配色方案與字型風格）
- [x] 6.6 在 TICKET_CONFIRMATION 確認後新增「AI 產生驗證項目」觸發按鈕
- [x] 6.7 實作取消功能：使用者可在動畫進行中取消 inspection，中止 SSE 連線

## 7. 前端 - AI 思考動畫

- [x] 7.1 建立 `app/static/js/qa-ai-helper/ai-thinking-animation.js` 模組
- [x] 7.2 實作「AI 思考中...」動畫元件，含脈動或旋轉指示器
- [x] 7.3 在 seed generation 呼叫前後掛載 / 卸載思考動畫
- [x] 7.4 在 testcase generation 呼叫前後掛載 / 卸載思考動畫
- [x] 7.5 新增思考動畫 CSS 樣式

## 8. Guided Intake 整合

- [x] 8.1 修改 `initialize_requirement_plan` 流程，支援從 inspection 結果初始化 plan（而非僅由 deterministic planner）
- [x] 8.2 實作跳過 AI inspection 的流程：使用者選擇跳過時直接進入空的 VERIFICATION_PLANNING
- [x] 8.3 確保 AI 填充結果與 deterministic planner section 結構的合併邏輯正確

## 9. i18n 與設定文件

- [x] 9.1 更新 `app/static/locales/` 對應語系檔，新增 MAGI 動畫、AI 思考動畫、inspection 相關文案
- [x] 9.2 更新 Jinja2 模板引入新的 JS/CSS 資源

## 10. 測試

- [x] 10.1 撰寫 config 擴展的單元測試（inspection model 設定載入、環境變數覆蓋、fallback）
- [x] 10.2 撰寫 prompt 載入的單元測試（新 stage 的模板載入與 placeholder 替換）
- [x] 10.3 撰寫 LLM 呼叫層的單元測試（inspection extraction / consolidation 的 mock 呼叫）
- [x] 10.4 撰寫 inspection 核心流程的整合測試（Phase 1 並行 + Phase 2 + 結果填充 + partial failure）
- [x] 10.5 撰寫 SSE endpoint 的 API 測試（事件格式、連線管理）
- [x] 10.6 撰寫 consolidation JSON → sections payload 轉換的單元測試
- [x] 10.7 執行既有 `pytest app/testsuite -q` 確認無 regression
