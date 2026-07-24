# assistant-data-boundary Delta — extend-assistant-deep-links-global

## MODIFIED Requirements

### Requirement: 工具結果採 allowlist projection

每個工具 SHALL 在工具矩陣中宣告 output projection（允許進入 LLM context 的欄位 allowlist）；executor MUST 在 loopback 回應與 LLM context 之間強制套用 projection，未宣告的欄位一律不外送；長度截斷 MUST 在 projection 之後才套用，截斷不得作為資料保護手段。

工具矩陣 MAY 宣告 server-generated 導航欄位（如 `_deep_links`）為 projection allowlist 的成員。此類欄位不存在於 API endpoint 的 raw response 中，而由 executor 在 projection 完成後以固定模板與型別驗證產生並注入。導航欄位的 URL MUST 以相對路徑（以 `/` 開頭）呈現，不得包含外部 scheme；欄位值中的識別碼 MUST 經 `int()` 或 `urllib.parse.quote()` 驗證，拒絕非預期型別。

**Local/in-process 工具（`execution_mode="local"`）的 `_deep_links` 注入時機特別說明**：local 工具的 result payload 先在 `tool_executor.run_read_tool` 中經過 `project_and_redact`（top-level key allowlist 過濾），再回傳至 `conversation_service.append_tool_call_and_result`，由後者在 `json.dumps` 前注入 `_deep_links`。因此 local 工具的 projection allowlist 不須包含 `_deep_links`——該欄位於投影完成後才加入 payload。若 local 工具需要宣告 `_deep_links`（例如為了一致性或防禦性），MAY 加入，但非必要。Loopback 工具（`execution_mode` 非 local）的 `_deep_links` 注入時序相同（post-projection），但其 projection allowlist 仍建議加入 `_deep_links` 作為防禦性宣告。

#### Scenario: 未宣告欄位不外送
- **WHEN** 端點回應包含 projection 未列出的欄位（含未來新增欄位）
- **THEN** 該欄位不出現在送往 LLM 的工具結果中

#### Scenario: server-generated 導航欄位經宣告後可進入 tool result
- **WHEN** 工具矩陣為某工具宣告 `_deep_links` 為 projection 成員，且該工具執行成功
- **THEN** executor 在 projection 與截斷完成後，以 `build_deep_links()` 產生 `_deep_links` dict 並注入 tool result payload，該欄位進入 LLM context 與持久化訊息

#### Scenario: local 工具的 _deep_links 不受 projection allowlist 限制
- **WHEN** 某 local 工具的 projection allowlist 不含 `_deep_links`，但其 result payload 經 projection 後由 conversation_service 注入 `_deep_links`
- **THEN** `_deep_links` 仍正常進入 LLM context 與持久化訊息（因 injection 發生在投影之後）
