## Why

TCRT 全域 AI Assistant 在處理大量作業（例如一次改寫數十隻 test case）時，經常因為單一 LLM 呼叫需要規劃與產出過多內容而觸發 timeout、輸出截斷（finish_reason=length）或回應過大導致解析失敗。現有 `batch_execute_actions` 複合工具雖可一次執行多個 action，但前提是 LLM 已經在一次 response 中產出所有 action 的完整參數，這正是瓶頸所在。本變更引入 plan-and-chunk 機制，把大規模批次作業拆成多次輕量 LLM 規劃與多次確認，讓大量規劃與回應的场景能夠穩定完成。

## What Changes

- 新增 `plan_batch` read 工具：讓 LLM 先產出輕量 batch plan（目標清單、分組策略、chunk 大小與順序）。
- 新增 `generate_chunk_actions` read 工具：讓 LLM 只針對單一 chunk 產出完整 action 參數。
- 新增 chunk 編排器：依 plan 迭代 chunk，每個 chunk 建立一個 `batch_execute_actions` pending action。
- 新增自動繼續授權機制：使用者可在首次確認時選擇信任後續同質 chunk 自動執行；授權僅限該 batch job，不跨 session、不記憶。
- 新增 batch progress 事件協定：`batch_plan_ready`、`batch_chunk_generated`、`batch_chunk_pending`、`batch_chunk_executed`、`batch_completed`、`batch_paused`、`batch_cancelled`。
- 擴充 `batch_execute_actions` 的 journal 記錄：在 result payload 中記錄每個子 action 的 outcome，支援 chunk 內中斷後識別未執行子集。
- 在 executor 加入 batch size guardrail：當 `batch_execute_actions` 的 action 數量或總參數大小超過門檻時，以 fixable 錯誤引導 LLM 改用 plan-and-chunk。
- 更新 system prompt 與 skill recipe：引導 LLM 在大量目標或複雜修改前優先使用 `plan_batch`。
- 不改變核心 agent loop、不改變 `batch_execute_actions` 整體 succeeded/failed/unknown 語意、不新增外部儲存或佇列、不新增 Python 套件。

## Capabilities

### New Capabilities

- `assistant-batch-planning`: 定義 `plan_batch` 工具的輸入輸出、plan 結構、目標驗證與分組策略。
- `assistant-batch-chunk-generation`: 定義 `generate_chunk_actions` 工具如何為單一 chunk 產出完整 action 參數，並受 plan 與 size 約束。
- `assistant-batch-orchestration`: 定義 chunk 編排器、batch progress 事件、自動繼續授權與停止機制。
- `assistant-batch-resume`: 定義 chunk 內中斷後如何識別未執行子集並以新 batch 繼續。

### Modified Capabilities

- `assistant-tool-execution`: 擴充 `batch_execute_actions` 的 journal 記錄格式，並新增 action 數量與參數大小的 fixable 上限。
- `assistant-agent-loop`: 明確 agent loop 遇到 batch plan / chunk generation 工具時的處理方式，以及 batch progress 事件如何與現有 SSE 事件共存。

## Impact

- 後端：新增 `app/services/assistant/tools_batch_planning.py` 與 chunk 編排邏輯；修改 `app/services/assistant/tool_executor.py`（batch size guardrail 與細部 journal）、`app/services/assistant/assistant_agent_service.py`（batch progress 事件）、`app/services/assistant/content_store.py`（system prompt / skill catalog 引導）。
- 資料庫：不新增 table；僅在現有 `assistant_tool_executions.result_payload_json` 與 `assistant_events.payload_json` 中增加結構化欄位，屬 backward-compatible JSON 擴充。
- API：不新增公開 REST endpoint，僅新增內部 assistant read 工具與 SSE event type。
- 前端：現有 widget 可先透過 SSE 事件呈現 batch progress；完整 batch job 視圖可留待後續變更。
- i18n：新增 batch progress 相關文案到 `app/static/locales/`。
- 部署：符合 Docker 化方向，不寫本機檔案；不新增 Python 套件；與現有 admission / lease / recovery 機制相容。
