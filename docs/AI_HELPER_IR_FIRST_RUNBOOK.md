# AI Agent Test Case Helper IR-first 流程與穩定性手冊

## 1. 適用範圍

本文件描述 `JIRA Ticket -> Test Case Helper` 的完整流程（含 IR、Analysis/Coverage、Testcase/Audit）、保證內容完整性的機制，以及常見故障排查。

## 2. 端到端流程（現行）

1. `fetch_ticket`：
   - 讀取 JIRA ticket（summary/description/components）。
   - 不再要求先做「需求整理 UI 編輯」才能進入分析。
2. `build_requirement_ir`：
   - 將 ticket 內容轉為 machine-readable IR。
   - 目標是完整保留需求資訊，不可任意新增需求。
3. `analysis`：
   - 以 IR 產生可執行 analysis item（含 `chk/exp/rid`）。
   - 禁止只輸出 `REF-xxx` 代號，不可用區間寫法。
4. `coverage`：
   - 產生 pre-testcase seed（1 seed 對應 1 未來 testcase）。
   - 每筆 seed 必須包含 `t/chk/exp/pre_hint/step_hint`。
5. coverage gate：
   - `validate_coverage_completeness` 檢查 `missing_ids/missing_sections`。
   - 先跑 LLM backfill，再由 deterministic backfill 補齊缺漏，確保可覆蓋 analysis。
6. `pretestcase`：
   - 將 seed 正規化為 section + entry，並套用 `010, 020, 030...` 編號規則。
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
- 解析失敗補救鏈：
  - 初次呼叫 -> 完整重生 -> JSON repair。
  - 偵測 `finish_reason=length/max_tokens` 視為可能截斷，強制走補救。
- coverage 完整性 gate：
  - 不允許 analysis 條目無 coverage 對應。
  - 缺漏由 backfill + deterministic backfill 補齊。
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
- `coverage_backfill_max_rounds`：coverage 缺漏的 LLM 補全回合數
- `coverage_backfill_chunk_size`：每回合補全的缺漏批次大小
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

- `regenerate_applied`
- `repair_applied`
- coverage `completeness`（`missing_ids/missing_sections`）

## 6. 常見故障與排查

### 6.1 `Coverage 回傳 JSON 解析失敗`

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

## 7. 回退策略

若需快速止血：

1. 降低每次輸入內容長度（優先分批）
2. 暫時降低 LLM 回合複雜度（仍保留 deterministic 補齊）
3. 必要時可關閉 `enable_ir_first` 做 A/B 觀測
