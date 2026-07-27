## Context

`remove-team-lark-repo-settings`（已實作，commit `6e9b5df`）把 team settings 的 Lark 欄位移除，但保留 DB 欄位與既有值，並明確把「變更前就已死的後端程式碼」留給本 change。

2026-07-27 重新掃描的事實：

| 目標 | 狀態 | 證據 |
|---|---|---|
| `test_runs.py` 8 支 Lark record 路由 | **壞的**（非死的） | 全部呼叫 `config.table_id`，`TestRunConfig` model 無此欄位 → `AttributeError` |
| `test_runs.py` `generate-html` / `report` | **活的**，不碰 Lark | `test-run-execution/reports.js:53` 使用 |
| `attachments.py` 6 支 Lark 寫入路由 | **死的** | 前端與測試皆無呼叫者；測試案例附件走 `test_cases.py` 本機路徑 |
| `attachments.py` 下載代理 | **活的**，Lark 只是最後回退 | 前端 3 處使用；`async-runtime-performance` spec + `test_attachment_proxy_contract.py` 鎖定行為 |
| `test_run_items.py:486` helper | **死的** | 定義後無呼叫者 |
| `test_result_file_service.py` | **死的** | 全 repo 零 importer |
| `models/test_run.py`（436 行） | **將死** | 唯一 importer 是 `test_runs.py` 的 8 支路由 |
| `TestResultCleanupService` Lark 分支 | **活的**（僅 legacy 資料） | 被 4 個 API 的刪除流程呼叫 |

## Goals / Non-Goals

**Goals**
- 移除所有「壞掉或無人呼叫」的 Lark 後端程式碼，讓剩下的 Lark 出站路徑少到可以一眼盤點。
- 把剩餘邊界寫成正式 spec，避免日後回頭長回來。
- 零行為變更：對任何**目前可用**的功能不產生影響。

**Non-Goals**
- 不關閉附件下載代理的 Lark 回退，也不動 `TestResultCleanupService` 的 Lark 分支（見 D3）。
- 不動組織層 Lark 整合（部門／使用者同步、Test Run 群組通知）。
- 不碰 `teams.wiki_token` / `test_case_table_id` 欄位與其資料。
- 不重構保留下來的報告端點。

## Decisions

### D1. `test_runs.py` 保留檔案、只留報告端點，而非整檔刪除

該檔案的 `generate-html`／`report` 是前端唯一在用的部分，且它們與 Lark 無關。與其把兩支端點搬到別的檔案（會動到前端 URL 或 router 組裝），不如原地保留、刪掉其餘。移除後該檔約從 1080 行縮到 130 行左右，`prefix="/teams/{team_id}/test-runs"` 與前端 URL 完全不變。

檔案 docstring 目前寫「直接操作 Lark 多維表格」，必須同步改寫，否則會誤導下一位讀者。

### D2. 連 `app/models/test_run.py` 一起刪

它是 Lark record 的欄位映射模型（`TestRunFieldMapping`、`from_lark_record`、`to_lark_fields`），唯一 importer 就是本次要刪的路由。留著會變成「沒有任何程式碼路徑會建構的 model」，且它的存在會讓人以為 test run 還有 Lark 表示法。已確認 `TestRunFieldMapping` / `TestRunFilter` 全 repo 無其他使用者。

注意：**不要**與 `app/models/test_run_config.py`、`test_run_set.py`、`test_run_item*` 混淆——那些是現行主線模型，被多處使用。

### D3. 保留下載代理的 Lark 回退與 cleanup service 的 Lark 分支

`remove-team-lark-repo-settings` 的 proposal 說後續 change 會「一併封閉舊 team 的 Lark 出口」。本 change **刻意不做這件事**，理由：

1. 這兩條路徑服務的是**既有資料**，不是死碼。移除它們是行為變更，不是清理。
2. 下載代理的錯誤映射被 `async-runtime-performance` spec 明文規定並有測試鎖定，關閉它需要同步改寫該 spec。
3. 判斷能不能關的前置條件是「生產 DB 中還有沒有 Lark 來源的附件」——這個問題本 change 無法回答，也不該用猜的。

因此把「封閉出口」與「清死碼」拆開：本 change 只做後者，並在新 capability 中明確記錄前者的前置條件。這比為了兌現一句話而在沒有證據的情況下砍掉使用者可能還需要的路徑要好。

### D4. 新增 capability `lark-runtime-boundary` 而非塞進既有 spec

被移除的端點沒有任何現行 spec 涵蓋（已掃描 `openspec/specs/` 確認），因此本次的契約無處可歸。`generated-report-storage` 講的是報告儲存、`test-run-management-ui` 講的是 UI，硬塞都不對。

新 capability 的價值是durable 的：它回答「這個系統還剩哪些 Lark 出站路徑」，這是一個會被反覆問到、且需要防止回歸的架構事實。未來若關閉剩餘出口，改的也是同一份 spec。

### D5. 驗證策略：以「沒有東西壞掉」為主

本次沒有新增行為，因此不新增功能測試。驗證重點是：

1. `test_attachment_proxy_contract.py` 仍通過（保留下來的下載代理未被誤傷）。
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
| 未兌現前一個 change 的「封閉出口」說法 | 低 | D3 明確記錄拆分理由與前置條件，不是默默跳過 |
