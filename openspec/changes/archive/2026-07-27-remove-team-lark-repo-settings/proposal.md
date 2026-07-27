## Why

`/team-management` 目前仍要求每個 team 填寫 Lark Bitable 的 `wiki_token` 與 `test_case_table_id`（兩者皆為必填，DB 欄位為 `NOT NULL`），並提供「驗證 Lark 連線」按鈕。但自 `remove-lark-test-case-sync`（2026-03-12 已封存）之後，test case 與 test run 資料已全數落在本地 DB，這兩個欄位在現行系統中沒有任何仍可運作的消費者：

- `app/api/test_runs.py` 的 8 支 Lark record CRUD 路由讀取 `config.table_id`，但 `TestRunConfig` model 早已沒有該欄位，呼叫必定 `AttributeError`（已是壞掉的死碼）。
- `app/api/attachments.py` 的 6 支 Lark 上傳／附加／刪除路由沒有任何前端或測試呼叫者；測試案例附件已改走 `app/api/test_cases.py` 的本機 `attachments/test-cases/...`。
- `app/api/test_run_items.py` 的 `_get_lark_client_for_team` 定義後從未被呼叫。

換句話說，這兩個欄位現在唯一的實際作用是**強迫使用者在建立 team 時輸入兩個沒有用途的 token**，並且 `GET /api/teams` 會把 `wiki_token` 明文回傳給任何看得到該 team 的使用者。

## What Changes

- **移除 team 設定中的 Lark Bitable 欄位**：`/team-management` 的「Lark 多維表格設定」區塊（Wiki Token、Test Case Table ID、驗證 Lark 連線按鈕）整段移除；建立／編輯 team 只需 team 名稱、描述、JIRA 設定與預設優先級。
- **移除 API 上的 Lark 欄位與驗證端點**：`TeamCreate` / `TeamUpdate` 不再接受 `lark_config`；`GET /api/teams` 回應不再包含 `lark_config`（同時消除 `wiki_token` 明文外洩）；刪除 `POST /api/teams/validate`、`POST /api/teams/validate-table`。
- **不動資料庫**：`teams.wiki_token` / `teams.test_case_table_id` 兩個 `NOT NULL` 欄位**保留原樣，無 migration**；既有 team 的值原封不動保存，新建立的 team 由後端寫入空字串。回滾等同 `git revert`，不涉及任何資料操作。
- **`is_lark_configured` 保留於回應但凍結為 `false`**：`/api/teams`、`/api/mcp/teams`、`/api/app/teams` 三處欄位仍存在（避免破壞外部 client 的 schema 驗證），但一律回傳 `false` 並標記為 deprecated，因為移除後系統已無任何 team 具備「可用的 Lark 設定」。
- **空 token 防呆**：`app/api/attachments.py` 的 Lark 下載回退路徑在 team token 為空時 SHALL 回 404 而非 500；`TestResultCleanupService` 的 Lark 分支同樣提前返回。既有 team 的 token 仍在，其舊 Lark 附件下載路徑**維持可用**——換句話說本次移除的是 UI 入口與新 team 的設定能力，並未封閉後端既有的 Lark 出口（完整封閉見下方後續 change）。
- **首頁與 Test Run 空狀態文案去除 Lark 字樣**：`app/static/js/index.js` 的「已連結 Lark 資料源」標示與「建立團隊並設定 Lark 資料來源」提示、`test_run_management.html` 的 `testRun.createFirstConfigHint`。

**明確不在本次範圍**（見 design D4；後續由 `purge-dead-lark-runtime-code` change 承接，屆時對舊 team 的 Lark 出口一併封閉）：`app/api/test_runs.py` 的 Lark record CRUD、`app/api/attachments.py` 的 6 支 Lark 上傳路由、`app/api/test_run_items.py` 死 helper、`app/services/test_result_file_service.py` 等**在本次變更之前就已經是死碼**的部分，另開 change 清理。組織層 Lark 整合（部門／使用者同步、Test Run 群組通知）使用全域 `settings.lark.app_id/app_secret`，與 team token 無關，完全不受影響。

## Capabilities

### Modified Capabilities
- `team-management-console`: team CRUD 的範圍描述移除 Lark Bitable 連結欄位與連線驗證；team 建立／編輯僅保留名稱、描述、JIRA 設定與預設優先級。
- `mcp-read-api`: `/api/mcp/teams` 與 `/api/app/teams` 的 team read model 中，`is_lark_configured` 欄位保留但凍結為 `false` 並標記 deprecated。

## Impact

- **後端**：`app/models/team.py`（移除 `LarkRepoConfig`、`Team.lark_config`、`is_lark_configured()`、`get_lark_url()`）、`app/api/teams.py`（`team_model_to_db`／`team_db_to_model`／刪除兩支 validate 端點與相關 request/response model）、`app/api/app_read.py`、`app/api/mcp.py`、`app/api/attachments.py`（空 token guard）、`app/services/test_result_cleanup_service.py`（空 token guard）。
- **前端**：`app/templates/team_management.html`、`app/static/js/team-management/main.js`、`app/static/js/index.js`、`app/templates/test_run_management.html`。
- **i18n**：三語系移除 `team.larkSettings`／`wikiToken*`／`testCaseTableId*`／`validateConnection`／`validating`／`pleaseEnterToken`／`connectionValid`／`connectionInvalid`／`connectionError`／`linked`，並改寫 `team.subtitle`／`team.createFirstTeamHint`／`testRun.createFirstConfigHint`。
- **資料庫**：**無 schema 變更、無 migration**。既有欄位值保留為 cold data。
- **測試**：既有 49 個測試檔的 `TeamDB(wiki_token=...)` fixture 不受影響（欄位仍在）；新增 `app/testsuite/test_teams_api.py` 補上目前完全缺席的 team CRUD 契約測試，含「legacy team 帶 token 仍可列出」「PUT 不會清空既有 token」兩條資料相容性回歸。
- **文件**：`docs/mcp_api_interface.md`、`docs/app_token_api_reference.md`（`is_lark_configured` 標 deprecated）、`docs/user_manual.md:134`。
