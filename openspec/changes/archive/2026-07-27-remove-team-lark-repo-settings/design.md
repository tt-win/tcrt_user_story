## Context

`teams` 表的 `wiki_token`（`String(255) NOT NULL`）與 `test_case_table_id`（`String(255) NOT NULL`）建立於初始 schema（`alembic/versions/7a26d2522198_initial_schema.py:59-60`），**沒有 unique index、沒有 server_default**。系統中唯一寫入 `TeamDB` 的位置是 `app/api/teams.py:104` 的 `team_model_to_db()`；唯一讀出並轉為 API 回應的位置是同檔 `team_db_to_model()`（被 4 處呼叫，全部在 `teams.py` 內）。

現行 team token 的消費者盤點（2026-07-27 實際掃描）：

| 消費者 | 狀態 |
|---|---|
| `app/api/teams.py` `/validate`、`/validate-table` | 活著，唯一呼叫者是本次要移除的前端按鈕 |
| `app/api/attachments.py:59` `get_lark_client_for_team` | 活著但僅供 6 支無人呼叫的上傳路由 + 下載代理的「優先級 4」Lark 回退 |
| `app/services/test_result_cleanup_service.py:203` | 活著但僅在 `result_files_uploaded==1` 且 `upload_history_json` 帶 `file_token` 的 legacy 資料上觸發 |
| `app/api/test_runs.py` Lark record CRUD | **已壞**：讀 `config.table_id`，`TestRunConfig` model 無此欄位 → `AttributeError` |
| `app/api/test_run_items.py:486` | 死碼，定義後無呼叫者 |
| `app/services/test_result_file_service.py` | 死碼，全 repo 無 importer |
| `is_lark_configured`（`teams.py:96`、`mcp.py:326`、`app_read.py:106`） | 活著，且已寫入對外文件 |

前端消費者僅 `app/static/js/team-management/main.js`（6 處）與 `app/static/js/index.js`（2 處文案）。測試套件中**沒有任何檔案** POST `/api/teams`、斷言 `lark_config` 或斷言 `is_lark_configured`；49 個測試檔只是直接以 `TeamDB(wiki_token=...)` 建 fixture。

## Goals / Non-Goals

**Goals**
- 使用者建立／編輯 team 時不再需要提供任何 Lark 欄位，頁面上不再出現 Lark Bitable 設定與連線驗證。
- **零 schema 變更、零資料異動**：既有 team 的 token 值保持原樣，回滾成本等於 `git revert`。
- 既有 team 的 legacy Lark 附件下載路徑維持可用。
- 消除 `GET /api/teams` 對 `wiki_token` 的明文外洩。

**Non-Goals**
- 不 drop 欄位、不改 nullability、不寫任何 migration。
- 不移除本次變更之前就已經是死碼／已損壞的 Lark 程式碼（另開 change）。
- 不觸碰組織層 Lark 整合（`lark_org_sync_service`、`lark_department_service`、`lark_user_service`、`lark_notify_service`、`organization_sync`），這些吃全域 `settings.lark.app_id/app_secret`，與 team token 無關。
- 不改變 Test Run 的 Lark 群組通知功能與其 UI 文案（`testRun.notifications.*`）。
- 不處理同類的其他遺留物：`teams.last_sync_at` 在 app 程式碼中沒有任何寫入者（Lark 同步時代遺留）、`Team` 與 `TeamResponse` 兩個 pydantic model 全 repo 無使用者。它們不屬於「team settings 的 Lark 欄位」，一併處理只會擴大 diff（見 redteam F8）。

## Decisions

### D1. 保留 `NOT NULL` 欄位，建立 team 時寫入空字串

`team_model_to_db()` 改為固定寫入 `wiki_token=""`、`test_case_table_id=""`。

- **替代方案 A：改成 nullable 的非破壞性 migration。** 否決：需要跨 SQLite（`batch_alter_table` 重建表）／MySQL 8／PostgreSQL 16 三引擎驗證，回滾需要 downgrade，換來的只是「NULL 比空字串漂亮」的語意差異。既有讀取端一律用 `bool(...)` truthy 判斷，空字串與 NULL 行為一致。
- **替代方案 B：直接 drop 欄位。** 否決：與「保持資料相容」的前提直接衝突，且不可逆。
- **後果**：DB 中會同時存在「舊 team 的真實 token」與「新 team 的空字串」。這是刻意的：空字串即代表「此 team 從未有過 Lark 設定」，與舊 team 的 cold data 可直接區分。

### D2. `lark_config` 必須同時從 API 回應移除，不能只改前端

`team_db_to_model()` 目前用 DB 值重建 `LarkRepoConfig`，而該 model 的 validator 要求 `wiki_token` 至少 10 字、`test_case_table_id` 必須以 `tbl` 開頭（`app/models/team.py:20-30`）。若只移除前端表單而後端仍寫空字串並重建 `LarkRepoConfig`，**第一次 `GET /api/teams` 就會 `ValidationError` 導致整個列表 500**。因此「移除回應中的 `lark_config`」與「建立時寫空字串」必須是同一個 commit 的原子變更，`LarkRepoConfig` class 一併刪除。

### D3. `is_lark_configured` 保留欄位但凍結為 `false`

- **保留欄位**：`docs/mcp_api_interface.md:84` 與 `docs/app_token_api_reference.md:238` 已公開此欄位，外部 MCP client 與 `tcrt-app` skill 可能對 response schema 做嚴格驗證，移除欄位是硬性破壞。
- **凍結為 `false` 而非維持計算值**：功能移除後，沒有任何 team 具備「可用的 Lark 設定」。若舊 team 繼續回傳 `true`，MCP 端的 LLM agent 會據此告訴使用者「此 team 已連結 Lark」，是實質誤導。凍結為 `false` 不動任何資料，屬 soft contract change（欄位在、值變），並在兩份文件標記 deprecated、待後續 change 移除。
- **順帶消除既有不一致**：`app_read.py:106` 目前算的是 `bool(team.wiki_token)`，`mcp.py:326` 算的是 `bool(wiki_token and test_case_table_id)`——同一個欄位在兩個端點的定義本來就不同。凍結為常數後兩者一致；diff 上看起來像「兩個不同的東西被改成同一個常數」，這是刻意的，不是漏改（redteam F6）。
- **驗證缺口**：目前沒有任何測試斷言此欄位（已掃描確認），新測試會補上「三個端點皆回 `false`」。
- **條件升級路徑**：本決策的成立前提是「無法枚舉所有外部 client」。tasks 0.1 會在實作前掃描 `tools/skills/tcrt-app`；若確認無任何依賴，且屆時判斷外部 MCP client 面夠小，可在同一個 change 內把決策升級為「直接移除欄位」，並同步改寫 `mcp-read-api` 的 delta。決策點刻意前置到實作第一步，避免變成無法檢驗的一廂情願（redteam F15）。

### D4. 死碼清理的界線：只清「因本次變更而變成不可達」的程式碼

本次只刪除因為前端 Lark 區塊消失而失去唯一呼叫者的東西：`POST /api/teams/validate`、`POST /api/teams/validate-table`、`SimpleTableValidationRequest`、`ValidationResponse`、`LarkRepoConfig`、`Team.lark_config`、`Team.is_lark_configured()`、`Team.get_lark_url()`、`teams.py` 的 `LarkClient` import。

`test_runs.py` 的 8 支 Lark CRUD、`attachments.py` 的 6 支上傳路由、`test_run_items.py:486` 的死 helper、`test_result_file_service.py` **在本次變更之前就已經無法運作或無人呼叫**，其存廢與 team 設定無關。把它們混進同一個 diff 會讓 review 面積擴大數倍、回歸風險與本次變更混淆。另開 change（暫名 `purge-dead-lark-runtime-code`）處理。

**已知後果（必須明講，否則會誤導 reviewer）**：這些路由在 change 落地後仍掛在 API surface 上。

- 對**新 team**：`attachments.py` 的上傳路由因空 token 落到 D5 的 guard（404）。
- 對**舊 team**：這 6 支上傳路由仍然會真的去打 Lark API——D6 刻意保留了它們的 token。也就是說本 change 並未封閉 Lark 出口，只是移除了 UI 入口與新 team 的設定能力（redteam F9）。
- `test_runs.py` 的 Lark CRUD 對**所有** team 本來就是 500（`AttributeError`），**不構成新的回歸**。

完整封閉留給後續的 `purge-dead-lark-runtime-code` change。

### D5. 空 token 的失敗語意：404 / 提前返回，不是 500

- `attachments.get_lark_client_for_team()`：`team.wiki_token` 為空時直接 `raise HTTPException(404, "附件不存在")`，不建立 `LarkClient`、不打 Lark API。理由：對新 team 而言「這個 Lark 附件不存在」是事實描述；回 500「無法連接到 Lark 服務」會誤導維運以為 Lark 服務掛了。
- `TestResultCleanupService._remove_files_from_test_case_sync()`：`team_config.wiki_token` 為空時直接 `return False` 並以 `debug`（非 `error`）記錄。理由：新 team 根本不會有 Lark 附件需要清理，維持 `error` 等級會在正常刪除流程中製造假警報。清理失敗本來就是 best-effort（呼叫端只用回傳數字），不改變既有錯誤處理契約。

### D6. 既有 team 的 legacy Lark 附件下載維持可用

`attachments.py` 下載代理的優先級 1-3（DB 查路徑／本機 `/attachments` 路徑／本機檔名搜尋）不動，優先級 4 的 Lark 回退也**保留**——舊 team 的 token 還在 DB 裡，這條路徑對它們仍然可用。這是「不刪資料」的實質意義：不只保住 bytes，也保住這些 bytes 仍能被用到。若未來要真正 drop 欄位，該 change 必須先確認 DB 中不存在帶 Lark `file_token` 的 `execution_results_json` / `upload_history_json`。

### D7. 補上目前缺席的 team CRUD 契約測試

`app/testsuite/` 目前**沒有任何** team CRUD API 測試。新增 `app/testsuite/test_teams_api.py`，比照 `test_pins_api.py` 的 harness（`db_test_helpers.create_managed_test_database` + `install_main_database_overrides` + `dependency_overrides[get_current_user]`），涵蓋：

1. `POST /api/teams` 不帶 `lark_config` → 201，且 DB 中該列 `wiki_token == ""`。
2. `POST /api/teams` 額外帶 `lark_config` → **201 且該欄位被忽略**，DB 中 `wiki_token` 仍為 `""`。（`TeamCreate` 沒有 `extra="forbid"`，Pydantic 2 預設 `ignore`；本次刻意不收緊契約，見 redteam F1。此案例證明「即使舊 client 還在送，也不會被偷偷寫回 DB」。）
3. `GET /api/teams` 回應不含 `lark_config` 鍵、`is_lark_configured is False`。
4. **資料相容性**：預先以 ORM／SQL 直接插入帶真實格式 token 的 legacy team（**不可**透過新 API 建立，否則只會拿到空字串而驗不到東西），`GET /api/teams` 不噴 `ValidationError` 且該 team 可正常列出。
5. **資料相容性回歸網**：對 legacy team `PUT` 只改 `name`，DB 中的 `wiki_token` 值不變。註記：移除 `TeamUpdate.lark_config` 後根本沒有程式碼路徑會寫這兩個欄位，所以此案例是**回歸網而非防護機制**——它能擋住未來有人把寫入加回來，但不代表資料層有保護（redteam F11）。
6. `POST /api/teams/validate`、`/validate-table` → 404（端點確實移除）。

**測試前置條件（易踩雷）**：`POST`／`PUT`／`DELETE /api/teams` 走 `require_admin()` → `require_role()` → `permission_service.check_user_role(current_user.id, ...)`，是**用 user id 查 DB**，不看注入物件的 `role` 屬性。只 override `get_current_user`（`test_pins_api.py` 的作法，因為它打的是非 admin-only 端點）會拿到 403。需 monkeypatch `app.auth.permission_service.permission_service.check_user_role` 回 `True`，或在測試 DB 插入對應的 admin user 列（redteam F3）。

### D8. i18n：移除孤兒 key，不留空殼

`team.larkSettings`／`wikiToken`／`wikiTokenHelp`／`wikiTokenPlaceholder`／`testCaseTableId`／`testCaseTableIdHelp`／`testCaseTableIdPlaceholder`／`validateConnection`／`validating`／`pleaseEnterToken`／`connectionValid`／`connectionInvalid`／`connectionError`／`linked` 在移除後全數變成孤兒，三語系一併刪除（比照 `move-assistant-admin-into-organization-tab` 對 `menuEntry` 的處理）。`team.configured`／`team.notConfigured` 隨卡片 badge 一起移除。`team.subtitle`／`team.createFirstTeamHint`／`testRun.createFirstConfigHint` 保留 key、改寫文案（去除 Lark 字樣）。

## Risks / Trade-offs

| 風險 | 等級 | 處置 |
|---|---|---|
| 只改前端未改後端 → `GET /api/teams` 全面 500 | 高（若拆錯 commit） | D2：原子變更，且 D7 測試 3/4 直接覆蓋 |
| 外部 client 依賴 `is_lark_configured == true` 分支 | 中 | D3：欄位保留、值凍結；文件標 deprecated。**待確認**：`tcrt-app` skill（gitignored）是否讀取此欄位 |
| 新 team 空 token 流入 legacy Lark 路徑 → 500 | 中 | D5 guard + D7 測試 |
| DB 殘留未使用的 token（半機密資料） | 低 | 淨改善：移除後 API 不再回傳 `wiki_token`，暴露面比現況小；真正刪除另開 change |
| 空字串與 NULL 語意混雜 | 低 | 所有讀取端皆為 truthy 判斷；D1 已記錄理由 |
| 既有 49 個測試檔 fixture 破損 | 極低 | 欄位保留，`TeamDB(wiki_token=...)` 仍合法 |

## Migration Plan

無 DB migration。部署即生效，無停機需求、無資料前置作業。

**回滾**：`git revert` 該 commit 即可還原前端表單、API 欄位與 validate 端點，DB 不需要任何動作——舊 team 的 token 從未被修改。但有一個必須明講的缺口：

> ⚠️ **回滾缺口（嚴重度高於直覺）**：`get_teams()`（`app/api/teams.py:146`）以 list comprehension 對**所有** team 呼叫 `team_db_to_model()`。revert 之後 `LarkRepoConfig` validator 回來，只要 DB 中存在**任何一筆**空字串 token 的 team（即本次上線後新建的 team），整個 `GET /api/teams` 就會 500——不是那一筆消失，而是**所有人都看不到任何 team**，`/team-management` 與首頁同時失效（redteam F2）。
>
> 觸發條件：上線後建立過新 team **且**需要回滾。處置為必要交付物 `rollback.md`（tasks 7.3），內含可直接執行的修復 SQL（把空字串補成通過 validator 的 placeholder）。
>
> **不採用「一開始就寫 placeholder 而非空字串」的替代方案**：那會讓 cold data 無法與真實歷史值區分，且 revert 後 `is_lark_configured` 會錯誤地回報 `true`。用一份 rollback 手冊換取資料語意的乾淨，是划算的。

## Open Questions

1. `tools/skills/tcrt-app`（gitignored）與外部 MCP client 是否讀取 `is_lark_configured`？→ 實作前以 `rg` 掃一次 skill 目錄確認；若有依賴 `true` 分支，需在該 skill 同步調整。
2. 生產 DB 是否仍存在帶 Lark `file_token` 的 `execution_results_json` / `upload_history_json`？→ 本 change 不需要答案（D6 保留回退路徑），但**後續 drop 欄位的 change 必須先回答**。
