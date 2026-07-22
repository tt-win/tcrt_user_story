## Why

Global AI assistant 已可用，但 **context budget 與工具結果形狀** 以短對話／小列表假設寫死：`history_max_chars=48k`、`tool_result_max_chars=8k`、list 結果整包 hard-truncate、`max_iterations=8`。實際使用 DeepSeek V4 Flash 等長 context 模型時，助手在「中大型 test run 批次指派／改結果／掃未執行」等操作上會過早截斷、無法完成多步任務。本 change 在**不實作前**先鎖定：擴大合理 budget、可安全 compact 的歷史機制、以操作意圖為中心的精簡工具／特化 API，以及可支撐多步工作流的步驟上限。

## What Changes

- **Context budget 升級（非 1:1 吃滿模型上限）**
  - 以 DeepSeek V4 Flash **官方 1M tokens** context 為能力上限參考；**實務 working budget 採「更激進」工作集**（非 262K 誤傳、亦非預設灌滿 1M）：history **480k** chars、tool result **64k** chars。
  - 提高 `history_max_chars`、`tool_result_max_chars`、對話訊息上限與 clamp 上界；預算仍以 **serialized characters** 為準（延續既有 agent-loop 設計，不做不可靠跨模型 token 估算）。
  - List 工具結果改為 **list-aware soft truncation**（保留完整列＋分頁 meta），取代整包 `{truncated, preview}` 毀滅式截斷（單筆巨大 detail 仍可 fallback hard truncate）。
- **History compact 機制**
  - 當 history 逼近 soft/hard budget 時，對**最舊 exchange groups** 做可驗證的 compact；**DB 完整訊息保留**（UI／稽核真相），compact 僅影響送往 LLM 的 request view。
  - Compact 產物必須 protocol-safe（不拆 tool-call／tool-result pair）、不得把 credential 原值寫回摘要、不得成為 write 確認內容來源。
- **操作盤點 → 精簡工具與特化 API**
  - 依使用者意圖分族（Discover／Select-refs／Mutate-by-id／Mutate-by-filter／Structure／Automation），優先用 **slim projection / ref-list 工具** 降低資料量。
  - 必要時新增 **assistant 專用 loopback 端點**（例如 test run item ref list、filter 批次指派），不污染既有 UI 契約；權限／team／confirmation 規則與現有 write 一致。
  - 更新 skills／system prompt 指引「先 stats／count／refs，再 full list」。
- **步驟與回合上限**
  - 提高 `max_iterations` 與對應 clamp、必要時提高 `turn_timeout_seconds` 與 lease 續租相容性，使「分頁查詢 → 組 batch → confirm」可完成。
- **非目標**
  - 不改成「一次把整個 team 的 cases 灌進 context」。
  - 不做跨模型精確 token 計價、不做 1M 預設 full window。
  - 不解除 write 一律 pending confirmation、不放寬 credential 寫入禁令。
  - 不重做 widget UI 大改版；不引入第二套 package manager。

## Capabilities

### New Capabilities

- `assistant-context-budget`：模型能力與實務 working budget、history／tool-result 字元上限、list soft truncation、相關 config／env clamp。
- `assistant-history-compaction`：request-view compact 觸發條件、exchange-group 邊界、摘要安全約束、DB 完整保留與失敗路徑。
- `assistant-efficient-tools`：操作族盤點、slim／ref 讀取工具、特化 batch API、預設 page size、skills 指引與 registry 擴充規則。

### Modified Capabilities

- （main `openspec/specs/` 尚無已 archive 的 assistant-*；行為基底在 `add-global-ai-assistant` change。本 change 以 **New Capabilities** 定案增量；實作時對齊並延伸既有 agent-loop／tool-execution／data-boundary 程式路徑。待兩邊 archive 時再合併進主 specs。）

## Impact

- **Config**：`AssistantConfig` 預設值與 `TCRT_ASSISTANT_*` clamp 上界；可能新增 compact 相關開關／閾值。
- **服務**：`history_builder`、`projection`／truncate、`assistant_agent_service` iteration 迴圈、可選 compact service；tool registry 與新 tools。
- **API**：可能新增 team-scoped assistant-oriented read／batch endpoints（loopback only 或一般 JWT 皆可，但契約明確）；既有 UI list endpoints 預設行為盡量不變。
- **Skills／prompt**：`prompts/assistant/skills/*`、`system.md`。
- **測試**：data-boundary truncation、agent-loop budget／iterations、新 tool contract、compact protocol safety。
- **成本／限流**：更高 budget 與 iterations 提高 token 與延遲；沿用既有 per-user／global admission 與 hourly message limit 作為安全閥。
- **風險**：compact 摘要被 tool-result 注入；過大 context 品質下降；特化 batch 誤傷範圍。  
  **紅隊產物：** 同目錄 `red-team-review.md`（RT-01…22、必測門檻、殘餘風險）；design Risks 僅摘要。
