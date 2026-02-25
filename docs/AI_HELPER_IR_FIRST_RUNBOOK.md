# AI Agent Test Case Helper IR-first 流程與穩定性手冊

## 1. 適用範圍

本文件描述 `JIRA Ticket -> Test Case Helper` 的完整流程（含 IR、Analysis/Coverage、Testcase/Audit）、保證內容完整性的機制，以及常見故障排查。

## 2. 端到端流程（現行）

1. `fetch_ticket`：
   - 讀取 JIRA ticket（summary/description/components）。
   - 不再要求先做「需求整理 UI 編輯」才能進入分析。
2. `structured requirement parser + validator`：
   - 先將 requirement 解析成標準契約：`Menu/User Story Narrative/Criteria/Technical Specifications/Acceptance Criteria/API 路徑`。
   - 產出 `structured_requirement` 與 `requirement_validation`（`missing_sections/missing_fields/quality_level`）。
   - 若格式不完整，回傳 warning gate，需使用者明確選擇「仍要繼續」才可前進（`override_incomplete_requirement=true`）。
3. `build_requirement_ir`：
   - 將 ticket 內容轉為 machine-readable IR。
   - 目標是完整保留需求資訊，不可任意新增需求。
4. `analysis + coverage (single prompt)`：
   - 以 IR 一次產生可執行 analysis item（含 `chk/exp/rid`）與 coverage seed。
   - 禁止只輸出 `REF-xxx` 代號，不可用區間寫法。
   - 每筆 coverage seed 必須包含 `t/chk/exp/pre_hint/step_hint`。
5. coverage gate：
   - `validate_coverage_completeness` 檢查 `missing_ids/missing_sections`。
   - 合併輸出若缺漏，先做同階段 LLM coverage 補全重試；重試仍失敗才由 deterministic backfill 補齊，確保可覆蓋 analysis。
6. `pretestcase`：
   - 將 seed 正規化為 section + entry，並套用 `010, 020, 030...` 編號規則。
   - 每條 entry 直接附帶 `requirement_context`（`summary/spec_requirements/verification_points/expected_outcomes`）。
7. `generate_testcases`（section 分批）：
   - 以單一 section 為單位呼叫 LLM 生成 testcase。
   - 此階段才查 Qdrant（`jira_references` + `test_cases`）。
8. `testcase_supplement` + deterministic fallback：
   - 若 section 內有缺漏/不完整條目，先補呼叫 LLM。
   - 仍不足則以 deterministic 規則補成完整 testcase。
9. `audit`（section 分批）：
   - 同 section 單位審核補強。
   - 最終保存 draft，等待使用者確認後 commit。

## 3. 完整性與前後連貫保證機制

- JSON 輸出穩定化：
  - JSON 階段優先用 `response_format: {"type":"json_object"}`。
  - 若模型不支援，會自動降級回 prompt-only JSON 規範，不中斷流程。
- requirement 契約 gate：
  - `structured_requirement` 驗證失敗時，不會直接進 analysis。
  - 使用者必須明確 override 才能繼續，並寫入 `override_trace`（actor/time/missing snapshot）。
- 解析失敗補救鏈：
  - 初次呼叫 -> 完整重生 -> JSON repair。
  - 偵測 `finish_reason=length/max_tokens` 視為可能截斷，強制走補救。
- coverage 完整性 gate：
  - 不允許 analysis 條目無 coverage 對應。
  - 缺漏先同階段補全重試，再由 deterministic backfill 補齊（不再做 coverage 專用 stage 呼叫）。
- testcase 對齊防錯：
  - 不再只靠陣列 index，改為 `id -> cid -> title -> 順序` 多層對齊，降低條目錯位。
- 小批次策略：
  - testcase/audit 以 section 分批，降低低推理模型在長上下文下失真機率。

## 4. 重要設定（config.yaml）

路徑：`ai.jira_testcase_helper`

- `models.analysis`：預設 `google/gemini-3-flash-preview`
- `models.coverage`：預設 `openai/gpt-5.2`
- `models.testcase`：預設 `google/gemini-3-flash-preview`
- `models.audit`：預設 `google/gemini-3-flash-preview`
- `coverage_backfill_max_rounds`：保留相容欄位；在合併模式下固定停用（0）
- `coverage_backfill_chunk_size`：每回合補全的缺漏批次大小
- `prompt_contract_version`：prompt 契約版本
- `payload_contract_version`：draft payload envelope 版本
- `prompts.*`：所有階段 prompt，含 `requirement_ir/analysis/coverage/coverage_backfill/testcase/testcase_supplement/audit`

## 5. Draft 與追蹤資料

`ai_tc_helper_drafts` 主要 phase：

- `jira_ticket`
- `requirement_ir`
- `analysis`
- `coverage`
- `pretestcase`
- `testcase`
- `audit`
- `final_testcases`

關鍵欄位：

- envelope：`schema_version/phase/data/quality/trace`
- requirement phase：
  - `structured_requirement`
  - `requirement_validation`
  - `override_trace`
- `regenerate_applied`
- `repair_applied`
- coverage `completeness`（`missing_ids/missing_sections`）
- pretestcase：
  - `requirement_context.summary/spec_requirements/verification_points/expected_outcomes`

## 6. 常見故障與排查

### 6.1 `Analysis(合併 Coverage) 回傳 JSON 解析失敗`

可能原因：

1. 模型輸出截斷（長度超過上限）
2. 模型未完全遵循 JSON 格式
3. provider 回傳 content 片段化

排查：

1. 看 draft 是否 `regenerate_applied=true`、`repair_applied=true`
2. 看 `finish_reason` 是否 `length` 類型
3. 調整 prompt 長度或分批策略（避免單次負載過大）

### 6.2 `OpenRouter 回傳內容為空`

可能原因：

1. provider 臨時異常
2. 回傳格式不在既有擷取路徑
3. 請求參數不被該模型接受

排查：

1. 查 API error body / status
2. 確認該模型是否支援 `response_format`
3. 確認重試後是否已自動降級成功

### 6.3 coverage/section testcase 數量不一致

處理策略：

1. 先做 supplement
2. 再用 deterministic testcase fallback 補齊
3. 最後 validate `steps/exp`（`exp` 必須單一條）

### 6.4 requirement warning 觸發頻率異常偏高

排查：

1. 查 `requirement_validation.missing_sections/missing_fields` 分布是否集中在同一欄位。
2. 查 `override_trace` 比例（同版本是否持續升高）。
3. 先優化 requirement 範本與提示，再調整 parser 規則。

## 7. Rollout 與回退策略

若需快速止血：

1. 降低每次輸入內容長度（優先分批）
2. 暫時降低 LLM 回合複雜度（仍保留 deterministic 補齊）
3. 必要時可關閉 `enable_ir_first` 做 A/B 觀測

建議 rollout：

1. 先在單一團隊啟用 requirement warning gate，觀察 `missing_sections/missing_fields` 分布。
2. 再擴大到全量團隊，持續觀察 override 比率與 pretestcase 編修比率。
3. 若 override 比率異常，先凍結 rollout，回頭修正 parser/validator 規則後再擴。

rollback：

1. 前端暫時以 `override_incomplete_requirement=true` 直接放行（保留 trace）。
2. 後端保留 parser 但關閉 gate（只記錄 `requirement_validation` 不阻擋）。
3. 必要時回退到舊版 pretestcase 呈現（仍保留 `requirement_context` 欄位，不刪資料）。
