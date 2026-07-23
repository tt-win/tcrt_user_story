## Context

TCRT 全域 AI Assistant 已經具備完整的 agent 迴圈、write 確認流程、`batch_execute_actions` 複合工具、DB-tail SSE 續傳、admission / lease / recovery 機制。當使用者要求大量修改（例如「把 50 隻 test case 的步驟改成熟練流程」）時，LLM 必須在一次 response 中產出 50 隻 test case 的完整參數，這經常觸發：

- `llm_timeout_seconds`（60s）逾時
- `finish_reason=length` 截斷
- 回應 JSON 過大，解析失敗或被截斷後參數殘缺

現有 `batch_execute_actions` 可以一次執行最多 50 個 action，但它假設所有 action 參數已經準備好。問題在於**參數產出階段**過重。

本設計引入 plan-and-chunk 模式：LLM 先產輕量 plan，再分 chunk 產詳細參數，每個 chunk 對應一個 `batch_execute_actions` pending。如此一來，單一 LLM 呼叫只處理 bounded 工作量，整體作業可以分段完成、分段確認、中斷後續傳。

## Goals / Non-Goals

**Goals:**
- 讓 assistant 能夠穩定處理需要大量 LLM 規劃與回應的批量作業。
- 把單一大量 LLM 輸出拆成多次輕量輸出（plan + per-chunk actions）。
- 每個 chunk 沿用現有的 pending / confirm / journal / recovery 機制，不引入新的權限或確認模型。
- 提供使用者可選的「自動繼續」模式，減少重複確認，但仍保留控制與可觀測性。
- 中斷後可以從下一個 chunk 或 chunk 內未執行子集繼續，不需要重頭規劃。
- 所有狀態存在現有 DB（assistant_messages / assistant_events / assistant_tool_executions），不寫本機檔案。
- 不新增 Python 套件，不改變核心 agent loop。

**Non-Goals:**
- 不是通用 workflow engine，不取代 Celery / Airflow / Temporal。
- 不改變現有 QA AI Helper 的七屏流程。
- 本次不實作新的前端頁面；只透過 SSE 事件讓現有 widget 可呈現進度。
- 不處理外部不可補償副作用（例如已寄出的 email、已觸發的 webhook），只記錄並要求啟動前確認。

## Decisions

### Decision 1：在現有 agent loop 外新增 read 工具，不改核心迴圈

**選項：**
- A. 修改 `_run_llm_loop` 加入 batch 特殊狀態。
- B. 新增 `plan_batch` 與 `generate_chunk_actions` 兩個 read 工具，由 LLM 自行決定何時呼叫。

**選擇 B。**

**理由：**
- 核心 agent loop 已經很複雜，修改它會提高迴歸風險。
- 新增 read 工具符合現有工具目錄模式，LLM 可以選擇使用，小批量仍可走原有 `batch_execute_actions`。
- 更容易測試與隔離。

### Decision 2：每 chunk 對應一個 `batch_execute_actions` pending

**選項：**
- A. 設計新的 composite action 類型。
- B. 沿用 `batch_execute_actions`，每個 chunk 產生一個 pending。

**選擇 B。**

**理由：**
- 複用現有的確認卡、權限驗證、fingerprint、confirm/cancel/expire/recovery 機制。
- 不需要改變 `assistant_pending_actions` schema。
- 每個 chunk 的確認範圍清晰、原子、可追蹤。

### Decision 3：自動繼續授權採用「信任使用者判斷」模式

**選項：**
- A. 系統根據風險等級自動決定哪些 chunk 可自動執行。
- B. 由使用者在首次確認時明確授權後續同質 chunk 自動執行。

**選擇 B。**

**理由：**
- 避免系統默默替使用者決定高風險操作。
- 授權範圍明確、可撤銷、不記憶。
- 符合 TCRT 現有「寫入必須經過確認」的設計哲學。

### Decision 4：Batch 進度與授權狀態存在現有 event/message 表

**選項：**
- A. 新增 `assistant_batch_jobs` table。
- B. 把進度摘要與授權記錄存在 `assistant_events` 與 `assistant_messages`。

**選擇 B。**

**理由：**
- 不新增 DB table，減少 migration 與 schema 維護成本。
- 進度摘要輕量，可放進 event payload。
- 重啟後可從現有 event/message 重建狀態。
- 缺點是 query 時需要解析 JSON，但 batch job 數量與查詢頻率可控。

### Decision 5：Chunk 內中斷後用新 batch 繼續未執行子集

**選項：**
- A. 修改 `batch_execute_actions` 整體狀態語意，允許部分成功。
- B. 保留整體 unknown 語意，但記錄每個子 action outcome，用新 batch 繼續未執行子集。

**選擇 B。**

**理由：**
- 不改變現有「整批 unknown 不重試」的核心規則。
- 利用 execution_key 唯一性與 journal 記錄，避免已執行子 action 重複執行。
- 新 batch 仍然經過完整 confirm 流程，安全。

### Decision 6：Plan 輸出必須輕量且經過目標驗證

**選項：**
- A. Plan 包含完整 test case 內容。
- B. Plan 只含 id + 摘要 + 分組，系統用 read 工具驗證 id 存在。

**選擇 B。**

**理由：**
- 減少 plan 階段的 LLM 輸出大小，避免再次觸發截斷。
- 驗證後的 plan 更可靠，減少 LLM 幻覺影響。

## Risks / Trade-offs

| 風險 | 影響 | 緩解 |
|------|------|------|
| LLM 不聽從引導，硬塞大量 action 到 batch_execute_actions | 單一 LLM 呼叫仍可能超載 | executor 加入 action 數量與參數大小 guardrail，超過時回 fixable error 引導使用 plan_batch |
| Plan 階段輸入 context 過大 | 目標 list 超過 tool_result budget | 先用 count 工具確認數量，大量時只傳摘要/分頁，要求使用者縮小範圍 |
| 自動繼續授權被濫用或誤用 | 後續 chunk 自動執行未經審查 | 授權綁定 batch_job_id / JWT session；偏離 plan 或高風險時強制人工確認；提供立即停止 API |
| Chunk 之間目標狀態改變 | 已刪除/移動的 test case 被納入後續 chunk | 每 chunk 開始前重新驗證目標存在與 team 歸屬 |
| 對話歷史膨脹 | batch progress 訊息累積 | progress 摘要輕量；必要時可在 batch 結束後壓縮成單一總結訊息 |
| 多個 batch job 同時進行 | 進度與授權混淆 | 每個 batch job 有唯一 id；一對話同時只允許一個進行中 batch job |
| 測試複雜度提高 | 涉及 plan、chunk、confirm、resume、stale 等多條路徑 | 分 MVP 實作；每階段都有單元與整合測試 |
| 不新增套件限制未來擴展 | 若規模持續放大，可能需要 queue/object storage | 現階段用 DB + 輕量狀態；未來需要時再評估 |

## Migration Plan

1. **Schema**：不新增 table，不須 migration；JSON payload 擴充為 backward-compatible。
2. **程式碼**：
   - 新增 `app/services/assistant/tools_batch_planning.py`。
   - 修改 `app/services/assistant/tool_executor.py`（guardrail、journal 記錄）。
   - 修改 `app/services/assistant/assistant_agent_service.py`（batch progress event）。
   - 修改 `app/services/assistant/content_store.py` 與 skill catalog（引導 LLM）。
   - 新增/更新 i18n 文案。
3. **部署**：feature branch 合併後直接部署；無特殊 rollback 需求，若發現問題可移除新工具註冊與 system prompt 引導。
4. **測試**：
   - contract tests 驗證新工具 registry 註冊與 schema。
   - 單元測試驗證 chunk 編排、guardrail、progress event。
   - 整合測試模擬完整 plan → chunk → confirm → resume 流程。

## Open Questions

1. MVP 1 是否先不實作 partial resume，只做 plan + chunk + 人工確認？
2. 自動繼續授權的 UI 呈現方式（確認卡內的 checkbox / 獨立 event）是否需前端配合？
3. Batch progress event 的 payload 欄位是否需要與前端預先對齊？
4. 是否需要把 batch plan 與 chunk generation 也納入現有 skill recipe 範本？
