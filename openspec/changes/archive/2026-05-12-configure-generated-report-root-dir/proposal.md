## Why

目前系統會把 HTML generated reports 固定寫入專案根目錄的 `generated_report/`，部署到 Docker volume、外部磁碟或不同環境時無法像附件一樣透過設定切換位置。We need a config-driven report root so deployment can change report storage without patching code.

## What Changes

- 新增 `reports.root_dir` 設定，並支援 `REPORTS_ROOT_DIR` 環境變數覆寫。
- 將 `/reports` 靜態掛載、HTML 報表產生、報表存在檢查統一改為使用同一個 resolved report root。
- 保留既有預設行為：未設定時仍使用專案根目錄 `generated_report/`。
- 確保報表根目錄與 `.tmp` 子目錄會在服務啟動與寫入前自動建立。

## Capabilities

### New Capabilities
- `generated-report-storage`: Allow generated HTML reports to be stored and served from a configurable root directory.

### Modified Capabilities
- None.

## Impact

- Affected code: `app/config.py`, `app/main.py`, `app/services/html_report_service.py`, `config.yaml.example`
- Affected behavior: generated HTML report storage path resolution and `/reports` static file serving
- Validation: config-loading tests and focused report-path tests
