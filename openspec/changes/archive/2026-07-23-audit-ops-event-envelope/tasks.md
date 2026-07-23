## 1. Observability 基礎（catalog + emit）

- [x] 1.1 新增 `app/services/observability/enums.py`：`Impact`、`Outcome`、`OpLevel` 三枚舉。→ verify: `uv run python -c "from app.services.observability.enums import Impact, Outcome, OpLevel; print('OK')"`
- [x] 1.2 新增 `app/services/observability/event_catalog.py`：`EventDef`、`EventCatalog`、`get_event_def`、`iter_catalog`、`get_catalog`、`register_event`；目錄預註冊 spec 表中 19 條 MVP 事件。→ verify: `uv run python -c "from app.services.observability import get_event_def, iter_catalog; print([e.event_code for e in iter_catalog()])"`
- [x] 1.3 新增 `app/services/observability/schemas.py`：所有 event 的 Pydantic details schema。→ verify: schema 驗證測試
- [x] 1.4 新增 `app/services/observability/__init__.py`：導出公共 API。→ verify: `uv run python -c "from app.services.observability import emit_event, safe_emit_event, get_event_def, Impact, Outcome, OpLevel; print('OK')"`
- [x] 1.5 **新增強制掃描測試**：`app/testsuite/test_emit_enforcement.py` 檢查無業務代碼直接呼叫 `emit_event`（僅允許 `safe_emit_event` / `emit_audit_event` / `emit_ops_event`）。→ verify: `uv run pytest app/testsuite/test_emit_enforcement.py -q`

### MVP Event Codes（已在 catalog 定義，對應 tasks 5.1/5.2）：

**Audit events (write_audit=True, write_ops=False):**
| event_code | impact | 用途 |
|---|---|---|
| `tcrt.audit.app_token.rotate` | SENSITIVE | App token 輪換成功 |
| `tcrt.audit.app_token.deny` | SENSITIVE | App token 拒絕存取（denied outcome） |
| `tcrt.audit.mcp_token.deny` | SENSITIVE | MCP token 拒絕存取（denied outcome） |
| `tcrt.audit.legacy.*` | auto-mapped | 既有 audit_service.log_action 站點（adapter 反推） |

**Ops events (write_audit=False, write_ops=True):**
| event_code | outcome | ops_level |
|---|---|---|
| `tcrt.ops.automation.result_provider.instantiate` | failure | ERROR |
| `tcrt.ops.automation.ci_artifact.download` | failure | INFO |
| `tcrt.ops.automation.allure_proxy.skip` | partial | DEBUG |
| `tcrt.ops.automation.allure_proxy.upload` | success | DEBUG |
| `tcrt.ops.automation.allure_proxy.upload` | partial | INFO |
| `tcrt.ops.automation.allure_proxy.upload` | failure | ERROR |
| `tcrt.ops.automation.result_provider.report_url` | failure | INFO |
| `tcrt.ops.automation.run.sync` | failure | INFO |
| `tcrt.ops.automation.run.backfill_report` | failure | INFO |
| `tcrt.ops.automation.run.cancel` | failure | INFO |

## 2. Audit DB 與 adapter

- [x] 2.1 alembic_audit migration：新增 `event_code` VARCHAR(128)、`impact`、`outcome`、`schema_version` SMALLINT NOT NULL DEFAULT 0 + 索引 `event_code`、`(event_code, timestamp)`。禁止 `schema_version NOT NULL DEFAULT 1`。→ verify: upgrade 後舊列 schema_version=0；downgrade 可跑
- [x] 2.2 更新 `AuditLogTable`、Pydantic models、create/query 路徑。→ verify: `uv run pytest app/testsuite/test_auxiliary_db_migrations.py -q`
- [x] 2.3 `log_action` 改 adapter：可選 `outcome`/`event_code`、severity 反推 impact、legacy severity 雙寫、走 `safe_emit_event`。→ verify: adapter 單元測試
- [x] 2.4 **同交付**遷移顯式 `AuditSeverity.WARNING` 站點（app_token rotate、app_token/MCP deny 等）為正確 outcome + catalog code。→ verify: deny 列 outcome=denied；rotate success+sensitive

## 3. Audit 查詢、搜尋、export API

- [x] 3.1 擴充 GET `/audit/logs`：impact、outcome、event_code、resource_id；回應含新欄位；**拒絕 query `q`（400）**。→ verify: API 測試
- [x] 3.2 實作 POST `/audit/logs/search`：完整 body 契約、分頁、LIKE escape、ASCII ilike、不搜 details、回應 shape 同 list。→ verify: 命中/details 不中/q 邊界/`q=%`/分頁測試
- [x] 3.3 export 支援新篩選與 CSV 新欄（event_code、impact、outcome、schema_version）。→ verify: export 測試
- [x] 3.4 權限與 super_admin 列隱藏回歸。→ verify: 權限測試 (既有 super_admin 篩選邏輯已涵蓋 event_code/impact/outcome 欄位)

## 4. Audit UI 與 i18n

- [x] 4.1 篩選控件：action_type、impact、outcome、resource_id + 搜尋框（POST search）。→ verify: `node --check app/static/js/audit_logs.js`
- [x] 4.2 表格 impact/outcome；legacy 提示；impact 篩選不含歷史列的說明文案。→ verify: 文案鍵存在
- [x] 4.3 三語系 en-US/zh-CN/zh-TW。→ verify: `node scripts/check-i18n-coverage.mjs`

## 5. Ops 路徑校正（Automation result）

- [x] 5.1 `run_service.py`：替換 `logger.warning` 為對應 catalog ops emit（event_code 見上表）。CI artifact 失敗→INFO；instantiate→ERROR；report_url→INFO。→ verify: mock logger 斷言 level
- [x] 5.2 `allure_proxy.py` / `maybe_fill_report_url`：skip→partial+DEBUG；upload fall through→partial+INFO；upload terminal→failure+ERROR（catalog 映射，非手寫雙 level）。→ verify: 兩 outcome 分支 level 測試

## 6. System log viewer

- [x] 6.1 ring buffer 解析最後一行尾碼 → optional event_code/outcome。→ verify: `uv run pytest app/testsuite/test_system_log_buffer.py -q`
- [x] 6.2 snapshot 與 SSE 同 schema；無 keyword 回歸。→ verify: `uv run pytest app/testsuite/test_system_log_api.py -q`
- [x] 6.3 UI 顯示 event_code（小改）。→ verify: `node --check` 相關 JS

## 7. 收尾驗證

- [x] 7.1 `openspec validate audit-ops-event-envelope --strict`。→ verify: 該指令
- [x] 7.2 `uv run ruff check` 本 change 變更檔。→ verify: 乾淨
- [x] 7.3 目標測試：`uv run pytest app/testsuite/test_system_log_api.py app/testsuite/test_system_log_buffer.py app/testsuite/test_auxiliary_db_migrations.py -q` 以及本 change 新增之 audit search/emit/automation level 測試檔全綠。→ verify: 該指令集合