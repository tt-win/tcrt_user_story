## Context

Automation Hub 目前把 storage / ci / result 三種 slot 統一存進 `team_automation_providers`，每個 team 各自配置。實務上 ci/result 通常是公司一份共用 infra（一台 Jenkins、一套 Allure），這層結構不符實際擁有權邊界。本機 DB 尚無任何 provider row，可不必擔心歷史資料遷移。

涉及的程式碼擁有以下呼叫拓樸：

- `provider_registry.get_active_provider_record(team_id, slot, session)` 是唯一入口，被 6 個檔案 9 個位置呼叫（[`run_service.py`](app/services/automation/run_service.py)、[`script_group_service.py`](app/services/automation/script_group_service.py)、[`script_service.py`](app/services/automation/script_service.py)、[`smart_scan_service.py`](app/services/automation/smart_scan_service.py)、[`automation_providers.py`](app/api/automation_providers.py)、[`automation_result.py`](app/api/automation_result.py)）。
- Storage 呼叫 4 處、CI 呼叫 3 處、Result 呼叫 2 處（含 `active-ci/runners` 端點）。
- Run row 存 `team_id` + `provider_id`；webhook handler 從 run 倒推 provider，不需 team scope。

## Goals / Non-Goals

**Goals:**
- DB 結構區分 per-team storage 與 org-level ci/result，新舊呼叫端 API 變動最小。
- API 權限分明：team admin 只能管 storage、Super Admin 才能管 ci/result。
- UI 進入點分流：`/automation-provider-settings` → storage（rename「Git 來源設定」）；`/team-management` 的「同步組織架構」modal → ci/result。
- 既有 provider feature（encryption、health check、test connection、discover runners、webhook handler）對兩種 scope 都繼續可用。

**Non-Goals:**
- 不在這次處理「team 之間共用 storage」的情境（GitHub 維持 per-team）。
- 不重寫 webhook 路徑或事件 schema — 只調整 provider lookup 來源。
- 不引入新權限角色，沿用 `require_super_admin`。
- 不做歷史資料遷移（已確認本機 DB 無資料）。

## Decisions

### Decision 1: Two-table approach (not single-table with nullable team_id)

**選**：新增 `system_automation_providers` 表（無 `team_id`），既有 `team_automation_providers` 加 CHECK constraint 限制 `provider_slot = 'storage'`。

**Why over alternative**：
- 替代方案：單表 + `team_id` nullable + 加 `scope` 欄位。優點是少一張表；缺點是 nullable FK 容易誤用、要靠 application 層守 invariant、SQLite 對 partial unique constraint 支援差。
- 兩表方案 schema 上強型別、`UniqueConstraint` 自然乾淨、ORM relationship 不需要區分 scope。重複的欄位（config_json、credentials_encrypted、is_active 等）約 10 個，可接受。
- 兩個 ORM class 共用一份 base mixin（`_ProviderColumnsMixin`）以避免欄位定義漂移。

### Decision 2: Single `get_active_provider_record` entrypoint dispatches internally

**選**：保留 `get_active_provider_record(team_id, slot, session)` 簽名不變，內部 dispatch：
- `slot == STORAGE` → query `team_automation_providers` with team_id（既有行為）
- `slot in (CI, RESULT)` → query `system_automation_providers`（忽略 team_id）

**Why over alternative**：
- 替代方案：拆 `get_team_provider_record()` + `get_system_provider_record()`，所有呼叫端各自決定。優點：明確；缺點：9 個呼叫點都要改、`AutomationProviderSlot.CI` 在多處硬編、容易漏改。
- 內部 dispatch 讓呼叫端零改動，type-safety 仍由 slot enum 保證。額外加 helper `is_system_scoped_slot(slot)` 給其他需要區分的地方（如 audit logging）。

### Decision 3: New API router under `/api/system/automation-providers/...`

**選**：新增 `app/api/system_automation_providers.py`，全部端點 `Depends(require_super_admin)`，路徑前綴 `/api/system/automation-providers`。

**Why over alternative**：
- 替代方案：在現有 router 加 `?scope=system|team` query param。優點：URL 收斂；缺點：權限 gate 要動態判斷、OpenAPI doc 混亂、前端要兩個 fetch path 共用同一個 mock 容易搞錯。
- 分檔分路由：權限 gate 一致（整 router 套 `Depends(require_super_admin)`）、OpenAPI 自動分組、前端兩個獨立 JS 模組。
- 既有 `/api/teams/{team_id}/automation-providers/...` 加 server-side validation：嘗試 POST/PUT slot != storage 回 400 `WRONG_SCOPE`。

### Decision 4: UI 進入點：org-sync modal 內新增 tab

**選**：`/team-management` 既有的 `#orgSyncModal`（已 super-admin only）加一個 `tab-org-automation-infra` tab，呈現 Jenkins / Allure provider 管理表格 + Add Provider modal。

**Why over alternative**：
- 替代方案 A：獨立 `/system/automation-infra` 頁面。缺點：要新建 routes、左側 nav、權限守門 — 工程量大。
- 替代方案 B：放在「系統設定」（如果有）。專案目前沒有專門 system settings 頁。
- Org-sync modal 已是 Super Admin 集中地，加 tab 最自然。Tab 內的 table + add modal 元件可從 `/automation-provider-settings` 抽取共用。

### Decision 5: 共用 provider modal HTML / JS 元件，不複製

**選**：把現有 `automation_provider_settings.html` 內的 `#providerModal` + `#providerHealthModal` 抽到 `_provider_modal.html` partial，兩邊 include。JS 也抽 `automation-hub/providers/shared.js` 含 schema 渲染、test-connection、discover-runners。

**Why over alternative**：
- 替代方案：完全複製一份給 org-level UI。短期省事，長期 bug fix 要做兩次。
- 抽 partial 工程量小（兩個 HTML block + JS module split），維護成本後續省回來。

### Decision 6: 加密金鑰共用

**選**：`AUTOMATION_PROVIDER_ENCRYPTION_KEY` 同一支金鑰，加解密邏輯與 scope 無關。

**Why**：本來 `provider_credential_service` 就是純函式，不知道 scope；切兩個 key 沒有 security benefit、徒增運維複雜度。

## Risks / Trade-offs

| Risk | Mitigation |
|---|---|
| 9 個 `get_active_provider_record` 呼叫點仍按舊簽名呼叫，但行為差異可能引入 bug | 在 `provider_registry.py` 改動處加 docstring + unit test 覆蓋 STORAGE / CI / RESULT 三種 slot 的 dispatch 行為。同時保留 `team_id` 參數可避免下游被迫改動。 |
| 既有測試對 `team_automation_providers.provider_slot` 有 ci / result fixture | tasks 階段 grep `provider_slot.*ci\|provider_slot.*result` 列出測試、改用 system 表 fixture |
| Org-sync modal 已有多個 tab，再加一個可能太擁擠 | tab 用 icon + 簡短文字、放在最右側；後續可考慮分頁拆組 |
| Bootstrap 「主資料庫缺重要表」check 列表沒加 `system_automation_providers` | 改 `database_init.py` 同時加上 system 表，並寫 smoke test 驗證 bootstrap 通過 |
| Webhook 處理對 org-level provider 抓不到 | 確認 webhook handler 透過 run row 的 `provider_id` 直接 lookup（不分 scope），實際路徑是 `automation_runs.provider_id` → provider record by id；驗證 unit test 對 system_automation_provider 用同樣的 lookup 正常 |
| UI 抽 partial 過程中漏改既有元件 ID 引用 | 抽元件後維持原本 element id 不變，僅變更檔案位置；既有 `automation-hub/providers/settings.js` 改名為 `team-storage-settings.js` 並指向新 partial |

## Migration Plan

**Schema:**
1. 新建 Alembic revision（`down_revision` 接 latest head）
2. `op.create_table("system_automation_providers", ...)` — 與 team 表同欄位但無 `team_id`、無 unique team scope
3. `op.create_index("ix_system_automation_providers_slot_active", ...)`
4. `op.create_check_constraint("ck_team_provider_storage_only", "team_automation_providers", "provider_slot = 'storage'")`
5. 不寫資料遷移 — 本機 DB 無 row、production 尚未部署

**Rollback:**
- `downgrade`：drop CHECK constraint、drop system 表 + index
- 由於無歷史資料，下游 service 即使在 rollback 後跑 `get_active_provider_record(team_id, CI)` 也只會回 None（既有行為一致），UI 顯示 `PROVIDER_NOT_CONFIGURED`

**Bootstrap:**
- `database_init.py` 的「主資料庫缺重要表」列表新增 `system_automation_providers`

## Open Questions

- ✅ 兩表 vs 單表 → 已決定兩表
- ✅ Audit log resource type → 新增 `ResourceType.SYSTEM_AUTOMATION_PROVIDER`，避免跟 team-scoped audit 紀錄混在一起
- ✅ MCP read API 是否需暴露 system provider → 暫不暴露（MCP machine principal 仍以 team scope 為主）；後續若有需求另開 change
- ⚠ Org-sync modal tab 順序與既有 i18n key 命名 → tasks 階段定 i18n key 結構時再敲定
