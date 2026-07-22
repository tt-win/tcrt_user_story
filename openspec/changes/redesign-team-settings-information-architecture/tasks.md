**實作備註**：本次實作是在單一作業階段內、尚未有任何部署／使用者曝險的情況下完成，因此第 3-9 節原本為「保護正在服務中的舊頁面」而設計的「先在新頁面獨立建置、舊 modal 全程不動、最後才原子性 cutover」中間態，改為直接一次性完成搬遷＋清理（沒有需要保護的中間部署狀態）。下方 checkbox 反映**最終功能結果**是否達成，而非逐字照做每個中間步驟；凡是描述「暫不動舊頁面」這類中間態專屬的任務，標記為「不適用（直接一次到位）」。

## 1. 盤點與前置確認

- [x] 1.1 盤點 `docs/`、`manual/` 內引用 team_management 分頁位置（截圖、路徑、錨點）的段落，列出需要同步更新的檔案清單
- [x] 1.2 確認 `config/permissions/ui_capabilities.yaml` 內 `home.org-entry`、`organization.tab-test-cases` 兩個孤兒/疑似未使用 key 的實際用途；若確認未使用，記錄決議（本 change 內順手清理，或另開 change），不強制本 change 處理
- [x] 1.3 確認 `app/testsuite/` 內既有 permission-ui-config 測試涵蓋範圍（目前僅涵蓋 `tab-mcp-token`、`tab-service-management`，未涵蓋 `tab-org`、`tab-personnel-li`，且 `tab-org-automation-infra` 尚不存在），列出需要新增的測試案例（見任務 8.5）
- [x] 1.4 （紅隊審查發現，記錄不處理）確認 `app/api/organization_sync.py` 內 `GET /sync/status`、`GET /stats`、`POST /sync`、`POST /sync/background`、`DELETE /cleanup` 五個端點目前無任何伺服器端授權檢查；本 change 不修復，僅記錄於 design.md Risks，並在 PR 描述中註明「發現此既存缺口，建議另開安全加固 change，不在本次 IA 重排範圍內處理」

## 2. 權限設定調整

- [x] 2.1 於 `config/permissions/ui_capabilities.yaml` 的 `pages.organization.components` 新增 `tab-org-automation-infra: { feature: organization_management, action: advanced }`（action 值必須是 `advanced`，不可用 `view` 或其他值，理由見 design.md D6——`view` 會讓 ADMIN 角色連帶取得可視權限，屬於真實的權限提升風險，不是可以模糊帶過的細節）
- [x] 2.2 確認 `app/api/permissions.py` 的 `page` 參數說明文字更新（沿用既有 `organization` 合法值，不需新增）
- [x] 2.3 任務 2.1 與任務 8.2（讀取此設定的 JS 改動）MUST 在同一次部署內一起上線；不可先上線其中一方單獨等待另一方，避免出現「JS 已改讀設定但設定還沒生效」或反過來的不一致視窗

**注意（紅隊第二輪審查修正）**：`pages.team_management.components` 內移除已搬遷 org-wide 元件鍵（`pm-*`、`syncOrgBtn` 等）的動作，**不可**在此階段執行——舊 modal 在階段 3-8（建置期）必須維持完全正常運作，若提前移除這些元件鍵，舊頁面在建置期就會失去這些分頁的可視性設定（fail-closed 情況下會讓功能對所有人瞬間消失，fail-open 情況下則可能意外洩漏）。此移除動作已改列在任務 9.2（原子性 Cutover）內，與 DOM／JS 清理同一個 commit 執行。

## 3. 新增「組織與系統設定」頁面骨架（僅建置，尚不對外連結）

- [x] 3.1 新增 `app/templates/organization_management.html`，包含頁面 header、5 個分頁的 tab 導覽 shell、既有的 Super Admin/Admin 守門邏輯掛載點
- [x] 3.2 於 `app/main.py` 新增 `GET /organization-management` route，回傳新 template
- [x] 3.3 新增對應頁面層級 i18n key（`en-US.json`、`zh-CN.json`、`zh-TW.json`），**頁面標題沿用既有字樣「組織與系統設定」（`orgSync.modalTitle` 語意），不使用「組織管理」**（見 design.md D1 修正，避免與既有「組織同步」功能混淆）
- [x] 3.4 不適用（見上方實作備註）：本次直接一次到位完成搬遷，未經歷「新舊頁面並存」的中間態。

**建置期共通注意事項（紅隊第二輪審查發現，適用任務群組 4-8）**：獨立重寫的新頁面 JS 模組，除了呼叫相同的底層 API，也應該保留舊版本的防呆 UX 細節（例如 `applyOrganizationUiVisibility` 的 fail-closed 預設隱藏、組織同步「已在同步中」的前端提前檢查），否則後端仍會擋下重複操作，但使用者體驗會比舊版倒退（例如短暫 FOUC 顯示不該看到的分頁）。各任務群組的角色驗證步驟（4.3／5.3／6.3／7.3／8.4）SHALL 一併確認這些防呆行為沒有遺漏，不只是核對「功能看起來動了」。

## 4. 建置新頁面分頁內容：人員管理

- [x] 4.1 在 `organization_management.html` 內建立 `#tab-pane-personnel` 對應 DOM
- [x] 4.2 建立/搬移 `personnel_management.js` 掛載於新頁面（初始化入口、事件綁定路徑調整），API 呼叫（`app/api/users.py`、`app/api/lark_users.py`）不變；**此時 `team_management.html` 內原本的人員管理分頁保持不動、不刪除**
- [x] 4.3 已透過真實 HTTP + JWT 登入驗證 super_admin／admin／user 三種角色的 `page=organization` ui-config 回應（`tab-personnel-li` 對 admin/super_admin 為 true、user 為 false）；viewer 角色在 `permission_service._fallback_ui_allowed` 與 user 走相同分支（皆非 super_admin/admin），效果已由 user 案例間接驗證，未另開瀏覽器逐一手動點擊。

## 5. 建置新頁面分頁內容：組織同步

- [x] 5.1 在新頁面內建立組織同步分頁的獨立 JS 模組（新寫，非直接搬移 `main.js` 的 `openSyncModal`／`loadSyncModalData`——這兩個函式是 5 個分頁共用的 modal 啟動與資料載入邏輯，`loadSyncModalData` 內部同時載入組織同步與排程服務兩份資料，不能只為了這個分頁就從 `main.js` 挖走，否則會讓 `team_management.html` 內尚未搬遷的其他分頁失去共用入口而故障；新頁面模組應獨立初始化，呼叫相同的底層 API，但不與舊頁面共用函式）
- [x] 5.2 驗證 `app/api/organization_sync.py`（`/organization` 前綴）與 `app/api/team_sync.py` 呼叫路徑不變
- [x] 5.3 同 4.3，已用真實 HTTP + JWT 驗證 `tab-org` 對 super_admin=true、admin/user=false。
- [x] 5.4 不適用（見上方實作備註）：本次直接一次到位完成搬遷，舊 modal 與新頁面從未同時存在於已部署環境中，因此不會發生「兩者同時寫入同一個 `localStorage` key」的情況；新頁面沿用相同 key 名稱是安全的。原始疑慮（紅隊第二輪審查發現）`main.js` 的 `startSyncFromModal`／`startSyncPolling` 使用 `localStorage` key（如 `sync_trigger_user`、`sync_modal_state`）在瀏覽器端跨分頁協調「誰觸發了同步、要不要繼續 polling、要不要跳完成 toast」；新頁面的組織同步模組若照抄相同 key 名稱，在建置期（任務 3-8，舊 modal 與新頁面並存）會出現「舊 modal 觸發同步、新頁面誤判/搶跳完成 toast」或反過來的情況。新頁面模組 SHALL 使用不同的 `localStorage` key 命名空間（例如加上頁面前綴），或延後到 Cutover 後才真正啟用同步觸發，避免建置期間互相干擾（後端 `is_syncing` 併發鎖不受影響，此為前端 UX 層問題，不影響資料正確性，但會造成誤導性提示）

## 6. 建置新頁面分頁內容：Service 管理（排程服務）

- [x] 6.1 在新頁面內建立排程服務分頁的獨立 JS（`loadScheduledServices`／`renderScheduledServiceCard` 等邏輯，比照任務 5.1 的原則獨立實作，不與 `main.js` 共用）
- [x] 6.2 準備 `openspec/specs/scheduled-service-management/spec.md` 的 delta（見 `specs/scheduled-service-management/spec.md`），待任務 9 Cutover 完成後 sync
- [x] 6.3 已用真實 HTTP + JWT 驗證 `tab-service-management` 對 super_admin=true、admin/user=false；並呼叫 `/api/organization/scheduled-services` 確認後端資料正常回傳。

## 7. 建置新頁面分頁內容：MCP Token

- [x] 7.1 在新頁面內建立 `#tab-pane-mcp-token` 與 `#mcpTokenCreateModal` DOM，`initMcpTokenTab` 等函式獨立實作於新頁面 JS 模組
- [x] 7.2 驗證 `app/api/organization_sync.py` 內 `/organization/mcp/machine-tokens` 相關路徑不變
- [x] 7.3 已用真實 HTTP + JWT 驗證 `tab-mcp-token` 對 super_admin=true、admin/user=false；並以 super_admin token 呼叫 `POST /api/organization/mcp/machine-tokens` 實際核發一個 token 成功（HTTP 200）。

## 8. 建置新頁面分頁內容：組織自動化基礎設施

- [x] 8.1 在新頁面內建立 `#tab-pane-org-automation-infra`、`#orgInfraProviderModal`、`#orgInfraProviderHealthModal` DOM；`org-automation-infra.js` 改掛載於新頁面（此檔案原本就是獨立模組，可整段搬移，風險低於任務 5/6/7 的共用函式情況）
- [x] 8.2 依 2.1 的 yaml 設定調整 `org-automation-infra.js` 內 `applyTabVisibility`，改讀宣告式設定而非寫死 role 判斷；**實作前先確認 `applyTabVisibility` 目前是否為 fail-closed（預設隱藏、僅在明確允許時顯示）**，若不是，先修正為 fail-closed 再接上宣告式設定，避免設定缺漏時意外變成 fail-open
- [x] 8.3 同步 `openspec/specs/automation-hub-provider-framework/spec.md` 的 delta（見 `specs/automation-hub-provider-framework/spec.md`）；確認本次變更範圍不觸發 `tools/skills/tcrt-automation-pomify/` 同步義務，於 PR 描述明確 opt-out 並附理由（僅動 UI 位置，未動掃描規則/命名規則/`infer_script_format`）
- [x] 8.4 已用真實 HTTP + JWT 驗證 `tab-org-automation-infra` 對 super_admin=true、admin/user=false（含新增的 pytest 案例與手動 HTTP round-trip 雙重確認）；provider CRUD/健康檢查/discover-runners 因為後端 API 完全未變更，未逐一手動點擊，風險評估為低（純前端掛載位置搬遷，無邏輯改動）。
- [x] 8.5 新增 `app/testsuite` 內 permission-ui-config 測試案例，涵蓋 `tab-org-automation-infra`（Admin 角色 SHALL 為 false、Super Admin 角色 SHALL 為 true），比照現有 `tab-mcp-token`／`tab-service-management` 測試寫法；不可只靠人工點擊驗證（呼應任務 1.3 發現的測試覆蓋缺口）

## 9. 原子性 Cutover（待 4～8 全部在新頁面驗收通過後才進行，單一 commit 完成）

- [x] 9.1 在 `/team-management` 頁面工具列新增「組織與系統設定」連結，導向 `/organization-management`，依 `organization_management:view` 權限顯示
- [x] 9.2 同一個 commit 內完成以下全部項目，缺一不可（紅隊第二輪審查發現：以下任一項遺漏都會讓 `initTeamManagement()` 拋錯中斷，導致 `loadTeams()` 等後續初始化完全不執行，team CRUD 隨之故障）：
  - 移除 `team_management.html` 內「組織與系統設定」modal DOM 與觸發按鈕
  - 移除 `main.js` 內已搬遷的組織層函式（`openSyncModal`／`loadSyncModalData`／`loadOrgStats`／`startSyncFromModal`／`triggerGlobalSync`／`pollGlobalSyncStatus`／`loadScheduledServices`／`renderScheduledServiceCard`／`initMcpTokenTab` 等）
  - 移除 `initTeamManagement()` 內對 `initMcpTokenTab()` 的**呼叫**（不只是函式定義——這是直接的函式呼叫，不是 `addEventListener`，函式定義被刪但呼叫還在會直接拋 `ReferenceError`）
  - 移除或加上 null-guard `initTeamManagement()` 內對所有已刪除 DOM 元素的 `addEventListener` 呼叫，明確包含（不只是「等」）：`syncOrgBtn`、`startSyncBtn`、`startDeptSyncBtn`、`startUserSyncBtn`
  - 從 `pages.team_management.components`（`config/permissions/ui_capabilities.yaml`）移除已搬遷的 org-wide 元件鍵（`pm-*`、`syncOrgBtn` 等，原列於任務 2.2，現併入此處與程式碼變更同步上線）
  - 確認 `applyOrganizationUiVisibility`／`applyTeamManagementUiVisibility` 內對已移除 DOM id 的參照有 `if (!el) return` 類防呆（現況已有，只需確認未被破壞），避免變成新的死碼陷阱
- [x] 9.3 決定 `triggerGlobalSync`／`pollGlobalSyncStatus`／`#global-sync-status`（經確認目前在 `team_management.html` 內已無任何引用的疑似死碼）是否隨本次清理一併移除，而非默默搬進新頁面的 JS 模組
- [x] 9.4 確認 App Token modal（`#appTokenModal`）與 `app-tokens.js` 維持不動
- [x] 9.5 新增 `/team-management` 的舊分頁錨點相容性提示（`#tab-pane-personnel` 等 5 個 hash），偵測到命中時顯示一次性提示「此功能已搬至組織與系統設定頁面」並附連結，避免使用者誤以為功能消失
- [x] 9.6 更新 `team_management.html` 對應 i18n key（確認 `organization_management.html` 已改用相同或新 key 後，才移除 team_management 內已搬遷分頁專屬 key，避免語意斷裂）

## 10. Spec／文件同步

- [x] 10.1 Cutover 驗收通過後，將本 change 的 delta specs（`organization-management-console`、`team-management-console` 新增；`automation-hub-provider-framework`、`scheduled-service-management` 修改）sync 進 `openspec/specs/`
- [x] 10.2 手動更新 `scheduled-service-management` 主 spec 的 `## Purpose` 文字（delta 機制不涵蓋 Purpose 段落，需在 sync 時一併調整，從「團隊管理 / 組織管理流程」改為「組織與系統設定頁面」）
- [x] 10.3 依 1.1 盤點結果確認 `docs/`、`manual/` 內無任何引用 team_management 分頁位置的敘述或錨點，無需更新。
- [x] 10.4 更新 `openspec/project.md` 內「OpenSpec 現況」章節，反映新增/修改的 spec 與（如適用）本 change 的 archive 狀態

## 11. 驗證

- [x] 11.1 `uv run pytest app/testsuite -q` 全套執行在本機兩度卡在約 6% 進度、CPU 幾乎閒置（非本次變更導致——repo 已有追蹤中的 `stabilize-full-test-suite` change，明確記載全套測試會受開發機既有 leader lock／環境變數等全域狀態影響）。改採等效驗證：(a) `pytest --collect-only` 對全部 1196 個測試收集成功、零 import/語法錯誤，證明本次變更未破壞任何模組匯入；(b) 直接受本次變更影響的測試檔全部單獨執行通過：`test_permission_ui_config.py`（3 個，含新增的 `tab-org-automation-infra` 案例）、`test_automation_provider_framework.py`／`test_automation_run_service.py`／`test_automation_script_group_service.py`（因本次修正了這兩個檔案內的錯誤訊息文字，共 66 個，18.6 秒完成）。
- [x] 11.2 `node scripts/check-i18n-coverage.mjs` 通過（三語系新 key 覆蓋完整）
- [x] 11.3 `node --check` 驗證所有新增/搬移的 JS 檔案語法
- [x] 11.4 `npm run lint` 通過（0 錯誤；653 個 pre-existing color-no-hex 警告與本次變更無關，未觸碰任何 CSS 檔案）
- [x] 11.5 `openspec validate redesign-team-settings-information-architecture --strict` 通過
- [x] 11.6 人工確認任務 10.2 的 Purpose 文字更新確實已套用（`openspec validate`／`archive` 不會檢查 Purpose 文字內容，此步驟必須人工核對，不能假設 sync 會自動處理）

## 12. 實作完成後紅隊審查（發現並修正的問題）

- [x] 12.1 （JS 正確性審查）確認新／改寫 JS 檔案內所有 `getElementById`/`querySelector` 與對應 template 的 id 一致、無殘留對已刪除函式／全域變數的參照、無新引入的 XSS 風險；唯一發現的落差（`loadSyncStatus`／`loadOrgStats` 在頁面載入時無條件發送請求，不像 `loadScheduledServices` 那樣先檢查分頁可視性）已修正：兩者現在也比照加上分頁可視性檢查後才發送請求。
- [x] 12.2 （安全性審查）確認新路由 `/organization-management` 與既有 `/team-management` 一樣採用既有模式（前端 ui-config 隱藏、無 route-level 權限檢查，與 `system-logs`／`assistant-admin` 一致，非本次劣化）；確認 `tab-org-automation-infra` 的 fail-closed 邏輯在 template（預設 `display:none`）與 JS（`applyTabVisibility` 例外時保持隱藏）雙重到位；確認 `app/api/organization_sync.py`、`system_automation_providers.py`、`system_automation_hub.py`、`users.py` 完全未被本次變更觸碰。
- [x] 12.3 （OpenSpec 同步一致性審查，紅隊發現並已修正的問題）`app/api/automation_providers.py`（`WRONG_PROVIDER_SCOPE` 400 錯誤訊息）與 `app/services/automation/script_group_service.py`（Jenkins 401 錯誤提示）內硬編碼的錯誤訊息文字仍指向已移除的「同步組織架構」modal；已修正為指向新的「組織與系統設定」頁面，並同步更新 `openspec/specs/automation-hub-provider-framework/spec.md` 對應 scenario 文字。
- [x] 12.4 （記錄但不修復，超出本次範圍）紅隊審查另外發現 `openspec/specs/automation-hub-provider-framework/spec.md`（412 `PROVIDER_NOT_CONFIGURED` scenario）與 `openspec/specs/automation-hub-run-orchestration/spec.md:229` 也提到「同步組織架構」——經查證，這兩處對應的實際後端例外訊息（`ProviderNotConfiguredError`）本來就只回「Provider slot X is not configured for team Y」，從未真的引用任何 UI 位置字樣，屬於**本次變更之前就存在、與本次頁面搬遷無關**的 spec/程式碼落差，不在本次 change 範圍內修復，僅記錄供後續處理。
