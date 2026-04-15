## Context

目前附件已可透過 `attachments.root_dir` 指定目錄，但 HTML generated reports 仍固定寫入專案根目錄 `generated_report/`。`app/main.py` 會將 `/reports` 掛到這個固定目錄，`HTMLReportService` 與報表存在檢查也直接依賴同一路徑，因此只改單一位置會造成寫入與讀取不一致。

## Goals / Non-Goals

**Goals:**
- 提供與附件類似的 `reports.root_dir` 設定能力
- 保持既有 `/reports/<report_id>.html` URL 契約不變
- 保持未設定時仍使用專案根目錄 `generated_report/`
- 讓 static mount、報表生成、存在檢查使用同一套 path resolution

**Non-Goals:**
- 不更動報表內容、檔名格式或 API 回傳結構
- 不搬移既有歷史報表檔案
- 不重構附件儲存邏輯

## Decisions

### 1. 新增獨立 `ReportsConfig`

在 `app/config.py` 新增 `ReportsConfig`，提供 `reports.root_dir` 與 `REPORTS_ROOT_DIR` 覆寫邏輯。

- Why: `reports` 與 `attachments` 雖然都是檔案輸出，但用途與生命週期不同，應保留獨立設定鍵。
- Alternative considered: 直接重用 `attachments.root_dir`。未採用，因為會把附件與報表混放，增加清理與權限邊界混淆。

### 2. 在 config model 內提供統一的 root resolution

由 `ReportsConfig.resolve_root_dir(project_root)` 負責將空值解析為 `<project_root>/generated_report`，非空值則直接使用設定值。

- Why: 讓 `app/main.py`、`HTMLReportService` 與報表存在檢查共用同一套規則，避免 duplicated path logic 漂移。
- Alternative considered: 在每個使用點各自寫 `Path(... ) if ... else ...`。未採用，因為後續容易出現不一致。

### 3. 在 mount / write 前先建立目錄

`/reports` 掛載前先建立 report root 與 `.tmp` 目錄；`HTMLReportService` 初始化時也確保 `.tmp` 存在。

- Why: 避免 fresh environment 或新設定路徑尚未建立時，static mount 或 atomic write 失敗。
- Alternative considered: 僅在 startup event 建目錄。未採用，因為 mount 發生在 startup 前。

## Risks / Trade-offs

- [切換 root_dir 後舊報表仍留在舊目錄] → Mitigation: 保持不自動搬檔，部署後可視需要重新產生報表。
- [自訂相對路徑會依賴程序工作目錄] → Mitigation: 保持與 `attachments.root_dir` 相同語意，避免兩者行為不一致。

## Migration Plan

- 不需要資料庫 migration。
- 若未設定 `reports.root_dir`，部署後行為維持不變。
- 若設定新路徑，需同步確保該路徑可寫入並納入持久化策略（例如 volume mount）。

## Open Questions

- None.
