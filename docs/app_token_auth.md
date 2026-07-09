# App Token 外部 API 使用說明

本文件說明 TCRT 的 team-owned app token：`/api/app/*` 的正式外部 API 憑證，取代原本「MCP 專用 machine token」定位。

- App token 可對 test case / test run 執行完整讀寫操作，並可觸發 Test Run Set automation。
- 既有 `/api/mcp/*` 保留為 read-only 相容端點，直到明確的移除計畫建立並完成；細節見 [mcp_machine_auth.md](mcp_machine_auth.md)。
- 對應 OpenSpec change：`openspec/changes/add-team-app-token-apis/`。

## 1. 憑證模型

資料表：`team_app_tokens`

| 欄位 | 說明 |
| --- | --- |
| `id` / `name` / `description` | 識別與備註 |
| `owner_team_id` | 擁有此 token 的 team（FK `teams.id`） |
| `token_hash` | raw token 的 SHA256（DB 不存明文） |
| `token_prefix` | raw token 前 16 字元，供列表識別，不足以重建 token |
| `status` | `active` / `revoked`（`expired` 由 `expires_at` 推導） |
| `scopes_json` | operation scope 清單（JSON 陣列） |
| `expires_at` | 到期時間，`NULL` 表示不到期 |
| `last_used_at` | 最後使用時間（節流更新，同一 token 60 秒內只更新一次） |
| `created_by_user_id` / `created_at` / `updated_at` / `revoked_at` | 稽核用時間戳 |

Raw token 格式為 `tcrt_app_` 前綴 + 256-bit 隨機值（`secrets.token_hex(32)`），例如 `tcrt_app_ab12cd34...`。

Legacy `mcp_machine_credentials`（`mcp_read` 權限）在相容期內仍可解析為 app-token principal（唯讀），並保留其原有的 `allow_all_teams` / `team_scope_json` 多 team 授權範圍，不會被縮減或擴大。

## 2. 建立 / 列表 / 撤銷 / 輪替（JWT 管理 API）

App token 由具備 team admin 權限的使用者透過既有 JWT 登入管理，Super Admin 可跨 team 管理。

```bash
# 建立（team admin JWT）
curl -X POST "http://127.0.0.1:9999/api/teams/1/app-tokens" \
  -H "Authorization: Bearer <JWT>" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "ci-integration",
    "description": "CI pipeline read/write",
    "scopes": ["test_case:read", "test_case:write", "test_run:read", "test_run:write", "test_run:execute", "automation:execute"],
    "expires_in_days": 90
  }'
# response 只在這裡回一次 raw_token，請立即安全保存

# 列表（metadata only，不含 raw_token / token_hash）
curl -H "Authorization: Bearer <JWT>" "http://127.0.0.1:9999/api/teams/1/app-tokens"

# 撤銷（idempotent）
curl -X DELETE -H "Authorization: Bearer <JWT>" "http://127.0.0.1:9999/api/teams/1/app-tokens/42"

# 輪替：舊 raw token 立即失效，沒有 grace period，需立刻更新外部設定
curl -X POST -H "Authorization: Bearer <JWT>" "http://127.0.0.1:9999/api/teams/1/app-tokens/42/rotate"
```

`expires_in_days` 省略時預設 90 天；帶 `0` 表示不到期（需明確選擇，不是預設值）。

## 3. Scope 模型

| Scope | 用途 |
| --- | --- |
| `test_case:read` | 讀取 test case / set / section / test data / attachment |
| `test_case:write` | 建立、更新 test case、test data、attachment 上傳 |
| `test_case:admin` | 刪除 test case（含批次）、set、section、attachment |
| `test_run:read` | 讀取 test run / config / set / item、report 查詢 |
| `test_run:write` | 建立、更新 test run config / set、membership、item 建立、report 產生 |
| `test_run:execute` | 更新 run item 執行結果、bug ticket 管理 |
| `test_run:admin` | 刪除 test run config、刪除 / archive test run set |
| `automation:execute` | 觸發、取消、對齊 Test Run Set automation run |

所有 mutation 預設拒絕，需 token 明確具備對應 scope 才會放行。

## 4. `/api/app/*` 端點總覽

Base path：`/api/app/teams/{team_id}/...`（team 管理 API 例外，走 `/api/teams/{team_id}/app-tokens`）。

- **Read**（沿用 `/api/mcp/*` 的 read model）：`GET /api/app/teams`、`GET /api/app/teams/{team_id}`、`GET /api/app/teams/{team_id}/test-cases`（+ `/{id}`、`/test-cases/lookup`）、`GET /api/app/teams/{team_id}/test-case-sections`、`GET /api/app/teams/{team_id}/test-runs`
- **Test case mutation**：`POST/PUT/DELETE /api/app/teams/{team_id}/test-cases`(`/{id}`)、`/test-cases/batch`、`/test-case-sets`(`/{id}`、`/{id}/impact-preview`)、`/test-case-sets/{set_id}/sections`(`/{id}`)、`/test-cases/{id}/attachments`(`/{target}`)
- **Test run mutation**：`POST/PUT/DELETE /api/app/teams/{team_id}/test-run-configs`(`/{id}`)、`/test-run-sets`(`/{id}`、`/{id}/archive`、`/{id}/members`、`/members/{config_id}/move`)、`/test-run-configs/{config_id}/items`(`/{item_id}`、`/{item_id}/bug-tickets`(`/{ticket_number}`)）、`/test-run-sets/{set_id}/generate-report`、`GET .../report`
- **Automation**：`POST /api/app/teams/{team_id}/test-run-sets/{set_id}/run-automation`、`/runs/{run_id}/cancel`、`/runs/{run_id}/reconcile`

所有寫入端點都重用既有 JWT API 的 service 層邏輯（`TestCaseSetService`、`TestCaseSectionService`、`TestRunScopeService`、`TestResultCleanupService`、`HTMLReportService` 等），確保與 UI / JWT API 產生相同的資料效果。

## 5. 錯誤碼

`/api/app/*` 使用穩定的 `detail.code`：

| HTTP | `detail.code` | 情境 |
| --- | --- | --- |
| 401 | `APP_TOKEN_REQUIRED` | 未帶 bearer token |
| 401 | `APP_TOKEN_INVALID` | token 不存在、已撤銷或已過期（對外統一，不洩漏狀態差異；deny audit 內細分原因） |
| 403 | `APP_TOKEN_TEAM_SCOPE_DENIED` | token 對目標 team 無授權 |
| 403 | `APP_TOKEN_SCOPE_DENIED` | 缺少必要 operation scope |
| 400 | `APP_TOKEN_VALIDATION_ERROR` | payload 驗證失敗（含跨 team set/section/config/suite reference） |
| 404 | `APP_TOKEN_RESOURCE_NOT_FOUND` | team 或 resource 不存在 |

Automation trigger/cancel/reconcile 額外使用既有 JWT automation 錯誤碼（例如 `AUTOMATION_PROVIDER_NOT_CONFIGURED`、`AUTOMATION_RUN_ALREADY_TERMINAL`、`NO_AUTOMATION_SUITES` 等），與 JWT API 一致，方便 client 端統一映射。

FastAPI 原生 422（request body 結構性驗證失敗）維持原生格式，client 應視為等同 validation error 處理。

## 6. 非冪等端點提醒

Create 類 endpoint（例如建立 test case、test run config/set）**非冪等**，重試會建立重複資源；呼叫端需自行做防重試設計（例如先查詢是否已存在）。Update / delete / revoke 類 endpoint 是冪等的。

## 7. Smoke Curl（read + write）

以下範例假設本機服務跑在 `http://127.0.0.1:9999`，`<APP_TOKEN>` 為 `tcrt_app_...` 開頭的 raw token；範例不印出真實 secret，執行時請自行代換。

```bash
# Read：列出 team 底下 test cases
curl -G -H "Authorization: Bearer <APP_TOKEN>" \
  "http://127.0.0.1:9999/api/app/teams/1/test-cases" \
  --data-urlencode "limit=20"

# Write：建立一筆 test case（需 test_case:write）
curl -X POST "http://127.0.0.1:9999/api/app/teams/1/test-cases" \
  -H "Authorization: Bearer <APP_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"test_case_number": "TC-EXT-001", "title": "External smoke test"}'

# Write：觸發 Test Run Set automation（需 automation:execute）
curl -X POST "http://127.0.0.1:9999/api/app/teams/1/test-run-sets/10/run-automation" \
  -H "Authorization: Bearer <APP_TOKEN>"
```

## 8. Rollback

若需回滾此能力：

1. 停用 `/api/app/*` router（feature flag 或移除 include_router），或直接批次撤銷相關 `team_app_tokens`（`status=revoked`）。
2. `/api/mcp/*` read-only 相容端點不受影響，既有 MCP client 可繼續讀取。
3. `team_app_tokens` 表與既有 audit 記錄保留，不做破壞性 rollback，以利事後追查。
4. 既有 `/api/teams/{team_id}/...` 人類 JWT API 完全不受影響。
