## Context

TCRT 目前有兩條認證路徑：

- 人類使用者 JWT：`get_current_user` 回傳 `User`，既有 `/api/teams/{team_id}/...` UI/API 透過 role、team permission、audit actor 與服務層邏輯執行 test case / test run 操作。
- MCP machine token：`/api/mcp/*` 使用 opaque token + SHA256 hash 驗證，支援 `mcp_read`、team scope、revoked/expired、`last_used_at` 與 allow/deny audit，但定位是 read-only。

新需求要讓外部系統 by team 以 app token 完整操作 test case / test run。如果直接讓 app token 走 `get_current_user` 或假造 `User`，會讓 audit actor、permission cache、role checks、資料刪改責任與安全邊界混在一起。因此本設計新增正式 app-token principal 與 `/api/app/*` namespace，並把 `/api/mcp/*` 降為相容 read alias。

這是安全、資料庫、API contract、UI、`tcrt_mcp` external client 的跨模組變更；需 OpenSpec、migration、focused tests、相容路徑與回滾策略一起落地。

## Goals / Non-Goals

**Goals:**
- 建立 team-owned app token credential lifecycle：create、list、revoke、rotate、expires、last_used、metadata-only list。
- 建立 app-token principal，不冒充人類 user；所有 audit 以 app principal 記錄。
- 新增 `/api/app/*` 作為正式 external API namespace，覆蓋 test case / test run 讀寫操作。
- 保留 `/api/mcp/*` read-only compatibility，讓現有 `tcrt_mcp` 可分階段遷移。
- 讓 app-token mutation 重用既有 test case / test run service / validation / cleanup / automation orchestration，避免產生第二套資料語意。
- 同步更新 `tcrt_mcp` client、tool surface、validation、audit redaction 與文件。

**Non-Goals:**
- 不讓 app token 直接呼叫既有 JWT API 或建立 fake `User`。
- 不在 `/api/mcp/*` 開放 mutation。
- 不重建 test case / test run domain service；只在需要時抽出共享 service boundary。
- 不讓 Automation Hub script/suite endpoint 重新提供 trigger；automation trigger 仍經 Test Run Set。
- 不在本 change 中移除既有 `/api/mcp/*` read endpoints。

## Decisions

### D1: 新增 app-token principal，不共用 `User`

做法：
- 新增 `AppTokenPrincipal` model，包含 credential id/name、team scope、scopes、status、legacy credential 來源標記。team scope 用 `team_scope_ids: list[int]` + `allow_all_teams: bool` 表示：新 app token 為 `[owner_team_id]` + `False`；legacy `mcp_machine_credentials` 映射時原樣保留其 `allow_all_teams` 與 `team_scope_json`，不縮減也不擴大（沿用現有 `MCPMachinePrincipal` 的表示法）。
- 新增 `get_current_app_token_principal` dependency，專供 `/api/app/*` 與 `/api/mcp/*` compatibility path 使用。
- 新增 `require_app_team_access(team_id)` 與 `require_app_scope(scope)` guard。
- `last_used_at` 更新沿用現有 per-request 模式，但實作 SHOULD throttle（例如距上次更新未滿 60 秒不重複寫入），降低 read-heavy client 的寫入放大。

理由：
- app token 是 machine actor，不應污染人類 user session、role hierarchy 或 permission cache。
- audit 可清楚區分 `user:<id>` 與 `app-token:<credential>`。
- 單一 owner team 的 principal 裝不下 legacy `allow_all_teams` / 多 team scope；用 list 表示可讓兩種 credential 走同一套 guard。

替代方案：
- 讓 app token 轉成 synthetic User。拒絕，因為會模糊 audit、role checks 與 revoke semantics。
- 在每個 endpoint 手寫 token 檢查。拒絕，會造成授權邏輯漂移。

### D2: 新表優先於擴充 `mcp_machine_credentials`

做法：
- 新增 `team_app_tokens` 表，保留既有 `mcp_machine_credentials` 不動。
- 欄位包含 owner team、token hash、token prefix、status、scopes json、expires/last_used、created/revoked metadata。不設 per-token legacy MCP 旗標：任何具對應 read scope 的 app token 在相容期內即可呼叫 `/api/mcp/*` read endpoints，省掉一個管理面欄位。
- Raw token 格式為 `tcrt_app_` 前綴 + 隨機片段（熵不低於現有 `secrets.token_hex(32)` 的 256-bit），hash 仍為 SHA256（與 legacy 一致）。`token_prefix` 存 raw token 前 16 字元，供列表識別與 secret scanning pattern，不足以重建 token。
- 到期政策：`expires_in_days` 未指定時預設 90 天；`expires_in_days=0` 明確表示不到期。
- 若需要支援既有 MCP token，auth dependency 可查 `team_app_tokens` 後 fallback 查 `mcp_machine_credentials`，並把 legacy token 映射成 read-only app principal（保留其 `allow_all_teams` / 多 team scope，見 D1）。

理由：
- app token 是正式長期模型，和 MCP read-only legacy model 在 scope、owner team、管理權限、rotation metadata 上差異大。
- 新表能做非破壞性 migration；回滾時可停用 `/api/app/*` 而不破壞既有 MCP token。

替代方案：
- 在 `mcp_machine_credentials` 加欄位。可行但會讓 legacy table 負擔過多語意，且名稱長期不準確。

### D3: `/api/app/*` 為 canonical，`/api/mcp/*` 為 read compatibility

做法：
- 新增 `app/api/app_tokens.py` 管理 API。
- 新增 `app/api/app_test_cases.py` 與 `app/api/app_test_runs.py`，prefix 使用 `/app/teams/{team_id}/...`。
- `/api/mcp/*` 繼續掛載既有 read routes，內部可改用共享 app-token auth guard，但不新增 mutation。

理由：
- 命名上清楚表達這是外部 app API，不再侷限 MCP。
- 可保留現有 MCP client 不中斷。

替代方案：
- 直接把 `/api/mcp/*` 改成 write-capable。拒絕，會破壞目前 read-only 契約，也讓 namespace 語意不準確。

### D4: API handler 薄層，domain operation 重用既有 service

做法：
- app-token routers 只做 auth/scope、payload shape、audit context 包裝。
- test case CRUD 重用或抽出既有 `TestCaseLocal`、test data、attachment、set/section service 邏輯。
- test run CRUD / execution 重用既有 test run config/set/item services、cleanup service、report service、automation run service。

理由：
- 外部 API 必須和 UI/JWT API 產生相同資料效果。
- 減少平行實作造成的 data drift。

替代方案：
- 直接 import UI route handler。拒絕，route handler 綁定 `User`、request shape 與 UI response，較難控制 app-token audit。

### D5: Scope 採 operation string，先做 coarse-grained

做法：
- 初始 scopes：`test_case:read`、`test_case:write`、`test_case:admin`、`test_run:read`、`test_run:write`、`test_run:execute`、`test_run:admin`、`automation:execute`。
- 破壞性操作與 scope 的固定對應：
  - `test_case:admin`：test case 單筆/批次刪除、set/section 刪除。
  - `test_run:admin`：test run config 刪除、test run set 刪除/archive。
  - `test_run:write`：config/set 建立與更新、membership 變更、run item 建立/更新/刪除（屬一般執行流程）。
  - `test_run:execute`：run item result/status 更新。
  - `automation:execute`：automation trigger、cancel、reconcile。
  - report generation 會在 server 端寫檔，歸 `test_run:write`；report metadata lookup 歸 `test_run:read`。
- scopes 存 JSON array，guard 做 set membership 檢查。

理由：
- 比單一 `mcp_read` 更能控管 write 風險。
- 避免第一版做過細 RBAC matrix，降低落地成本。

替代方案：
- 逐 endpoint scope。延後，成本高且 UI 管理複雜；可在後續 change 細化。

### D6: Audit helper 統一 redaction

做法：
- 新增 app-token audit helper，輸入 principal、resource、operation、payload summary。
- 對 raw token、token hash、credential 類 test data value、attachment local absolute path 做 redaction。
- allow / deny / mutation 都寫 audit；deny 的 audit 不阻斷原錯誤回應。

理由：
- app token 外部寫入風險高，必須完整可追蹤。
- 現有 MCP audit 與 automation audit 行為可重用概念，但需抽出共同 redaction。

### D7: `tcrt_mcp` 分階段支援 app-token API

做法：
- 第一階段：client 支援 `api_namespace = app|mcp` 或自動 fallback；config 新增 `app_token`，`machine_token` 保留 alias。
- 第二階段：read tools 改呼叫 `/api/app/*`。
- 第三階段：新增 write tools，例如 `create_test_case`、`update_test_case`、`create_test_run_set`、`update_test_run_item_result`、`run_test_run_set_automation`。
- 每個 write tool 必須有參數驗證與 local audit redaction。
- delete 與批次破壞性 tool 必須要求明確 `confirm=true` 參數；未帶 confirm 時不執行 mutation，並在 TCRT impact preview endpoint 可用時回傳影響摘要，作為 server-side dry-run 的替代。

理由：
- `tcrt_mcp` 現有 spec 明確 read-only；需要同步改契約與測試。
- 分階段能保留現有部署可用性。

## Risks / Trade-offs

- [Risk] Token 外洩後可寫入或刪除大量資料 → Mitigation：scope 最小權限、預設 90 天 expires、revoke、rotate、audit、破壞性操作獨立 admin scope（`test_case:admin` / `test_run:admin`）、`tcrt_app_` 前綴支援 secret scanning；IP allowlist / rate limit 列為 future work（見 Resolved Questions）。
- [Risk] app-token API 與 JWT API 資料語意漂移 → Mitigation：app-token route handler 只做薄層，核心操作重用 existing service，測試比較兩條路徑的結果。
- [Risk] Migration 影響多 DB engine → Mitigation：只做非破壞性新增表/索引；Alembic + `database_init.py` + SQLite/MySQL/PostgreSQL portable type。
- [Risk] Audit 寫入失敗影響主流程或漏紀錄 → Mitigation：allow/deny audit failure 不吞主錯誤但要 log warning；mutation audit failure 需評估是否阻斷高風險寫入，第一版採 log warning + test 覆蓋 redaction。
- [Risk] `tcrt_mcp` write tools 被 AI agent 誤用 → Mitigation：tool name 明確使用動詞，description 標示 mutation，破壞性 tool 要求明確 `confirm=true` 並先回 impact preview，scope guard server-side 強制，client-side validation 只是輔助。
- [Risk] `/api/mcp/*` 與 `/api/app/*` 雙 namespace 維護成本 → Mitigation：read implementation 共用 service / schema；`/api/mcp/*` 只做 compatibility wrapper。
- [Trade-off] Rotate 立即失效、無 grace period → 外部整合在 rotate 與更新設定之間有中斷窗。v1 接受此取捨（簡單、安全），UI 確認流程與文件明確警告；若日後有常態輪替需求，再以獨立 change 增加 overlap window。
- [Trade-off] 401 對外統一 `APP_TOKEN_INVALID`（不區分 revoked/expired）→ 犧牲 caller 自助除錯便利，換取不對外洩漏 token 狀態；細分原因只寫入 deny audit，管理者可查。

## Migration Plan

1. 新增 `team_app_tokens` model、migration、`database_init.py` bootstrap 相容。
2. 新增 app-token auth dependency 與 audit helper，先覆蓋 auth unit tests。
3. 新增 token management API，再補 UI/i18n。
4. 新增 `/api/app/*` read endpoints，先與 `/api/mcp/*` read behavior 對齊。
5. 新增 test case mutation endpoints，重用既有 service，補 focused tests。
6. 新增 test run mutation / execution endpoints，重用 existing orchestration，補 focused tests。
7. 更新 `/api/mcp/*` compatibility guard，保留 legacy `mcp_read` token read-only。
8. 更新 `tcrt_mcp` client/config/docs/tests，先支援 `/api/app/*` read，再新增 write tools。（外部 repo deliverable：因 `/api/mcp/*` 相容期存在，此步可獨立於 TCRT 發布時程，於 TCRT 端完成後另行實作與驗證。）
9. 跑 targeted tests、OpenSpec validate、migration/bootstrap checks、i18n coverage、必要的 `tcrt_mcp` pytest。

Rollback:
- 關閉 `/api/app/*` router 或 feature flag。
- 批次 revoke `team_app_tokens` active tokens。
- 保留 `team_app_tokens` 表與 audit 供追查，不做破壞性 rollback。
- `/api/mcp/*` read-only compatibility 保持可用，讓既有 MCP client 不受影響。

## Resolved Questions (v1 取捨)

- IP allowlist / rate limit：v1 不做。以預設 90 天 expires、revoke/rotate、deny audit 管控；列為 future work，若出現暴力嘗試跡象再以獨立 change 加入。
- `test_case:admin` 邊界：v1 不再細拆 `test_case:delete` / `test_case:set_admin`，維持 coarse-grained admin；對應關係已固定於 D5，細粒度留給後續 change。
- Idempotency key：v1 不提供。update/delete 類 endpoint 天然冪等（revoke 亦為 idempotent）；create 類 endpoint 非冪等，API 文件（tasks 9.1）必須明確告知 caller 需自行防重試。
- `tcrt_mcp` write tools dry-run：不做 server-side dry-run 模式。以「破壞性 tool 要求明確 `confirm=true` + 未 confirm 時回傳 impact preview 摘要」替代（見 D7），重用既有 impact preview endpoints。
