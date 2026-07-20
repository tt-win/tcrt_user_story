# App Token 使用說明與 API 參考

最後更新：2026-07-20

本文件是 TCRT team-owned **App Token** 的完整使用說明與 `/api/app/*` API 參考，內容以目前程式碼為準（`app/api/app_*.py`、`app/auth/app_token_dependencies.py`、`app/models/app_token.py`）。

- 概觀、憑證生命週期與 rollback 說明見 [app_token_auth.md](app_token_auth.md)。
- 既有 `/api/mcp/*` 為 read-only 相容端點，細節見 [mcp_machine_auth.md](mcp_machine_auth.md)。
- 對應 OpenSpec change：`openspec/changes/add-team-app-token-apis/`。

## 目錄

- [1. 總覽](#1-總覽)
- [2. 認證](#2-認證)
- [3. Token 管理 API（JWT）](#3-token-管理-apijwt)
- [4. Scope 模型](#4-scope-模型)
- [5. 通用行為](#5-通用行為)
- [6. 錯誤碼](#6-錯誤碼)
- [7. API 參考：Read](#7-api-參考read)
- [8. API 參考：Test Case](#8-api-參考test-case)
- [9. API 參考：Test Case Set / Section](#9-api-參考test-case-set--section)
- [10. API 參考：Test Case Attachment](#10-api-參考test-case-attachment)
- [11. API 參考：Test Run Config](#11-api-參考test-run-config)
- [12. API 參考：Test Run Set](#12-api-參考test-run-set)
- [13. API 參考：Test Run Item](#13-api-參考test-run-item)
- [14. API 參考：Bug Ticket](#14-api-參考bug-ticket)
- [15. API 參考：Report](#15-api-參考report)
- [16. API 參考：Automation](#16-api-參考automation)
- [17. API 參考：Pins](#17-api-參考pins)
- [18. 列舉值](#18-列舉值)
- [19. 端對端工作流程範例](#19-端對端工作流程範例)
- [20. 安全注意事項](#20-安全注意事項)

---

## 1. 總覽

App Token 是 team 層級的長效 API 憑證，供 CI/CD、腳本、外部整合以 machine-to-machine 方式存取 TCRT，涵蓋：

| 能力 | 說明 |
| --- | --- |
| Test Case 讀寫 | 列表、查詢、建立、更新、批次操作、附件上傳/下載/刪除 |
| Test Run 讀寫 | 建立/更新 Test Run Config 與 Set、membership 管理、run item 結果回報、bug ticket、HTML report |
| Automation 觸發 | 觸發、取消、對齊 Test Run Set 關聯的 automation suite |
| Team Pins | team 共用的釘選清單（與使用者個人 pins 獨立） |

系統中有兩組相關 API，使用不同憑證：

| API | 路徑 | 認證 | 用途 |
| --- | --- | --- | --- |
| Token 管理 API | `/api/teams/{team_id}/app-tokens`、`/api/app-tokens` | 使用者 JWT（team admin / Super Admin） | 建立、列表、撤銷、輪替 app token |
| App Token 資源 API | `/api/app/*` | `Authorization: Bearer tcrt_app_...` | 實際的 test case / test run / automation / pins 存取 |

## 2. 認證

### 2.1 Token 格式與傳遞

- Raw token 格式：`tcrt_app_` 前綴 + 64 個 hex 字元（256-bit 隨機值，`secrets.token_hex(32)`），例如 `tcrt_app_ab12cd34...`。
- 每個請求以 HTTP Bearer 傳遞：

```http
Authorization: Bearer tcrt_app_<64-hex>
```

- DB 只存 SHA256 hash（`team_app_tokens.token_hash`），不存明文；列表只顯示前 16 字元 `token_prefix` 供識別。
- Raw token **只在建立與輪替的回應中各出現一次**，請立即保存；遺失只能 rotate。

### 2.2 驗證流程與失效條件

每次請求解析順序：

1. 未帶 Bearer token → `401 APP_TOKEN_REQUIRED`。
2. 以 SHA256 查 `team_app_tokens`；查無 → 查 legacy `mcp_machine_credentials`；都查無 → `401 APP_TOKEN_INVALID`。
3. Token 狀態非 `active`（已撤銷）或 `expires_at` 已過 → `401 APP_TOKEN_INVALID`（對外統一，不洩漏差異；deny audit 內記錄實際原因）。
4. **Legacy MCP machine credential 不可用於 `/api/app/*`**，會被 `401 APP_TOKEN_INVALID` 拒絕（防止唯讀舊 token 觸及更大的 app 讀取面）；新 app token 不受影響。
5. 驗證通過後更新 `last_used_at`（節流：同一 token 60 秒內只更新一次）。

### 2.3 Team 授權範圍

- 每個 app token 綁定單一 `owner_team_id`，只能存取該 team 的資源；存取其他 team → `403 APP_TOKEN_TEAM_SCOPE_DENIED`。
- 例外：`GET /api/app/teams` 與 `GET /api/app/test-cases/lookup` 會回傳 token 可存取 team 範圍內的結果（對新 app token 而言即其 owner team）。
- Legacy MCP credential 保留其原本的 `allow_all_teams` / `team_scope_json` 多 team 範圍，但僅限 `/api/mcp/*`。

### 2.4 認證失敗 Rate Limit

- 針對 `/api/app/*` 與 `/api/mcp/*` 的**認證失敗**做 per-IP token bucket 限流；成功的請求不消耗額度，正常流量不受影響。
- 預設：60 秒窗口內 30 次失敗（可用環境變數 `APP_TOKEN_AUTH_FAIL_LIMIT`、`APP_TOKEN_AUTH_FAIL_WINDOW_SECONDS` 調整）。
- 超過上限 → `429`，`detail.code = APP_TOKEN_RATE_LIMITED`，附 `Retry-After` header（秒）。

## 3. Token 管理 API（JWT）

由具備 team admin 權限的使用者以既有 JWT 登入管理；Super Admin 可跨 team 管理。這組 API **不接受 app token 呼叫**。

### 3.1 建立 token

`POST /api/teams/{team_id}/app-tokens`（需 team admin，201 Created）

Request body：

| 欄位 | 型別 | 必填 | 說明 |
| --- | --- | --- | --- |
| `name` | string | 是 | 1–100 字元 |
| `description` | string | 否 | 備註 |
| `scopes` | string[] | 是 | 至少一個，須為有效 scope（見[第 4 節](#4-scope-模型)），否則 `400 APP_TOKEN_VALIDATION_ERROR` |
| `expires_in_days` | int | 否 | 省略預設 90 天；`0` 表示不到期；上限 3650 |

```bash
curl -X POST "http://127.0.0.1:9999/api/teams/1/app-tokens" \
  -H "Authorization: Bearer <JWT>" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "ci-integration",
    "description": "CI pipeline read/write",
    "scopes": ["test_case:read", "test_case:write", "test_run:read", "test_run:write", "test_run:execute", "automation:execute"],
    "expires_in_days": 90
  }'
```

Response（`raw_token` 只出現這一次）：

```json
{
  "id": 42,
  "name": "ci-integration",
  "description": "CI pipeline read/write",
  "owner_team_id": 1,
  "token_prefix": "tcrt_app_ab12cd3",
  "status": "active",
  "scopes": ["test_case:read", "test_case:write", "test_run:read", "test_run:write", "test_run:execute", "automation:execute"],
  "expires_at": "2026-10-18T00:00:00",
  "last_used_at": null,
  "created_by_user_id": 7,
  "created_at": "2026-07-20T00:00:00",
  "updated_at": "2026-07-20T00:00:00",
  "revoked_at": null,
  "raw_token": "tcrt_app_<64-hex>"
}
```

### 3.2 列出 team tokens

`GET /api/teams/{team_id}/app-tokens`（需 team admin）

回傳 `{ "items": [...], "total": n }`，item 欄位同建立回應但**不含 `raw_token`**（也從不暴露 `token_hash`）。

### 3.3 撤銷 token

`DELETE /api/teams/{team_id}/app-tokens/{token_id}`（需 team admin）

- 將 `status` 設為 `revoked` 並記錄 `revoked_at`；對已撤銷的 token 重複呼叫為冪等（回 200）。
- Token 不存在 → `404 APP_TOKEN_RESOURCE_NOT_FOUND`。

### 3.4 輪替 token

`POST /api/teams/{team_id}/app-tokens/{token_id}/rotate`（需 team admin）

- 產生新 raw token 並立即取代 hash/prefix；**舊 token 立刻失效，沒有 grace period**，外部設定需同步更新。
- 非 active 的 token 不可輪替 → `400 APP_TOKEN_VALIDATION_ERROR`。
- 回應含一次性 `raw_token`：`{ "id", "name", "token_prefix", "status", "raw_token", "updated_at" }`。

### 3.5 Super Admin 全域管理

| 方法 | 路徑 | 說明 |
| --- | --- | --- |
| GET | `/api/app-tokens` | 列出所有 team 的 app tokens（metadata only） |
| DELETE | `/api/app-tokens/{token_id}` | 撤銷任一 team 的 token（冪等） |

所有管理操作都會寫 audit log（含操作者、token 名稱/前綴、IP、User-Agent）。

## 4. Scope 模型

所有 mutation 預設拒絕，token 必須明確具備對應 scope；讀取端點需要 `test_case:read` 或 `test_run:read` 任一。

| Scope | 用途 |
| --- | --- |
| `test_case:read` | 讀取 test case / set / section / attachment 列表、跨 team lookup |
| `test_case:write` | 建立、更新 test case；批次建立/操作/複製；附件上傳 |
| `test_case:admin` | 刪除 test case（含批次刪除）；test case set / section 的新增、更新、刪除與 impact-preview；附件刪除 |
| `test_run:read` | 讀取 test run / set / item、bug ticket 列表、report 狀態查詢 |
| `test_run:write` | 建立、更新 test run config / set、狀態轉換、membership 管理、item 批次建立、report 產生 |
| `test_run:execute` | 更新 run item 執行結果、上傳執行結果檔案、bug ticket 管理 |
| `test_run:admin` | 刪除 test run config / item、archive / 刪除 test run set |
| `automation:execute` | 觸發、取消、對齊 Test Run Set automation run |

> 注意：Test Case Set / Section 的新增與更新走的是 `test_case:admin`（不是 `test_case:write`），與 test case 本體的寫入不同。

## 5. 通用行為

- **Base URL**：文件範例假設服務在 `http://127.0.0.1:9999`，依部署調整。
- **Content-Type**：除附件上傳（`multipart/form-data`）外，一律 `application/json`。
- **冪等性**：Create 類端點（建立 test case、test run config/set 等）**非冪等**，重試會產生重複資源；timeout 或 5xx 後請先查詢再決定是否重試。Update / Delete / Revoke / Pin 類端點為冪等。
- **Audit**：`/api/app/*` 每個請求（允許與拒絕）都寫 audit log，actor 為 `app-token:<token name>`；credential 類 test data、token、本機絕對路徑在 audit 與讀取回應中都會被遮蔽（`[REDACTED]`）。
- **跨 team 參照**：寫入端點會拒絕引用其他 team 的 set / section / config / suite（`400 APP_TOKEN_VALIDATION_ERROR`）。
- **FastAPI 422**：request body 結構性驗證失敗維持 FastAPI 原生 422 格式，client 應視同 validation error。
- **Service 層共用**：寫入端點重用 JWT API 的 service 層（`TestCaseSetService`、`TestCaseSectionService`、`TestRunScopeService`、`TestResultCleanupService`、`HTMLReportService` 等），資料效果與 UI / JWT API 一致。

## 6. 錯誤碼

`/api/app/*` 的錯誤回應為 `{"detail": {"code": ..., "message": ...}}`：

| HTTP | `detail.code` | 情境 |
| --- | --- | --- |
| 401 | `APP_TOKEN_REQUIRED` | 未帶 Bearer token |
| 401 | `APP_TOKEN_INVALID` | token 不存在、已撤銷、已過期，或 legacy credential 用於 `/api/app/*` |
| 403 | `APP_TOKEN_TEAM_SCOPE_DENIED` | token 對目標 team 無授權 |
| 403 | `APP_TOKEN_SCOPE_DENIED` | 缺少端點需要的 operation scope |
| 400 | `APP_TOKEN_VALIDATION_ERROR` | payload 驗證失敗（含跨 team 參照） |
| 404 | `APP_TOKEN_RESOURCE_NOT_FOUND` | team 或資源不存在 |
| 429 | `APP_TOKEN_RATE_LIMITED` | 認證失敗次數超過 per-IP 上限，附 `Retry-After` |

部分端點沿用其業務邏輯的原生錯誤格式（例如建立重複 `test_case_number` 回 `409`，`detail` 為字串），client 應同時容忍字串與物件兩種 `detail` 形態。

Automation 端點額外錯誤碼見[第 16 節](#16-api-參考automation)。

## 7. API 參考：Read

讀取端點需要 `test_case:read` 或 `test_run:read` 任一 scope。回應 model 與 `/api/mcp/*` read 一致。

### 7.1 列出可存取的 teams

`GET /api/app/teams`

回傳 token 可存取的 team 清單（已去敏）：

```json
{
  "total": 1,
  "items": [
    {
      "id": 1,
      "name": "QA Team",
      "description": "...",
      "status": "active",
      "test_case_count": 128,
      "created_at": "...",
      "updated_at": "...",
      "last_sync_at": null,
      "is_lark_configured": true,
      "is_jira_configured": false
    }
  ]
}
```

### 7.2 列出 team 的 test cases

`GET /api/app/teams/{team_id}/test-cases`

Query 參數：

| 參數 | 型別 | 預設 | 說明 |
| --- | --- | --- | --- |
| `skip` | int | 0 | 分頁位移 |
| `limit` | int | 100 | 每頁筆數，上限 500 |
| `search` | string | – | title 模糊搜尋（case-insensitive） |
| `priority` | string | – | `High` / `Medium` / `Low` |
| `test_result` | string | – | 依測試結果篩選 |
| `set_id` | int | – | 依 Test Case Set 篩選 |
| `section_id` | int | – | 依 Section 篩選 |
| `tcg` | string | – | 保留參數（目前不影響結果） |
| `ticket` | string | – | 保留參數（目前不影響結果） |
| `include_content` | bool | false | `true` 時每筆附 `precondition` / `steps` / `expected_result` |

回應：

```json
{
  "team_id": 1,
  "filters": {"search": null, "priority": null, "test_result": null, "set_id": null, "section_id": null},
  "sets": [
    {"id": 3, "name": "Default", "description": null, "is_default": true, "test_case_count": 128, "created_at": "...", "updated_at": "..."}
  ],
  "test_cases": [
    {
      "id": 11,
      "record_id": "local-TC-0001",
      "test_case_number": "TC-0001",
      "title": "Login smoke test",
      "priority": "High",
      "test_result": "Passed",
      "assignee": null,
      "tcg": ["PRJ-123"],
      "test_case_set_id": 3,
      "test_case_section_id": 8,
      "created_at": "...",
      "updated_at": "...",
      "last_sync_at": null
    }
  ],
  "page": {"skip": 0, "limit": 100, "total": 128, "has_next": true}
}
```

### 7.3 取得單一 test case 詳情

`GET /api/app/teams/{team_id}/test-cases/{case_id}`

回傳完整內容（含 `precondition`、`steps`、`expected_result`、`attachments`、`test_results_files`、`user_story_map`、`parent_record`、`raw_fields`、`test_data`），並附 `linked_automation_scripts`（marker-derived 關聯的自動化 script：`script_id` / `name` / `script_format` / `ref_path` / `link_type`）。

> credential 類（`category: "credential"`）的 test data `value` 在讀取回應中會被遮蔽。

找不到 → `404 APP_TOKEN_RESOURCE_NOT_FOUND`。

### 7.4 跨 team lookup

`GET /api/app/test-cases/lookup`

以關鍵字、編號或 ticket 在 token 可存取範圍內查找 test case。

| 參數 | 型別 | 預設 | 說明 |
| --- | --- | --- | --- |
| `q` | string | – | title / test_case_number 模糊搜尋 |
| `test_case_number` | string | – | 精確編號 |
| `ticket` | string | – | 依 tcg 內的 ticket 查找 |
| `team_id` | int | – | 限定 team |
| `skip` | int | 0 | 分頁位移 |
| `limit` | int | 20 | 每頁筆數，上限 100 |

`q`、`test_case_number`、`ticket` 至少需提供一個，否則 `400 APP_TOKEN_VALIDATION_ERROR`。

每筆結果含 `team_id`、`team_name`、`match_type`（`test_case_number_exact` / `test_case_number_partial` / `ticket` / `keyword_number_exact` / `keyword_number_partial` / `keyword_ticket` / `keyword_title`）與 `test_case` 摘要。

### 7.5 列出 test case sections

`GET /api/app/teams/{team_id}/test-case-sections`

| 參數 | 型別 | 預設 | 說明 |
| --- | --- | --- | --- |
| `set_id` | int | – | 限定 Test Case Set |
| `parent_section_id` | int | – | 限定父 section |
| `roots_only` | bool | false | 只回傳根 section |

回傳 `sections`（含 `id`、`test_case_set_id`、`parent_section_id`、`name`、`description`、`level`、`sort_order`、`test_case_count`、時間戳）與 `total`。

### 7.6 列出 team 的 test runs

`GET /api/app/teams/{team_id}/test-runs`

| 參數 | 型別 | 預設 | 說明 |
| --- | --- | --- | --- |
| `status` | string | – | 逗號分隔的狀態篩選 |
| `run_type` | string | 全部 | 逗號分隔組合：`set` / `unassigned` / `adhoc`；`all` 或省略表示三者皆含。不支援的值 → `400` |

回應分三段：

- `sets`：Test Run Set（含其下 configs，每個 config 附 `total_test_cases` / `executed_cases` / `passed_cases` / `failed_cases` 統計）
- `unassigned`：未加入任何 set 的 Test Run Config
- `adhoc`：Ad-hoc Run
- `summary`：`{"sets": n, "unassigned": n, "adhoc": n}`

## 8. API 參考：Test Case

### 8.1 建立 test case

`POST /api/app/teams/{team_id}/test-cases` — scope：`test_case:write`，201 Created

Request body（未列出的 `TestCaseCreate` schema 欄位會被 app-token 路徑忽略）：

| 欄位 | 型別 | 必填 | 說明 |
| --- | --- | --- | --- |
| `test_case_number` | string | 是 | 唯一編號；不可含 `/`、`\`、`..`、NULL（用於附件路徑） |
| `title` | string | 是 | 標題 |
| `priority` | string | 否 | `High` / `Medium` / `Low`，預設 `Medium` |
| `precondition` / `steps` / `expected_result` | string | 否 | 內容欄位 |
| `test_result` | string | 否 | 初始測試結果 |
| `test_case_set_id` | int | 否 | 省略時寫入 team 預設 Set |
| `test_case_section_id` | int | 否 | 省略時寫入（必要時自動建立）`Unassigned` section |
| `tcg` | string[] | 否 | 關聯 ticket 清單 |
| `test_data` | object[] | 否 | Test Data 項目，見下 |

`test_data` 項目格式：`{"id": "<可省略，server 產生 UUID>", "name": "...", "category": "text|number|credential|email|url|identifier|date|json|other", "value": "..."}`；限制：最多 100 筆、name 不可空白且同 case 內唯一、name ≤ 500 字、value ≤ 100,000 字。

```bash
curl -X POST "http://127.0.0.1:9999/api/app/teams/1/test-cases" \
  -H "Authorization: Bearer <APP_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{
    "test_case_number": "TC-EXT-001",
    "title": "External smoke test",
    "priority": "High",
    "precondition": "Service is up",
    "steps": "1. GET /health",
    "expected_result": "200 OK",
    "tcg": ["PRJ-123"],
    "test_data": [{"name": "endpoint", "category": "url", "value": "https://staging.example.com"}]
  }'
```

- 同 team 內 `test_case_number` 重複 → `409`（`detail` 為字串 `Test case number already exists`）。
- 指定的 set / section 不存在或不屬於此 team → `404` / `400`。
- 回應為序列化後的 test case：`id`、`team_id`、`test_case_number`、`title`、`priority`、`precondition`、`steps`、`expected_result`、`test_result`、`test_case_set_id`、`test_case_section_id`、`tcg`、`test_data`。

### 8.2 更新 test case

`PUT /api/app/teams/{team_id}/test-cases/{case_id}` — scope：`test_case:write`

Body 欄位同建立（全部選填，只更新有提供的欄位）。重新指定 `test_case_set_id` / `test_case_section_id` 時會驗證歸屬，失敗回 `400`。找不到 → `404`。

### 8.3 刪除 test case

`DELETE /api/app/teams/{team_id}/test-cases/{case_id}` — scope：`test_case:admin`，204 No Content

### 8.4 批次建立

`POST /api/app/teams/{team_id}/test-cases/batch` — scope：`test_case:write`

Body：`{"items": [<TestCaseCreate>, ...]}`（`items` 不可為空）。逐筆處理、單筆失敗不影響其他筆：

```json
{
  "results": [
    {"success": true, "test_case_number": "TC-1001", "id": 11},
    {"success": false, "test_case_number": "TC-1002", "error": "Test case number already exists"}
  ],
  "total": 2,
  "success_count": 1
}
```

### 8.5 批次操作

`POST /api/app/teams/{team_id}/test-cases/batch-operations`

- `operation: "delete"` → scope：`test_case:admin`
- 其他 operation → scope：`test_case:write`

Body：

| 欄位 | 說明 |
| --- | --- |
| `operation` | `delete` / `update_priority` / `update_tcg` / `update_section` / `update_test_set` |
| `record_ids` | 目標 test case id 清單（不可為空） |
| `update_data` | 各 operation 所需的更新內容（delete 不需要） |

回應：`success`、`processed_count`、`success_count`、`error_count`、`error_messages`，以及批次異動 set 範圍時的 `cleanup_summary`。

### 8.6 批次複製（bulk clone）

`POST /api/app/teams/{team_id}/test-cases/bulk-clone` — scope：`test_case:write`

Body：`{"items": [{"source_record_id": "11", "test_case_number": "TC-COPY-1", "title": "可選，預設沿用來源"}]}`

回應：`{"success": bool, "created_count": n, "duplicates": [...], "errors": [...]}`。

## 9. API 參考：Test Case Set / Section

> 以下全部需要 `test_case:admin` scope。

| 方法 | 路徑 | 說明 |
| --- | --- | --- |
| POST | `/api/app/teams/{team_id}/test-case-sets` | 建立 set，body `{"name": "...", "description": "..."}`，201 |
| PUT | `/api/app/teams/{team_id}/test-case-sets/{set_id}` | 更新 `name` / `description` |
| GET | `/api/app/teams/{team_id}/test-case-sets/{set_id}/impact-preview` | 刪除前預覽對 Test Run 的影響；預設 set 不可刪除（`400`） |
| DELETE | `/api/app/teams/{team_id}/test-case-sets/{set_id}` | 刪除 set，回應含 `cleanup_summary` |
| POST | `/api/app/teams/{team_id}/test-case-sets/{set_id}/sections` | 建立 section，body `{"name": "...", "description": "...", "parent_section_id": null}`，201 |
| PUT | `/api/app/teams/{team_id}/test-case-sets/{set_id}/sections/{section_id}` | 更新 `name` / `description` |
| DELETE | `/api/app/teams/{team_id}/test-case-sets/{set_id}/sections/{section_id}` | 刪除 section |

Set / section 不存在或不屬於該 team → `404`；業務驗證失敗 → `400`。

## 10. API 參考：Test Case Attachment

### 10.1 上傳附件

`POST /api/app/teams/{team_id}/test-cases/{case_id}/attachments` — scope：`test_case:write`，201

`multipart/form-data`，欄位 `files`（可多次）。檔名會加上 UTC 時間戳前綴並 sanitize，儲存於 `attachments/test-cases/{team_id}/{test_case_number}/`。

```bash
curl -X POST "http://127.0.0.1:9999/api/app/teams/1/test-cases/11/attachments" \
  -H "Authorization: Bearer <APP_TOKEN>" \
  -F "files=@./evidence.png" \
  -F "files=@./log.txt"
```

回應：`{"success": true, "uploaded": 2, "files": [{"name", "stored_name", "size", "type", "uploaded_at", ...}], "base_url": "/attachments"}`。

### 10.2 列出附件

`GET /api/app/teams/{team_id}/test-cases/{case_id}/attachments` — scope：`test_case:read`

回應：`{"success": true, "files": [...], "count": n, "base_url": "/attachments"}`。

### 10.3 刪除附件

`DELETE /api/app/teams/{team_id}/test-cases/{case_id}/attachments/{target}` — scope：`test_case:admin`

`{target}` 為附件的 stored name；回應含剩餘附件數 `remaining`。

## 11. API 參考：Test Run Config

「Test Run」在資料模型上是 Test Run Config；可在建立時以 `set_id` 直接掛入 Test Run Set，或之後用 membership 端點調整。

### 11.1 建立 test run config

`POST /api/app/teams/{team_id}/test-run-configs` — scope：`test_run:write`，201

| 欄位 | 型別 | 說明 |
| --- | --- | --- |
| `name` | string | 必填，≤ 100 字 |
| `description` | string | 描述 |
| `set_id` | int | 建立時直接掛入的 Test Run Set |
| `test_case_set_ids` | int[] | 允許的 Test Case Set 範圍（會驗證皆屬於此 team） |
| `test_version` / `test_environment` / `build_number` | string | 版本、環境、建置編號 |
| `related_tp_tickets` | string[] | TP 票號，格式 `TP-<數字>`，最多 100 個 |
| `status` | string | 初始狀態，預設 `draft` |
| `start_date` | datetime | 開始日期 |
| `notifications_enabled` / `notify_chat_ids` / `notify_chat_names_snapshot` | – | Lark 通知設定（chat id 長度 5–128、最多 100 個） |

回應：`id`、`team_id`、`name`、`description`、`status`、`test_version`、`test_environment`、`build_number`、`test_case_set_ids`、`related_tp_tickets`、`created_at`、`updated_at`、`cleanup_summary`（此處為 null）。

### 11.2 更新 test run config

`PUT /api/app/teams/{team_id}/test-run-configs/{config_id}` — scope：`test_run:write`

可更新：`name`、`description`、`test_version`、`test_environment`、`build_number`、`status`、`related_tp_tickets`、`test_case_set_ids`。

- 縮小 `test_case_set_ids` 範圍時會清理超出範圍的 run item，並在回應 `cleanup_summary` 回報。
- 此端點**不會**更新通知設定與 `start_date` / `end_date`；通知請於建立時設定，日期由狀態轉換帶動或於 web UI 編輯。

### 11.3 狀態轉換

`PUT /api/app/teams/{team_id}/test-run-configs/{config_id}/status` — scope：`test_run:write`

Body：`{"status": "active|completed|draft|archived", "reason": "可選"}`。

與單純 PUT 不同，此端點強制走狀態機（非法轉換 `400`）、套用 start/end date 副作用，並重新計算所屬 set 狀態。

### 11.4 刪除 test run config

`DELETE /api/app/teams/{team_id}/test-run-configs/{config_id}` — scope：`test_run:admin`，204

連同 run items 與已上傳的結果檔案一起清除（cascade）。

## 12. API 參考：Test Run Set

### 12.1 建立 test run set

`POST /api/app/teams/{team_id}/test-run-sets` — scope：`test_run:write`，201

| 欄位 | 型別 | 說明 |
| --- | --- | --- |
| `name` | string | 必填，≤ 120 字 |
| `description` | string | 描述 |
| `related_tp_tickets` | string[] | TP 票號（`TP-<數字>`） |
| `automation_suite_ids` | int[] | 關聯的 Automation Suite id；**app-token 路徑會在建立時驗證皆屬於此 team**（跨 team `400`） |
| `default_automation_environment` | string | 預設 automation 環境名 |
| `initial_config_ids` | int[] | 建立時要加入的 Test Run Config id |

回應：`id`、`team_id`、`name`、`description`、`status`、`archived_at`、`related_tp_tickets`、`automation_suite_ids`、`created_at`、`updated_at`。

### 12.2 更新 test run set

`PUT /api/app/teams/{team_id}/test-run-sets/{set_id}` — scope：`test_run:write`

可更新：`name`、`description`、`status`、`related_tp_tickets`、`automation_suite_ids`（同樣驗證 team 歸屬）、`default_automation_environment`（空字串清除、`null` 不變更）。

### 12.3 Membership 管理

| 方法 | 路徑 | 說明 |
| --- | --- | --- |
| POST | `/api/app/teams/{team_id}/test-run-sets/{set_id}/members` | 把既有 config 加入 set，body `{"config_ids": [12, 13]}`；完成後重算 set 狀態 |
| POST | `/api/app/teams/{team_id}/test-run-sets/members/{config_id}/move` | 移動 config 到其他 set，body `{"target_set_id": 5}`；`null` 表示移出（unassign）；來源與目標 set 狀態都會重算 |

兩者 scope 皆為 `test_run:write`。

### 12.4 Archive / 刪除

| 方法 | 路徑 | scope | 說明 |
| --- | --- | --- | --- |
| POST | `/api/app/teams/{team_id}/test-run-sets/{set_id}/archive` | `test_run:admin` | 設為 `archived` 並記錄 `archived_at` |
| DELETE | `/api/app/teams/{team_id}/test-run-sets/{set_id}` | `test_run:admin` | 刪除 set 及其下所有 config / item 與結果檔案，204 |

## 13. API 參考：Test Run Item

### 13.1 列出 run items

`GET /api/app/teams/{team_id}/test-run-configs/{config_id}/items` — scope：`test_run:read`

Query：`skip`（預設 0）、`limit`（預設 100，上限 500）。

```json
{
  "team_id": 1,
  "config_id": 12,
  "items": [
    {"id": 501, "test_case_number": "TC-0001", "test_result": "Passed", "executed_at": "...", "execution_duration": 12, "assignee_name": "Alice", "updated_at": "..."}
  ],
  "page": {"skip": 0, "limit": 100, "total": 1, "has_next": false}
}
```

### 13.2 批次建立 run items

`POST /api/app/teams/{team_id}/test-run-configs/{config_id}/items` — scope：`test_run:write`，201

Body：`{"items": [{"test_case_number": "TC-0001", "assignee": {"id","name","en_name","email"}, "test_result": "...", "executed_at": "...", "execution_duration": 秒}]}`（單筆建立即單元素 batch）。

行為：

- 同 config 內相同 `test_case_number` 已存在 → 計入 `skipped_duplicates`。
- test case 不存在 → 記入 `errors` 並繼續。
- config 已設定 `test_case_set_ids` 範圍時，不在範圍內的 case 會被拒絕；未設定範圍時會依實際加入的 case 自動推導範圍。

回應：`{"success": bool, "created_count": n, "skipped_duplicates": n, "errors": [...]}`。

### 13.3 更新單一 item 結果

`PUT /api/app/teams/{team_id}/test-run-configs/{config_id}/items/{item_id}` — scope：`test_run:execute`

Body（皆選填）：`test_result`、`executed_at`、`execution_duration`、`assignee_name`（空字串清除 assignee 全部欄位）、`change_reason`、`change_source`。

每次結果變更都會寫入 result history（`changed_by` 記為 `app-token:<token name>`）。回應為完整 item（含 test case 快照欄位）。

### 13.4 批次更新結果

`POST /api/app/teams/{team_id}/test-run-configs/{config_id}/items/batch-update-results` — scope：`test_run:execute`

```json
{
  "updates": [
    {"id": 501, "test_result": "Passed", "executed_at": "2026-07-20T10:00:00"},
    {"id": 502, "assignee_name": "Bob", "comment": "retest"}
  ],
  "change_source": "ci-pipeline"
}
```

每筆至少需含 `id` 與一個更新欄位（`test_result` / `assignee_name` / `executed_at`）或 `comment`；單筆失敗不影響其他筆。回應：`success`、`processed_count`、`success_count`、`error_count`、`error_messages`。

### 13.5 刪除 run item

`DELETE /api/app/teams/{team_id}/test-run-configs/{config_id}/items/{item_id}` — scope：`test_run:admin`，204

同時刪除其 result history 與已上傳的結果檔案。

### 13.6 上傳執行結果檔案

`POST /api/app/teams/{team_id}/test-run-configs/{config_id}/items/{item_id}/upload-results` — scope：`test_run:execute`，201

`multipart/form-data`，欄位 `files`（可多次）。儲存於 `attachments/test-runs/{team_id}/{config_id}/{item_id}/`，並累計到 item 的 `execution_results` 與 upload history。

回應：`{"success": true, "uploaded_files": n, "upload_details": [...], "base_url": "/attachments"}`。

## 14. API 參考：Bug Ticket

Run item 層級的 bug ticket 關聯：

| 方法 | 路徑 | scope | 說明 |
| --- | --- | --- | --- |
| GET | `/api/app/teams/{team_id}/test-run-configs/{config_id}/items/{item_id}/bug-tickets` | `test_run:read` | 列出 tickets（`[{"ticket_number", "created_at"}]`） |
| POST | 同上 | `test_run:execute` | body `{"ticket_number": "PRJ-123"}`；自動轉大寫；重複 `400`；201 |
| DELETE | `.../bug-tickets/{ticket_number}` | `test_run:execute` | 移除；不存在 `404`；204 |

## 15. API 參考：Report

### 15.1 產生 Test Run Set HTML report

`POST /api/app/teams/{team_id}/test-run-sets/{set_id}/generate-report` — scope：`test_run:write`

回應：

```json
{
  "success": true,
  "report_id": "team-1-set-10",
  "report_url": "http://127.0.0.1:9999/reports/team-1-set-10.html",
  "generated_at": "...",
  "overwritten": true
}
```

### 15.2 查詢 report 狀態

`GET /api/app/teams/{team_id}/test-run-sets/{set_id}/report` — scope：`test_run:read` 或 `test_run:write`

回應：`{"exists": true, "report_url": "http://.../reports/team-1-set-10.html"}`（不存在時 `report_url` 為 `null`）。

## 16. API 參考：Automation

以下全部需要 `automation:execute` scope。

### 16.1 觸發 automation

`POST /api/app/teams/{team_id}/test-run-sets/{set_id}/run-automation`

Body（全選填）：`{"suite_id": 7, "environment": "staging"}`

- 不帶 `suite_id` → 觸發 set 關聯的所有 suite；帶 `suite_id` → 只觸發該 suite（必須已關聯到此 set）。
- `environment` 依 suite 設定可能是必填；缺環境或環境變數不完整時回 422。

回應：`{"triggered_suite_ids": [7], "run_ids": [9001]}`。

錯誤碼（在[第 6 節](#6-錯誤碼)通用碼之外）：

| HTTP | `detail.code` | 情境 |
| --- | --- | --- |
| 404 | `TEST_RUN_SET_NOT_FOUND` | set 不存在 |
| 400 | `NO_AUTOMATION_SUITES` | set 未關聯任何 suite |
| 400 | `AUTOMATION_SUITE_INVALID` | suite 不存在或屬於其他 team |
| 400 | `AUTOMATION_SUITE_NOT_IN_SET` | 指定 suite 未關聯到此 set |
| 422 | `ENVIRONMENT_REQUIRED` | 需要指定環境（`detail.available` 列出可選環境） |
| 422 | `ENVIRONMENT_INCOMPLETE` | 環境變數未設齊（`detail.missing` 列出缺項） |
| 400 | `AUTOMATION_PROVIDER_NOT_CONFIGURED` / `AUTOMATION_PROVIDER_INVALID` | CI provider 未設定或設定無效 |
| 502 | `AUTOMATION_RUN_CI_API_FAILED` | 呼叫 CI provider API 失敗 |
| 400 | `AUTOMATION_RUN_OPERATION_FAILED` | 其他觸發失敗 |

### 16.2 取消 automation run

`POST /api/app/teams/{team_id}/test-run-sets/{set_id}/runs/{run_id}/cancel`

- run 不存在或不在此 set 下 → `404`。
- run 已到終態 → `409 AUTOMATION_RUN_ALREADY_TERMINAL`。
- 缺 external id → `400 AUTOMATION_RUN_EXTERNAL_ID_MISSING`。

回應：`{"id": 9001, "status": "cancelling", "external_run_id": "..."}`。

### 16.3 對齊（reconcile）automation run

`POST /api/app/teams/{team_id}/test-run-sets/{set_id}/runs/{run_id}/reconcile`

Body（選填）：`{"external_run_id": "..."}`。向 CI provider 重新查詢 run 最新狀態並同步本地。回應同 cancel：`{"id", "status", "external_run_id"}`。

## 17. API 參考：Pins

Team 共用的釘選清單，與使用者個人 `/api/pins` 完全獨立；任何可存取該 team 的 app token 都可讀寫。

可釘選的 `entity_type`：`test_case_set`、`test_run_set`、`test_run`、`adhoc_run`。

| 方法 | 路徑 | scope | 說明 |
| --- | --- | --- | --- |
| GET | `/api/app/teams/{team_id}/pins` | 任一 read scope | 依 entity_type 分組回傳：`{"test_case_set": [3], "test_run_set": [], "test_run": [12], "adhoc_run": []}` |
| POST | `/api/app/teams/{team_id}/pins` | `test_case_set` → `test_case:write`；其他 → `test_run:write` | body `{"entity_type": "test_case_set", "entity_id": 3}`；冪等，已存在回 `already_pinned: true`，201 |
| DELETE | `/api/app/teams/{team_id}/pins/{entity_type}/{entity_id}` | 同 POST | 冪等，回應 `{"success": true, "deleted": 0或1}` |

## 18. 列舉值

| 列舉 | 值 |
| --- | --- |
| `Priority` | `High`、`Medium`、`Low` |
| `TestResultStatus` | `Passed`、`Failed`、`Retest`、`Not Available`、`Pending`、`Not Required`、`Skip` |
| `TestRunStatus`（config） | `draft`、`active`、`completed`、`archived` |
| `TestRunSetStatus` | `active`、`completed`、`archived` |
| `TestDataCategory` | `text`、`number`、`credential`、`email`、`url`、`identifier`、`date`、`json`、`other` |
| Pin `entity_type` | `test_case_set`、`test_run_set`、`test_run`、`adhoc_run` |
| Token `status` | `active`、`revoked`（`expired` 由 `expires_at` 推導，非儲存狀態） |

## 19. 端對端工作流程範例

以下以 CI pipeline 回報測試結果為例（`<APP_TOKEN>` 請自行代換，不要寫進腳本或 commit）：

```bash
BASE="http://127.0.0.1:9999"
AUTH="Authorization: Bearer <APP_TOKEN>"

# 1. 確認 token 可存取的 team
curl -H "$AUTH" "$BASE/api/app/teams"

# 2. 建立 Test Run Set（關聯 automation suite 7）
curl -X POST "$BASE/api/app/teams/1/test-run-sets" \
  -H "$AUTH" -H "Content-Type: application/json" \
  -d '{"name": "Release 1.2 Regression", "automation_suite_ids": [7]}'
# → set id = 10

# 3. 建立 Test Run Config 並掛入 set
curl -X POST "$BASE/api/app/teams/1/test-run-configs" \
  -H "$AUTH" -H "Content-Type: application/json" \
  -d '{"name": "build-4821", "set_id": 10, "test_version": "1.2.0", "test_environment": "staging"}'
# → config id = 12

# 4. 加入 run items
curl -X POST "$BASE/api/app/teams/1/test-run-configs/12/items" \
  -H "$AUTH" -H "Content-Type: application/json" \
  -d '{"items": [{"test_case_number": "TC-0001"}, {"test_case_number": "TC-0002"}]}'

# 5. 觸發 automation（需要 automation:execute）
curl -X POST "$BASE/api/app/teams/1/test-run-sets/10/run-automation" \
  -H "$AUTH" -H "Content-Type: application/json" \
  -d '{"environment": "staging"}'

# 6. 回報執行結果（需要 test_run:execute）
curl -X POST "$BASE/api/app/teams/1/test-run-configs/12/items/batch-update-results" \
  -H "$AUTH" -H "Content-Type: application/json" \
  -d '{"updates": [{"id": 501, "test_result": "Passed"}], "change_source": "ci-build-4821"}'

# 7. 上傳結果檔案
curl -X POST "$BASE/api/app/teams/1/test-run-configs/12/items/501/upload-results" \
  -H "$AUTH" -F "files=@./junit.xml"

# 8. 產生 HTML report
curl -X POST "$BASE/api/app/teams/1/test-run-sets/10/generate-report" -H "$AUTH"
```

## 20. 安全注意事項

1. **Token 保管**：raw token 只在建立/輪替時各出現一次；請存放於 secret manager 或 CI 受保護變數，不要寫入 repo、log 或聊天記錄。外洩時立即 revoke 或 rotate（rotate 無 grace period，舊 token 立刻失效）。
2. **最小權限**：依用途只開必要 scope（例如純回報結果的 CI 只需要 `test_run:read` + `test_run:execute`），並設定合理到期時間；`expires_in_days: 0`（不到期）需明確選擇，避免當預設。
3. **敏感資料**：`category: "credential"` 的 test data 在讀取回應與 audit 中會遮蔽 value，但呼叫端仍不應主動印出含 credential 的回應內容。
4. **網路層**：生產環境務必走 HTTPS；app token 等同該 team 的資料存取權。
5. **稽核**：所有 `/api/app/*` 請求（含拒絕）皆記錄 actor、endpoint、IP、User-Agent；429 限流前的暴力嘗試也會留下 deny audit。
6. **刪除類操作**：`test_case:admin` / `test_run:admin` 的刪除與 archive 不可透過 API 還原，呼叫端請先以 impact-preview / 列表端點確認範圍。

## 相關文件

- [app_token_auth.md](app_token_auth.md) — 憑證模型、生命週期與 rollback 概觀
- [mcp_machine_auth.md](mcp_machine_auth.md) — legacy `/api/mcp/*` read-only 相容層
- [mcp_api_interface.md](mcp_api_interface.md) — MCP read model 細節
- [automation-hub-overview.md](automation-hub-overview.md) — Automation Hub 與 suite 概念
- `openspec/changes/add-team-app-token-apis/` — 設計與契約來源
