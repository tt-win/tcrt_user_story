## Why

目前 Dashboard 的快速功能未提供既有 per-team App Token 管理入口，Admin 與 Super Admin 必須先自行找到 Team Management 再進入管理流程。需要補上角色限定的快捷入口，同時避免把敏感管理能力投影給一般 User 或 Viewer。

## What Changes

- Personal Dashboard 僅在目前角色為 `ADMIN` 時加入 App Token 快速功能；`USER` 與 `VIEWER` 不顯示。
- System Administration Dashboard 為 `SUPER_ADMIN` 加入同一個 App Token 快速功能。
- 快速功能沿用既有緊湊、icon-only、等寬 Dashboard action rail，點擊後直接在 Dashboard 開啟共用 App Token 管理 modal，不導向 Team Management。
- Admin 以 Dashboard 已驗證的偏好團隊直接載入 modal；Super Admin 因系統工作台沒有偏好團隊，先在同一 modal 選擇 Team。
- 目標頁面與 App Token API 繼續執行既有 team admin／Super Admin 授權，不因 Dashboard 入口而放寬權限。
- 同步三語系 label 與角色投影回歸測試。

## Capabilities

### New Capabilities

無。

### Modified Capabilities

- `personal-dashboard`: 新增僅供 Admin 的 App Token 快速功能，並明確排除 User／Viewer。
- `system-administration-dashboard`: 新增 Super Admin 的 App Token 管理快速功能。

## Impact

- 後端：Dashboard quick-action allowlist 的角色化投影。
- 前端：將 Team Management 的 App Token modal、CSS 與 controller 抽成 Dashboard／Team Management 共用元件，沿用既有 action renderer，無新相依套件。
- i18n：`en-US`、`zh-CN`、`zh-TW` 新增 App Token label。
- 測試：Dashboard API role matrix 與前端固定入口契約。
- 資料庫／migration：無 schema、資料或 migration 變更。
- 相容性／回復：API response 僅 additive；回復時移除兩個角色的 action、共用 modal include 與 locale key 即可，不影響既有 App Token 資料或授權。
