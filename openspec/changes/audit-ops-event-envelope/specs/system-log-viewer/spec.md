## ADDED Requirements

### Requirement: Log 記錄可選 structured 欄位
系統 log 捕捉層與快照／串流 API 的每筆 record SHALL 在既有必填欄位（seq、timestamp、level、logger_name、message、pid）之外，MAY 包含可選字串欄位 `event_code` 與 `outcome`。當 message **最後一行**的行尾符合 ops 尾碼慣例（最後一個 ` | ` 之後含 `event=<code>` 與 `outcome=<outcome>`，code 匹配 `[a-z0-9._-]+`）時，捕捉層 MUST 解析並填入；否則 MUST 省略可選欄位。解析失敗或 message 含 traceback 多行時，MUST 只嘗試最後一行且失敗時不得丟棄整筆 log 或影響 stdout handler 拓樸。

#### Scenario: 可解析尾碼帶出 event_code
- **WHEN** message 為 `hello | event=tcrt.ops.example.action outcome=failure` 並被捕捉
- **THEN** snapshot 與 SSE log event 中該 record 的 event_code 與 outcome 正確，message 仍為完整原文

#### Scenario: human 正文含分隔符時以最後一個分隔為準
- **WHEN** message 為 `a | b | event=tcrt.ops.example.action outcome=success`
- **THEN** event_code 解析為 tcrt.ops.example.action（以最後一個 ` | ` 之後為準）

#### Scenario: 普通 message 仍可捕捉
- **WHEN** free-form log 不含 structured 尾碼
- **THEN** record 含既有必填欄位；event_code 與 outcome 省略或為 null

### Requirement: Snapshot 與 SSE 共用 record schema
`GET /api/admin/system-logs` 快照中的每筆 record 與 SSE `log` event 的 JSON payload SHALL 使用同一 record schema（必填欄位相同；可選 event_code／outcome 規則相同）。

#### Scenario: stream 與 snapshot 欄位一致
- **WHEN** 同一筆含 event_code 的 log 分別出現在 snapshot 與 SSE log event
- **THEN** 兩處皆含相同 seq 語意下的 level、message、event_code、outcome 等對應欄位

### Requirement: 前端可顯示 event_code
`/system-logs` 的 Logs 分頁 SHALL 在 record 具有 event_code 時顯示該值；無該欄位時行為與現況一致。MUST NOT 引入 server-side keyword 或 `q` 查詢參數。

#### Scenario: 有 event_code 時顯示
- **WHEN** Super Admin 檢視含 event_code 的 log 列
- **THEN** UI 可見該 event_code

#### Scenario: 仍無 server keyword
- **WHEN** 客戶端呼叫 system-logs 快照或串流 API
- **THEN** 伺服器不接受亦不依 keyword／q 參數過濾

## MODIFIED Requirements

### Requirement: Super Admin 專用 log 快照 API
系統 SHALL 提供 log 快照查詢 API `GET /api/admin/system-logs`，MUST 僅允許 Super Admin 角色存取、MUST NOT 出現在公開 API schema。查詢參數 SHALL 僅有 `level`（最低門檻語意）、`logger`（名稱前綴比對）、`limit`（有預設值與伺服器上限，超過即收斂；語意為 tail——篩選後取**最新** N 筆再依序號遞增回傳）；**MUST NOT 提供 keyword 參數**（避免敏感搜尋字串進入 access log 與 URL）。回應 SHALL 依序號遞增排序，附 worker instance 識別與序號範圍，且 SHALL 帶 `Cache-Control: no-store` 與 `Pragma: no-cache`。每筆 record SHALL 含序號、ISO 8601 UTC 時間戳、level、logger 名稱、訊息、PID，並 MAY 含 `event_code` 與 `outcome`。

#### Scenario: Super Admin 取得快照
- **WHEN** Super Admin 以有效憑證呼叫 `GET /api/admin/system-logs`（可帶 level / logger / limit）
- **THEN** 回傳符合條件、依序號遞增的 record（每筆含序號、ISO 8601 UTC 時間戳、level、logger 名稱、訊息、PID；若有則含 event_code／outcome），以及 worker instance 識別與最舊/最新序號

#### Scenario: level 為最低門檻
- **WHEN** 以 `level=WARNING` 查詢
- **THEN** 回傳 WARNING 與更嚴重等級的 record，不含 INFO/DEBUG

#### Scenario: limit 超過上限被收斂
- **WHEN** 呼叫端帶入超過伺服器上限的 limit
- **THEN** 伺服器以上限值處理，不報錯、不放行極端值

#### Scenario: limit 取最新而非最舊
- **WHEN** 篩選後符合的 record 數多於 limit
- **THEN** 回傳序號最大的 N 筆（log tail），再依序號遞增排序，不得回傳 buffer 最舊的 N 筆

#### Scenario: 非 Super Admin 被拒絕
- **WHEN** 未登入使用者或非 Super Admin 角色呼叫快照或串流 API
- **THEN** 回傳 401 或 403，且不洩漏任何 log 內容

#### Scenario: 可選 structured 欄位不破壞舊客戶端
- **WHEN** 回應中部分 record 含 event_code／outcome
- **THEN** 其餘必填欄位語意不變，未知欄位可被舊客戶端忽略
