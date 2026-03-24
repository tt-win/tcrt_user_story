## Context

目前組織架構同步 modal 已經有「組織」與「MCP Token」兩個進階分頁，並透過 `config/permissions/ui_capabilities.yaml` 與 `/api/permissions/ui-config?page=organization` 控制只有 Super Admin 可見。另一方面，`app/services/scheduler.py` 已在 app startup 啟動，但目前僅保留單機 in-memory loop，沒有持久化設定、沒有對外 API，也沒有任何實際註冊中的任務。若要讓排程服務可被營運人員管理，需要同時解決 UI、持久化設定、scheduler service registry、執行狀態回寫與權限控制。

## Goals / Non-Goals

**Goals:**
- 在組織架構同步管理 modal 中新增符合既有 TCRT 風格的 Service 管理 tab
- 讓 Super Admin 可查詢目前系統支援排程的服務、啟用/停用排程並設定每日執行時間
- 讓 UI 可看到已排程服務的目前狀態、下次執行時間、上次執行狀態與最近錯誤
- 讓 scheduler 在啟動時自動載入資料庫中的排程設定，並於執行時更新狀態
- 第一版至少支援 Lark 組織同步作為可排程服務，並保留未來擴充多服務的結構

**Non-Goals:**
- 不處理多副本分散式鎖與 leader election
- 不把現有手動同步 UI 移除或改成完全由排程驅動
- 不在此變更中支援 cron expression 或複雜週期規則；先採每日固定時間
- 不建立獨立新頁，而是維持在既有 modal/tab 架構內

## Decisions

### 1. 建立資料庫持久化表 `scheduled_services`

新增主資料庫表 `scheduled_services` 儲存每個 service 的排程設定與最近執行資訊，例如：`service_key`、`display_name`、`description`、`schedule_type`、`run_at_time`、`enabled`、`is_running`、`last_run_started_at`、`last_run_finished_at`、`last_run_status`、`last_run_message`、`last_error`、`next_run_at`。

- Why: 目前 scheduler 狀態只存在 process memory，重啟後會消失，也無法提供 UI 查詢。
- Alternative considered: 使用 `config.yaml` 儲存排程設定。未採用，因為 UI 需要即時修改且需保存執行結果，不適合寫回檔案。

### 2. 用 scheduler registry 管理「系統可排程服務」

在 `TaskScheduler` 內新增 service registry，將可排程服務定義成具有 `service_key`、顯示名稱、描述、支援的 schedule 類型、實際執行函式的 metadata。第一版先提供 `lark_org_sync`。

- Why: 需求明確要求 UI 可以「選擇目前系統可用來排程的服務」，這需要由後端宣告來源，而不是前端寫死。
- Alternative considered: 前端直接硬編碼一個 service 下拉。未採用，因為之後新增第二個 service 時會變成多處同步維護。

### 3. 排程規則先採「每日固定時間」

UI 以簡化模式提供 `enabled` + `run_at_time(HH:MM)`，由 scheduler 在每分鐘輪詢時計算 `next_run_at` 並觸發。

- Why: 符合目前 scheduler 的簡單輪詢設計，也符合使用者的「可以設定時間」需求。
- Alternative considered: 支援 cron expression。未採用，因為會增加 UI 與驗證複雜度，且超出當前需求。

### 4. 執行狀態由 scheduler 寫回持久化表

當 scheduler 執行某個 service 時，會在開始前將 `is_running=true`、更新 `last_run_started_at`；完成後更新 `last_run_finished_at`、`last_run_status`、`last_run_message`、`last_error` 與新的 `next_run_at`。

- Why: UI 需求要看「上次執行狀態」與「目前狀態」，單靠 `SyncHistory` 不足以表示 service 層級的當前排程狀態。
- Alternative considered: 直接從 `SyncHistory` 動態推算。未採用，因為 `SyncHistory` 是團隊同步歷史，不是 scheduler service 狀態表，且 scheduler 未來不只會跑組織同步。

### 5. 前端設計延續 TCRT 現有 modal/card/tabs 語言

「Service 管理」tab 會沿用 `team_management.html` 現有的 Bootstrap card + tab 架構，但在內容佈局上增加較明確的摘要帶、服務卡片、狀態 badge 與時間設定面板，讓它比目前的組織同步卡片更具管理介面感，同時不脫離現有 TCRT 視覺語言。

- Why: 使用者要求使用 frontend design skill，但也要求符合目前 TCRT 的風格與設計。
- Alternative considered: 做成完全新的獨立控制台視覺。未採用，因為會與現有 modal 風格落差過大。

### 6. 權限控制沿用 `organization` UI capability 與 `require_super_admin`

新增 `tab-service-management` UI capability，對齊 `tab-org` / `tab-mcp-token` 的 `organization_management: advanced` 權限；相關 API 一律以 `require_super_admin()` 保護。

- Why: 現有組織進階功能已採同一套模式，能減少額外權限模型成本。
- Alternative considered: 自建 scheduler 專屬 feature/action。未採用，因為目前需求範圍仍屬組織管理的一部分。

## Risks / Trade-offs

- [多副本部署會重複觸發排程] → Mitigation: 本 change 僅建立單機/單 process 能力，於 spec 與文件明示多副本需 leader lock 或拆 worker。
- [service 執行中 app 重啟導致 `is_running` 殘留] → Mitigation: scheduler startup 時對殘留 running 狀態做安全回收，標記為 interrupted/failed 並重算 `next_run_at`。
- [scheduler 與手動同步共用同一組同步 service，可能互相阻擋] → Mitigation: 延續既有 `is_syncing` guard，scheduled job 遇到同步中時記錄 skipped/busy 訊息並保留下一次執行。
- [新增資料表需要 migration] → Mitigation: 使用 Alembic 新 migration，並讓 `database_init.py` 將其納入 required tables 檢查。

## Migration Plan

- 新增 Alembic migration 建立 `scheduled_services` 表。
- app startup 時 scheduler 載入 registry，若資料表內尚無對應 service 記錄則自動 seed 預設資料。
- 既有環境升級後，不會自動啟用任何排程；預設為 disabled，需由 Super Admin 在 UI 啟用。
- 若需 rollback，保留資料表即可；回退程式碼後不會影響其他核心流程。

## Open Questions

- 第一版是否只暴露 `lark_org_sync` 一個 service：目前預設是，且設計上保留未來擴充更多 service。
