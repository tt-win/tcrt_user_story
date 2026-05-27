## Why

`TestCaseSection`（[`app/models/database_models.py:363`](app/models/database_models.py:363)）形成 Test Case Set 內最多 5 層的巢狀結構，是 QA 在 TCRT UI 上實際導覽 test cases 的主要分類軸。

[`/api/mcp/teams/{team_id}/test-cases`](app/api/mcp.py:447) 雖然會在每筆 case 上回傳 `test_case_section_id`，但目前 MCP consumer 拿到該 ID 後**沒有任何端點可以反查 section 名稱、parent、層級**，只能從 case payload 反推出曾經出現過哪些 section_id，無法重建完整 section tree。

實務影響：透過 MCP 連進來的 AI agent 無法回答「這個 set 底下有哪些測試模組？」「Login 區塊有幾個 subsection？」「`section_id=88` 是什麼？」這類常見導覽問題，只能 fallback 到列出大量 test cases 後讓 LLM 從 title 猜分類。

本 change 補一個唯讀端點讓 MCP consumer 可以平行查詢 section tree（含每個 section 的 test_case_count），與 `tcrt_mcp` 的 `align-mcp-with-latest-tcrt-data-model` 配套，讓下游能新增 `list_test_case_sections` MCP tool。

## What Changes

- 新增端點 `GET /api/mcp/teams/{team_id}/test-case-sections`（資源命名與既有 `test-cases`、`test-runs` 風格對齊）：
  - Query params：
    - `set_id`（optional, int）：限制單一 Test Case Set；省略時回傳該 team 在所有 set 下的 sections。
    - `parent_section_id`（optional, int）：限制單一 parent；用於分層延展查詢。
    - `include_empty`（optional, bool, default `true`）：是否包含 `test_case_count == 0` 的 section（QA 可能會建立空 section 占位）。
  - Response：扁平 list（不做 server-side tree 組裝，由 consumer 根據 `parent_section_id` 重建），每筆 section 包含 `id / test_case_set_id / parent_section_id / name / description / level / sort_order / test_case_count / created_at / updated_at`，並回傳 `filters` echo 與 `total`。
  - 排序：`test_case_set_id ASC, level ASC, sort_order ASC, id ASC`，確保同 set 同層級內 LLM 看到的順序穩定。
  - Auth：沿用 `require_mcp_team_access`（team scope 守門）。
  - 不存在的 `team_id` 回 404；不存在的 `set_id` 在 `strict_set` 場景比照 `test-cases` 端點處理（這次採非嚴格：`set_id` 不存在則回空 list 並在 `filters` 加 `set_not_found: true`）。
- 新增 Pydantic 模型於 [`app/models/mcp.py`](app/models/mcp.py)：
  - `MCPTestCaseSectionItem`（與上述 fields 對應）
  - `MCPTeamTestCaseSectionsResponse(team_id, filters, sections, total)`
- 路由註冊維持在既有 `router = APIRouter(prefix="/mcp", tags=["mcp"])` 之下。

## 非目標 (Non-goals)

- **不**做 section 的 mutate API（建立 / 更新 / 刪除維持在現有 user JWT 端點）。
- **不**回傳 server-side 預組樹狀結構；MCP 友善的扁平 list + `parent_section_id` 可由 consumer 自行 reconstruct，避免回應大小與遞迴深度問題。
- **不**修改既有 [`/api/mcp/teams/{team_id}/test-cases`](app/api/mcp.py:447) 回應的 `sets` 結構（維持只列 sets，不夾 sections）。
- **不**處理 section 與 test_data 的 cross-cutting；本 change 僅針對 section tree 暴露。

## Capabilities

### Modified Capabilities
- `mcp-read-api`：新增 sections 唯讀端點與對應 Pydantic 響應模型；明確 section tree 採扁平回傳並由 consumer 重建。

## Impact

### Code
- [app/api/mcp.py](app/api/mcp.py)：新增 `list_team_test_case_sections` route handler；新增 `_section_payload` helper（搭配 `test_case_count` 子查詢）。
- [app/models/mcp.py](app/models/mcp.py)：新增 `MCPTestCaseSectionItem`、`MCPTeamTestCaseSectionsResponse`。

### Tests
- [app/testsuite/test_mcp_api.py](app/testsuite/test_mcp_api.py)：補
  - 預設（無 query）回傳 team 全部 sections，包含跨 set
  - `set_id` 過濾（存在 / 不存在）
  - `parent_section_id` 過濾（含 root parent 為 `null` 的查詢）
  - `include_empty=false` 排除 count=0 section
  - `team_scope_ids` 守門：scope 外 team 回 403
  - 排序穩定性

### Migration / 相容性
- 純新端點，無 DB migration、無既有路由變更。
- 既有 MCP consumer（包括 `tcrt_mcp` 舊版）不感知新端點，行為不變。
- 與本 repo 另一 change `expose-test-data-in-mcp-api` 互相獨立，可任意順序 land。

### 風險
- `test_case_count` 需子查詢；section 數量大時要避免 N+1。建議用 `func.count` + `group_by(section_id)` 的單次聚合查詢，並 left join 帶出沒有 case 的 section。
- 5 層深度上限由現有 model 強制；本端點不再驗證 level 範圍（信任 DB constraint）。
- 若未來 section 模型加上 `archived_at` 之類欄位，需同步擴充本端點 filter；先不預先設計。
