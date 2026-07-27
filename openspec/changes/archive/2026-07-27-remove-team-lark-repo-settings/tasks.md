## 0. 前置確認

- [x] 0.1 `rg -n "is_lark_configured|lark_config|wiki_token" tools/skills/tcrt-app`（gitignored 目錄）確認外部 skill 是否依賴這些欄位；若有，記錄於 design Open Question 1 並同步調整。**結果**：`rg` 在 `tools/skills/`（含 `tcrt-app`）對四個關鍵字皆 0 命中，外部 skill 不依賴此欄位
- [x] 0.2 確認分支已從最新 `main` 開出，且工作區沒有夾帶不相關的既有未追蹤檔案

## 1. 後端：team 模型與 API

- [x] 1.1 `app/models/team.py`：刪除 `LarkRepoConfig` class；`Team.lark_config`、`TeamCreate.lark_config`、`TeamUpdate.lark_config` 移除；刪除 `Team.is_lark_configured()` 與 `Team.get_lark_url()`；`model_config.json_schema_extra.example` 移除 `lark_config` 範例
- [x] 1.2 `app/api/teams.py` `team_model_to_db()`：`wiki_token=""`、`test_case_table_id=""`（欄位為 `NOT NULL`，必須顯式寫入）
- [x] 1.3 `app/api/teams.py` `team_db_to_model()`：移除 `LarkRepoConfig` import 與 `lark_config` 鍵；`is_lark_configured` 改為固定 `False`（保留鍵、加註 deprecated 註解）
- [x] 1.4 `app/api/teams.py` `update_team()`：移除 `team_update.lark_config` 分支（DB 中既有值因此保持不變——這正是資料相容性的實作點）
- [x] 1.5 `app/api/teams.py`：刪除 `POST /validate`（:185-204）、`POST /validate-table`（:207-240）、`SimpleTableValidationRequest`、`ValidationResponse`、`from app.services.lark_client import LarkClient`（:30）
- [x] 1.6 `app/api/teams.py:31` 的模組級 `from app.config import settings` 在 1.5 之後變成未使用，必須移除（否則 ruff F401 擋 CI）。**同名遮蔽陷阱**：同檔還有 `team_db_to_model()` 內的區域變數 `settings = TeamSettings(...)`（:76、:86）與 `delete_team()` 內的函式級 `from app.config import settings`（:439-441），這兩者**不可**動（redteam F4）
- [x] 1.7 `app/api/mcp.py:326`、`app/api/app_read.py:106`：`is_lark_configured` 改為固定 `False`，加註 deprecated（兩處現行算法本來就不一致，見 design D3；若 0.1 掃描確認無外部依賴，可依 D3 條件升級為直接移除欄位並同步改寫 `mcp-read-api` delta）。**採用凍結而非移除**：0.1 雖確認 skill 無依賴，但外部 MCP client 無法枚舉，維持 D3 的可逆選項

## 2. 後端：空 token 防呆

- [x] 2.1 `app/api/attachments.py` `get_lark_client_for_team()`：`team.wiki_token` 為空時 `raise HTTPException(404, "附件不存在")`，不建立 `LarkClient`、不打外部 API
- [x] 2.2 `app/services/test_result_cleanup_service.py` `_remove_files_from_test_case_sync()`：`team_config.wiki_token` 為空時提前 `return False`，log 等級用 `debug`（避免正常刪除流程產生假警報）

## 3. 前端：team management 頁面

- [x] 3.1 `app/templates/team_management.html`：移除第 120-146 行的「Lark 多維表格設定」整段（Wiki Token 欄位、Test Case Table ID 欄位、`validateLarkBtn`、`larkValidationResult`）
- [x] 3.2 `app/templates/team_management.html:14`：`team.subtitle` 改用 5.2 的定稿字串（含元素內文 fallback）
- [x] 3.3 `app/static/js/team-management/main.js`：移除 `validateLarkConnection()`（:388-441）、`validateLarkBtn` 的 listener（:74），以及 `showValidationMessage()`（:537）——已確認其 4 個呼叫點（:395、:426、:429、:435）全在 `validateLarkConnection()` 內，且函式本體操作的 `#larkValidationResult` 節點隨 3.1 一併刪除，留著會是操作不存在節點的孤兒函式（redteam F12）
- [x] 3.4 `app/static/js/team-management/main.js`：`editTeam` 帶入表單處移除 296-297 行；`saveTeam` 送出 payload 移除 `lark_config`（312-314）與必填檢查（322 只留 `name`）
- [x] 3.5 `app/static/js/team-management/main.js:196-201`：移除卡片上的 `Lark: 已設定/未設定` badge 區塊

## 4. 前端：其他頁面的 Lark 文案

- [x] 4.1 `app/static/js/index.js:140-143`：移除「已連結 Lark 資料源」badge（`team.linked`）
- [x] 4.2 `app/static/js/index.js:91-93`：`team.createFirstTeamHint` 改用 5.2 的定稿字串（含元素內文 fallback）
- [x] 4.3 `app/templates/test_run_management.html:80-83`：`testRun.createFirstConfigHint` 改用 5.2 的定稿字串（含元素內文 fallback）

## 5. i18n

- [x] 5.1 三語系（`en-US.json`／`zh-CN.json`／`zh-TW.json`）刪除孤兒 key：`team.larkSettings`、`team.wikiToken`、`team.wikiTokenHelp`、`team.wikiTokenPlaceholder`、`team.testCaseTableId`、`team.testCaseTableIdHelp`、`team.testCaseTableIdPlaceholder`、`team.validateConnection`、`team.validating`、`team.pleaseEnterToken`、`team.connectionValid`、`team.connectionInvalid`、`team.connectionError`、`team.linked`、`team.configured`、`team.notConfigured`
- [x] 5.2 三語系改寫（保留 key）——定稿字串，避免三語系語氣不一致（redteam F13）：
  - `team.subtitle`：zh-TW「管理各團隊的基本設定與功能入口」／zh-CN「管理各团队的基本设置与功能入口」／en-US「Manage each team's basic settings and entry points」
  - `team.createFirstTeamHint`：zh-TW「建立團隊以開始管理測試案例」／zh-CN「创建团队以开始管理测试用例」／en-US「Create a team to start managing test cases」
  - `testRun.createFirstConfigHint`：zh-TW「建立測試執行以開始追蹤測試結果」／zh-CN「创建测试执行以开始跟踪测试结果」／en-US「Create a test run to start tracking results」
- [x] 5.3 同步改寫 `team_management.html:14`、`index.js:91-93`、`test_run_management.html:80-83` 中 `data-i18n` 元素**內文的中文 fallback**（i18n 尚未載入時會直接顯示這段文字，不改會閃現舊的 Lark 字樣）
- [x] 5.4 `node scripts/check-i18n-coverage.mjs` 通過。注意此 gate 檢查三語系 key 對稱 + 可見字面量 baseline：刪 key 必須三檔同步，且改寫文案時不得引入新的 raw CJK 字面量（會讓 baseline 上升而失敗）（redteam F5）

## 6. 測試

- [x] 6.1 新增 `app/testsuite/test_teams_api.py`（目前完全沒有 team CRUD 測試），涵蓋 design D7 的 6 個案例。兩個前置條件：(a) 需 monkeypatch `permission_service.check_user_role` 回 `True`（或插入真實 admin user 列），只 override `get_current_user` 會 403（redteam F3）；(b) 案例 2 的預期是 **201 + 欄位被忽略**，不是 422（`TeamCreate` 無 `extra="forbid"`，redteam F1）
- [x] 6.2 `uv run pytest app/testsuite/test_teams_api.py -q` 通過
- [x] 6.3 抽樣跑受影響的既有測試確認 fixture 未破：`uv run pytest app/testsuite/test_app_token_read_api.py app/testsuite/test_mcp_api.py -q`（逐檔跑，勿合併跑）。**結果**：`test_app_token_read_api.py` 14 passed、`test_mcp_api.py` 26 passed；另抽樣 4 檔見驗證報告
- [ ] 6.4 `uv run pytest app/testsuite -q` 全套：**未跑**（既有已知問題：多檔合併跑會卡在 async 端點測試）。改為逐檔抽樣，見 6.2／6.3

## 7. 文件與 spec

- [x] 7.1 `docs/mcp_api_interface.md:84`、`docs/app_token_api_reference.md:238`：`is_lark_configured` 標記 deprecated 且永遠為 `false`
- [x] 7.2 `docs/user_manual.md:134`：移除「設定團隊對應的 Lark Wiki Token 與 App ID」敘述
- [x] 7.3 本 change 目錄的 `rollback.md`（已於設計階段完成）：回滾缺口的觸發條件、症狀、備份要求、修復 SQL 與替代做法
- [x] 7.4 `openspec validate remove-team-lark-repo-settings --strict` 通過

## 8. 品質門檻

- [x] 8.1 `uv run ruff check app scripts database_init.py`。**結果**：本次觸碰的 6 個檔案 All checks passed；repo 全域 360 errors 與 HEAD 完全相同（既有債務，非本次新增）
- [x] 8.2 `npm run lint`。**結果**：0 errors / 671 warnings、inline style 253（baseline 259），與 HEAD 相同
- [x] 8.3 `node --check app/static/js/team-management/main.js`、`node --check app/static/js/index.js`
- [x] 8.4 一次性 disposable SQLite DB 實測：建立 team 不帶 Lark 欄位 → 201；`GET /api/teams` 不含 `lark_config` 且 `is_lark_configured` 為 `false`；`/api/teams/validate` 回 404。**legacy team 必須以直接 SQL INSERT／ORM 繞過 API 的方式構造**（帶 ≥10 字 wiki_token 與 `tbl` 開頭的 table id），用新 API 建出來的只會是空字串，等於什麼都沒驗到（redteam F16）。**實作方式**：以 `TestClient` 對一次性 SQLite DB 執行（`test_teams_api.py`，legacy team 以 ORM 直接插入）。**發現**：validate 端點回的是 **405** 而非 404——路徑被同層 `/{team_id}` 涵蓋且該路徑無 POST，spec delta 已改寫為實際行為
- [x] 8.5 若本機 MySQL 8 容器可用，對同一組建立/列出流程再跑一次（驗證空字串寫入 `NOT NULL` 在非 SQLite 引擎同樣成立）；若不可用，須在驗證報告的「待驗證」明確列出，不得默認為已驗證（redteam F10）。**未執行**：本機沒有任何 docker 容器在跑，MySQL 8 驗證列為待驗證
