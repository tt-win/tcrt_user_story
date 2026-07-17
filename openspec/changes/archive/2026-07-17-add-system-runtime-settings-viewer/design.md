# Design: add-system-runtime-settings-viewer

## Context

- `/system-logs` 已是 Super Admin log tail；HTML shell 在 `app/main.py` **無**後端授權，資料面靠 `/api/admin/system-logs*` 的 `require_super_admin`。
- Capability `system-log-viewer` 若尚未進 main specs，須由使用者另行核准 archive 前置 change；**本 change 不得代為 archive**。
- 既有頁面 Requirement 名稱：`Super Admin 專用即時 log 檢視頁面`。
- `WEB_CONCURRENCY` 預設僅在 shell 內計算；未 export 時子 process 看不到；reload 模式強制單 worker；app 無法自知實際 worker 總數。

## Goals / Non-Goals

**Goals:**

- 固定 JSON allowlist（型別、nullability、enum）。
- 安全：結構化 DB 欄位；無 URL／query／完整路徑。
- Concurrency：configured + inferred default + 固定 note code；不冒充 actual。
- UI tabs；Settings 顯示 pid／instance；worker mismatch 規則一致。
- 權限對齊 log viewer；audit 對齊既有一級欄位模式。

**Non-Goals:**

- v1 bootstrap 區塊。
- HTML route 後端授權。
- 本 change 流程 archive 其他 change。
- 顯示 config／backup／certificate 路徑。
- 由 API 回傳 actual worker 進程數（除非未來另 change export resolved 值）。

## Decisions

### D1 — 同一路由分頁

`/system-logs` 內 Bootstrap 5 tabs：`Logs` | `Runtime Settings`。

### D2 — API

`GET /api/admin/system-runtime-settings`  
`require_super_admin`、`include_in_schema=False`、`Cache-Control: no-store`。

### D3 — 固定 JSON 契約（v1 allowlist）

根物件**恰好**下列鍵（缺值用 `null`，鍵不省略）：

```text
generated_at: string          # UTC ISO-8601 秒精度 + Z
pid: integer
worker_instance_id: string | null
  # 僅當 system log handler 已安裝時用其 id；否則 null
  # 不得另造隨機 id

process: object
  configured_web_concurrency: integer | null
  inferred_default_web_concurrency: integer
  web_concurrency_source: "configured" | "inferred_default" | "invalid_configured"
  worker_count_note_code: "not_actual_worker_count"   # 固定 enum，v1 僅此值

database: object
  main: DbEndpoint
  audit: DbEndpoint
  usm: DbEndpoint

app: object
  public_base_url: string | null
  enable_auth: boolean
  auth_enabled_source: "settings"   # v1 固定

log_viewer: object
  buffer_size: integer
  max_streams: integer
  max_message_chars: integer
  subscriber_queue_size: integer
  keepalive_seconds: integer
  stream_max_lifetime_seconds: integer
```

`DbEndpoint` **恰好**：

```text
engine: "sqlite" | "mysql" | "postgresql" | "other"
driver: string | null
host: string | null
port: integer | null
database: string | null
```

**禁止**：`url`、`url_redacted`、`note`（改用 `worker_count_note_code`）、query、username／password、secret 鍵值、檔案系統完整路徑。

#### D3a — Dialect／driver 正規化

對 `make_url(url).drivername`（小寫）正規化：

| drivername 模式 | engine | driver 欄位 |
|-----------------|--------|-------------|
| `sqlite`、`sqlite+*` | `sqlite` | `+` 後段或 null |
| `mysql`、`mysql+*` | `mysql` | 例 `asyncmy`／`pymysql`；無 `+` 則 null |
| `postgresql`、`postgresql+*`、`postgres`、`postgres+*` | `postgresql` | 例 `asyncpg`／`psycopg`；`postgres` 無 `+` 則 null |
| 其他／解析失敗 | `other` | 盡力取 `+` 後段或 null |

- `inferred_default_web_concurrency`：`sqlite`→1，`mysql`→5，`postgresql`→5，`other`→1。
- **必須**與 entrypoint／start.sh 把 `postgres://` 當 PostgreSQL 的行為一致（不可落到 `other` 導致 inferred=1）。
- query 全部丟棄；SQLite `database` 僅 **basename** 或 null。

#### D3b — `public_base_url`（合法定義）

解析後必須同時滿足，否則整欄 `null`：

1. scheme 僅 `http` 或 `https`（大小寫不敏感，輸出可正規化小寫 scheme）
2. hostname（或 IP）必須存在且非空
3. 若有 port：必須可解析為整數且 ∈ [1, 65535]
4. 去除 userinfo、query、fragment；保留 path（可為 `/` 或空 path）

**非法／回 null 的例子**：相對路徑（`/app`、`//host/path` 無 scheme）、`ftp://`、無 host、port=`99999` 或非數字、空字串、無法 parse。

### D4 — Concurrency（對齊 entrypoint：僅空值才推導）

entrypoint／start.sh 僅在 `WEB_CONCURRENCY` **未設或精確空字串 `""`** 時套用引擎預設（shell `-z`：未設與 `""` 為空；**純空白 `"   "` 為非空**，會原樣傳給 uvicorn，**不會** fallback）。

固定演算法（**禁止**先 `strip()` 再判斷是否空，否則與 shell 不一致）：

```text
raw is None 或 raw == ""
  → source = inferred_default；configured = null

否則可解析為整數 n 且 n >= 1（整段字串，不以 strip 後空白當空）
  → source = configured；configured = n

其他值（含純空白 "   "、0、負數、非整數、前後空白包數字等若解析規則定義為失敗）
  → source = invalid_configured；configured = null
```

| 環境 `WEB_CONCURRENCY` | `configured_web_concurrency` | `web_concurrency_source` | UI 語意 |
|------------------------|------------------------------|--------------------------|---------|
| 未設或精確 `""` | null | `inferred_default` | 腳本會用 inferred 預設 |
| 可解析正整數 ≥1 | 該整數 | `configured` | 明確設定 |
| 純空白 `"   "`、`0`、負數、非整數等 | null | `invalid_configured` | **設定異常**；不暗示腳本會採用 inferred |

`inferred_default_web_concurrency` 在三種 source 下**皆可**依 main engine 計算，供對照；但僅 `inferred_default` 表示「腳本會用它」。  
`invalid_configured` 時 UI 必須顯示異常，不得顯示成「將使用預設 5」。

`worker_count_note_code` 恒為 `"not_actual_worker_count"`。UI 映射三語；API 不帶英文說明句。
### D5 — 前端

- 首次切入 Settings：**lazy fetch 一次**；**重新整理**可再 fetch。
- loading／error／success。
- 安全 text DOM；tab panel 加 `tabindex="0"`（Bootstrap 5.3 a11y）。
- Keyboard：沿用 Bootstrap tab（方向鍵、Home／End）。
- i18n：`i18nReady`／`languageChanged` + `retranslate`。
- **Worker mismatch 規則（唯一）**：
  1. Logs 與 Settings 的 `worker_instance_id` **皆為非空字串**時：不同 → 顯示 mismatch banner；相同 → 不顯示。
  2. **任一方** instance id 缺失（null／空）→ **不**判定 mismatch；可顯示「無法確認是否同一 worker」次要提示（可選 i18n）。
  3. **PID 僅供顯示**，不參與 mismatch 判定（容器內常為 PID 1）。

### D6 — 權限與 audit

- HTML shell 不本 change 加 Depends。
- 導覽入口僅 Super Admin 可見；資料 API 401／403。
- 每次 HTTP 200 best-effort audit，對齊 `system-logs-stream` 寫法：
  - `ip_address=` request client host
  - `user_agent=` request header
  - `details={"pid": ..., "worker_instance_id": ...}` 僅此二鍵（instance 可 null）
  - resource_id=`system-runtime-settings`
  - **禁止**快照本體進 audit
  - audit 失敗不阻斷 200

### D7 — v1 排除 bootstrap

不回傳 `BOOTSTRAP_*`。

### D8 — MODIFIED 寫作

只改 `Super Admin 專用即時 log 檢視頁面`；全名、原 scenarios 保留。

### D9 — 前置 change（人工閘）

實作開始：

1. 檢查 main `openspec/specs/`（或已合併行為）是否已有該 Requirement。  
2. 若**沒有** → **停止實作**，回報使用者，請其另行核准 verify／archive `add-super-admin-log-viewer`（或等價合併）。  
3. **禁止**本 change 的 apply agent 自動 archive 其他 change。

## Risks / Trade-offs

| Risk | Mitigation |
|------|------------|
| `postgres://` 誤判 other | D3a 正規化 + 測試 |
| 使用者誤信 worker 數 | 固定 note code + UI 文案 |
| 跨 worker 誤報 mismatch | 僅雙端 instance 皆在時比較 |
| 前置未 archive | D9 停工，不代 archive |

## Migration Plan

1. 使用者確認前置 capability 已在 main（或核准 archive）。  
2. 部署本功能；無 DB migration。  
3. Rollback：回退版本。

## Open Questions

無。
