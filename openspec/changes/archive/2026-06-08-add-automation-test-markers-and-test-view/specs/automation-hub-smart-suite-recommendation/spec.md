## MODIFIED Requirements

### Requirement: System MUST detect test script entry points deterministically
Smart Scan SHALL 以 deterministic path filtering + structural content analysis 判斷 entry points。LLM SHALL NOT be required for entry point detection.

**Phase 1 - Path filtering:**
- 掃描範圍：`StorageProvider.list_scripts(path=effective_tests_path, recursive=True)`；`effective_tests_path` 優先來自 `tcrt-automation.yml` 的 `paths.tests`，缺省時 fallback 為 provider config 的 `smart_scan.scan_path`，再缺省則為 `"tests/"`
- 納入條件：檔案名稱符合 `test_*`、`*_test.py`、`*.spec.*`、`*.test.*`
- 排除條件：
  - `__init__.py`、`conftest.py`、`conftest.js`、`conftest.ts`
  - 路徑含 `pages/`、`page_objects/`、`pom/`、`flows/`、`utils/`、`helpers/`、`fixtures/`、`mocks/`、`resources/`、`testdata/`、`data/`、`config/`、`scripts/`、`reports/`
  - 路徑含 `.github/`、`.git/`、`node_modules/`、`venv/`、`env/`、`__pycache__/`
  - 副檔名非 `.py`、`.js`、`.ts`、`.jsx`、`.tsx`

**Phase 2 - Structural content validation:**
- 對 Phase 1 通過的檔案，service SHALL 讀取可接受大小內的 content（預設 `max_scan_bytes=262144`）
- Python SHALL 使用 `ast` 判斷 `def test_*`、`async def test_*`、`class Test*`，並 SHALL 走訪 `decorator_list` 解析 `@pytest.mark.tcrt(...)` marker
- JS/TS SHALL 先以 bounded lexical scan 判斷 `test(`、`test.describe(`、`test.only(`、`test.skip(`、`it(`、`describe(`；同時 SHALL 解析緊鄰其上方的 `// tcrt: ...` 註解作為 marker
- 若內容不含任何 test pattern，SHALL 標記為 `false_positive` 並排除
- 若檔案超過 `max_scan_bytes`，SHALL 不送 LLM，並 MAY 以 Phase 1 結果保守納入且標記 `content_unverified=true`；此情況下 marker 視為未解析、不影響 derived link

**回傳 entry point 每筆 SHALL 包含**：

- 既有欄位：`ref_path`、`ref_branch`、`etag`、`detected_format`、`test_names`、`test_count`、`content_unverified`
- **新增 `test_entries: list[TestEntry]`**：每個 test 函式 / class / JS test 一筆，含：
  - `name`（函式名 / test() 字串）
  - `kind`（`"function"` / `"class"` / `"js_test"`）
  - `line`（在檔案內的起始行）
  - `docstring`（Python `ast.get_docstring()` 結果，JS/TS 為 null）
  - `markers: list[MarkerHit]`：每個 marker 一筆，含 `tc_ids: list[str]`、`link_type: str`、`source_line: int`、`raw: str`
- **新增 `derived_links: list[DerivedLinkSummary]`**：sync 完成後該 entry 已生效的 marker-sync link 摘要（`test_case_id`、`test_case_number`、`link_type`、`source`）
- **新增 `marker_warnings: list[dict]`**（entry 級別）：含 `unknown_tc`、`invalid_tc_format`、`non_literal_marker`、`orphan_marker_comment`、`link_type_conflict`，每筆帶 `line` 或 `tc_id` 等定位資訊

`test_names` 與 `test_count` 維持原語意以保 API 向下相容。新欄位為 additive，舊 client 可忽略。

#### Scenario: Mixed repo with helpers and real tests
- **WHEN** repo 結構含 `tests/auth/test_login.py`、`tests/pages/login_page.py`、`tests/conftest.py`
- **THEN** Smart Scan SHALL 只把 `tests/auth/test_login.py` 納入 entry points
- **THEN** 被排除檔案 SHALL 在 result 中提供 reason，例如 `helper_path`、`conftest`、`unsupported_extension`

#### Scenario: Python false positive is filtered by AST
- **WHEN** `tests/auth/test_data_builder.py` 檔名符合 `test_*` 但 AST 內沒有 test function 或 `class Test*`
- **THEN** Smart Scan SHALL 將它標記為 `false_positive`，不納入 suite 建議

#### Scenario: Python marker parsed into test_entries
- **WHEN** `tests/test_login.py` 含 `@pytest.mark.tcrt("TC-001")\ndef test_login_happy():\n    """Verify happy path"""`
- **THEN** entry_point.test_entries SHALL 含 `{name: "test_login_happy", kind: "function", docstring: "Verify happy path", markers: [{tc_ids: ["TC-001"], link_type: "covers", source_line: <N>}]}`

#### Scenario: JS marker parsed via adjacent comment
- **WHEN** `tests/login.spec.ts` 含 `// tcrt: TC-001\ntest('login happy', async () => {})`
- **THEN** entry_point.test_entries SHALL 含 `{name: "login happy", kind: "js_test", markers: [{tc_ids: ["TC-001"], link_type: "covers"}]}`

#### Scenario: Marker warnings surfaced at entry level
- **WHEN** test 函式含 marker 指向 `TC-999`（該 team 不存在的 case）
- **THEN** scan response 該 entry_point 的 `marker_warnings[]` SHALL 含 `{type: "unknown_tc", tc_id: "TC-999", line: <N>}`

#### Scenario: Oversized file skips marker parsing
- **WHEN** 檔案超過 `max_scan_bytes`
- **THEN** entry_point SHALL 標 `content_unverified=true`、`test_entries=[]`、`marker_warnings=[]`（不嘗試部分解析）

#### Scenario: Backward compatibility for test_names
- **WHEN** 舊 client 只讀 `entry_point.test_names`
- **THEN** 該欄位 SHALL 保持原語意（函式名 / 類名清單），新增欄位 (`test_entries`、`derived_links`、`marker_warnings`) 不影響 client 解析
