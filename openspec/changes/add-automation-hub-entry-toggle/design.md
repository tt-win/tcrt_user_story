## Context

Automation Hub 的兩個 team card 入口目前一律顯示。需要一個由 Super Admin 於執行期切換的組織層級開關來治理入口可見性。現況限制：

- 既有的 UI 治理開關（`ai-assist-ui-exposure-control`、`test-case-helper-config-toggle`）皆為**靜態設定**（`settings.ai.qa_ai_helper.enable`，於 template render 時注入），無法由 UI 即時切換。
- 後端目前**沒有** runtime-writable 的鍵值設定儲存（無 system settings / feature-flag 表）。
- 啟動時 `app/db_migrations.py` 會以 `compare_metadata` 做 schema drift 檢查；任何 model 變動都必須有對應 Alembic migration，否則啟動驗證失敗。
- 首頁 team card 由 `index.js` 在 `await applyIndexUiVisibility()` 之後 `loadTeams()` 渲染；團隊管理 team card 由 `team-management/main.js` 的 `loadTeams()` 渲染。兩者皆為 JS 動態渲染。

## Goals / Non-Goals

**Goals:**
- 提供組織層級、runtime-mutable 的 Automation Hub 入口開關，Super Admin 可於「組織自動化基礎設施」分頁切換。
- 開關關閉時隱藏兩個 team card 入口；預設開啟維持現狀。
- 任何已登入使用者可讀開關狀態（決定入口可見性）；僅 Super Admin 可寫。

**Non-Goals:**
- 不阻擋 `/automation-hub` 頁面或 automation API（UI-only hiding，能力保留）。
- 不提供 per-team 覆寫。
- 不改動 Automation Hub 既有功能。

## Decisions

### D1: 以新的 `system_settings` 鍵值表持久化（runtime-mutable）

UI 開關需可即時切換並跨重啟保留，靜態設定（env/yaml/pydantic settings）不適用，且專案無現成可寫入的設定儲存。新增 main DB 的 `system_settings(key PK, value, updated_at, updated_by)` 表，以 key `automation_hub_entry_enabled` 存放布林（字串 `"true"`/`"false"`）。

- **為何鍵值表而非專用 singleton 表**：鍵值表為最小且通用的原語，未來其他組織層級開關可重用而無需再次 schema 變更；singleton 表需處理「保證單列」的 upsert 較繁瑣。
- **避免過度通用化**：雖採通用儲存，但對外 API 僅暴露此單一開關的專屬端點（非通用 settings CRUD），維持表面積最小、意圖明確。
- **預設行為**：key 不存在時讀取回退為 `true`（開啟），確保升級非破壞性。

### D2: 專屬讀寫端點，讀取開放給已登入者、寫入限 Super Admin

- `GET /api/system/automation-hub/settings` → `{ "enabled": bool }`，依賴 `get_current_user`（任一已登入角色）。首頁與團隊管理頁面在所有角色下都要讀此值決定入口可見性。
- `PUT /api/system/automation-hub/settings`（body `{ "enabled": bool }`）→ 依賴 `require_super_admin()`，寫入並記稽核（沿用 `audit_service`，`ResourceType.SYSTEM`）。
- **為何不併入 `/api/permissions/ui-config`**：該端點語意為 per-role RBAC 能力，與「組織層級 runtime 設定」概念不同；分開可維持關注點清晰。

### D3: 前端在渲染 team card 前先取得開關狀態（避免閃爍／競態）

新增共用 helper 取得並快取開關狀態：

- `index.js`：於 `applyIndexUiVisibility()`（已被 `await`）內一併讀取並快取，`renderTeamCards()` 依快取值決定是否輸出 Automation Hub 按鈕。
- `team-management/main.js`：於 `loadTeams()` 渲染前 `await` 取得開關狀態（快取後成本極低），`renderTeamCards()` 依值決定是否輸出「進入團隊」選單的 Automation Hub 項目。
- 取得失敗時**回退為顯示（開啟）**，避免因暫時性錯誤誤把功能藏起來（與預設開啟一致）。

### D4: 開關 UI 沿用既有 org-automation-infra 樣式

於「組織自動化基礎設施」分頁頂部以 Bootstrap `form-switch` 呈現開關，載入時讀取目前狀態，切換時呼叫 `PUT`。該分頁已由 `org-automation-infra.js` 以 Super Admin gating 控制可見，開關 UI 隨之只對 Super Admin 顯示。

## Risks / Trade-offs

- **[UI-only hiding：關閉後仍可由直接網址進入 `/automation-hub`]** → 為刻意設計（能力保留），與既有 `ai-assist-ui-exposure-control` 治理模式一致；已於 proposal 列為 Non-Goal。若日後需硬性停用，可另開變更加上 server-side guard。
- **[讀取端點被高頻呼叫]** → 僅於頁面載入各呼叫一次、回應極小（單一布林），影響可忽略；前端再以模組變數快取避免重複請求。
- **[鍵值表的通用性可能被誤用為任意設定傾倒區]** → 對外僅暴露此開關專屬端點，不提供通用 settings API；新增其他設定須各自走審查。
- **[啟動 drift 檢查]** → 已納入：model 與 migration 同步新增，啟動驗證可通過。

## Migration Plan

1. 於 `app/models/database_models.py` 新增 `SystemSetting` model（對應 `system_settings` 表）。
2. 新增 Alembic migration（main target）建立 `system_settings` 表，`down_revision` 指向目前 head。
3. 升級時無需資料回填；缺漏即視為開啟。
4. **Rollback**：migration `downgrade` 直接 `drop_table('system_settings')`；因無既有資料相依，移除安全。
