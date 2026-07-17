# system-runtime-settings-viewer Spec

## ADDED Requirements

### Requirement: Super Admin 可讀取固定契約的 runtime 設定快照

系統 SHALL 提供 `GET /api/admin/system-runtime-settings`（經 admin router 掛於 `/api` 下），僅 Super Admin 可成功讀取。端點 MUST NOT 出現在 OpenAPI schema。成功回應 MUST 為 JSON 物件，且 MUST 帶 `Cache-Control: no-store`（或等價不可快取指示）。

成功 JSON 的根物件 MUST **恰好**包含下列鍵：

| 鍵 | 型別 | nullability |
|----|------|-------------|
| `generated_at` | string | 非 null；UTC ISO-8601 秒精度 + `Z` |
| `pid` | integer | 非 null |
| `worker_instance_id` | string \| null | log handler 未安裝時為 null |
| `process` | object | 非 null |
| `database` | object | 非 null |
| `app` | object | 非 null |
| `log_viewer` | object | 非 null |

`process` MUST **恰好**包含：

| 鍵 | 型別 | 語意 |
|----|------|------|
| `configured_web_concurrency` | integer \| null | 僅 env 為可解析正整數（≥1）時；其餘情況 null |
| `inferred_default_web_concurrency` | integer | 依 main 正規化引擎：sqlite→1，mysql→5，postgresql→5，other→1（三種 source 皆可填，供對照） |
| `web_concurrency_source` | string | 僅 `configured` \| `inferred_default` \| `invalid_configured` |
| `worker_count_note_code` | string | v1 **固定**為 `not_actual_worker_count` |

`web_concurrency_source` 判定 MUST 對齊部署腳本的 shell `-z` 語意（僅 **未設** 或 **精確空字串 `""`** 才採用推導預設；**純空白 `"   "` 為非空**，不會被腳本 fallback）。實作 MUST NOT 先 `strip()` 再判斷是否空字串。

固定演算法：

1. `raw is None` 或 `raw == ""` → `inferred_default`，`configured_web_concurrency = null`
2. 否則若整段字串可解析為整數 `n` 且 `n >= 1` → `configured`，`configured_web_concurrency = n`
3. 其他（含純空白、`0`、負數、非整數字串）→ `invalid_configured`，`configured_web_concurrency = null`

| env `WEB_CONCURRENCY` | source | configured 欄位 |
|------------------------|--------|-----------------|
| 未設或精確 `""` | `inferred_default` | null |
| 可解析正整數 ≥1 | `configured` | 該整數 |
| 純空白 `"   "`、`0`、負數、非整數字串等 | `invalid_configured` | null |

`worker_count_note_code` MUST 恒為 `not_actual_worker_count`（機器 code；UI i18n；API MUST NOT 以人類可讀句取代此 code）。`invalid_configured` 時 UI MUST 標示設定異常，MUST NOT 暗示 runtime 會自動改用 inferred 預設。
`database` MUST **恰好**包含 `main`、`audit`、`usm`；每值 MUST **恰好**包含：

| 鍵 | 型別 |
|----|------|
| `engine` | `sqlite` \| `mysql` \| `postgresql` \| `other` |
| `driver` | string \| null |
| `host` | string \| null |
| `port` | integer \| null |
| `database` | string \| null |

引擎正規化 MUST 將 `postgres` 與 `postgres+*` 視為 `postgresql`（與部署腳本一致）。`mysql+asyncmy` 的 engine 為 `mysql`、driver 為 `asyncmy`；無 `+driver` 時 driver 為 null。

`app` MUST **恰好**包含：`public_base_url`（string \| null）、`enable_auth`（boolean）、`auth_enabled_source`（固定字串 `settings`）。

`public_base_url` 合法時 MUST 為去除 userinfo／query／fragment 後的 http(s) URL 摘要；且 MUST 同時滿足：scheme 僅 `http` 或 `https`、hostname 非空、若有 port 則為 1–65535 之整數。相對 URL、非 http(s) scheme、缺 host、非法 port 或無法解析 → MUST 為 null。
`log_viewer` MUST **恰好**包含整數：`buffer_size`、`max_streams`、`max_message_chars`、`subscriber_queue_size`、`keepalive_seconds`、`stream_max_lifetime_seconds`。

v1 回應 MUST NOT 包含 bootstrap 相關鍵，MUST NOT 包含 `note` 鍵（已由 `worker_count_note_code` 取代）。

#### Scenario: Super Admin 成功取得快照

- **WHEN** Super Admin 呼叫設定快照 API
- **THEN** HTTP 200，body 根物件與各巢狀物件鍵集合與型別符合上表，且含 `no-store`

#### Scenario: 非 Super Admin 被拒絕

- **WHEN** 未授權或非 Super Admin 呼叫
- **THEN** 401 或 403，且 body 不含設定 allowlist 欄位內容

#### Scenario: OpenAPI 不含端點

- **WHEN** 取得應用 OpenAPI schema
- **THEN** 路徑中不出現 system-runtime-settings 端點

#### Scenario: worker_instance_id 在 handler 缺失時為 null

- **WHEN** system log handler 尚未安裝
- **THEN** 成功快照中 `worker_instance_id` 為 null，且仍回傳其他 allowlist 欄位

#### Scenario: worker_count_note_code 固定

- **WHEN** 任一成功快照
- **THEN** `process.worker_count_note_code` 精確等於 `not_actual_worker_count`

### Requirement: 資料庫與 base URL 以結構化安全欄位輸出

系統 MUST NOT 在快照中輸出完整或 redacted 字串形式的資料庫 URL。資料庫資訊 MUST 僅以 `engine`／`driver`／`host`／`port`／`database` 呈現。所有 query 參數 MUST 丟棄。SQLite 的 `database` MUST NOT 包含檔案系統目錄路徑（僅 basename 或 null）。`public_base_url` MUST 符合本 spec 上文之合法 http(s) 定義（含 scheme／host／port 規則）；否則 null。
#### Scenario: MySQL URL 不含密碼與 query

- **WHEN** main URL 為 `mysql+asyncmy://user:secret@dbhost:3306/tcrt_main?token=abc&ssl_key=/x`
- **THEN** `database.main` 為 engine=`mysql`、driver=`asyncmy`、host=`dbhost`、port=`3306`、database=`tcrt_main`，且回應全文不出現 `secret`、`token=abc`、`ssl_key`

#### Scenario: postgres 別名正規化

- **WHEN** main URL 為 `postgres://user:secret@dbhost:5432/tcrt_main`
- **THEN** `database.main.engine` 為 `postgresql`，且 `process.inferred_default_web_concurrency` 為 5（在 configured 為 null 時）

#### Scenario: SQLite 不洩漏路徑

- **WHEN** main URL 指向 `/var/lib/tcrt/data/test_case_repo.db`
- **THEN** `database.main.database` 不為該完整路徑（僅 basename 或 null），且回應不出現 `/var/lib/tcrt`

#### Scenario: malformed DB URL

- **WHEN** 某 target 的 URL 無法解析
- **THEN** 該 target `engine` 為 `other`，其餘 DbEndpoint 欄位為 null，且 API 仍可 200

#### Scenario: public_base_url 去除 userinfo／query／fragment

- **WHEN** 設定之 public base 為合法 `https://user:pass@example.com:443/app?x=1#y`
- **THEN** 快照中 `app.public_base_url` 不含 userinfo、query、fragment，且 scheme 為 https、host 為 example.com

#### Scenario: 非法 public_base_url

- **WHEN** public base 為相對路徑、非 http(s) scheme、缺 hostname、port 非法或無法解析
- **THEN** `app.public_base_url` 為 null

#### Scenario: 禁止 url 鍵

- **WHEN** Super Admin 取得快照
- **THEN** JSON 中不存在 `url`、`url_redacted`、`DATABASE_URL` 等鍵

### Requirement: WEB_CONCURRENCY 語意為 configured、inferred_default 或 invalid_configured

系統 MUST 區分：明確合法設定、腳本空值推導預設、以及非空非法設定。MUST NOT 將任一者標示為實際 worker 進程數。MUST NOT 將非空非法 env 標成 `inferred_default`（部署腳本不會對此 fallback）。

#### Scenario: 未設定 env 且 MySQL

- **WHEN** 環境未設定 `WEB_CONCURRENCY` 或精確為 `""`，且 main 引擎為 mysql
- **THEN** `configured_web_concurrency` 為 null，`inferred_default_web_concurrency` 為 5，`web_concurrency_source` 為 `inferred_default`

#### Scenario: 明確正整數設定

- **WHEN** 環境 `WEB_CONCURRENCY=2`
- **THEN** `configured_web_concurrency` 為 2，`web_concurrency_source` 為 `configured`

#### Scenario: 非法非空 WEB_CONCURRENCY

- **WHEN** 環境 `WEB_CONCURRENCY` 為 `0`、負數或非整數字串
- **THEN** `configured_web_concurrency` 為 null，`web_concurrency_source` 為 `invalid_configured`（`inferred_default_web_concurrency` 仍可填對照值，但 source 不得為 `inferred_default`）

#### Scenario: 純空白 WEB_CONCURRENCY

- **WHEN** 環境 `WEB_CONCURRENCY` 為僅空白字元的字串（例如三個空白 `"   "`）
- **THEN** `configured_web_concurrency` 為 null，`web_concurrency_source` 為 `invalid_configured`（不得為 `inferred_default`）

### Requirement: 每次成功讀取寫入 audit 且 details 邊界固定

系統 SHALL 在每次快照 API 成功（HTTP 200）時 best-effort 寫入 audit：`ActionType.READ`、`ResourceType.SYSTEM`、resource_id `system-runtime-settings`。  
`ip_address` 與 `user_agent` MUST 使用 audit API 既有一級參數（與 system log stream 相同模式），MUST NOT 再放入 `details`。  
`details` MUST **恰好**可含 `pid` 與 `worker_instance_id`（後者可 null），MUST NOT 含設定快照其他欄位或 URL／密碼片段。  
audit 失敗 MUST NOT 使 API 改為非 200。

#### Scenario: 成功讀取留下稽核

- **WHEN** audit 啟用且 Super Admin 成功取得快照
- **THEN** 新增一筆 resource_id 為 `system-runtime-settings` 的紀錄，且 IP／UA 在一級欄位、`details` 僅 pid／worker_instance_id

#### Scenario: audit 失敗不阻斷

- **WHEN** audit 寫入失敗
- **THEN** API 仍 200 且 body 為完整 allowlist 快照

### Requirement: System Logs 頁 Runtime Settings 分頁唯讀載入

`/system-logs` 的 Runtime Settings 分頁 SHALL 透過本 API 載入並唯讀顯示；MUST NOT 提供修改伺服器設定的控制項。首次切入該分頁 SHALL lazy fetch 一次；成功後同頁再次切入可不自動重打，但 MUST 提供明確重新整理動作以再次 fetch。使用者可見字串 MUST 支援 en-US／zh-CN／zh-TW，並在 `i18nReady`／`languageChanged` 後正確 retranslate。`worker_count_note_code` MUST 經前端映射為三語文案，不得直接把 code 當唯一使用者說明（code 可保留給除錯但不取代 i18n 句）。

Worker 是否同一 process 的判定 MUST 為：僅當 Logs 與 Settings 的 `worker_instance_id` 皆為非空且不相等時顯示 mismatch 提示；任一方 instance 缺失時 MUST NOT 以 PID 判定 mismatch。

#### Scenario: 切換至 Runtime Settings

- **WHEN** Super Admin 選擇 Runtime Settings 分頁
- **THEN** 前端請求快照 API，以安全文字渲染，並顯示 pid 與 worker_instance_id（null 時顯示為未知／—）

#### Scenario: 重新整理

- **WHEN** 使用者在 Settings 分頁觸發重新整理
- **THEN** 再次請求 API 並更新畫面

#### Scenario: 雙端 instance 不同時 mismatch

- **WHEN** Logs 與 Settings 的 `worker_instance_id` 皆非空且不同
- **THEN** UI 顯示 worker mismatch 提示

#### Scenario: instance 缺失不誤報 mismatch

- **WHEN** Logs 或 Settings 任一方缺少 `worker_instance_id`
- **THEN** UI 不因 PID 不同而顯示 mismatch（可顯示無法確認同一 worker）
