## Context

TCRT 目前有兩套紀錄子系統，語彙重疊但目的不同：

| 子系統 | 儲存 | 讀者 | 現況問題 |
|---|---|---|---|
| Audit | 獨立 audit DB `audit_logs` | Admin / Super Admin | severity 混用「敏感度」與「警示感」；UI 篩選不全；無法搜 `action_brief` |
| System log | stdout + in-memory ring buffer | Super Admin `/system-logs` | free-form 字串；大量 soft-fail 用 WARNING；server 刻意不提供 keyword |

代表誤標路徑（ops）：`load_result_provider` / CI artifact download / Allure proxy fallback 使用 `logger.warning`，即使流程設計為可降級。

代表 audit 缺口：`GET /audit/logs` 後端支援部分篩選，但 HTTP 層未暴露全部（如 `resource_id`）；UI 只暴露 username/role/resource/team/time；無全文；無 outcome。既有 `audit_service.log_action` 為 **best-effort**（例外吞掉、不影響業務請求）。

本 change 在**不合併兩套 store**的前提下，引入共同 envelope 語意與 catalog 治理，先打通 audit 搜尋與高噪 ops level 校正。

## Goals / Non-Goals

**Goals:**

1. 定義 envelope v1 與 event catalog，使新寫入可機器驗證、可擴充。
2. Audit 分軸：`impact` + `outcome`；legacy `severity` 可映射讀寫。
3. Audit Phase A 搜尋：篩選補齊 + `q` 限縮欄位 + 避免 `q` 進 URL query。
4. 鎖定 automation result 相關 ops 路徑的 level 規則並落地。
5. 維持 system-log-viewer 安全契約：**禁止 server keyword**；ring buffer **不改變 handler 拓樸／不平行第二條 stdout**。

**Non-Goals:**

- 全站 logger 改寫、FTS、統一搜尋 UI、OTel/ELK。
- 擴大 auto-audit middleware 覆蓋。
- 強制歷史 audit 列 backfill `event_code`／`impact`／`outcome`（僅新寫入必填；舊列保持 null）。
- 保證反向代理或未來 body logger 永不記錄 POST body（超出 app 控制）。
- 連續失敗自動升級 level（follow-up）。

## Decisions

### D1 — 三軸分離（硬性）

| 軸 | 適用 | 值 | 語意 |
|---|---|---|---|
| `impact` | audit（新寫入必填） | `routine \| notable \| sensitive \| privileged` | 動作本質敏感度；**與成敗無關** |
| `outcome` | audit 新寫入必填；ops 必填 | `success \| denied \| failure \| partial` | 本次結果 |
| `level` | system log only | stdlib levels | 是否需運維介入 |

禁止再用單一 `severity=warning` 同時表示「敏感操作」與「失敗」。

**Legacy 映射（新寫入同時寫入 `severity`）：**

| impact | outcome | legacy severity |
|---|---|---|
| privileged | * | `critical` |
| sensitive | * | `warning` |
| notable \| routine | failure \| denied | `warning` |
| notable \| routine | success \| partial | `info` |

讀取 UI：優先 impact + outcome；若 `impact IS NULL` 則顯示 legacy `severity` 並標 `legacy`。

**已知限制（accepted）：** 以 `impact=` 篩選**不會**自動命中 migration 前僅有 `severity` 的列。UI 須提示；使用者可改以 `severity` 篩選歷史。

### D2 — Event code、catalog 路徑、雙寫規則

- 命名：`tcrt.<domain>.<entity>.<verb>[.<qualifier>]`，`domain` ∈ {`audit`, `ops`}（擴充須登錄）。
- **模組路徑（已決，ADR-001）：** `app/services/observability/event_catalog.py` + `app/services/observability/emit.py`（audit 與 ops 共用，避免分裂）。
- Catalog 每筆：`event_code`、`domain`、`write_audit`、`write_ops`、`default_impact`（ops-only 可 null）、`ops_level_by_outcome`（ops 事件必填；缺 outcome key → validate raise）、`details_schema`（pydantic）、可選 `brief_template`。
- **單一入口 `emit_event(...)`：** 依 catalog 旗標決定是否寫 audit／ops；caller **不**需打兩次。薄包裝 `audit_events.emit` / `ops_log.emit` 可保留，但內部皆走 `emit_event`。
- **雙寫順序與半失敗（已決）：** 先 **validate**（code + details）→ 通過後若 `write_ops` 則寫 ops logger → 若 `write_audit` 則寫 audit DB。驗證失敗：**兩者皆不寫**，核心 raise（safe 則 raw ERROR）。ops 已寫但 audit DB 失敗：ops 保留（logger 不可回滾），audit 不列，safe 路徑 raw ERROR；**不**為 audit 失敗重試污染業務。
- 未知 `event_code`：`emit_event` MUST raise 型別固定的 `UnknownEventCodeError`（僅供呼叫端可測）。**業務 request 路徑的呼叫端 MUST catch 並降級為 best-effort**（見 D4）。
- details 不符 schema：validate 階段失敗 → 不寫 ops、不寫 audit。

### D3 — Envelope v1 欄位

Audit 新列必填：`schema_version`、`event_code`、`impact`、`outcome`；建議 `action_brief`；可選 `details`（驗證 + 遮罩）。

**`schema_version`（已決）：`SMALLINT NOT NULL DEFAULT 0`。**

- 新 emit 寫 `1`。
- 歷史列保持 `0`（legacy）。
- Legacy 判定：`schema_version = 0`（或 `impact IS NULL`、`event_code IS NULL`）。

Ops message（單行可讀 + 可解析尾碼）：

```text
{human_message} | event={event_code} outcome={outcome} [k=v ...]
```

- human 正文在前；尾碼以**最後一個** ` | ` 分隔。
- `event_code` 字元類：`[a-z0-9._-]+`；`outcome` 為四枚舉之一。
- 捕捉層只解析**最後一行**的行尾尾碼；失敗則省略 optional 欄位。

### D4 — Emit 與 best-effort（寫死，禁止二選一）

| 層級 | 行為 |
|---|---|
| `emit_event` 核心 | 未知 code → raise `UnknownEventCodeError`；details 非法 → raise `EventDetailsValidationError`；**ops 事件** outcome 不在 `ops_level_by_outcome` → raise `EventDetailsValidationError`（或同等 validate 例外）。audit-only 事件不要求 level map |
| 業務／middleware 呼叫 | MUST 使用 wrapper `safe_emit_event(...)`：**吞掉**上述與 DB 錯誤，改以 **raw** `logger.error`（**不得**再進 catalog，防遞迴）記錄，**不**影響 HTTP／背景 job 成功路徑 |
| 單元測試 | 可直接測核心 raise；整合測業務路徑不得因錯誤 event 變 500 |

既有 `audit_service.log_action` 改為呼叫 `safe_emit_event` 的 adapter，維持「審計失敗不阻斷業務」。

### D5 — Adapter + deny 同交付（禁止錯誤 outcome 窗口）

`log_action` 簽名新增可選 `outcome: AuditOutcome | None = None`、`event_code: str | None = None`。

反推規則（無 event_code 時）：

| 舊 severity | 反推 impact |
|---|---|
| critical | privileged |
| warning | sensitive |
| info | routine |

- **`notable` 永不由 severity 反推**（僅 catalog 可產生）。
- 若 caller 傳 `outcome`，用之；否則預設 `success`。
- **本 change 同一交付**必須把所有顯式 `AuditSeverity.WARNING` 站點改為傳正確 `outcome`（至少：app token / MCP deny → `denied`；token rotate 成功 → `success` + sensitive catalog code）。禁止只上 adapter 預設 success 而留下 deny 污染。

Legacy event_code：`tcrt.audit.legacy.<action>_<resource>` 小寫拼接，或固定集合於 catalog 預先登錄（adapter 用的 code MUST 皆在 catalog）。

### D6 — Audit DB migration

- 新增：`event_code` VARCHAR(128)、`impact`、`outcome`、`schema_version` SMALLINT NOT NULL DEFAULT 0。
- Portable string enum（`native_enum=False`）與現況一致。
- 索引：`event_code`、`(event_code, timestamp)`；不對 `action_brief` 假裝 `%q%` 可用 B-tree 加速。
- Downgrade：drop 新欄／索引。

### D7 — Audit 搜尋 Phase A（完整契約）

#### HTTP

| 方法 | 路徑 | 用途 |
|---|---|---|
| GET | `/audit/logs` | 篩選列表（**無** `q`） |
| POST | `/audit/logs/search` | 含 `q` 的搜尋 + 相同篩選 |
| GET | `/audit/logs/export` | export；篩選與 list 對齊；**無** `q`（避免長查詢）；若需搜尋後 export 可 follow-up |

**GET list / export 新增 Query：** `impact`、`outcome`、`event_code`、`resource_id`（精確）、既有 username/role/resource_type/action_type/team_id/severity/time/page/page_size。

**POST search body（JSON）：**

```json
{
  "q": "string",
  "impact": null,
  "outcome": null,
  "event_code": null,
  "resource_id": null,
  "action_type": null,
  "resource_type": null,
  "severity": null,
  "username": null,
  "role": null,
  "team_id": null,
  "start_time": null,
  "end_time": null,
  "page": 1,
  "page_size": 50
}
```

- `q`：必填；`strip` 後長度 ∈ **[1, 200]**，否則 **400**（`INVALID_QUERY`）。Whitespace-only → 400。篩選-only 請用 GET list。
- 比對欄位：`action_brief`、`event_code`、`resource_id`、`username`（OR）。
- **MUST NOT** 搜 `details`。
- **LIKE 萬用字元：** 實作 MUST escape `%`、`_`（及引擎相關 escape）；`q="%"` 只匹配字面含 `%` 的列，不得變全表。
- **大小寫：** 以 SQLAlchemy `ilike` 為實作（與現有 username 一致）；契約保證 **ASCII** case-insensitive；非 ASCII 大小寫折疊折疊 best-effort、跨引擎不保證一致（accepted，寫進測試以 ASCII 為主）。
- **分頁／排序：** 與 GET list 相同（`page`、`page_size` 上限、預設 `timestamp desc`）。
- **回應 shape：** 與 GET list **完全相同**（`items`、`total`、`page`、`page_size`、`total_pages`）；item **不含** `details`（與現況 list 一致）；含 `impact`、`outcome`、`event_code`、`schema_version`、`severity`、`action_brief` 等。
- **權限：** Admin；非 Super Admin 隱藏 super_admin 列（既有）。
- **URL 安全：** GET **MUST NOT** 接受 `q` 參數（有則 400 或忽略並文件化；已決：**400**）。POST 避免 `q` 進 access log 的 query string；應用層 MUST NOT 自訂把 body.`q` 打進 access／audit 的明文。反向代理 body 記錄不在範圍。

**效能（accepted）：** Phase A 為 `%q%` 掃描；建議 UI 搭配時間範圍；不加假 index；FTS follow-up。

### D8 — Ops level 準則與鎖定路徑（無 OR 歧義）

準則表同前：DEBUG / INFO（含已處理可預期降級）/ WARNING / ERROR / CRITICAL。

**鎖定路徑（控制流 → outcome → catalog level；禁止同 outcome 雙 level）：**

Level **只**由 `ops_level_by_outcome[outcome]` 決定；同一 event_code 不得對同一 outcome 映射兩個 level。若需不同嚴重度，MUST 用不同 outcome 或不同 event_code。

| 情境（對齊 `maybe_fill_report_url`） | event_code | outcome | catalog level |
|---|---|---|---|
| Result provider 未配置 → return None | （不 emit） | — | — |
| Result provider instantiate 例外 | `tcrt.ops.automation.result_provider.instantiate` | failure | ERROR |
| CI artifact 下載失敗且繼續 Allure／legacy | `tcrt.ops.automation.ci_artifact.download` | failure | INFO |
| Allure 未配置 base_url → fall through | `tcrt.ops.automation.allure_proxy.skip` | partial | DEBUG |
| Allure 上傳失敗且 **程式繼續** strategy 2（legacy URL） | `tcrt.ops.automation.allure_proxy.upload` | **partial** | INFO |
| Allure 上傳失敗且 **決定不** fall through（例如已知無 result provider／明確 terminal 分支） | `tcrt.ops.automation.allure_proxy.upload` | **failure** | ERROR |
| report URL lookup 失敗 | `tcrt.ops.automation.result_provider.report_url` | failure | INFO |

`allure_proxy.upload` catalog 映射：**partial→INFO，failure→ERROR，success→DEBUG**。

**判定「是否 fall through」：** 以 `run_service.maybe_fill_report_url` 控制流為準——現況 `AllureProxyError` 後進入 strategy 2 時 emit **partial**；若未來或實作在 upload 前已知 `load_result_provider` 會是 None 而選擇直接 return，則 emit **failure**。測試 MUST 覆蓋 partial 與 failure 兩種 outcome（可用 mock 分支），而非依賴模糊的「或 INFO 或 ERROR」。

**額外 ops 事件（run_service.py 背景同步與取消）：**

| 情境 | event_code | outcome | catalog level |
|---|---|---|---|
| Provider cancel 失敗 | `tcrt.ops.automation.run.cancel` | failure | ERROR |
| Sync run 失敗（HTTP/連線） | `tcrt.ops.automation.run.sync` | failure | INFO |
| Sync run 失敗（其他例外） | `tcrt.ops.automation.run.sync` | failure | WARNING |
| Backfill report 失敗 | `tcrt.ops.automation.run.backfill_report` | failure | INFO |

### D9 — system-log-viewer 相容

- **不變：** ring buffer 旁路、不平行 stdout、無 server keyword、Super Admin、SSE 契約骨架。
- **有意變更：** 經 catalog 的 ops 路徑之 **level 與 message 正文／尾碼**（stdout 內容會變——這是功能目標，不是 buffer 副作用）。
- Snapshot 與 SSE `log` event 的 record JSON **同一 schema**：必填舊欄位 + 可選 `event_code`/`outcome`。
- 解析：見 D3。

### D10 — 連續失敗升級

本 change **不做**。Accepted residual；依賴正確 level。

## Risks / Trade-offs

| 風險 | 緩解 |
|---|---|
| 歷史 impact 篩選漏列 | UI 提示 + severity 篩選；accepted |
| `%q%` 大表慢 | Admin-only；建議時間窗；FTS 另案 |
| safe_emit 吞錯導致 silent audit 缺口 | raw ERROR log + 監控 follow-up |
| 非 ASCII ilike 跨引擎差 | 契約限 ASCII 保證；測試用 ASCII |
| 不全站改 warning | 鎖定路徑 + WARNING audit 站點同交付 |

## Migration Plan

1. audit migration（`schema_version` NOT NULL DEFAULT 0 + 新欄）。
2. catalog + `emit_event` / `safe_emit_event` + adapter（`app/services/observability/`）。
3. **同 PR：** WARNING audit 站點 outcome 修正。
4. search/list/export API + UI。
5. automation result ops 路徑（run_service.py、allure_proxy.py）。
6. system log buffer 可選欄位 + 契約測試。

**Rollback：** 回滾 app；migration downgrade 可丟新欄資料。  
**Forward：** 只回滾 app、保留新欄時，舊程式忽略未映射 column 即可（注意 ORM 需與 DB 對齊時應一起回滾）。

## Open Questions

（無未決項；下列為已決摘要）

- Search：`POST /audit/logs/search`；GET 拒 `q`。
- `schema_version`：`SMALLINT NOT NULL DEFAULT 0`，新寫入=1。
- Emit：核心 raise + `safe_emit_event` best-effort。
- Catalog 路徑：`app/services/observability/`（ADR-001）。
- Allure upload：fall through→outcome partial→INFO；terminal→failure→ERROR（catalog 單一映射）。
- 雙寫：先 validate，再 ops，再 audit；validate 失敗兩者皆不寫。

---

## Appendix: MVP Event Code Catalog (Complete)

### Audit Events (domain=audit, write_audit=true, write_ops=false)

| event_code | impact | details_schema | brief_template |
|---|---|---|---|
| `tcrt.audit.app_token.rotate` | sensitive | AppTokenAccessDetails | "Rotated app token '{token_name}' (id={token_id})" |
| `tcrt.audit.app_token.access.allowed` | sensitive | AppTokenAccessDetails | "App token '{token_name}' (id={token_id}) allowed from {client_ip}" |
| `tcrt.audit.app_token.access.denied` | sensitive | AppTokenAccessDetails | "App token '{token_name}' (id={token_id}) DENIED from {client_ip}" |
| `tcrt.audit.mcp_token.access.allowed` | sensitive | MCPTokenAccessDetails | "MCP token {machine_id} allowed from {client_ip}" |
| `tcrt.audit.mcp_token.access.denied` | sensitive | MCPTokenAccessDetails | "MCP token {machine_id} DENIED from {client_ip}" |
| `tcrt.audit.legacy.{action}_{resource}` | (mapped) | AuditGenericDetails | "{action} {resource}" |

### Ops Events (domain=ops, write_audit=false, write_ops=true)

| event_code | outcome | ops_level |
|---|---|---|
| `tcrt.ops.automation.result_provider.instantiate` | failure | ERROR |
| `tcrt.ops.automation.ci_artifact.download` | failure | INFO |
| `tcrt.ops.automation.allure_proxy.skip` | partial | DEBUG |
| `tcrt.ops.automation.allure_proxy.upload` | success | DEBUG |
| `tcrt.ops.automation.allure_proxy.upload` | partial | INFO |
| `tcrt.ops.automation.allure_proxy.upload` | failure | ERROR |
| `tcrt.ops.automation.result_provider.report_url` | failure | INFO |
| `tcrt.ops.automation.run.cancel` | failure | ERROR |
| `tcrt.ops.automation.run.sync` | failure | INFO (HTTP error) / WARNING (other) |
| `tcrt.ops.automation.run.backfill_report` | failure | INFO |

> Note: Each ops event_code with multiple outcomes has a single `ops_level_by_outcome` mapping in the catalog. No duplicate mappings for same outcome.