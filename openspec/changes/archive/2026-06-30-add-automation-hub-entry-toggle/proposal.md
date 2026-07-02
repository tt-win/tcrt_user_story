## Why

目前 Automation Hub 對所有團隊一律顯示入口（首頁 team card 的「Automation Hub」按鈕、團隊管理「進入團隊」選單項目）。組織若尚未準備好、或暫時不開放自動化能力，沒有一個集中、可即時切換的方式把入口收起來。本變更提供一個組織層級、可由 Super Admin 於執行期切換的開關，治理 Automation Hub 入口的可見性。

## What Changes

- 在「團隊管理 → 同步組織架構 → 組織自動化基礎設施」分頁新增一個 **Automation Hub 入口** 開關（開／關），僅 Super Admin 可操作。
- 開關狀態以組織層級設定（runtime-mutable）持久化；預設為 **開啟**，維持現有行為（既有顯示行為不變）。
- 當開關為 **關閉** 時，隱藏兩個 team card 入口：
  - 團隊管理 →「進入團隊」下拉選單中的「Automation Hub」項目。
  - 首頁 team card 上綠色「Automation Hub」按鈕。
- 採 **UI-only hiding**（入口治理）：`/automation-hub` 頁面與 automation 相關 API 不因開關關閉而被阻擋，仍可由直接網址存取；後端能力完整保留。此與本專案既有的 `ai-assist-ui-exposure-control`／`test-case-helper-config-toggle` 治理模式一致。
- 新增讀取端點供任何已登入使用者取得開關狀態（首頁與團隊管理頁面在所有角色下都需要讀取以決定入口可見性）；寫入端點僅限 Super Admin。

非目標（Non-Goals）：

- 不阻擋 `/automation-hub` 頁面或 automation API（非「停用功能」，僅「隱藏入口」）。
- 不提供 per-team 覆寫；本開關為單一組織層級設定。
- 不改變 Automation Hub 既有功能、provider 設定或執行流程。

## Capabilities

### New Capabilities
- `automation-hub-entry-toggle`: 以組織層級設定控制 Automation Hub 入口（team card 進入點）顯示／隱藏的行為，並定義讀寫權限與預設行為。

### Modified Capabilities
<!-- 無既有 capability 的需求被變更；本變更僅新增入口治理需求。 -->

## Impact

- **資料庫**：新增 `system_settings` 鍵值表（key/value/updated_at/updated_by）以存放 runtime-mutable 設定；需新增一支 Alembic migration（main DB）。設定缺漏時讀取回退為預設「開啟」，故為非破壞性升級；rollback 僅需移除該表（無既有資料相依）。
- **後端 API**：新增 `GET /api/system/automation-hub/settings`（任何已登入者可讀）與 `PUT /api/system/automation-hub/settings`（Super Admin only，寫入並寫稽核紀錄）。
- **前端**：
  - `app/templates/team_management.html`：在 `組織自動化基礎設施` 分頁新增開關 UI。
  - `app/static/js/team-management/org-automation-infra.js`：載入／儲存開關狀態。
  - `app/static/js/team-management/main.js`：「進入團隊」選單依開關狀態隱藏 Automation Hub 項目。
  - `app/static/js/index.js`：首頁 team card 依開關狀態隱藏 Automation Hub 按鈕。
  - i18n：`en-US.json` / `zh-CN.json` / `zh-TW.json` 新增開關相關字串。
- **相容性**：預設開啟保留現狀；舊資料庫升級後在尚未設定前一律視為開啟，無行為退化。
