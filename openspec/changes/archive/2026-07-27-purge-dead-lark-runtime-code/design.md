## Context

`remove-team-lark-repo-settings`（已實作，commit `6e9b5df`）把 team settings 的 Lark 欄位移除，但保留 DB 欄位與既有值，並明確把「變更前就已死的後端程式碼」留給本 change。

2026-07-27 重新掃描的事實：

| 目標 | 狀態 | 證據 |
|---|---|---|
| `test_runs.py` 8 支 Lark record 路由 | **壞的**（非死的） | 全部呼叫 `config.table_id`，`TestRunConfig` model 無此欄位 → `AttributeError` |
| `test_runs.py` `generate-html` / `report` | **活的**，不碰 Lark | `test-run-execution/reports.js:53` 使用 |
| `attachments.py` 6 支 Lark 寫入路由 | **死的** | 前端與測試皆無呼叫者；測試案例附件走 `test_cases.py` 本機路徑 |
| `attachments.py` 下載代理 | **活的**；Lark 回退經資料掃描後確認無資料可服務 → 移除，本機路徑保留 | 前端 3 處使用；掃描結果見 D3 |
| `test_run_items.py:486` helper | **死的** | 定義後無呼叫者 |
| `test_result_file_service.py` | **死的** | 全 repo 零 importer |
| `models/test_run.py`（436 行） | **將死** | 唯一 importer 是 `test_runs.py` 的 8 支路由 |
| `TestResultCleanupService` | 看似活的，實為不可執行 | 6 個呼叫點；但其 Lark 分支因 JSON 結構不符（list vs dict）必拋例外，且掃描確認無 `file_token` 資料 → 整個服務移除 |

## Goals / Non-Goals

**Goals**
- 移除所有「壞掉或無人呼叫」的 Lark 後端程式碼，讓剩下的 Lark 出站路徑少到可以一眼盤點。
- 把剩餘邊界寫成正式 spec，避免日後回頭長回來。
- 零行為變更：對任何**目前可用**的功能不產生影響（下載代理的 Lark 回退在確認生產資料後才納入移除，見 D3）。

**Non-Goals**
- 不動組織層 Lark 整合（部門／使用者同步、Test Run 群組通知、Lark 使用者查詢），它們使用全域 app 憑證。
- 不碰 `teams.wiki_token` / `test_case_table_id` 欄位與其資料。
- 不重構保留下來的報告端點。

## Decisions

### D1. `test_runs.py` 保留檔案、只留報告端點，而非整檔刪除

該檔案的 `generate-html`／`report` 是前端唯一在用的部分，且它們與 Lark 無關。與其把兩支端點搬到別的檔案（會動到前端 URL 或 router 組裝），不如原地保留、刪掉其餘。移除後該檔約從 1080 行縮到 130 行左右，`prefix="/teams/{team_id}/test-runs"` 與前端 URL 完全不變。

檔案 docstring 目前寫「直接操作 Lark 多維表格」，必須同步改寫，否則會誤導下一位讀者。

### D2. 連 `app/models/test_run.py` 一起刪

它是 Lark record 的欄位映射模型（`TestRunFieldMapping`、`from_lark_record`、`to_lark_fields`），唯一 importer 就是本次要刪的路由。留著會變成「沒有任何程式碼路徑會建構的 model」，且它的存在會讓人以為 test run 還有 Lark 表示法。已確認 `TestRunFieldMapping` / `TestRunFilter` 全 repo 無其他使用者。

注意：**不要**與 `app/models/test_run_config.py`、`test_run_set.py`、`test_run_item*` 混淆——那些是現行主線模型，被多處使用。

### D3. 先排除、取得資料證據後納入：關閉最後兩條 Lark 出站路徑

本 change 原本**刻意排除**下載代理的 Lark 回退與 cleanup service 的 Lark 分支，理由是它們服務既有資料、有 spec 與測試保護，而「能不能關」取決於一個當時無法回答的問題：生產 DB 裡還有沒有 Lark 來源的附件。

2026-07-27 對生產 DB（MySQL 8 `tcrt_main`）執行唯讀掃描後取得證據，因此納入本 change：

| 掃描項目 | 結果 |
|---|---|
| teams 總數 / 仍帶非空 `wiki_token` | 13 / 13（全部是 legacy team，尚無新建 team） |
| `test_run_items` 總數 | 36,082 |
| `upload_history_json` 帶 `file_token` | **0** |
| `execution_results_json` 帶精確 Lark 標記（`file_token` / `larksuite` / `feishu`） | **0** |
| `test_cases.attachments_json` 帶精確 Lark 標記 | 2 |

兩點關鍵判讀：

1. **模糊比對的 2 筆是假陽性**。以 `lark` 當關鍵字時 `execution_results_json` 命中 2 筆，逐筆檢視後是檔名為 `Lark20260424-164715.mp4`（Lark app 錄影檔）的**本機**檔案，metadata 帶 `relative_path`，與 Lark Drive 無關。改用精確標記後命中 0。
2. **那 2 筆 test case 的 Lark 附件不經過本系統代理**。`test-case-management/attachments.js:220-222` 對帶 `url` 的附件直接輸出 `<a href>` 指向 `open.larksuite.com`，從不呼叫下載代理；下載代理只被 `test-run-execution` 的 3 處呼叫，而 test run 側的 Lark 命中為 0。因此移除代理的 Lark 回退不會讓任何目前可取得的附件變成不可取得。

另外掃描過程順帶發現 cleanup service 的 Lark 分支**本來就無法執行**：它做 `json.loads(upload_history_json).get('uploads', [])`，但實際資料是 list（`[{"uploaded": 1, "at": ..., "files": [...]}]`），`.get` 會拋 `AttributeError` 被外層 except 吞掉。也就是說每次刪除帶附件的 item 都在 log 裡留下一筆假錯誤。

**連帶決定：刪除整個 `TestResultCleanupService`**。移除 Lark 分支後它沒有剩下任何工作——該服務從頭到尾都沒有本機檔案清理邏輯（本機檔案由 `delete_test_run_config_cascade_sync` 與 team 刪除流程處理）。6 個呼叫點的回傳值只用於 log，未進入任何 API 回應（已確認前端不讀 `cleaned_files_count`），因此移除不改變任何對外契約。

**spec 連帶影響**：`async-runtime-performance` 的「附件下載代理以 async 串流轉發且保留既有行為契約」requirement 規範對象消失 → REMOVED；`core-runtime-performance` 的事件迴圈 requirement 改為只涵蓋組織層 Lark 呼叫 → MODIFIED。`app/testsuite/test_attachment_proxy_contract.py` 測的是被移除的 Lark 代理路徑，隨之刪除。

### D4. 新增 capability `lark-runtime-boundary` 而非塞進既有 spec

被移除的端點沒有任何現行 spec 涵蓋（已掃描 `openspec/specs/` 確認），因此本次的契約無處可歸。`generated-report-storage` 講的是報告儲存、`test-run-management-ui` 講的是 UI，硬塞都不對。

新 capability 的價值是durable 的：它回答「這個系統還剩哪些 Lark 出站路徑」，這是一個會被反覆問到、且需要防止回歸的架構事實。未來若關閉剩餘出口，改的也是同一份 spec。

### D5. 驗證策略：以「沒有東西壞掉」為主

本次沒有新增行為，因此不新增功能測試。驗證重點是：

1. 下載代理的本機三條路徑仍可運作；其 Lark 專屬契約測試 `test_attachment_proxy_contract.py` 隨代理路徑一併刪除（測試對象已不存在）。
2. app 能正常 import 與掛載 router（刪除模組後沒有殘留 import）。
3. `generate-html` 端點仍存在於 route table。
4. ruff 無新增錯誤（刪檔後最容易留下未使用 import）。

## Risks / Trade-offs

| 風險 | 等級 | 處置 |
|---|---|---|
| 誤刪仍在使用的報告端點 | 中 | D1 明確界線 + 驗證步驟 3 檢查 route table |
| 刪 `models/test_run.py` 後有隱藏 importer | 低 | 已用精確 grep 確認唯一 importer；刪除後以 app import 驗證 |
| 殘留未使用 import 擋 ruff | 低 | 驗證步驟 4 |
| 外部 client 正在呼叫被刪的端點 | 極低 | test_runs 那 8 支對所有 team 本來就 500；attachments 那 6 支無呼叫者。**但這是 breaking change 的形式**，故寫進 spec 讓紀錄留下 |
| 移除下載代理 Lark 回退後，某些舊附件變成取不到 | 低 | D3 的唯讀掃描：test run 側精確 Lark 標記命中 0；test case 側的 2 筆由前端直連 Lark，不經代理 |
| 刪除 `TestResultCleanupService` 讓本機檔案沒人清 | 極低 | 該服務從來就沒有本機清理邏輯；本機檔案由 config cascade 刪除與 team 刪除流程處理 |
