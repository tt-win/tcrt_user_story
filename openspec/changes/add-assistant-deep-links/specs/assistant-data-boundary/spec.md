# assistant-data-boundary Delta — add-assistant-deep-links

## MODIFIED Requirements

### Requirement: 工具結果採 allowlist projection
每個工具 SHALL 在工具矩陣中宣告 output projection（允許進入 LLM context 的欄位 allowlist）；executor MUST 在 loopback 回應與 LLM context 之間強制套用 projection，未宣告的欄位一律不外送；長度截斷 MUST 在 projection 之後才套用，截斷不得作為資料保護手段。

工具矩陣 MAY 宣告 server-generated 導航欄位（如 `_deep_links`）為 projection allowlist 的成員。此類欄位不存在於 API endpoint 的 raw response 中，而由 executor 在 projection 完成後以固定模板與型別驗證產生並注入。導航欄位的 URL MUST 以相對路徑（以 `/` 開頭）呈現，不得包含外部 scheme；欄位值中的識別碼 MUST 經 `int()` 或 `urllib.parse.quote()` 驗證，拒絕非預期型別。

#### Scenario: 未宣告欄位不外送
- **WHEN** 端點回應包含 projection 未列出的欄位（含未來新增欄位）
- **THEN** 該欄位不出現在送往 LLM 的工具結果中

#### Scenario: server-generated 導航欄位經宣告後可進入 tool result
- **WHEN** 工具矩陣為某 create 類工具宣告 `_deep_links` 為 projection 成員，且該工具執行成功
- **THEN** executor 在 projection 與截斷完成後，以 `build_deep_links()` 產生 `_deep_links` dict 並注入 tool result payload，該欄位進入 LLM context 與持久化訊息

#### Scenario: 導航欄位缺失 ID 時不產生連結
- **WHEN** `build_deep_links()` 無法從 result payload 或 tool arguments 取得有效 ID（值為 None、型別錯誤或 key 不存在）
- **THEN** `_deep_links` 為空 dict 或不注入，tool result 仍正常持久化且送往 LLM