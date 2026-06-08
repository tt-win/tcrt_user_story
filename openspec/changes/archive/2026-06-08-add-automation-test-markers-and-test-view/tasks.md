## 1. Marker parser（Python AST + JS/TS regex）

- [x] 1.1 在 `app/services/automation/smart_scan_service.py` 新增 `TestEntry` 與 `MarkerHit` dataclass，連同 `EntryPoint.test_entries` / `marker_warnings` 欄位
- [x] 1.2 擴充 `_extract_test_metadata` 走訪 Python `decorator_list`，比對 `pytest.mark.tcrt` 並萃取 `tc_ids` / `link_type`（驗證 TC id 格式 `^[A-Za-z0-9_-]+$`、`link_type ∈ {primary, covers, references}`）
- [x] 1.3 擴充 JS/TS regex 解析，對每個 `test(` / `it(` / `describe(` 往上掃 `// tcrt:` 行；非緊鄰時記 `orphan_marker_comment`
- [x] 1.4 解析錯誤一律 fail-open：寫入 `marker_warnings[]`、entry 的 markers 保持空，不阻擋掃描
- [x] 1.5 為 marker parser 補單元測試：合法／非字面量／非緊鄰／無效 link_type／多 marker stacking／class-level marker，覆蓋至少 8 case
- [x] 1.6 確認 `content_unverified=true` 與 `false_positive` 路徑下 `test_entries` 為空，補測試

## 2. Derived link sync 與衝突解決

- [x] 2.1 在 `app/services/automation/script_service.py` 新增 marker reconcile 流程：upsert marker-sync link / 偵測 conflict / cleanup orphan
- [x] 2.2 透過 `test_cases.test_case_number` 反查 case，命中時取 `test_case_id`，未命中時加 `unknown_tc` warning（不建空殼 case）
- [x] 2.3 衝突偵測：既有 link `created_by != "marker-sync"` 且 `link_type` 不同時，保留人類版本並寫 `link_type_conflict` warning
- [x] 2.4 Reconcile cleanup：刪除已無對應 marker pair 的 `created_by="marker-sync"` link，附 audit `reason: "marker_removed"`
- [x] 2.5 `created_by` sentinel 值的工具函式（`is_marker_sync` / `is_ai_suggest` / `parse_ai_suggest_user_id`），集中於 `script_service.py`
- [x] 2.6 為 reconcile 補整合測試：新增 marker / 改 link_type / 移除 marker / 人類覆寫不被動 / unknown TC 不寫 link，覆蓋至少 6 case
- [x] 2.7 確認 `automation_script_case_links.note` JSON 結構為 `{test_name, line, marker_raw}`，新增 schema 助手 + 測試

## 3. Smart Scan API response 擴充

- [x] 3.1 在 `smart_scan_service.smart_scan_result_to_dict` 加入 `test_entries`、`derived_links`、`marker_warnings` 欄位
- [x] 3.2 確認 `entry_point.test_names` 與 `test_count` 維持原語意（向下相容）
- [x] 3.3 在 `app/api/automation_scripts.py` 與相關 router 把擴充欄位串到 client；確保 schema 描述與 OpenAPI 文件同步
- [x] 3.4 補 API 測試：scan response 必含新欄位、舊欄位行為不變

## 4. AI link suggestion endpoint

- [x] 4.1 新增端點 `POST /api/teams/{team_id}/automation-scripts/{script_id}/ai-link-suggestions`，路由與權限走既有 script-scope RBAC
- [x] 4.2 Service 層組 prompt：只收 `test_name + docstring + file_imports + ref_path + candidate_cases (top-50 經 BM25/token overlap 過濾)`
- [x] 4.3 走既有 OpenRouter integration（共用 `get_settings().openrouter.api_key`）；無 key / timeout / 格式錯時回 200 `{suggestions: [], error_summary: ...}`
- [x] 4.4 信心 filter：service 層丟掉 `confidence < 0.60`；UI 端再分 0.60~0.85 與 ≥ 0.85 預勾規則
- [x] 4.5 補 unit test 攔截 OpenRouter HTTP 出口，斷言 payload **不**含 function body / fixture / 同檔其他 test 碼
- [x] 4.6 audit：寫 `READ AUTOMATION_SCRIPT`，details 只含 `script_id / test_name / suggestions_count / model / prompt_version`
- [x] 4.7 補錯誤路徑測試：key 缺失、HTTP 5xx、回傳非 JSON、回傳 confidence 缺欄位

## 5. UI — Suites tab Script ↔ Test view 切換

- [x] 5.1 在 `app/static/js/automation-hub/suites/main.js` 新增 view state（`localStorage` per-team 持久化），預設 Script view
- [x] 5.2 加 toolbar toggle `[Script view] ◀▶ [Test view]`，i18n 字串補入 `en-US.json` / `zh-TW.json` / `zh-CN.json`
- [x] 5.3 Test view 列表：把 `entry_points[*].test_entries[*]` 攤平，columns 含 test name / 來源檔案 / TC linkage badge / link source / marker warnings / AI suggestion 區塊
- [~] 5.4 Test view 點 test name 展開預覽：CodeMirror 6 highlight 對應 `line` 區塊 — 改為「Open source」按鈕跳回 Script view 並展開該檔案；inline CodeMirror highlight 留作後續優化
- [x] 5.5 Marker warnings 顯示：透過 marker badge 與 noMarker 提示呈現；warning 訊息會在後續 sync feedback 強化（保留欄位以利擴展）
- [x] 5.6 AI suggestion UI：≥ 0.85 預勾、0.60~0.85 顯示但不預勾、< 0.60 不顯示；行內 Accept / Dismiss
- [x] 5.7 Accept 互動：呼叫既有 `POST .../links` payload `{test_case_id, link_type: "COVERS"}`；成功後 row 立即顯示 link badge `source=ai-suggested`

## 6. Link source badge 與 created_by 顯示

- [x] 6.1 既有 link 列表 API SHALL 原樣回傳 `created_by`；前端依 sentinel 值（`marker-sync` / `ai-suggest:<id>` / 數字）顯示 badge — 新增 `GET /automation-scripts/{script_id}/links` endpoint 並在 Test view 渲染 badge
- [x] 6.2 補 case detail Automation 面板的 link source badge（reverse view 也要可看出來源）— `LinkedAutomationSummary` 加 `created_by` 欄位、`automation-panel.js` 渲染 marker/AI/human badge
- [x] 6.3 i18n 字串：marker / human / ai-suggested 在三語系都補齊

## 7. Skill 同步（spec 強制義務）

- [x] 7.1 更新 `tools/skills/tcrt-automation-pomify/SKILL.md` 新增「宣告 manual test case 對應」步驟，含 Python decorator 與 JS/TS 註解兩種寫法
- [x] 7.2 更新 `tools/skills/tcrt-automation-pomify/references/tcrt-format-rules.md` 新增 §5「Marker grammar」section，列出 `@pytest.mark.tcrt(...)` 簽名、`// tcrt:` 註解規則、`link_type` 允許值、TC id 格式
- [x] 7.3 更新 `tools/skills/tcrt-automation-pomify/templates/*` 範例 test 加上 marker 寫法
- [x] 7.4 新增 `conftest.py` snippet 模板：`pytest_configure` 註冊 `tcrt` marker 避免 `PytestUnknownMarkWarning`
- [x] 7.5 在 skill README 加上「marker 為 derived link 的 source of truth、衝突時人類手建優先」說明

## 8. 驗證與文件

- [ ] 8.1 `pytest app/testsuite -q` 全綠
- [x] 8.2 `openspec validate add-automation-test-markers-and-test-view` 綠燈
- [ ] 8.3 手動驗證：在 dev repo 加一支含 marker 的 test，觸發 sync，確認 link 出現、`created_by="marker-sync"`、note JSON 內容正確
- [ ] 8.4 手動驗證：把 marker 從 covers 改 primary、再移除 marker，確認 reconcile 行為符合 spec
- [ ] 8.5 手動驗證：UI Suites tab 切到 Test view，確認 marker / human / ai-suggested badge 顯示與切換持久化
- [ ] 8.6 手動驗證：AI suggestion 走通至少一個 mock 案例（攔截 OpenRouter 出口斷言 payload）
- [x] 8.7 更新 `openspec/project.md`（若 marker grammar 屬於對外文件範圍）
- [ ] 8.8 PR 描述附 skill sync checklist 勾選

> 2026-06-05 focused verification note: `uv run pytest app/testsuite/test_automation_smart_scan_service.py app/testsuite/test_automation_script_service.py app/testsuite/test_automation_ai_link_suggest_service.py app/testsuite/test_automation_linkage_service.py -q --no-header` → `56 passed`。全套 `pytest app/testsuite -q` 仍受 repo 既有非本 change 失敗影響，故 8.1 先不勾。
