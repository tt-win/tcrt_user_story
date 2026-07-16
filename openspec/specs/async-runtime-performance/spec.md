# async-runtime-performance Specification

## Purpose

保證 TCRT web runtime 的 event loop 不被同步外部 I/O 阻塞，並定義 ASGI runtime 加速組態（uvloop/httptools）與 JSON 回應序列化（orjson）在行為上必須維持的相容語意。本 capability 的核心驗收原則：行為不變、只變快。

## Requirements

### Requirement: Async 請求路徑不得被同步外部 I/O 阻塞

Web runtime 的 async 請求路徑（含 scheduler 綁定在 event loop 上執行的背景服務）呼叫同步外部 HTTP client（Lark、Jira 等 `requests`-based client）時，MUST 在 async→sync 邊界以執行緒離載（`asyncio.to_thread` 或等效機制）執行，event loop 不得被外部 HTTP 連線、回應等待或重試退避（`time.sleep`）佔用。

#### Scenario: 慢速 Lark 呼叫不阻塞其他請求

- **WHEN** 某一請求觸發的 Lark API 呼叫需時 10 秒（慢回應或重試退避中）
- **THEN** 同時抵達的其他無關請求（如 `/api/version/`）在正常時間內回應，不等待該 Lark 呼叫完成

#### Scenario: 排程的 Lark 組織同步不阻塞 web 請求

- **WHEN** scheduler 觸發 Lark 組織同步且同步過程中呼叫多個 Lark API
- **THEN** 同步期間 web 請求的回應延遲不受影響

#### Scenario: 同步 client 的共享狀態在執行緒離載下安全

- **WHEN** 多個請求並發觸發離載後的 Lark 呼叫且 token 快取同時到期
- **THEN** token 刷新受既有鎖保護，不產生競態或重複刷新造成的錯誤

### Requirement: 附件下載代理以 async 串流轉發且保留既有行為契約

附件下載代理（Lark 檔案代理下載路徑）MUST 使用 async HTTP client 串流轉發，且 MUST 保留既有對外行為：上游 401 回 401、上游 404 回 404、其他非 200 回 502、逾時（30 秒）回 504、連線錯誤回 502；Content-Type、Content-Disposition（含 RFC 5987 非 ASCII 檔名格式）、Content-Length 的傳遞規則不變；串流結束或中斷時 MUST 釋放上游連線。

#### Scenario: 代理下載期間不阻塞 event loop

- **WHEN** 使用者透過代理下載一個大型附件（串流進行中）
- **THEN** 其他請求正常回應，不等待該下載完成

#### Scenario: 上游錯誤狀態碼映射不變

- **WHEN** Lark 回應 401 / 404 / 500
- **THEN** 代理分別回應 401 / 404 / 502，與變更前一致

#### Scenario: 逾時語意不變

- **WHEN** 上游在 30 秒內未完成回應
- **THEN** 代理回應 504

#### Scenario: 非 ASCII 檔名的 Content-Disposition 不變

- **WHEN** 下載附件時指定含中文的檔名
- **THEN** 回應以 RFC 5987 `filename*=UTF-8''<percent-encoded>` 格式攜帶檔名，與變更前一致

### Requirement: JSON 回應序列化維持 stdlib 相容語意

系統採用加速 JSON 序列化器（orjson）產生 API 回應時，MUST 維持與 stdlib `json` 相容的對外語意：非字串 dict key（如 int）MUST 序列化為字串 key；既有端點的回應內容與狀態碼不得因序列化器更換而改變。直接回傳 `JSONResponse` 的端點不受影響。

#### Scenario: int-key dict 回應與 stdlib 行為一致

- **WHEN** 端點回傳以 int 為 key 的 dict
- **THEN** 回應 JSON 的 key 為對應字串，狀態碼 200（與 stdlib `json.dumps` 行為一致，不得拋錯）

#### Scenario: 既有讀取 API 回應內容不變

- **WHEN** 呼叫 MCP read API 與 team statistics API（含 credential 遮蔽等既有行為）
- **THEN** 回應 JSON 內容與變更前逐欄位一致，既有測試全數通過

### Requirement: ASGI runtime 使用加速組態

服務安裝 MUST 包含 uvloop 與 httptools（`uvicorn[standard]`），使 uvicorn 於支援平台（Linux/macOS）自動採用 uvloop event loop 與 httptools HTTP 解析器；不支援平台（Windows）MUST 自動回退 asyncio loop 且服務正常啟動。啟動指令不因此變更。

#### Scenario: 支援平台自動採用 uvloop

- **WHEN** 於 Linux/macOS 以既有啟動指令（entrypoint / start.sh）啟動服務
- **THEN** uvicorn 採用 uvloop 與 httptools，服務正常提供請求且全部既有測試通過

#### Scenario: 測試套件不受 loop 變更影響

- **WHEN** 執行 `uv run pytest app/testsuite -q`
- **THEN** 測試自建 event loop 執行，結果與變更前一致
