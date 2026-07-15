## Why

一次針對 app token（`/api/app/*`）與共用 legacy MCP machine credential（`/api/mcp/*`）認證授權面的安全審查，發現一個認證後可任意寫檔的路徑遍歷漏洞、數個授權邊界過寬的問題，以及缺乏防濫用機制（無 rate limit、審計表無限增長）。這些缺陷已存在於現行 production 路徑，需儘快收斂。

## What Changes

以下依審查嚴重度排序，涵蓋可直接修補的項目：

- **[HIGH] 修補 attachment 上傳的路徑遍歷**：`test_case_number` 目前僅做 `.strip()`，允許 `/`、`\`、`..`，經 `POST /api/app/teams/{team_id}/test-cases/{case_id}/attachments` 可將檔案寫到 attachments 根目錄之外。改為在 model 層拒絕路徑分隔字元與 `..`（涵蓋 create / batch / update），並把 `_ensure_within_root` 容器檢查移到**寫檔之前**。
- **[MEDIUM] 修補 app token 更新的跨 team 指派**：`PUT /api/app/teams/{team_id}/test-cases/{case_id}` 直接採用 body 的 `test_case_set_id` / `test_case_section_id` 而未驗證歸屬，改為比照 create 與 JWT 路徑驗證目標 set/section 屬於該 team。
- **[MEDIUM] 加入認證失敗防濫用**：對 `/api/app/*` 與 `/api/mcp/*` 的無效 token 加上 per-IP rate limit（重用 `automation_webhooks_public.py` 既有 token-bucket 模式），避免未認證者放大審計寫入與 DB 負載。
- **[MEDIUM] 修復審計保留機制**：`audit_service.cleanup_old_records()` 目前零呼叫者、`AUDIT_CLEANUP_DAYS` 為死設定，將其掛上 scheduler，並為審計寫入失敗時的 in-memory 重排緩衝加上上限，避免無限增長。
- **[LOW] `expires_in_days` 加上下界驗證**：拒絕負值（避免建立即過期 token）與過大值（避免 `timedelta` `OverflowError` → 500）。
- **[LOW] 消除 attachment 刪除的跨 team 存在性 oracle**：以 team 過濾查詢並在不符時回 404，取代目前洩漏所屬 team 的 409 訊息。
- **[LOW] 讀取回應 redact credential 類 test_data**：對 `category=="credential"` 的 test_data 在讀取回應（尤其 legacy / `allow_all_teams` principal）比照審計層做遮蔽。
- **[MEDIUM] 收斂 legacy MCP credential 的可及範圍**：legacy `MCPMachineCredential`（含 `allow_all_teams`）目前經共用 resolver 可存取比原始 `/api/mcp/*` 更大的 `/api/app/*` 讀取面。改為讓 `is_legacy` principal 在 `/api/app/*` 一律被拒（回 401/403），強制其回到原始 MCP read-only 面；新 team app token 不受影響。
- **[TEST] 補齊回歸測試**：過期/撤銷 legacy token 在 `/api/mcp/*` 被拒、legacy principal 在 `/api/app/*` 一律被拒、路徑遍歷編號被拒、跨 team set/section 指派被拒。

## Non-Goals

- 不重寫 app token / MCP 的整體認證架構；只做針對性收斂。
- 不引入 HTTPS/HSTS/TrustedHost 至 app 層（由反向代理負責，屬部署層）。
- 不變更 token 產生演算法、hash 儲存或一次性顯示流程（審查確認為安全）。
- `/docs`、`/openapi.json` 的 production gating 視為獨立 ops 決策，不在本 change 範圍。
- **全域 ADMIN 可管理任意 team 的 app token**（`check_team_permission` 忽略 `UserTeamPermission`）屬全站 RBAC 設計取捨，經確認不在本 change 處理，留待專門的 RBAC change。

## Capabilities

### New Capabilities
- `app-token-security-hardening`: app token 與 legacy MCP credential 在輸入驗證（路徑安全）、跨 team 授權完整性、認證防濫用（rate limit）、審計保留與敏感資料遮蔽上的強化需求。

### Modified Capabilities
<!-- app-token / test-case 的既有行為 spec 尚未 sync 進 openspec/specs（引入 change 仍在 active），故本 change 以新 capability 承載安全需求，不修改主 spec。 -->

## Impact

- **API**：`app/api/app_test_cases.py`（attachment 上傳/刪除、update）、`app/api/app_tokens.py`（expires 驗證）、`app/api/app_read.py`（test_data 遮蔽）。
- **Auth**：`app/auth/app_token_dependencies.py`（rate limit hook）、`app/auth/mcp_dependencies.py`。
- **Model**：`app/models/test_case.py`（`test_case_number` 驗證）。
- **Storage**：`app/services/attachment_storage.py`（容器檢查前置）。
- **Audit / Ops**：`app/audit/audit_service.py`、`app/services/scheduler.py`（cleanup 排程）。
- **Config**：可能新增 rate limit 相關設定於 `app/config.py`。
- **Tests**：`app/testsuite/test_app_token_*`、`test_mcp_api.py`。
- **無 schema 變更、無 migration**；rate limit 為 in-process、無外部相依。
