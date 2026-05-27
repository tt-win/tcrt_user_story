## 1. Pydantic 模型

- [x] 1.1 在 [`app/models/mcp.py`](app/models/mcp.py) 新增 `MCPTestCaseSectionItem(BaseModel)`，欄位：`id: int`、`test_case_set_id: int`、`parent_section_id: Optional[int] = None`、`name: str`、`description: Optional[str] = None`、`level: int`、`sort_order: int = 0`、`test_case_count: int = 0`、`created_at: Optional[datetime] = None`、`updated_at: Optional[datetime] = None`。
- [x] 1.2 新增 `MCPTeamTestCaseSectionsResponse(BaseModel)`，欄位：`team_id: int`、`filters: Dict[str, Any]`、`sections: List[MCPTestCaseSectionItem] = Field(default_factory=list)`、`total: int`。
- [x] 1.3 將兩個新模型 export 在 `app/models/mcp.py` 同層的 `__all__` 或維持現狀（依專案慣例）。維持現狀（檔案無 `__all__`，採隱式 export）。

## 2. Route Handler

- [x] 2.1 在 [`app/api/mcp.py`](app/api/mcp.py) 新增 import：`TestCaseSection as TestCaseSectionDB`。
- [x] 2.2 新增 helper：`async def _get_section_case_counts(db, team_id) -> dict[int, int]`，做 `SELECT test_case_section_id, COUNT(*)` GROUP BY，回傳 `{section_id: count}`，section_id 為 `None` 的 case 不計。
- [x] 2.3 新增 route handler `async def list_team_test_case_sections(team_id, db, principal, set_id, parent_section_id, roots_only, include_empty)`，路徑為 `@router.get("/teams/{team_id}/test-case-sections", response_model=MCPTeamTestCaseSectionsResponse)`，沿用 `require_mcp_team_access` dependency。
- [x] 2.4 在 handler 內：所有列出的步驟已實作（_ensure_team_exists, set_id 軟驗證, count map, parent_section_id/roots_only/include_empty 過濾, 排序, payload 組裝）。

## 3. URL 一致性檢查

- [x] 3.1 確認 router prefix 維持 `/mcp`，最終完整 URL 為 `/api/mcp/teams/{team_id}/test-case-sections`。命名與既有 `/teams/{team_id}/test-cases`、`/teams/{team_id}/test-runs` 對齊（已透過 `app.openapi()` 驗證）。

## 4. Tests

- [x] 4.1 在 [`app/testsuite/test_mcp_api.py`](app/testsuite/test_mcp_api.py) 新增 fixture：擴展 `_seed_mcp_data` 新增 set_a2 + 4 個 sections（Login, SSO 子層, Empty, Misc）+ 3 個額外 cases。
- [x] 4.2 撰寫測試：預設查詢回傳全部 sections（含跨 set），`total` 與陣列長度一致。
- [x] 4.3 撰寫測試：`set_id=A` 過濾正確；`set_id=999`（不存在）回 `set_not_found=true` 與空 list。
- [x] 4.4 撰寫測試：`parent_section_id=X` 只回 X 的直系 children，不遞迴。
- [x] 4.5 撰寫測試：`roots_only=true` 只回 `parent_section_id IS NULL` 的 sections。
- [x] 4.6 撰寫測試：`include_empty=false` 排除 count=0 的 sections；預設或 `true` 時包含。
- [x] 4.7 撰寫測試：排序穩定性 — 同樣 query 連續呼叫兩次，回傳 id 順序相同。
- [x] 4.8 撰寫測試：team scope 守門 — scope 外 team 回 403；不存在 team 回 404。
- [x] 4.9 撰寫測試：`test_case_count` 不遞迴（root section 直接掛的 case 數，不含子 section 的）。
- [x] 4.10 撰寫測試：POST/PUT/DELETE 對端點皆回 405 或 404（FastAPI 預設行為，驗證即可）。

## 5. Smoke / 文件

- [ ] 5.1 PR description 附 curl 範例：
  - `curl ... /api/mcp/teams/1/test-case-sections`
  - `curl ... /api/mcp/teams/1/test-case-sections?set_id=10&roots_only=true`（PR 階段補上）
- [x] 5.2 確認 `/openapi.json` 自動更新後，新端點與兩個 Pydantic 模型有正確型別定義（已透過 `app.openapi()` 驗證 `MCPTestCaseSectionItem` / `MCPTeamTestCaseSectionsResponse` 都在 schemas，新 path 註冊成功）。

## 6. 驗收

- [x] 6.1 `pytest app/testsuite/test_mcp_api.py -q` 全綠（26 passed，含本 change 新增 9 個測試）。
- [x] 6.2 `openspec validate expose-test-case-sections-in-mcp-api` 通過。
- [ ] 6.3 對著 `tcrt_mcp` 本地環境驗證：在尚未升級 `tcrt_mcp` 的情況下，新端點不影響既有 5 個 MCP tool 的 smoke flow。（PR 前由 owner 跑）
