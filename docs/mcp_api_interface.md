# TCRT MCP Read API 介面規格（給 MCP Server 開發）

本文件聚焦在「MCP Server 如何對接 `/api/mcp/*`」。
若你需要先建立 machine token，請先看：[mcp_machine_auth.md](/Users/hideman/code/tcrt_user_story/docs/mcp_machine_auth.md)。

## 1. 介面定位

- 類型：唯讀 API（Read-only）
- 命名空間：`/api/mcp/*`
- 授權：`Authorization: Bearer <MACHINE_TOKEN>`
- 權限：token 必須具備 `mcp_read`
- 範圍控制：受 `allow_all_teams` / `team_scope_json` 限制

## 2. 共用規範

### 2.1 Base URL

以本機預設為例：

```text
http://127.0.0.1:9999
```

### 2.2 Request Header

```http
Authorization: Bearer <RAW_MACHINE_TOKEN>
Accept: application/json
```

### 2.3 時間欄位格式

所有時間欄位為 ISO 8601 字串（UTC），例如：

```text
2026-03-03T07:42:11.123456
```

### 2.4 錯誤回應格式

此 API 的 `detail` 可能是字串或物件；machine auth 類錯誤固定為物件：

```json
{
  "detail": {
    "code": "INVALID_MACHINE_TOKEN",
    "message": "machine token 無效"
  }
}
```

## 3. 端點規格

---

### 3.1 取得可見團隊

`GET /api/mcp/teams`

#### 功能

- 回傳 machine token 可存取的團隊清單與總數
- 已做資料去敏感，不會包含 `wiki_token`、`test_case_table_id` 等機密欄位

#### Query 參數

- 無

#### Response 範例

```json
{
  "total": 2,
  "items": [
    {
      "id": 1,
      "name": "Team A",
      "description": "Alpha",
      "status": "active",
      "test_case_count": 132,
      "created_at": "2026-03-03T07:00:00.000000",
      "updated_at": "2026-03-03T07:00:00.000000",
      "last_sync_at": null,
      "is_lark_configured": true,
      "is_jira_configured": false
    }
  ]
}
```

---

### 3.2 跨團隊查詢 Test Case（不知道 team 時使用）

`GET /api/mcp/test-cases/lookup`

#### 功能

- 針對 MCP 可見範圍內的所有團隊做查詢
- 適合以下場景：
  - 只知道 `test case number`
  - 不知道 `team_id/team_name`
  - 只知道 ticket/單號（例如 `TCG-*`、`ICR-*`）

#### Query 參數

- `q`（optional, string）：通用關鍵字（可放 number / ticket / title）
- `test_case_number`（optional, string）：Test Case Number 查詢
- `ticket`（optional, string）：Issue/Ticket/單號（對應 `tcg_json`）
- `team_id`（optional, int）：限制單一 team
- `team_name`（optional, string）：team 名稱模糊搜尋
- `include_content`（optional, bool，預設 `true`）：是否回傳 `precondition`、`steps`、`expected_result`
- `skip`（optional, int，預設 `0`）
- `limit`（optional, int，預設 `20`，範圍 `1..200`）

> 至少需提供 `q`、`test_case_number`、`ticket` 其中之一。

#### Response 範例

```json
{
  "filters": {
    "q": null,
    "test_case_number": "TC-B-001",
    "ticket": null,
    "team_id": null,
    "team_name": null,
    "include_content": true
  },
  "items": [
    {
      "team_id": 2,
      "team_name": "Team B",
      "match_type": "test_case_number_exact",
      "test_case": {
        "id": 2001,
        "record_id": "2001",
        "test_case_number": "TC-B-001",
        "title": "Cross team case",
        "priority": "Medium",
        "test_result": "Pending",
        "assignee": null,
        "tcg": [],
        "precondition": null,
        "steps": null,
        "expected_result": null,
        "test_case_set_id": 20,
        "test_case_section_id": 88,
        "created_at": "2026-03-03T07:00:00.000000",
        "updated_at": "2026-03-03T07:00:00.000000",
        "last_sync_at": null
      }
    }
  ],
  "page": {
    "skip": 0,
    "limit": 20,
    "total": 1,
    "has_next": false
  }
}
```

---

### 3.3 取得團隊 Test Cases（含 filter + 分頁）

`GET /api/mcp/teams/{team_id}/test-cases`

#### 功能

- 回傳指定團隊的：
  - `sets`（Test Case Set 清單）
  - `test_cases`（符合 filter 後的 test case）
  - `page`（分頁資訊）

#### Path 參數

- `team_id`：整數

#### Query 參數

- `set_id`（optional, int）：只看指定 Test Case Set
- `strict_set`（optional, bool，預設 `false`）：
  - `false`：當 `set_id` 不存在時，不回 404，改為忽略 set 過濾繼續查詢
  - `true`：當 `set_id` 不存在時，回 `404`
- `search`（optional, string）：`title` / `test_case_number` 模糊搜尋（不含 ticket/單號）
- `priority`（optional, string）：例如 `High`, `Medium`, `Low`（大小寫不敏感）
- `test_result`（optional, string）：例如 `Passed`, `Failed`, `Pending`（大小寫不敏感）
- `assignee`（optional, string）：在 `assignee_json` 進行關鍵字搜尋
- `tcg`（optional, string）：在 `tcg_json` 進行關鍵字搜尋（支援 `TCG-*`、`ICR-*`、其他 issue 前綴）
- `ticket`（optional, string）：`tcg` 的語意別名（推薦給 AI agent 用於「ticket/單號/issue」查詢）
- `include_content`（optional, bool，預設 `false`）：若為 `true`，`test_cases[]` 會包含 `precondition`、`steps`、`expected_result`
- `skip`（optional, int，預設 `0`）：offset
- `limit`（optional, int，預設 `100`，範圍 `1..1000`）

#### Response 範例

```json
{
  "team_id": 1,
  "filters": {
    "set_id": 10,
    "resolved_set_id": 10,
    "set_not_found": false,
    "search": "login",
    "priority": "High",
    "test_result": "Passed",
    "assignee": "alice",
    "tcg": "TP-1001",
    "ticket": null,
    "strict_set": false,
    "include_content": true
  },
  "sets": [
    {
      "id": 10,
      "name": "Default-1",
      "description": "Team A Default Set",
      "is_default": true,
      "test_case_count": 58,
      "created_at": "2026-03-03T07:00:00.000000",
      "updated_at": "2026-03-03T07:00:00.000000"
    }
  ],
  "test_cases": [
    {
      "id": 1001,
      "record_id": "1001",
      "test_case_number": "TC-A-001",
      "title": "Login should work",
      "priority": "High",
      "test_result": "Passed",
      "assignee": "Alice",
      "tcg": [
        "TP-1001"
      ],
      "precondition": "User is on login page",
      "steps": "1. Input account\n2. Click login",
      "expected_result": "Redirect to dashboard",
      "test_case_set_id": 10,
      "test_case_section_id": 88,
      "created_at": "2026-03-03T07:00:00.000000",
      "updated_at": "2026-03-03T07:00:00.000000",
      "last_sync_at": null
    }
  ],
  "page": {
    "skip": 0,
    "limit": 100,
    "total": 1,
    "has_next": false
  }
}
```

---

### 3.4 取得單筆 Test Case 詳細內容

`GET /api/mcp/teams/{team_id}/test-cases/{test_case_id}`

#### 功能

- 回傳單筆 test case 的完整內容，包含：
  - 基本欄位（編號、標題、priority、assignee、tcg）
  - 詳細內容（`precondition`、`steps`、`expected_result`）
  - JSON 欄位（`attachments`、`test_results_files`、`user_story_map`、`parent_record`、`raw_fields`）

#### Path 參數

- `team_id`：整數
- `test_case_id`：整數（`test_cases.id`）

#### Response 範例

```json
{
  "team_id": 1,
  "test_case": {
    "id": 1001,
    "record_id": "rec-a1",
    "test_case_number": "TC-A-001",
    "title": "Login should work",
    "priority": "High",
    "test_result": "Passed",
    "assignee": "Alice",
    "tcg": [
      "TP-1001"
    ],
    "precondition": "User is on login page",
    "steps": "1. Input account\n2. Click login",
    "expected_result": "Redirect to dashboard",
    "test_case_set_id": 10,
    "test_case_section_id": 88,
    "created_at": "2026-03-03T07:00:00.000000",
    "updated_at": "2026-03-03T07:00:00.000000",
    "last_sync_at": null,
    "attachments": [
      {
        "name": "spec.pdf"
      }
    ],
    "test_results_files": [
      {
        "name": "result.png"
      }
    ],
    "user_story_map": [
      {
        "id": "US-1",
        "title": "Login"
      }
    ],
    "parent_record": [
      {
        "record_id": "rec-parent"
      }
    ],
    "raw_fields": {
      "custom_field": "custom-value"
    }
  }
}
```

---

### 3.5 取得團隊 Test Runs（set/unassigned/adhoc 統一模型）

`GET /api/mcp/teams/{team_id}/test-runs`

#### 功能

- 統一回傳三類 run：
  - `sets`（Test Run Set + 其內 test_runs）
  - `unassigned`（未歸類的 TestRunConfig）
  - `adhoc`（Ad-hoc runs）

#### Path 參數

- `team_id`：整數

#### Query 參數

- `status`（optional, string）：可逗號分隔，例如 `active,completed`
- `run_type`（optional, string，預設 `all`）：
  - `set`
  - `unassigned`
  - `adhoc`
  - `all`
- `include_archived`（optional, bool，預設 `false`）

#### Response 範例

```json
{
  "team_id": 1,
  "filters": {
    "status": "active,completed",
    "run_type": "all",
    "include_archived": false
  },
  "sets": [
    {
      "id": 300,
      "name": "Release Cycle",
      "status": "active",
      "test_runs": [
        {
          "id": 501,
          "name": "Regression Run",
          "status": "active",
          "total_test_cases": 10,
          "executed_cases": 5,
          "passed_cases": 4,
          "failed_cases": 1,
          "created_at": "2026-03-03T07:00:00.000000",
          "updated_at": "2026-03-03T07:00:00.000000"
        }
      ]
    }
  ],
  "unassigned": [
    {
      "id": 502,
      "name": "Smoke Run",
      "status": "completed",
      "total_test_cases": 8,
      "executed_cases": 8,
      "passed_cases": 8,
      "failed_cases": 0,
      "created_at": "2026-03-03T07:00:00.000000",
      "updated_at": "2026-03-03T07:00:00.000000"
    }
  ],
  "adhoc": [
    {
      "id": 900,
      "name": "Adhoc Active",
      "status": "active",
      "total_test_cases": 6,
      "executed_cases": 2,
      "created_at": "2026-03-03T07:00:00.000000",
      "updated_at": "2026-03-03T07:00:00.000000"
    }
  ],
  "summary": {
    "set_count": 1,
    "set_run_count": 1,
    "unassigned_count": 1,
    "adhoc_count": 1,
    "total_runs": 3
  }
}
```

### 3.6 Automation 唯讀端點

> 以下 automation 端點皆唯讀、沿用 2.2 的 machine token 驗證，並採 `skip` / `limit` 分頁（回應含 `page: {skip, limit, total, has_next}`）。執行 / 觸發 / smart-scan / provider 設定為寫入或含憑證操作，**不**經 MCP 暴露。

#### 3.6.1 列出 Automation Scripts

`GET /api/mcp/teams/{team_id}/automation-scripts`

- 功能：列出 team 內所有 automation script，含 linked test case 數與最多 20 筆 case number。
- Query 參數：`skip`（≥0, 預設 0）、`limit`（1–200, 預設 50）、`format`（script_format）、`keyword`（對 `name` 或 `ref_path` partial match）。
- 主要回傳欄位（`items[i]`）：`id`、`name`、`script_format`、`ref_path`、`ref_branch`、`description`、`preferred_runner_label`、`tags[]`、`linked_test_case_count`、`linked_test_case_numbers[]`、`last_synced_at`、`created_at`、`updated_at`。

#### 3.6.2 列出 Automation Script Groups（可執行 suite）

`GET /api/mcp/teams/{team_id}/automation-script-groups`

- 功能：列出 team 內所有可執行 suite 及其組成；用於從 automation-run 的 `script_group_id` 反查 suite 名稱、成員 script 與對應 CI job。
- Query 參數：`skip`（≥0, 預設 0）、`limit`（1–200, 預設 50）、`keyword`（對 `name` 或 `description` partial match）。
- 主要回傳欄位（`items[i]`）：`id`、`name`、`description`、`ref_repo`、`script_paths[]`、`script_count`、`script_ids[]`、`ci_job_name`、`ci_job_type`、`created_at`、`updated_at`。
- 說明：`script_paths` 為 suite 儲存的組成（ref_path 清單）；`script_ids` 為這些 path 解析回同 team 現存 script id 的結果（保留 stored 順序，已改名／刪除的 stale path 略過，故 `len(script_ids)` 可能小於 `script_count`）。可沿 `run.script_group_id → suite → script_ids → /automation-scripts` 串接導覽。

#### Response 範例

```json
{
  "team_id": 1,
  "items": [
    {
      "id": 12,
      "name": "Login Regression Suite",
      "description": "login + logout",
      "ref_repo": "ex/auto",
      "script_paths": ["tests/test_login.py", "tests/test_logout.py", "tests/test_ghost.py"],
      "script_count": 3,
      "script_ids": [101, 102],
      "ci_job_name": "tcrt-suite-login",
      "ci_job_type": "JENKINS",
      "created_at": "2026-06-10T07:00:00.000000",
      "updated_at": "2026-06-10T07:00:00.000000"
    }
  ],
  "page": {"skip": 0, "limit": 50, "total": 1, "has_next": false}
}
```

#### 3.6.3 列出某 Test Run Set 的 Automation Runs

`GET /api/mcp/teams/{team_id}/test-run-sets/{set_id}/automation-runs`

- 功能：列出指定 Test Run Set 所觸發的 automation runs（執行入口已集中於 Test Run Set，故 run 一律 set-scoped）。
- Query 參數：`status`、`branch`、`skip`（≥0, 預設 0）、`limit`（1–200, 預設 50）。
- 主要回傳欄位（`items[i]`）：`id`、`automation_script_id`、`script_group_id`、`test_run_set_id`、`workflow_id`、`branch`、`status`、`triggered_by`、`triggered_by_user_id`、`external_run_id`、`external_run_url`、`report_url`、`runner_label`、`started_at`、`finished_at`、`duration_ms`、`tcrt_correlation_id`、`error_summary`、`created_at`、`updated_at`。
- `set_id` 不存在於該 team → `404`，detail code `TEST_RUN_SET_NOT_FOUND`。

#### 3.6.4 取得 Automation Coverage

`GET /api/mcp/teams/{team_id}/automation-coverage`

- 功能：回傳該 team 的自動化覆蓋率摘要、未覆蓋 case 取樣、stale script，以及近 30 日趨勢。
- 主要回傳欄位：`summary`（`total_test_cases` / `with_primary_link` / `with_covers_link` / `with_any_link` / `uncovered_count` / `by_format{}`）、`uncovered_sample[]`（最多 50 筆）、`stale_scripts[]`、`trend[]`（30 點）。

## 4. 錯誤碼對照（建議 MCP Server 映射）

### 4.1 認證/授權

- `401 MCP_AUTH_REQUIRED`
- `401 INVALID_MACHINE_TOKEN`
- `401 MACHINE_TOKEN_REVOKED`
- `401 MACHINE_TOKEN_EXPIRED`
- `403 INSUFFICIENT_MACHINE_PERMISSION`
- `403 TEAM_SCOPE_DENIED`

### 4.2 資料不存在或參數錯誤

- `404 找不到團隊 ID {team_id}`
- `404 找不到團隊 {team_id} 的 Test Case Set {set_id}`
- `404 找不到團隊 {team_id} 的 Test Case {test_case_id}`
- `400 run_type 不支援的值`
- `400 至少需要提供 q、test_case_number、ticket 其中之一`

## 5. MCP Server 建議同步流程

1. 呼叫 `GET /api/mcp/teams` 取得可見團隊。
2. 對每個 team：
   - 呼叫 `test-cases`（用 `skip/limit` 分頁，直到 `has_next=false`）。
   - 呼叫 `test-runs`（依需求調整 `run_type` 與 `status`）。
3. 查單一 test case 詳細內容時，建議流程：
   - 先呼叫 `GET /api/mcp/teams/{team_id}/test-cases?search=<case_number>&limit=10`
   - 取得目標 `test_case.id` 後，再呼叫 `GET /api/mcp/teams/{team_id}/test-cases/{test_case_id}`
   - 若有提供 `set_id`，預設 `strict_set=false`，即使 set 不存在也可回傳 `set_not_found=true` 並繼續找 case
4. 將 `filters` 與 `summary` 一併寫入快取，方便除錯。
5. 遇到 `401/403` 立即停止並觸發 token/權限檢查流程，不要重試風暴。

## 6. 範例：最小可用呼叫

```bash
curl -H "Authorization: Bearer <RAW_MACHINE_TOKEN>" \
  "http://127.0.0.1:9999/api/mcp/teams"

curl -G -H "Authorization: Bearer <RAW_MACHINE_TOKEN>" \
  "http://127.0.0.1:9999/api/mcp/test-cases/lookup" \
  --data-urlencode "test_case_number=TC-B-001"

curl -G -H "Authorization: Bearer <RAW_MACHINE_TOKEN>" \
  "http://127.0.0.1:9999/api/mcp/test-cases/lookup" \
  --data-urlencode "ticket=ICR-93178.010.010"

curl -G -H "Authorization: Bearer <RAW_MACHINE_TOKEN>" \
  "http://127.0.0.1:9999/api/mcp/teams/1/test-cases" \
  --data-urlencode "set_id=158" \
  --data-urlencode "strict_set=false" \
  --data-urlencode "search=TCG-127189.010.010" \
  --data-urlencode "limit=10"

curl -H "Authorization: Bearer <RAW_MACHINE_TOKEN>" \
  "http://127.0.0.1:9999/api/mcp/teams/1/test-cases/1001"

curl -G -H "Authorization: Bearer <RAW_MACHINE_TOKEN>" \
  "http://127.0.0.1:9999/api/mcp/teams/1/test-cases" \
  --data-urlencode "tcg=TP-1001" \
  --data-urlencode "include_content=true" \
  --data-urlencode "skip=0" \
  --data-urlencode "limit=100"

curl -G -H "Authorization: Bearer <RAW_MACHINE_TOKEN>" \
  "http://127.0.0.1:9999/api/mcp/teams/1/test-runs" \
  --data-urlencode "run_type=all" \
  --data-urlencode "include_archived=false"
```
