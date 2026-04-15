# Change: Add custom CA support for Jira client

## Why
部分 JIRA 伺服器使用自簽或內部 CA 憑證，現行客戶端無法指定自訂 CA，導致連線失敗。

## What Changes
- 新增 `jira.ca_cert_path` 設定欄位（`config.yaml`）。
- 參照 `jira_sync_v3` 的做法，建立可合併系統 CA + 自訂 CA 的工具函式。
- Jira 客戶端請求新增 `verify` 設定以使用自訂 CA，保留未設定時的預設行為。

## Impact
- Affected specs: `jira-connection`（新增能力）
- Affected code: `app/config.py`, `config.yaml.example`, `app/services/jira_client.py`, 新增 `app/services/tls_utils.py`
- Runtime behavior: 不影響未設定 `jira.ca_cert_path` 的既有部署
