# Proposal: add-system-runtime-settings-viewer

## Why

Super Admin 已有 `/system-logs` 即時 log 檢視，但排查時仍常需對照「這台 process 的運維設定視角」——例如 DB 引擎、環境中設定或可推導的 `WEB_CONCURRENCY`、對外 base URL、log viewer 容量等。這些資訊散落在 env／容器設定，沒有與 log viewer 同級的唯讀網頁入口。

## What Changes

- 在既有 **System Logs** 頁新增分頁：
  - **Logs**：維持既有即時 log 契約（見 capability `system-log-viewer`）。
  - **Runtime Settings**：唯讀顯示**本請求 process** 的設定快照（非跨 worker 聚合、**不宣稱實際 worker 進程數**）。
- 新增 Super Admin API `GET /api/admin/system-runtime-settings`（`include_in_schema=False`、`no-store`）。
- 回傳**固定 allowlist JSON**（型別與 nullability 見 design／spec）；資料庫以結構化欄位呈現，**不回傳近似原始 URL**。
- `WEB_CONCURRENCY` 拆成 `configured_web_concurrency`（僅合法正整數）與 `inferred_default_web_concurrency`（僅未設或精確 `""` 時對應腳本預設）；`web_concurrency_source` 為 `configured`｜`inferred_default`｜`invalid_configured`（含純空白；非法非空 env 不暗示腳本會 fallback；判定不先 strip）。
- **不**以推導值冒充實際 worker 數；固定 `worker_count_note_code: "not_actual_worker_count"`，UI i18n 映射。
- v1 **不含** bootstrap 政策區塊（非 Settings 集中建模，且 API 無法知悉 CLI `--no-backup`）。
- 每次成功 API 讀取 best-effort audit：`ip_address`／`user_agent` 用既有一級欄位；`details` 僅 `pid`／`worker_instance_id`（不含快照本體）。
- 三語系 i18n；文件標示 Settings 與 Logs 可能落在不同 worker。

### 非目標（Non-goals）

- 不可編輯設定；不回傳 secret／token／私鑰明文。
- 不顯示完整 `config.yaml`、backup 路徑、憑證路徑、SQLite 完整檔案路徑。
- 不強化 HTML route 授權（維持：入口隱藏 + API 嚴格拒絕；與既有 log viewer 一致）。
- 不變更 DB schema／migration／MCP／AI helper。
- **本 change 的 apply／實作流程不得自行 archive 其他 change**（含 `add-super-admin-log-viewer`）。若 main 尚無對應 `system-log-viewer` Requirement，實作者 MUST 停止並請使用者另行核准 verify／archive 前置 change。

## Capabilities

### New Capabilities

- `system-runtime-settings-viewer`: Super Admin 唯讀 runtime 設定快照（固定 JSON 契約、結構化 DB 摘要、遮罩規則、分頁 UI、稽核）。

### Modified Capabilities

- `system-log-viewer`: **僅**修改既有 Requirement `Super Admin 專用即時 log 檢視頁面`（名稱必須一字不差），在保留原全文與 scenarios 的前提下加入分頁殼層與 Runtime Settings 入口；不新增近似名稱的替代 Requirement。

## Impact

- **前置（人工）**：實作前檢查 main 是否已有 `Super Admin 專用即時 log 檢視頁面`；若無，停工並請使用者核准前置 archive，**不得**由本 change 流程代 archive。
- **後端**：admin API + settings assembler；測試含授權、exact key set、遮罩、`postgres://` alias、concurrency、audit 一級欄位。
- **前端**：`system_logs.html` tabs + JS/CSS/i18n；必須有 JS 測試覆蓋 lazy／refresh／mismatch／語系。
- **文件**：`docs/system-log-viewer.md`。