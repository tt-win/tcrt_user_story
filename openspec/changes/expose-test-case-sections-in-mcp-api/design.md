## Context

[`TestCaseSection`](../../../app/models/database_models.py:363) 是 TCRT UI 上 QA 實際導覽 test case 的主軸：每個 Test Case Set 內最多 5 層巢狀分類，靠 `parent_section_id` 自參考、`level` 標記深度、`sort_order` 控制同層順序。

關鍵約束（DB 層）：
- 同一 `(test_case_set_id, parent_section_id, name)` 唯一（`uq_section_name_in_parent`）
- 索引：`ix_sections_set_parent`、`ix_sections_set_level`
- CASCADE：刪除 set 連帶刪 sections；刪除 parent section 連帶刪 children
- TestCase.test_case_section_id 為 nullable（case 可不掛 section）

[MCP 既有 API](../../../app/api/mcp.py) 已在每筆 test case 上回 `test_case_section_id`，但**沒有任何端點可以反查**：section 名稱、parent、level、test_case_count。AI agent 拿到 `section_id=88` 也無法回答「這是什麼模組」。

## Goals / Non-Goals

**Goals**
- 提供唯讀端點讓 MCP consumer 列出 team 範圍內的 sections（含 metadata 與 case 計數）。
- 支援按 `set_id` 過濾、按 `parent_section_id` 過濾（含 root parent = `null`）。
- 回應結構讓消費端可重建 tree（不在 server 預組）。
- 排序穩定，保證 LLM 重複查詢看到同樣順序。
- 沿用既有 team scope 守門 (`require_mcp_team_access`)。

**Non-Goals**
- 不做 mutate API（建立/編輯/刪除維持在 user JWT 端點）。
- 不在 server 端預組 nested tree（避免遞迴序列化 + 大 response）。
- 不修改既有 `/api/mcp/teams/{id}/test-cases` 的 `sets` 子物件結構（不夾 sections）。
- 不暴露 section 與其 child sections / cases 的詳細關係（只回 section metadata）。
- 不做 section 全文搜尋（QA 用 UI 即可，MCP 不是搜尋場景）。

## Decisions

### 1. URL 設計：`GET /api/mcp/teams/{team_id}/test-case-sections`
- **Rationale**：team 是 MCP scope 的最小單位（machine token scope 以 team_id 為粒度），sections 跨 set 也需被一次取得（QA 在組織導覽時）。掛在 team 下、用 `set_id` 過濾比 `/sets/{id}/sections` 更靈活。資源名 `test-case-sections` 與既有 `test-cases`、`test-runs` 命名風格對齊。
- **Alternatives considered**：
  - `/api/mcp/teams/{team_id}/sets/{set_id}/sections` → 拒絕。會強迫消費端先知道 set_id；但常見場景是「給我 team 全部 sections，我看完再決定」。
  - `/api/mcp/teams/{team_id}/sections`（短名）→ 拒絕。在「test_case_section」與「test_run section」未來可能並存的命名空間內，短名易混淆。
  - 把 sections 塞進 `/api/mcp/teams/{id}/test-cases` 的 response → 拒絕。每次列 cases 都帶完整 section tree 是浪費；且 sections 應可獨立查詢。

### 2. Query 參數
| Param | Type | Default | Description |
|---|---|---|---|
| `set_id` | int? | `null` | 限制單一 set；null = team 全部 set |
| `parent_section_id` | int? | `null` | 限制單一 parent；用於延展查詢。注意：傳 `null` 表示 query 不帶該 param（不過濾），若要查 root sections 用獨立的 `roots_only=true` flag |
| `roots_only` | bool | `false` | 只回 `parent_section_id IS NULL` 的 root sections |
| `include_empty` | bool | `true` | 是否包含 test_case_count == 0 的 section |

- **`parent_section_id` 的 null 歧義處理**：HTTP query string 沒辦法區分「不傳」與「明確傳 null」。採用 `roots_only` flag 來表達「只要 root」的需求；`parent_section_id=42` 則表示「只要 42 的直系子 section」。
- **`include_empty=true` 為預設**：QA 可能會建立空 section 占位（規劃中），預設帶出避免漏看。

### 3. Response：扁平 list + `parent_section_id`
- **Rationale**：
  - 5 層上限不算深，但 server 預組 nested 會讓 response 層次與 schema 變複雜；扁平更符合 REST 慣例。
  - LLM 對扁平 list + parent ref 的處理能力與 nested 相當（只要 prompt 說明），但回應 token 數較少（沒有重複的包覆物件）。
  - 消費端要 reconstruct tree 也很簡單（`{parent_id: [children]}` map）。
- **回應 shape**：
  ```json
  {
    "team_id": 1,
    "filters": {
      "set_id": 10,
      "set_not_found": false,
      "parent_section_id": null,
      "roots_only": false,
      "include_empty": true
    },
    "sections": [
      {
        "id": 88,
        "test_case_set_id": 10,
        "parent_section_id": null,
        "name": "Login",
        "description": "User authentication scenarios",
        "level": 1,
        "sort_order": 0,
        "test_case_count": 12,
        "created_at": "2026-03-03T07:00:00.000000",
        "updated_at": "2026-03-03T07:00:00.000000"
      }
    ],
    "total": 1
  }
  ```

### 4. `test_case_count` 計算策略
- **Rationale**：QA / AI agent 經常用 count 決定要不要往下鑽（避免拉開空目錄）。
- **實作**：
  - 用 `SELECT test_case_section_id, COUNT(*) FROM test_cases WHERE team_id = ? GROUP BY test_case_section_id` 一次撈出 map。
  - 對每個 section 從 map 取值，預設 0。
  - 不做 recursive count（不把 children 的 case 算進來），避免 N+1 + 語意混淆。「Login section 有 12 個 case」指的是直接掛在 Login 下的 case，不含 Login → SSO 子 section 的 case。
- **Alternatives considered**：
  - 預先在 `TestCaseSection` 加 `test_case_count` 欄位（trigger 維護）→ 拒絕，超出本 change 範圍且增加寫入路徑複雜度。
  - Recursive count → 拒絕，效能差且語意不清。

### 5. `set_id` 不存在的處理
- 沿用 `/api/mcp/teams/{id}/test-cases` 既有的「非嚴格」行為：回空 list + `filters.set_not_found = true`。不額外設計 `strict_set` flag（避免 query 表面積膨脹；若需要嚴格，未來可加）。
- 不存在的 `team_id` 維持 404（與其他 MCP 端點一致）。
- 不存在的 `parent_section_id`：直接回空 list（沒有對應的 children）；不做特殊提示，符合 REST 慣例。

### 6. 排序：`test_case_set_id ASC, level ASC, sort_order ASC, id ASC`
- **Rationale**：
  - 跨 set 查詢時，按 set 分群讓 LLM 容易理解邊界。
  - 同 set 內按 level 由淺至深，符合「先看大分類再看小分類」的人類思維。
  - 同 level 用 `sort_order`（QA 在 UI 上拖曳的順序）。
  - 最後 tie-break 用 `id`（保證 deterministic）。

### 7. Auth：沿用 `require_mcp_team_access`
- 已有 dependency 完成 `team_scope_ids` 守門。本端點直接套用。
- 不需要 `mcp_read` 額外子權限（與其他 read API 等同對待）。

## Risks

- **`test_case_count` 子查詢效能**：team 可能有上千 sections，但 `GROUP BY` + index `ix_test_cases_set_section` 應夠快；若日後變慢可加 covering index。
- **大 team 回應大小**：1000 sections × 每筆 ~300 bytes ≈ 300 KB，仍可接受；若極端場景需要 pagination，未來再加。
- **`parent_section_id` query 語意混淆**：用 `roots_only` 而非 nullable param 來避開 HTTP null 歧義；但 API 表面多了一個 param，需在 docstring + spec 文件說清楚。
- **跨 set 同名 section**：UI 不限同一 set 跨層級不可重名，但 set A 與 set B 可有同名「Login」section。回應的扁平 list 必須保留 `test_case_set_id` 才能讓消費端正確 group。
