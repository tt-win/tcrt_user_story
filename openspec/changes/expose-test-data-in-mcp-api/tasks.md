## 1. Pydantic 模型擴充

- [x] 1.1 在 [`app/models/mcp.py`](app/models/mcp.py) 的 `MCPTestCaseDetailItem` 新增 `test_data: List[Dict[str, Any]] = Field(default_factory=list)`，註明 `每筆物件包含 id/name/category/value`。
- [x] 1.2 確認既有 import 已涵蓋 `List`、`Dict`、`Any`、`Field`（無則補 import）。

## 2. API 序列化邏輯

- [x] 2.1 在 [`app/api/mcp.py::_build_case_payload`](app/api/mcp.py:130) 的 `include_extended=True` 分支補 `"test_data": _parse_json_list(row.test_data_json)`。
- [x] 2.2 為 `_build_case_payload` 加入新參數 `include_test_data: bool = False`；當 `include_extended=False` 但 `include_test_data=True` 時，僅追加 `"test_data"` 而不帶其他 extended 欄位。
- [x] 2.3 確認 `_parse_json_list` 對 `test_data_json` 的解析能正確保留 `id / name / category / value` 四欄位（既有實作會直接 passthrough dict，已符合，但加註解以防未來有人加 normalization）。

## 3. List 端點 (`/api/mcp/teams/{team_id}/test-cases`)

- [x] 3.1 在 [`app/api/mcp.py::list_team_test_cases`](app/api/mcp.py:447) 新增 query 參數 `include_test_data: bool = Query(False, description="是否回傳 test_data 陣列")`。
- [x] 3.2 將 `include_test_data` 傳給 `_build_case_payload(..., include_test_data=...)`。
- [x] 3.3 在 response 的 `filters` 物件加入 `"include_test_data": include_test_data`。

## 4. Lookup 端點 (`/api/mcp/test-cases/lookup`)

- [x] 4.1 在 [`app/api/mcp.py::lookup_test_cases`](app/api/mcp.py:305) 新增同名 query 參數 `include_test_data: bool = Query(False, ...)`。
- [x] 4.2 將 `include_test_data` 傳給 `_build_case_payload`。
- [x] 4.3 在 response 的 `filters` 物件加入 `"include_test_data": include_test_data`。

## 5. Detail 端點 (`/api/mcp/teams/{team_id}/test-cases/{test_case_id}`)

- [x] 5.1 確認 [`app/api/mcp.py::get_team_test_case_detail`](app/api/mcp.py:597) 仍呼叫 `_build_case_payload(row, include_content=True, include_extended=True)`；無需新增參數，`test_data` 會自動隨 `include_extended` 帶出。
- [x] 5.2 撰寫 docstring 註解：「detail 端點預設帶 test_data，與 attachments 等 extended 欄位等價對待」。

## 6. Tests

- [x] 6.1 在 [`app/testsuite/test_mcp_api.py`](app/testsuite/test_mcp_api.py) 新增 fixture：建立含兩筆 test_data 的 test case（一筆 `category="text"`、一筆 `category="credential"`）。
- [x] 6.2 撰寫測試：detail 端點回傳 `test_data` 陣列、長度正確、`category` 與 `value` 完整保留（特別驗證 `credential` 類別 value 未被遮罩）。
- [x] 6.3 撰寫測試：detail 端點對 `test_data_json` 為 `null` 的 case 回傳 `test_data: []`。
- [x] 6.4 撰寫測試：detail 端點對 `test_data_json` 為毀損 JSON 字串時不報 500，回傳 `test_data: []`。
- [x] 6.5 撰寫測試：list 端點 `include_test_data=true` 時每筆 `test_cases[i]` 含 `test_data`，預設或 `false` 時無 `test_data` 鍵。
- [x] 6.6 撰寫測試：list 端點 `filters.include_test_data` 正確 echo（true/false 兩情境）。
- [x] 6.7 撰寫測試：lookup 端點 `include_test_data=true` 時 `items[i].test_case.test_data` 存在。
- [x] 6.8 撰寫測試：list 端點同時帶 `include_content=true&include_test_data=false`，回應有 precondition/steps/expected_result 但無 test_data。
- [x] 6.9 撰寫測試：未授權 team 的 test case 不會因 test_data 而洩漏（沿用既有 team scope 守門驗證，但確認新欄位不會繞過）。

## 7. Smoke / 文件

- [ ] 7.1 在 PR description 附帶 curl 範例：`curl ... /api/mcp/teams/1/test-cases?include_test_data=true&limit=5`。（PR 階段補上）
- [x] 7.2 確認 OpenAPI schema 自動更新後，`include_test_data` 與 `test_data` 欄位有正確型別說明（已透過 `app.openapi()` 驗證 `MCPTestCaseDetailItem.test_data` 為 array of object，list/lookup 也帶 `include_test_data` query param）。
- [x] 7.3 不需更動 `mcp_machine_auth.md` 等既有 docs（行為純加欄位）。

## 8. 驗收

- [x] 8.1 `pytest app/testsuite/test_mcp_api.py -q` 全綠（17 passed，含新增 6 個測試）。
- [x] 8.2 `openspec validate expose-test-data-in-mcp-api` 通過。
- [ ] 8.3 在本地對著 `tcrt_mcp` smoke 測試（即使未升級的 `tcrt_mcp` 0.x 對齊版也能正確讀取，dict 透傳不壞）。（PR 前由 owner 跑）
