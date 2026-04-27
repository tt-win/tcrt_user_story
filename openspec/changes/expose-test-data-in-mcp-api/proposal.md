## Why

`add-test-data-crud`（archive `2026-04-23-add-test-data-crud`）已將 `test_data_json` 欄位加進 `TestCaseLocal` 並提供 `/api/test-cases/{id}/test-data` 內部 CRUD，搭配 `TestDataItem` 的 `id/name/category/value` 結構（category enum：`text|number|credential|email|url|identifier|date|json|other`，每筆上限 100 項）。Test Run 在建立時也會 snapshot test data 到 TestRunItem。

但 `/api/mcp/*` 唯讀 API 至今未跟進：

- [`app/api/mcp.py::_build_case_payload`](app/api/mcp.py:130) 的 `include_extended=True` 分支只塞 `attachments / test_results_files / user_story_map / parent_record / raw_fields`，**沒有 `test_data`**。
- [`app/models/mcp.py::MCPTestCaseDetailItem`](app/models/mcp.py:69) 也沒有 `test_data` 欄位定義。
- list (`/api/mcp/teams/{id}/test-cases`) 與 lookup (`/api/mcp/test-cases/lookup`) 沒有對應的 `include_test_data` query param。

實務影響：透過 MCP 連進 TCRT 的 AI agent（例如 `tcrt_mcp` MCP server）拿不到測試帳號、API endpoint、payload 等核心執行資訊，必須讓 user 手動再貼一次。考量 Test Data 的 category 已包含 `credential` 這類敏感分類，MCP consumer（例如 `tcrt_mcp` audit log）也需要能感知 category 以做後續 redaction，因此 API 必須完整回傳 `category` 欄位（不是把 value 抹掉）。

## What Changes

- `app/models/mcp.py::MCPTestCaseDetailItem` 新增 `test_data: List[Dict[str, Any]] = Field(default_factory=list)`。
- `app/api/mcp.py::_build_case_payload` 在 `include_extended=True` 分支新增 `"test_data": _parse_json_list(row.test_data_json)`；既有的 detail endpoint 因為硬編 `include_extended=True` 自動受惠。
- `app/api/mcp.py::list_team_test_cases` (GET `/api/mcp/teams/{team_id}/test-cases`) 與 `app/api/mcp.py::lookup_test_cases` (GET `/api/mcp/test-cases/lookup`) 新增 query param `include_test_data: bool = Query(False)`；當 `True` 時把 `test_data` 加進每筆 `test_case`（與 `include_content` 解耦，這個欄位通常很短，但仍預設關閉以避免不必要的資料量）。
- list / lookup 的 response `filters` 物件需 echo 回 `include_test_data` 值。
- `_parse_json_list` 對 `test_data_json` 的解析應保留 `id / name / category / value` 四個欄位原樣；不可丟掉 `category`（MCP consumer 需據此決定是否 redact）。
- 既有 list / lookup 預設行為（不帶 `include_test_data`）必須保持不變，避免 `tcrt_mcp` 舊版本壞掉。

## 非目標 (Non-goals)

- **不**新增 test data 的 mutate API 到 `/api/mcp/*`（MCP 維持唯讀；既有 `/api/test-cases/{id}/test-data` 由 user JWT 控管）。
- **不**重新設計 Lark sync 相關欄位（`last_sync_at`, `lark_*`, `sync_status`, `record_id`）；那部分由 `tcrt_mcp` 端透過 spec 註記處理，不影響 API contract。
- **不**新增 sections 端點（`/api/mcp/teams/{id}/sections`）；雖然 MCP consumer 提過想要，但會獨立成另一個 change（`expose-test-case-sections-in-mcp-api`）。
- **不**修改 `/api/test-cases/{id}/test-data` 既有的 mutate API 或 TestRunItem snapshot 行為。

## Capabilities

### Modified Capabilities
- `mcp-read-api`：新增 `test_data` 在 detail 端點預設回傳；新增 `include_test_data` query param 給 list / lookup；明確 `category` 欄位必須完整回傳以利下游 redaction。

## Impact

### Code
- [app/api/mcp.py](app/api/mcp.py)：`_build_case_payload`、`list_team_test_cases`、`lookup_test_cases` 三處
- [app/models/mcp.py](app/models/mcp.py)：`MCPTestCaseDetailItem` 加欄位

### Tests
- [app/testsuite/test_mcp_api.py](app/testsuite/test_mcp_api.py)：補
  - detail 端點預設帶 `test_data`（含 credential 類別 fixture，驗證 category 不被 strip）
  - list 端點 `include_test_data=true` 時各筆 case 帶 `test_data`、預設不帶
  - lookup 端點 `include_test_data=true` 行為一致
  - `filters` echo 包含 `include_test_data`

### Migration / 相容性
- 純 API 層加欄位 + 加可選 query param，**不需 DB migration**（`test_data_json` 欄位已在 archive `2026-04-23-add-test-data-crud` 時建立）。
- 既有 MCP consumer 不感知 `test_data` 也能繼續運作（dict 透傳）。
- 與 `tcrt_mcp` 的 `align-mcp-with-latest-tcrt-data-model` change 為配套關係：本 change 必須先 land，下游才能跟進。

### 風險
- 若日後新增更敏感 category（如 `secret_url`），API 不會自動 redact；本 change 採取「忠實回傳 + 由消費端 redact」策略，需確保 `category` 欄位永遠存在於 payload。
- `include_test_data=true` 在大量 case 的 list 場景仍可能拉高 response size。沿用既有 `limit ≤ 1000` 的上限即可，不需額外節流。
- TestRunItem 的 test_data snapshot 並不在本 change 暴露範圍；若未來 MCP 想看 run-time snapshot，需另起 change。
