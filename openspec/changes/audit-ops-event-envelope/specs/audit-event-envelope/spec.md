## ADDED Requirements

### Requirement: Audit event envelope v1
系統 SHALL 以版本化 envelope 記錄新的 audit 事件。經 catalog 成功寫入的新列 MUST 包含：`schema_version=1`、已登錄的 `event_code`、`impact`（`routine` | `notable` | `sensitive` | `privileged`）、`outcome`（`success` | `denied` | `failure` | `partial`）、既有 actor／action／resource 欄位，以及可選的 `action_brief` 與經遮罩且通過 schema 驗證的 `details`。`impact` MUST 描述動作本質敏感度且 MUST NOT 依成敗改變；`outcome` MUST 描述該次結果。歷史列（migration 前）的 `event_code`／`impact`／`outcome`／`schema_version` MUST 可為 null。

#### Scenario: 成功建立資源的 audit 列
- **WHEN** 授權使用者成功建立一筆需稽核的資源且 safe emit 使用已登錄 event_code 與 outcome=success
- **THEN** audit 列含 `schema_version=1`、該 `event_code`、catalog 決定的 `impact`、`outcome=success`

#### Scenario: 授權拒絕仍記錄 outcome
- **WHEN** 主體嘗試需稽核的敏感操作且被拒絕，且呼叫端傳 outcome=denied
- **THEN** audit 列的 `outcome` 為 `denied`，`impact` 仍為該操作的 catalog 敏感度

#### Scenario: 歷史列欄位為 null
- **WHEN** 查詢 migration 前寫入的列
- **THEN** `impact`、`outcome`、`event_code` 可為 null，且既有 `severity` 仍可讀

### Requirement: Event catalog 為 impact 與寫入策略的唯一真相
系統 SHALL 在 `app/observability/event_catalog.py` 維護 event catalog。每個 `event_code` MUST 宣告 domain、是否寫 audit／ops、audit 用預設 `impact`、ops level 對照，以及 details schema。新 audit 寫入的 `impact` MUST 由 catalog 決定。

#### Scenario: catalog 決定 impact
- **WHEN** 兩個已登錄 event_code 分別宣告 routine 與 privileged 並成功寫入 audit
- **THEN** 兩筆的 `impact` 分別符合 catalog，而非呼叫端臨時覆寫的任意 impact

### Requirement: Emit 驗證失敗不阻斷業務請求
系統 SHALL 提供核心 `emit_event`（未知 event_code 或 details 不符 schema 時 raise 固定例外型別）以及 `safe_emit_event` wrapper。業務 API、middleware 與背景 job 的 audit／ops 寫入 MUST 走 `safe_emit_event`（或等價）：驗證或 DB 失敗時 MUST NOT 使原本成功的業務請求改為 5xx；MUST 不寫入該筆失敗的 audit 列；MUST 以 raw logger（不經 catalog）記錄 ERROR 級診斷。單元測試可直接驗證核心 raise 行為。

#### Scenario: 未知 event_code 不產生 audit 列且不 500
- **WHEN** 業務成功路徑誤傳未登錄 event_code 並經 safe_emit_event
- **THEN** 不新增 audit 列、HTTP 仍為業務成功狀態碼，且 raw ERROR log 可觀測

#### Scenario: details 不符 schema 不產生 audit 列
- **WHEN** safe_emit_event 的 details 不符合該 event_code schema
- **THEN** 不新增 audit 列，業務路徑不因該失敗而失敗

#### Scenario: 核心 emit 對未知 code raise
- **WHEN** 測試直接呼叫核心 emit_event 並傳未登錄 event_code
- **THEN** 抛出固定的 UnknownEventCodeError（或專案命名之同等型別）

### Requirement: Legacy severity 相容映射
系統 SHALL 在新 audit 寫入成功時同步填入既有 `severity`：`privileged` → `critical`；`sensitive` → `warning`；`routine` 或 `notable` 且 outcome 為 `failure` 或 `denied` → `warning`；其餘 `routine` 或 `notable` → `info`。讀取歷史列（`impact` 為 null）時，API／UI MUST 仍可顯示既有 `severity` 並可辨識 legacy。

#### Scenario: 新寫入雙寫 severity
- **WHEN** `impact=privileged` 且 `outcome=success` 的事件寫入成功
- **THEN** 列上 `severity` 為 `critical` 且 `impact` 為 `privileged`

#### Scenario: 歷史列無 impact
- **WHEN** 列表含 `impact` 為 null 的列
- **THEN** 回應仍含 `severity`，且 `impact` 為 null 以標示 legacy

### Requirement: Deprecated log_action adapter 與 deny 同交付
系統 SHALL 保留 `log_action`／`log_create`／`log_update`／`log_delete` 等 adapter，並新增可選參數 `outcome` 與 `event_code`。未傳 event_code 時 MUST 使用已登錄的 legacy event_code，並將舊 severity 反推 impact（critical→privileged，warning→sensitive，info→routine）；**notable 不得由 severity 反推**。未傳 outcome 時預設 `success`。本 change 交付時，所有顯式使用 `AuditSeverity.WARNING` 的站點 MUST 改為傳入正確 `outcome`（deny 路徑為 `denied`，成功但敏感操作為 `success`），避免拒絕存取被記成 success。

#### Scenario: 舊 log_delete 寫入新欄位
- **WHEN** 呼叫 log_delete 且未傳 event_code
- **THEN** 列含非 null impact（privileged）、outcome（預設 success）與 severity=critical，且 event_code 為已登錄 legacy code

#### Scenario: app token 或 MCP 拒絕路徑 outcome=denied
- **WHEN** app token 或 MCP 認證／授權拒絕並寫 audit
- **THEN** 該列 `outcome` 為 `denied` 且不得為 `success`

### Requirement: Audit 列表與 export 篩選擴充
`GET /audit/logs` 與 `GET /audit/logs/export` SHALL 接受可選篩選：`impact`、`outcome`、`event_code`（精確）、`resource_id`（精確）、以及既有 username、role、resource_type、action_type、team_id、severity、時間、分頁。`GET /audit/logs` MUST NOT 接受 `q` 參數；若傳入 `q` MUST 回 400。列表 item 與 export 欄位 SHALL 包含 `event_code`、`impact`、`outcome`、`schema_version`（可 null）並保留 `severity`；列表 item MUST NOT 含 `details`（export 可含 details 欄，與現況一致且僅 Admin）。權限：僅 Admin／Super Admin；非 Super Admin MUST NOT 看到 role=super_admin 的列。以 `impact` 篩選 MUST NOT 自動映射歷史僅有 severity 的列（已知限制）。

#### Scenario: 依 impact 篩選
- **WHEN** Admin 以 impact=privileged 呼叫 GET list
- **THEN** 回傳列（可見範圍內）皆為 impact=privileged

#### Scenario: GET 帶 q 被拒
- **WHEN** Admin 呼叫 GET /audit/logs?q=foo
- **THEN** 回傳 400

#### Scenario: resource_id 篩選
- **WHEN** Admin 以 resource_id 精確值查詢
- **THEN** 回傳列的 resource_id 皆等於該值

#### Scenario: export 含新欄
- **WHEN** Admin 匯出同時含新 envelope 列與歷史列的 CSV
- **THEN** 檔案含 event_code、impact、outcome、schema_version 欄；新列 schema_version 為 1；歷史列 schema_version 為空

### Requirement: Audit 文字搜尋 API
系統 SHALL 提供 `POST /audit/logs/search`。請求 JSON body MUST 含必填 `q`，以及與 list 對齊的可選篩選與 `page`／`page_size`。`q` 經 strip 後長度 MUST ∈ [1, 200]，否則 400（含空字串與純空白）。搜尋 MUST 以 OR 比對 `action_brief`、`event_code`、`resource_id`、`username` 的大小寫不敏感子字串（契約保證 ASCII case-insensitive）；MUST NOT 搜尋 `details`。實作 MUST 跳脫 LIKE 萬用字元 `%` 與 `_`，使 `q` 為 `%` 時只匹配字面包含 `%` 的欄位值。分頁與排序 MUST 與 GET list 相同。回應 JSON shape MUST 與 GET list 相同，item 不含 details。權限與 super_admin 隱藏規則與 list 相同。

#### Scenario: 以 brief 關鍵字命中
- **WHEN** 存在 action_brief 含「Rotated app token」的列，Admin POST search 且 q 為 Rotated
- **THEN** 回應 items 包含該列且含 total／page 分頁欄位

#### Scenario: 不搜 details
- **WHEN** 某列 details 含唯一字串 S 但 brief／event_code／resource_id／username 皆不含 S
- **THEN** q=S 的 search 不回傳該列

#### Scenario: q 為空或過長
- **WHEN** Admin 提交 q 為空字串、純空白、或長度大於 200
- **THEN** 回傳 400

#### Scenario: LIKE 萬用字元字面匹配
- **WHEN** 資料中無人的 brief 含字元 % 且 Admin 以 q=% 搜尋
- **THEN** 不得回傳全部列；僅回傳 brief／event_code／resource_id／username 字面含 % 者（若無則空列表）

#### Scenario: 分頁
- **WHEN** 命中數大於 page_size 且 page=1
- **THEN** items 長度 ≤ page_size 且 total 反映總命中數

### Requirement: Audit UI 可篩選與搜尋
`/audit-logs` 頁面 SHALL 提供 action_type、impact、outcome、resource_id 篩選，以及文字搜尋（呼叫 POST search）。結果表 SHALL 顯示 impact 與 outcome；當 impact 為 null 時顯示 legacy severity 並標示 legacy。UI 文案 SHALL 提示 impact 篩選不含歷史僅有 severity 的列。新文案 MUST 同步 en-US、zh-CN、zh-TW。

#### Scenario: 使用者搜尋與 outcome 篩選
- **WHEN** Admin 輸入關鍵字並選擇 outcome=failure 後套用
- **THEN** 前端以 POST search 送出 q 與 outcome，並渲染回傳列

#### Scenario: 歷史列 legacy 顯示
- **WHEN** 列的 impact 為 null 且 severity 有值
- **THEN** UI 顯示該 severity 與 legacy 提示

### Requirement: Audit schema migration 可升級可降級
系統 SHALL 以 audit Alembic migration 新增可 null 欄位：`event_code`、`impact`、`outcome`、`schema_version`（INTEGER NULL，新寫入為 1，禁止以 DEFAULT 把舊列標成 1）。型別／portable enum 策略與既有 audit 表一致。Downgrade MUST 移除本 change 新增欄位與索引。

#### Scenario: 升級後舊列可查且 schema_version 為 null
- **WHEN** 對含舊列的 DB 執行 upgrade 後 list
- **THEN** 舊列可回傳，其 schema_version 與 impact 為 null

#### Scenario: downgrade 移除新欄
- **WHEN** 執行對應 downgrade
- **THEN** 新欄位不存在
