## 1. DB Schema 與 ORM

- [x] 1.1 在 `app/models/database_models.py` 抽出 `_AutomationProviderColumnsMixin`（id, provider_slot, provider_type, name, config_json, credentials_encrypted, is_active, last_health_check_at, last_health_status, created_by, updated_by, created_at, updated_at）— 共用給 team / system 兩個 ORM
- [x] 1.2 重構 `TeamAutomationProvider` 使用 mixin、加 `CheckConstraint("provider_slot = 'storage'", name="ck_team_provider_storage_only")`
- [x] 1.3 新增 `SystemAutomationProvider` ORM class（無 team_id），加 `CheckConstraint("provider_slot IN ('ci', 'result')", name="ck_system_provider_ci_or_result_only")`、`UniqueConstraint("provider_slot", "name")`、`Index("ix_system_automation_providers_slot_active", "provider_slot", "is_active")`；同時把 `automation_runs.provider_id` FK retarget 到 `system_automation_providers.id`、`AutomationRun.provider` relationship 改指 `SystemAutomationProvider`
- [x] 1.4 新建 Alembic revision `b9d4e7a3c0f2_split_automation_provider_scope.py`：upgrade CREATE TABLE + ADD CHECK + 用 raw SQL 重建 automation_runs（避免 batch_alter 留下舊 FK）；downgrade 反向
- [x] 1.5 `database_init.py` 「主資料庫缺重要表」清單加入 `system_automation_providers`
- [x] 1.6 跑 `uv run alembic upgrade head` + `uv run python database_init.py` 驗證 bootstrap 通過

## 2. Provider Registry 分流

- [x] 2.1 `app/services/automation/provider_registry.py` 修改 `get_active_provider_record(team_id, slot, session)`：依 slot 分派查 `TeamAutomationProvider`（STORAGE）或 `SystemAutomationProvider`（CI/RESULT），`team_id` 對 system 來源忽略
- [x] 2.2 加 helper `is_system_scoped_slot(slot: AutomationProviderSlot) -> bool`
- [x] 2.3 grep `provider_slot.*ci\|provider_slot.*result` 與 `AutomationProviderSlot.CI\|AutomationProviderSlot.RESULT`，確認沒有 service 直接 query `team_automation_providers` 查 ci/result（除新 system 路徑外）
- [x] 2.4 確認既有 `get_active_provider_record` 呼叫點行為不變；同時更新 `run_service._provider_from_run_record` 與 `_resolve_ci_provider` 內 SELECT 來源從 `TeamAutomationProvider` 改成 `SystemAutomationProvider`（FK retarget 連動）；`script_group_service._resolve_ci_provider` 回傳型別改 `SystemAutomationProvider`

## 3. Per-team API 加守門

- [x] 3.1 `app/api/automation_providers.py` 加 `_require_storage_slot()` helper，套用到 `validate_provider_config` / `create_automation_provider` / `update_automation_provider` / `test_unsaved_provider_config`，違反回 400 `WRONG_PROVIDER_SCOPE`
- [x] 3.2 `GET /types` 過濾保留 `storage:*`（team-scoped 端點不暴露 ci/result）
- [x] 3.3 `POST /test-config` 加 `_require_storage_slot` 守門；`POST /discover-runners` 跟 `GET /active-ci/runners` 整個移除（搬到 system router）
- [x] 3.4 `active-ci/runners` 與 `discover-runners` 都已移至 system router；保留 `_collect_runner_labels` 邏輯 + 對外 `collect_runner_labels` alias 給 system router import

## 4. System API Router

- [x] 4.1 新建 `app/api/system_automation_providers.py`，prefix `/api/system/automation-providers`，全 router `Depends(require_super_admin)`
- [x] 4.2 端點集合：`GET /`、`GET /{id}`、`POST /`、`PUT /{id}`、`DELETE /{id}`、`POST /{id}/test-connection`、`POST /test-config`、`POST /discover-runners`、`GET /active-ci/runners`、`GET /types`、`POST /validate`
- [x] 4.3 `_require_ci_or_result_slot()` 限 slot 與 provider_type slot prefix 為 `ci` / `result`，違反回 400 `WRONG_PROVIDER_SCOPE`
- [x] 4.4 `GET /types` 只回 `ci:*` + `result:*` 兩類
- [x] 4.5 把 team-router 上的 `GET /active-ci/runners` 搬到 system router；同步移除 team router 該端點
- [x] 4.6 在 `app/api/__init__.py` 註冊新 router
- [x] 4.7 加 audit log：sysadmin CRUD 寫 `ResourceType.SYSTEM_AUTOMATION_PROVIDER`、`team_id = None`

## 5. Audit ResourceType

- [x] 5.1 `app/audit/models.py` `ResourceType` enum 加 `SYSTEM_AUTOMATION_PROVIDER = "system_automation_provider"`
- [x] 5.2 team router 仍寫 `AUTOMATION_PROVIDER`、system router 寫 `SYSTEM_AUTOMATION_PROVIDER`

## 6. Frontend — Git Source Settings 頁

- [x] 6.1 `app/templates/automation_provider_settings.html` 標題改為 `gitSourceSettings.title`、`<title>` 也換成「Git 來源設定」
- [x] 6.2 `app/static/js/automation-hub/providers/settings.js` 的 `CANONICAL_TYPES` 收斂為 `['storage:github']`
- [x] 6.3 既有的 `isCiProvider` gate 確認會跳過 discover-runners UI（storage:github 不會觸發）
- [x] 6.4 編輯流程的 `extraType` 機制仍允許 storage:local_git
- [x] 6.5 `slotIcon` / `slotOptionLabel` 預設值仍包含 ci/result 兜底（不會壞），實務上 storage-only

## 7. Frontend — Org Automation Infra Tab

- [x] 7.1 `app/templates/team_management.html` 的 org-sync modal 加 `tab-org-automation-infra` tab（icon `fa-cogs`、i18n key `orgAutomationInfra.tabTitle`，置於最右側）
- [x] 7.2 Tab pane 結構：header 動作（refresh + add）+ loading/empty/content 三態 + provider table（slot icon / name / credentials / health / status / actions）+ Add Provider modal trigger
- [~] 7.3 暫不抽 partial — git-source-settings 用既有 `#providerModal`/`#providerHealthModal`，org-infra tab 用 `#orgInfraProviderModal`/`#orgInfraProviderHealthModal` 獨立一份；後續若兩者長期分歧再共用
- [x] 7.4 新增 `app/static/js/team-management/org-automation-infra.js` — load/render/save/edit/delete/test-connection/test-config，呼叫 `/api/system/automation-providers/*`
- [~] 7.5 共用 `shared.js` 抽取暫延 — 兩邊邏輯結構相同但 DOM ids 不同；後續見必要再抽
- [x] 7.6 Tab 透過 `shown.bs.tab` 事件做 lazy-load（首次打開才打 API）
- [x] 7.7 其他既有 org-sync tab（部門/用戶/完整同步、Service 管理、MCP Token）不受影響

## 8. 入口 / 導航

- [~] 8.1 Automation Hub 工具列上的 `automationHub.settings.providers` 連結維持，自動指向新名「Git 來源設定」（頁面內標題已改名）；toolbar 文案後續可選改為更精準的「Git Source」
- [~] 8.2 Automation Hub Settings tab 仍顯示「Providers」卡片連到 Git 來源設定；CI/Result 由 Team Management → 同步組織架構 → Org Automation Infra 進入（建議由 UI 補一個跳轉連結作為 follow-up）
- [~] 8.3 Deep-link 機制（`?openOrgSync=1&tab=org-automation-infra`）暫未實作；user 可手動點選 tab。後續若需要可在 team-management/main.js 加 query param parsing

## 9. i18n

- [x] 9.1 三語系新增 `gitSourceSettings.title` + `gitSourceSettings.subtitle`
- [x] 9.2 三語系新增 `orgAutomationInfra.*` 系列 key（tabTitle / tabHint / addProvider / emptyTitle / emptyDesc / providersLabel / healthLabel / backToHub）
- [x] 9.3 三語系新增 `orgAutomationInfra.wrongScopeToSystem` / `wrongScopeToTeam` 提示訊息
- [x] 9.4 既有 `automationHub.providers.*` key 完整保留（git-source-settings 頁仍使用）

## 10. 測試

- [ ] 10.1 `app/testsuite/test_automation_provider_framework.py` 加 unit test：`get_active_provider_record(team_id=X, slot=CI)` 查到 system row、`(team_id=X, slot=STORAGE)` 查到 team row
- [ ] 10.2 加 API test：team-scoped router POST `provider_slot=ci` 回 400、POST `provider_slot=storage` 回 200
- [ ] 10.3 加 API test：system router POST `provider_slot=ci`（用 Super Admin token）回 200、用 team-admin token 回 403
- [ ] 10.4 加 service test：兩個 team 觸發 run 共用同一 org-level CI provider record（`automation_runs.provider_id` 相同）
- [ ] 10.5 加 audit test：sysadmin CRUD 寫 `SYSTEM_AUTOMATION_PROVIDER`、team admin CRUD 寫 `AUTOMATION_PROVIDER`
- [ ] 10.6 跑 `uv run pytest app/testsuite -q` 確認沒有 regression
- [ ] 10.7 跑 `uv run python -m app.main` 開伺服器，手動 smoke：
   - `/automation-provider-settings` 標題顯示「Git 來源設定」、只看到 storage type
   - `/team-management` 開 org-sync modal、看到 Org Automation Infra tab、新增 Jenkins + Allure provider 成功
   - 觸發一個 run 走通（trigger → external_run_id → status sync → report URL）

## 11. Cleanup 與文件

- [ ] 11.1 更新 `openspec/project.md`（如有）或 `README.md` 的 provider 章節，反映新 scope
- [ ] 11.2 `openspec validate "simplify-provider-scope-with-org-level-ci-result" --strict` 通過
- [ ] 11.3 commit 後跑 `/opsx:verify` 確認 spec 與實作一致
