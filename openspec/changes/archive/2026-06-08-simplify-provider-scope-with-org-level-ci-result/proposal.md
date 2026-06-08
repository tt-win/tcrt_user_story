## Why

目前 Automation Provider 三種 slot（storage / ci / result）一律 per-team 配置，但實務上：

- **CI（Jenkins）跟 Result（Allure）通常是公司共用 infra** — 一台 Jenkins server 服務多個 team、一套 Allure server 收所有 team 的報告。讓每個 team admin 各自設一份相同的 base_url / credentials 既重複又容易設錯。
- **Jenkins/Allure 的管理權限本來就比較高** — 涉及全公司 CI 帳號跟 token 旋轉，給 team admin 等級權限去動不合適。
- **Storage（GitHub）天然 per-team** — 每個 team 對應自己的 repo，不能 org-level 化。

讓 slot 範圍對齊真實的擁有權邊界：storage 留在 team-level、ci/result 上推到 org-level 由 Super Admin 管，可以同時拿掉「重複設定」跟「權限不匹配」兩個痛點。**本機 DB 還沒任何 provider row，schema 可以直接 alter 不必 migrate。**

## What Changes

- **BREAKING**：CI/Result provider 從 per-team 移到 org-level —
  - 新增 `system_automation_provider` 表（無 `team_id`，slot ∈ {ci, result}）
  - `team_automation_providers` 加 CHECK constraint：`provider_slot = 'storage'`
- 新增 `/api/system/automation-providers/...` 系列端點，全部 gate 為 `require_super_admin`
- 既有 `/api/teams/{team_id}/automation-providers/...` 限制只能 CRUD slot=storage（嘗試傳 ci/result 回 400）
- `provider_registry.get_active_provider_record(team_id, slot, session)` 對 ci/result slot 改查 `system_automation_provider`；storage 維持 team 表
- **UI**：
  - `/automation-provider-settings` 頁面標題改為「Git 來源設定」(`Git Source Settings`)、`CANONICAL_TYPES` 拿掉 `ci:jenkins` / `result:allure`
  - `/team-management` 頁面的「同步組織架構」modal 加 **Org Automation Infra** 區塊（Jenkins + Allure provider 管理，gate 為 Super Admin）
- **i18n**：rename `automationHub.providers.title` 對應字串、新增 `automationHub.orgInfra.*` 系列 key（en-US、zh-TW、zh-CN）
- **測試**：Provider framework 測試補上「team admin 不能存 ci/result」「super admin 才能存 system-level」「run service 對 ci/result 解析到 system 表」三類 case

## Capabilities

### New Capabilities

無 — 這次沒有新的 capability，是把既有 capability 的 scope 切分。

### Modified Capabilities

- `automation-hub-provider-framework`: provider 設定範圍從「per-team 三種 slot」拆成「per-team storage」+「org-level ci/result」，包含 DB schema、API 路由、權限 gate、UI 進入點。
- `automation-hub-run-orchestration`: 觸發 run 時對 ci provider 的解析改查 org-level；webhook 註冊邏輯也要對應 org-level provider lookup。

## Impact

**Code**：
- DB schema：`app/models/database_models.py`（新增 `SystemAutomationProvider` ORM + 修改 `TeamAutomationProvider` constraint）
- Migration：新建一支 Alembic revision（無歷史資料、直接 CREATE TABLE + ALTER TABLE ADD CHECK）
- API：`app/api/automation_providers.py`（既有 router 加 slot 過濾）+ 新增 `app/api/system_automation_providers.py`
- Service：`app/services/automation/provider_registry.py`（active provider 查表分流）、`app/services/automation/run_service.py` + `webhook_service.py`（呼叫端對接）
- Templates：`app/templates/automation_provider_settings.html`（標題、CANONICAL_TYPES 過濾）、`app/templates/team_management.html`（org-sync modal 加區塊）
- JS：`app/static/js/automation-hub/providers/settings.js`（CANONICAL_TYPES 收斂）、新建 `app/static/js/team-management/org-automation-infra.js`
- i18n：`app/static/locales/{en-US,zh-TW,zh-CN}.json`

**APIs**：
- 新增：`GET/POST/PUT/DELETE /api/system/automation-providers/...`（含 `test-connection` / `test-config` / `discover-runners`）
- 既有：`/api/teams/{team_id}/automation-providers/...` 對 ci/result 回 400

**Dependencies / Systems**：
- 認證：依賴既有 `require_super_admin` Depends，不引入新權限模型
- DB topology：仍在 main DB，無跨 DB 影響
- MCP read API：`/mcp/...` 若有暴露 provider 列表也要對應切兩個 endpoint（待 design 階段確認 mcp-read-api spec 是否需要 delta）
- Bootstrap：`database_init.py` 要在「主資料庫缺重要表」check 加上 `system_automation_provider`

**Risk / Rollback**：
- DB 已確認無資料，rollback 只需 downgrade revision、UI/API 改動可逆
- 主要風險在 run service / webhook service 的 provider lookup 切換 — 須確保所有呼叫端都更新，否則 trigger run 會找不到 provider 而 fail。tasks 階段會列詳細 grep checklist。
