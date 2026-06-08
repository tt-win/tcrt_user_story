## Context

`TestRunSet` 已經是 automation execution 的唯一互動入口，但目前 implementation 只完成了最薄的一層：後端可儲存 `automation_suite_ids`、detail API 可回傳 suite ids、`Run as Automation` 可呼叫 trigger API。真正讓使用者完成工作流所需的 suite membership UX 仍缺一大段，包括 create/edit modal 沒有 suite picker、detail 頁只顯示 `Suite #id`、觸發前無法確認 suite summary、觸發後也缺少立即可理解的 refresh 與 recent-runs 對應。

這個 change 的目標不是再建立另一套 execution model，而是把 `test-run-management-ui` 主規格中已接受的 automation suite integration 補到可用。現有資料欄位 `test_run_sets.automation_suite_ids_json` 與後端 trigger flow 已足夠支撐第一階段 UX 補齊，因此本 change 應優先避免再引入新的 schema 或 join table。

## Goals / Non-Goals

**Goals:**
- 讓使用者可直接在 Test Run Set create/edit flow 中管理 automation suite membership。
- 讓 Test Run Set detail 頁顯示可讀的 automation suite summary，而不是只有 ids。
- 讓 `Run as Automation` 在觸發前後都有足夠的 suite-level feedback 與 refresh。
- 讓 Test Run Set detail response 可選擇性攜帶 suite summaries，減少前端為顯示名稱與摘要而自行拼接查詢。

**Non-Goals:**
- 不把 manual `TestRunConfig` 與 automation suite 混成同一資料模型。
- 不新增 `test_run_set_suites` join table，也不對 `automation_suite_ids_json` 做 schema migration。
- 不在本 change 內處理 case-level `covered by suites` 聚合顯示。
- 不重新設計 Automation Hub 的 suite detail 頁整體版面；僅在 Test Run Set flow 所需範圍內補必要互通資訊。

## Decisions

### 1. 延續 `automation_suite_ids_json`，不新增 join table

`TestRunSet` 已有 `automation_suite_ids_json`，且 create / update / detail / trigger API 都已圍繞這個欄位運作。此 change 僅補 UX 與 response summary，不需要 per-membership metadata、排序規則或跨表查詢能力，因此維持 JSON array 是最小且足夠的做法。

替代方案是引入 normalized join table，把 suite membership 做成像 `TestRunSetMembership` 那樣的實體。這會改善未來可擴充性，但目前會帶來 migration、bootstrap、API 與測試成本，而現階段沒有對應的功能需求，因此不採用。

### 2. 由 Test Run Set detail API 回傳 `automation_suites` summary

目前 detail 只回 `automation_suite_ids`，前端只能顯示 `Suite #id`。本 change 應在 `TestRunSetDetail` response 補一個 summary 陣列，例如 `{id, name, ci_job_name, ref_branch, script_count}`，讓 detail 區塊、confirm modal、trigger success feedback 都可共用同一份資料。

替代方案是前端拿到 ids 後再額外呼叫 suite list/detail API 做 join。這會增加畫面初始化的 request 數量，也讓 modal、detail、toast 各自維護 mapping，容易出現顯示不同步，因此不採用。

### 3. create/edit modal 直接整合 suite picker，而不是額外開獨立管理流程

`TestRunSet` 的 suite membership 屬於 set 本身的一部分，最自然的位置就是 create/edit modal。使用者在命名 set、填描述、整理 TP tickets 的同時，也應能一次完成 suite 選擇。實作上可在 modal 內加入 suite list / search / checkbox 選取區，提交時直接帶 `automation_suite_ids`。

替代方案是把 membership 管理只放在 detail 頁的「Add Suite / Remove」流程。這會讓新建 set 與編輯 set 的心智模型分裂，也無法解決目前 create/edit 會被迫只「保留既有值」的半成品狀態，因此不採用作為第一入口。detail 頁仍可保留 quick manage 能力，但資料來源與行為必須與 modal 對齊。

### 4. `Run as Automation` 保持既有 trigger API，前端只補 summary 與 refresh

後端 `POST /test-run-sets/{id}/run-automation` 與 `TestRunSetAutomationService.trigger_automation_suites()` 已具備正確的 ownership 與 guardrails。本 change 不改 trigger ownership，只在前端補：

- 以 suite summary 組成確認訊息
- 成功後 refresh detail 與 recent-runs 區塊
- 將 success state 與 newly queued runs 連回目前 set context

替代方案是改 API response shape，直接回一組 enriched run objects。這是可選優化，但不是第一階段必要條件；若現有 `triggered_suite_ids` + `run_ids` 搭配 detail refresh 已足夠，就先避免 API 擴張。

## Risks / Trade-offs

- [Modal 變複雜] → 以現有 `set-modal.js` 為基礎擴充，避免再開第二套 membership modal；若列表過長，可先加 search/filter，不先做分頁。
- [Suite summary 與實際 DB 狀態不同步] → detail response 每次由後端即時計算 summary；若某 suite 已被刪除，response 應保留錯誤可見性而不是靜默略過。
- [前端同時維護 ids 與 summary 容易漂移] → 以 `automation_suites` 作為顯示來源，以 `automation_suite_ids` 作為提交來源；所有畫面切換都由同一個 in-memory state 驅動。
- [Recent runs refresh 不即時] → 成功 trigger 後至少 refresh current set detail；若未來需要更即時，可再加 polling，但本 change 先不引入新的 background polling。
- [Hub 與 Test Run Management 導航閉環只做一半] → 本 change 先保證 Test Run Set 是主要操作入口；Automation Hub 反向 linked sets 若實作成本超出範圍，可退為後續 follow-up，而不阻塞核心 picker / trigger UX。
