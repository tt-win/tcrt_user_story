## Why

Automation Hub 目前的掃描單位是「檔案」(`tests/test_login.py`)，但一個檔案通常包含多個 test 函式，各自對應到不同的 manual test case（TC-001、TC-005…）。實務上會出現以下問題：

1. **資訊粒度錯位**：UI 只顯示檔案列表與 linked case 總數，看不到「`test_login_with_2fa` 對應 TC-005」這種直接關係，QA 無法靠介面回答「哪個測試 case 已自動化、哪個沒」。
2. **連結無法自說明**：`automation_script_case_links` 表必須在 UI 手動建立，測試碼本身沒有任何 metadata 宣告 coverage，使用者重構或新增 test 後容易忘記回 TCRT 補 link。
3. **既有資料閒置**：smart-scan 服務的 `_extract_test_metadata` 早就解析出 `test_*` 函式名與 `Test*` 類別名，回傳 `entry_point.test_names`，但 UI 從未渲染這份資料。

這個 change 把測試碼裡的「coverage 意圖」變成程式碼自帶的標記，讓掃描結果以 test 函式為單位呈現，並把現有 link 表變成 marker 同步出來的 derived state。

## What Changes

- **新增 marker 文法**：
  - Python：`@pytest.mark.tcrt("TC-001")` decorator，可接多個 TC 與 `link_type` kwarg
  - JS/TS：`// tcrt: TC-001` 註解（位於 `test()` / `it()` 上方），支援多 case 與 link_type 後綴
- **擴充 smart-scan parser**：`_extract_test_metadata` 加入 decorator walk（Python AST）與行對位 regex（JS/TS），回傳 `(test_name, [tc_ids], link_type, source)` 結構。
- **Derived link sync**：`AutomationScriptService.sync()` 解析 marker 後 upsert `automation_script_case_links`，`created_by="marker-sync"`、`note` 內含 `{test_name, line, marker_args}`。人類手建 link（`created_by != "marker-sync"`）優先級高於 marker，衝突時保留人類版本並在 scan result 標示 conflict。
- **Smart-scan API 擴充**：response 新增 `entry_point.marker_links[]` 與 `warnings[]`（含 unresolved TC、conflict）。
- **Suites tab 新增 Script ↔ Test view 切換**：
  - Script view（現狀，保留）：以檔案為單位，展開後顯示函式列表
  - Test view（新增）：把所有 entry_points 攤平成 test 函式 flat list，每列顯示來源檔案、TC 連結、link 來源 badge（marker / human / ai-suggested）
- **AI 建議式連結（suggestion-only）**：新 endpoint `POST .../automation-scripts/{id}/ai-link-suggestions`，輸入 test_name + docstring + 同檔 imports（**不送 function body**），回傳 top-N TC 候選與 confidence；UI 顯示 ≥ 0.6 的候選，使用者必須點 confirm 才寫入 link。
- **Skill 同步義務**：`tools/skills/tcrt-automation-pomify/` 強制更新：
  - `SKILL.md` 加 marker 撰寫步驟
  - `references/tcrt-format-rules.md` 加 §5 marker grammar
  - `templates/*` 範例 test 加上 marker 與 `conftest.py` 註冊 snippet

**非目標**（明確劃出 scope 邊界）：

- ❌ Per-test run status — 需要 ingest Allure JSON 才能拿到 per-test pass/fail，獨立 change
- ❌ 新增 `automation_script_tests` per-test entity 表 — spike 已確認 derived links 足夠，避免 schema 膨脹
- ❌ AI 自動建立 link 而不需人類確認 — 誤連結會污染 coverage 報表
- ❌ Marker 解析支援檔案 sidecar YAML / docstring 標頭 — 先收斂在兩種主流文法

## Capabilities

### New Capabilities

無 — 所有變更皆掛在現有 capability 下。

### Modified Capabilities

- `automation-hub-script-management`：新增 marker grammar requirement、derived link sync requirement、Suites tab Script ↔ Test view requirement、skill 同步義務的補充（marker 文法納入既有 sync 義務範圍）
- `automation-hub-smart-suite-recommendation`：smart-scan response schema 擴充 `marker_links` 與 `warnings`；entry-point 解析需暴露 marker 來源 metadata

> 註：AI 建議端點刻意**不**獨立成新 capability。理由：它只是 script-management 內 link 操作的輔助 surface，沒有獨立生命週期；獨立 capability 會讓 spec 邊界變模糊。若未來 AI 建議延伸到 suite 推薦、case 撰寫等場景，再抽出 `automation-hub-ai-link-suggestion` 不遲。

## Impact

**程式**：
- `app/services/automation/smart_scan_service.py` — `_extract_test_metadata` 擴充 marker 解析、回傳結構新增 `marker_links` 與 `warnings`
- `app/services/automation/script_service.py` — `sync()` 增加 derived link 寫入邏輯、衝突偵測、清理孤兒 marker link
- `app/api/automation_scripts.py` — smart-scan response schema 擴充；新增 `/ai-link-suggestions` endpoint
- `app/static/js/automation-hub/suites/main.js` — Script ↔ Test view 切換、AI 建議互動 UI
- `app/static/locales/{en-US,zh-TW,zh-CN}.json` — 新 UI 字串與 marker warning 訊息

**資料庫**：
- 無 schema 變更（複用既有 `automation_script_case_links`，靠 `created_by` 欄位區分來源）
- 無 migration，無 rollback 風險

**API / 相容性**：
- smart-scan response 新增欄位（additive，向下相容）
- `automation_script_case_links.created_by` 出現新 sentinel 值 `"marker-sync"`；既有讀取端只需把它當不透明字串顯示
- 新 endpoint 為純加項

**外部依賴**：
- AI 建議走既有 OpenRouter integration（與 smart-scan LLM enrichment 共用），無新增供應商
- pytest marker 需使用者在 `conftest.py` 註冊（否則 pytest 跑時會出 `PytestUnknownMarkWarning`） — skill template 提供 snippet

**Skill 同步**（spec 強制義務）：
- `tools/skills/tcrt-automation-pomify/SKILL.md`
- `tools/skills/tcrt-automation-pomify/references/tcrt-format-rules.md`
- `tools/skills/tcrt-automation-pomify/templates/*`

未同步將被 `openspec validate` 與 PR review 阻擋 archive / merge。

**風險**（細節留到 design.md）：
- Marker 與人類手建 link 衝突的 UX
- Unknown TC number 的處理（warn vs error vs auto-create）
- Marker 移除時 derived link 的清理時機
- AI 信心門檻、prompt 內容安全邊界
