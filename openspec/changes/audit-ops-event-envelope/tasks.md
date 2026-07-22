## 1. Observability 基礎（catalog + emit）

- [ ] 1.1 新增 `app/observability/event_catalog.py`：登錄結構、查詢、重複 code 啟動／測試檢測。 → verify: 單元測試 catalog 無重複、未知 code 查詢失敗
- [ ] 1.2 新增 `app/observability/emit.py`：核心 `emit_event`（UnknownEventCodeError／EventDetailsValidationError；**ops** outcome 不在 level map 亦 validate 失敗；audit-only 不需 level map）、`safe_emit_event`（吞錯 + raw logger.error 不經 catalog）、雙寫順序 validate→ops→audit、薄包裝。 → verify: 核心 raise 測試 + safe 不拋 + 雙寫順序／半失敗測試
- [ ] 1.3 登錄 MVP event 集合：legacy audit codes、WARNING 遷移站點 codes、automation result ops codes（含 level_by_outcome）。 → verify: catalog 單元測試列出必要 code

## 2. Audit DB 與 adapter

- [ ] 2.1 alembic_audit migration：nullable `event_code`、`impact`、`outcome`、`schema_version` + 索引；禁止 schema_version NOT NULL DEFAULT 污染舊列。 → verify: upgrade 後舊列 schema_version IS NULL；downgrade 可跑
- [ ] 2.2 更新 `AuditLogTable`、Pydantic models、create／query 路徑。 → verify: `uv run pytest app/testsuite/test_auxiliary_db_migrations.py -q`
- [ ] 2.3 `log_action` 等改 adapter：可選 outcome／event_code、severity 反推 impact、legacy severity 雙寫、走 safe_emit。 → verify: adapter 單元測試
- [ ] 2.4 **同交付**遷移顯式 `AuditSeverity.WARNING` 站點（app token rotate、app token／MCP deny 等）為正確 outcome + catalog code。 → verify: deny 列 outcome=denied；rotate success+sensitive

## 3. Audit 查詢、搜尋、export API

- [ ] 3.1 擴充 GET `/audit/logs`：impact、outcome、event_code、resource_id；回應含新欄位；**拒絕 query `q`（400）**。 → verify: API 測試
- [ ] 3.2 實作 POST `/audit/logs/search`：完整 body 契約、分頁、LIKE escape、ASCII ilike、不搜 details、回應 shape 同 list。 → verify: 命中／details 不中／q 邊界／`q=%`／分頁測試
- [ ] 3.3 export 支援新篩選與 CSV 新欄（event_code、impact、outcome、schema_version）。 → verify: export 測試
- [ ] 3.4 權限與 super_admin 列隱藏回歸。 → verify: 權限測試

## 4. Audit UI 與 i18n

- [ ] 4.1 篩選控件：action_type、impact、outcome、resource_id + 搜尋框（POST search）。 → verify: `node --check app/static/js/audit_logs.js`
- [ ] 4.2 表格 impact／outcome；legacy 提示；impact 篩選不含歷史列的說明文案。 → verify: 文案鍵存在
- [ ] 4.3 三語系 en-US／zh-CN／zh-TW。 → verify: `node scripts/check-i18n-coverage.mjs`

## 5. Ops 路徑校正（Automation result）

- [ ] 5.1 `run_service.py` 鎖定路徑改 ops emit；CI artifact 失敗→INFO；instantiate→ERROR；report_url→INFO。 → verify: mock logger 斷言 level
- [ ] 5.2 `allure_proxy`／`maybe_fill_report_url`：skip→partial+DEBUG；upload 後續 fall through→partial+INFO；upload terminal→failure+ERROR（catalog 映射，非手寫雙 level）。 → verify: 兩 outcome 分支 level 測試

## 6. System log viewer

- [ ] 6.1 ring buffer 解析最後一行尾碼 → optional event_code／outcome。 → verify: `uv run pytest app/testsuite/test_system_log_buffer.py -q`
- [ ] 6.2 snapshot 與 SSE 同 schema；無 keyword 回歸。 → verify: `uv run pytest app/testsuite/test_system_log_api.py -q`
- [ ] 6.3 UI 顯示 event_code（小改）。 → verify: `node --check` 相關 JS

## 7. 收尾驗證

- [ ] 7.1 `openspec validate audit-ops-event-envelope --strict`。 → verify: 該指令
- [ ] 7.2 `uv run ruff check` 本 change 變更檔。 → verify: 乾淨
- [ ] 7.3 目標測試：`uv run pytest app/testsuite/test_system_log_api.py app/testsuite/test_system_log_buffer.py app/testsuite/test_auxiliary_db_migrations.py -q` 以及本 change 新增之 audit search／emit／automation level 測試檔全綠。 → verify: 該指令集合
