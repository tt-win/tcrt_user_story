# TCRT App Token API — AI Agent 使用指南

Client 介面、token 設定與 transport 選擇見 [SKILL.md](../SKILL.md)；完整 endpoint 與
scope 表見 [api-reference.md](api-reference.md)。本指南只放工作流。開始前先跑
`sh scripts/tcrt_api.sh check` 驗證設定。在 Windows PowerShell prompt 中把範例的
`sh scripts/tcrt_api.sh` 換成
`powershell -ExecutionPolicy Bypass -File scripts/tcrt_api.ps1`。單引號 JSON 不可直接複製到 `cmd.exe`。

## 0. 任務索引（先查這裡，再跳對應章節）

| 你要做的事 | 章節 | 核心呼叫 |
| --- | --- | --- |
| 回報一輪測試結果（最常見） | §1 | create config → add items → batch-update-results → `/status` |
| 計算 team / set 的案例數 | §2 | `GET test-cases` 的 `sets[]` 與 `page.total` |
| 讀取 run item 執行快照 | §3 | `GET .../items`（分頁） |
| 建立 Test Case Set 並放入多筆案例 | §4 | create Set → roots → batch create/guarded move → verify |
| 建 test run 並批次掛入／搬移／移出 Test Run Set | §5 | `include_archived=true`、`/members`、`/members/batch-move` |
| 推進 run 狀態、上傳結果檔 | §5 | `PUT .../status`、`upload-results` |
| Test Case 批次建立／複製／跨 Set 或 Section 搬移 | §6 | `batch`、`bulk-clone`、preview → guarded move |
| Test Run Item 批次建立／指派／結果回報 | §1、§3 | `POST .../items`、`batch-update-results` |
| 歸檔或永久刪除 | §7 | `/status archived`、`/archive`；`DELETE` 僅限明確要求 |
| 401/403/timeout 處理 | §8 | |

通則：**多筆同類操作使用對應批次端點，不要迴圈打單筆 API**。Guarded Test Case move 與 Test Run membership batch move 是 all-or-nothing；其他舊 batch operations 才可能逐項回報錯誤。

## 1. 最常見工作流：回報一輪測試結果

```sh
# 1) 建立 test run（掛進 set 5、限定案例範圍），記下回應的 id
sh scripts/tcrt_api.sh POST /api/app/teams/1/test-run-configs \
  --data '{"name":"Sprint 12 regression","set_id":5,"test_case_set_ids":[3]}'

# 2) 批次加入要執行的案例（重複的自動 skip；scope 外逐項報錯）
sh scripts/tcrt_api.sh POST /api/app/teams/1/test-run-configs/12/items \
  --data '{"items":[{"test_case_number":"TC-1001"},{"test_case_number":"TC-1002"}]}'

# 3) 推進到 active（狀態機 + 自動設 start_date）
sh scripts/tcrt_api.sh PUT /api/app/teams/1/test-run-configs/12/status \
  --data '{"status":"active"}'

# 4) 讀 snapshot 拿 item id（分頁：skip=100、200… 直到 page.has_next=false）
sh scripts/tcrt_api.sh GET /api/app/teams/1/test-run-configs/12/items --query 'limit=100'

# 5) 一次批次回報全部結果（需要 test_run:execute）
sh scripts/tcrt_api.sh POST /api/app/teams/1/test-run-configs/12/items/batch-update-results \
  --data '{"updates":[{"id":42,"test_result":"Passed"},{"id":43,"test_result":"Failed","comment":"flaky env"}]}'

# 6)（可選）為失敗案例上傳證據檔
sh scripts/tcrt_api.sh POST /api/app/teams/1/test-run-configs/12/items/43/upload-results \
  --file files=@./failure.png --file files=@./run.log

# 7) 完成：active → completed（自動設 end_date、重算所屬 set 狀態）
sh scripts/tcrt_api.sh PUT /api/app/teams/1/test-run-configs/12/status \
  --data '{"status":"completed"}'

# 8)（可選）產出 set 的 HTML 報表
sh scripts/tcrt_api.sh POST /api/app/teams/1/test-run-sets/5/generate-report
```

既有 run 只需從步驟 4 開始。批次結果回報前，先取得使用者對目標 config 的明確授權；
任一步 timeout 或 5xx 時重新讀 snapshot，只對尚未是目標結果的 items 續傳，不要盲目重送。

## 2. 計算 Test Case 總數與 Set 總數

未帶 filter 的 `page.total` 是 team 的 Test Case 總數；回應內每個 `sets[]` item 的
`test_case_count` 是該 set 的 team-wide 總數，空 set 會是 `0`。若只要某個 set 的
case-list 總數，使用 `set_id` query 並讀取 `page.total`：

```sh
# Team total：讀取 response.page.total
sh scripts/tcrt_api.sh GET /api/app/teams/1/test-cases --query 'limit=1'

# 一個 Test Case Set 的 filtered total：讀取 response.page.total
sh scripts/tcrt_api.sh GET /api/app/teams/1/test-cases --query 'set_id=3&limit=1'
```

`sets[].test_case_count` 不會因 `set_id`、search、priority 或 test result filter 改變；
這些 filter 只影響 `test_cases[]` 與 `page.total`。

## 3. 讀取 Test Run Item 執行快照

```sh
# 分頁讀取；只回 id、test_case_number、test_result、executed_at、execution_duration、assignee_name
sh scripts/tcrt_api.sh GET /api/app/teams/1/test-run-configs/5/items --query 'limit=100'
```

只保留 item id 與結果欄位作為作業紀錄，不要把 response 中的測試案例內容貼入對話。
要更新結果時走 §1 步驟 5 的批次端點；單筆 `PUT .../items/{item_id}` 僅適合零星修正。
既有 API 無法把 `test_result` 清回 `null`，不能承諾自動還原成未執行狀態。

Assignee 契約僅適用 Test Run Item create、single update 與
`batch-update-results`：

```json
{"assignee":{"id":"ou_...","name":"Alice","en_name":null,"email":"alice@example.com"}}
{"assignee_name":"Alice"}
{"assignee":null}
```

Structured identity 的 `id` 或 normalized email 至少一個必須來自使用者或可信上游；不可由 name 猜測，不可與 `assignee_name` 混用，不可送 `assignee_user_id`。App Token 沒有 contact lookup，structured 僅保存 Lark snapshot。Test Case create/update 不支援這套 assignee payload。

## 4. 建立 Test Case Set 並放入案例

```sh
# 1) 建立 Set，記下 response.id
sh scripts/tcrt_api.sh POST /api/app/teams/1/test-case-sets \
  --data '{"name":"Sprint 12","description":"Regression scope"}'

# 2) 先驗證 filters.set_not_found=false，再選 name=="Unassigned"
#    且 parent_section_id==null 的 canonical root id
sh scripts/tcrt_api.sh GET /api/app/teams/1/test-case-sections \
  --query 'set_id=9&roots_only=true&include_empty=true'

# 3) 新案例可直接 batch create 到 Set/Section
sh scripts/tcrt_api.sh POST /api/app/teams/1/test-cases/batch \
  --data '{"items":[{"test_case_number":"TC-2001","title":"Login","test_case_set_id":9,"test_case_section_id":31}]}'
```

既有案例要放入新 Set 時，使用 §6 的 guarded move；完成後以 `GET .../test-cases?set_id=9` 驗證。

## 5. 將 Test Run 加入／搬移／移出 Test Run Set

一個 "test run" 就是一個 Test Run Config。Mutation 前後都使用：

```sh
sh scripts/tcrt_api.sh GET /api/app/teams/1/test-runs --query 'include_archived=true'
```

Current membership 來自 `sets[].test_runs[].id` 與 `unassigned[].id`，不是 config 上猜測的 `set_id`。

```sh
# a) 建立 test run 時直接指定所屬 set
sh scripts/tcrt_api.sh POST /api/app/teams/1/test-run-configs \
  --data '{"name":"Sprint 12 regression","set_id":5}'

# b) 只有 read-back 證實全部位於 unassigned[] 才用 attach shortcut
sh scripts/tcrt_api.sh POST /api/app/teams/1/test-run-sets/5/members \
  --data '{"config_ids":[12,13],"expected_memberships":[{"config_id":12,"set_id":null},{"config_id":13,"set_id":null}]}'

# c) 已歸組或 mixed batch 一律用 explicit relocation
sh scripts/tcrt_api.sh POST /api/app/teams/1/test-run-sets/members/batch-move \
  --data '{"config_ids":[12,13],"target_set_id":7,"expected_memberships":[{"config_id":12,"set_id":5},{"config_id":13,"set_id":null}]}'

# d) 批次 detach：target_set_id 必填且明確為 null
sh scripts/tcrt_api.sh POST /api/app/teams/1/test-run-sets/members/batch-move \
  --data '{"config_ids":[12,13],"target_set_id":null,"expected_memberships":[{"config_id":12,"set_id":5},{"config_id":13,"set_id":7}]}'

# e) 單筆 move/detach 也必須提供 expected source
sh scripts/tcrt_api.sh POST /api/app/teams/1/test-run-sets/members/12/move \
  --data '{"target_set_id":7,"expected_source_set_id":5}'
```

`movements[]` 列出 per-config previous→target；`affected_set_ids` 只含實際改變且已重算的 Set。409 `APP_TOKEN_STATE_CHANGED` 表示 read-back 過時，要重讀，不可盲送舊 body。

更新 Set 本身屬性使用 `PUT /api/app/teams/1/test-run-sets/{set_id}`。

## 5A. Test Run 狀態轉換與結果檔上傳

```sh
# 推進 Test Run 生命週期：狀態機驗證 + 自動設定開始/結束時間 + 重算所屬 set
sh scripts/tcrt_api.sh PUT /api/app/teams/1/test-run-configs/5/status \
  --data '{"status":"active"}'

# 上傳某 run item 的結果檔（截圖 / log），可多檔；需要 test_run:execute
sh scripts/tcrt_api.sh POST /api/app/teams/1/test-run-configs/5/items/42/upload-results \
  --file files=@./screenshot.png --file files=@./run.log
```

合法轉換：draft→active→completed→archived（archived 可回 active/draft）。一般
`PUT .../test-run-configs/{id}` 也能直接設 `status`，但**不會**套用狀態機驗證與日期連動；
推進階段一律用 `/status`。`--file` 走 multipart，與 `--data` 互斥；python client 參數相同。

## 6. Test Case 批次建立／複製／搬移

```sh
# 同 Set 內批次搬 Section（cross-Set section id 會被拒絕）
sh scripts/tcrt_api.sh POST /api/app/teams/1/test-cases/batch-operations \
  --data '{"operation":"update_section","record_ids":["TC-1001","TC-1002"],"update_data":{"section_id":31}}'

# 批次刪除案例（需要 test_case:admin；destructive，先取得明確確認）
sh scripts/tcrt_api.sh POST /api/app/teams/1/test-cases/batch-operations \
  --data '{"operation":"delete","record_ids":["TC-1001"]}'

# 從既有案例批次複製（需要 test_case:write；不複製 TCG/附件/結果）
sh scripts/tcrt_api.sh POST /api/app/teams/1/test-cases/bulk-clone \
  --data '{"items":[{"source_record_id":"42","test_case_number":"TC-NEW-001"}]}'
```

Generic `update_test_set` 只保留為解析後回 400 的 legacy shape，**不可用來搬 Set**。跨 Set 必須：

```sh
# 1) preview（需 test_case:write + test_run:read）
sh scripts/tcrt_api.sh POST /api/app/teams/1/test-cases/impact-preview/move-test-set \
  --data '{"record_ids":["TC-1001","TC-1002"],"target_test_set_id":9}'

# 2) impacted_item_count > 0 時，重述 canonical cases、目標 Set、Run 與移除數後取得明確確認

# 3) 傳回同一 fingerprint 做 guarded mutation
sh scripts/tcrt_api.sh POST /api/app/teams/1/test-cases/move-test-set \
  --data '{"record_ids":["TC-1001","TC-1002"],"target_test_set_id":9,"impact_fingerprint":"<preview value>"}'

# 4) 讀 target_test_case_set_id 與 placements[].target_section_id，再 list/detail 驗證
```

409 `APP_TOKEN_IMPACT_CHANGED` 表示 preview 後 case/scope/Run Item 已變；必須重做 preview，impact 仍非零時也必須重新確認。Timeout/5xx 後先 read-back；即使 placement 吻合，也只能回報「final state verified; original outcome and cleanup count unknown」。

單筆跨 Set 且指定 Section，在 guarded body 加 `target_section_id`。批次指定 Section 需先 guarded move 到 target Unassigned，再做同 Set `update_section`；第二步失敗只重試 Section step，不反向搬回。

`bulk-clone` 保留 source Set/Section 且 response 不保證回新 ids。跨 Set 複製時以請求內的新 case numbers read-back，再 preview/guarded move。

### 不支援矩陣

- Section tree cross-Set move/reorder：無直接 API；只能逐 case guarded Set move 後做 same-Set Section move。
- Run Item cross-config move/copy：無直接 API；`POST .../items` 是在目標 Run 建立 execution item，不會移走來源 item。
- Batch permanent delete Test Runs/Sets：無 API；只能逐一，且每次需對精確目標取得「永久刪除」確認。
- `bulk-clone` directly-to-target-set：無 API；必須 clone → 以新 case numbers read-back → guarded move。

## 7. Archive 與永久刪除

**archive（歸檔）絕不可使用 `DELETE`。** 呼叫前必須向使用者重述資源類型、ID、正確 endpoint 與影響，並取得明確確認。

```sh
# Archive a Test Run Config: preserves the config and its items
sh scripts/tcrt_api.sh PUT /api/app/teams/1/test-run-configs/5/status \
  --data '{"status":"archived"}'

# Archive a Test Run Set: preserves the set and its runs
sh scripts/tcrt_api.sh POST /api/app/teams/1/test-run-sets/5/archive
```

`DELETE /api/app/teams/.../test-run-configs/{config_id}` 會永久刪除 config 與其 Test Run Items；`DELETE /api/app/teams/.../test-run-sets/{set_id}` 會永久刪除 set 與其 runs。只有使用者明確要求「永久刪除」並確認精確目標時才能使用 `DELETE`；絕不可將 HTTP 204 的 `DELETE` 回應報告為 archive 成功。

## 8. 失敗處理

- 401/403：停止重試；請使用者讓 team admin 補發或補上正確 scope。
- mutation 的 timeout/5xx：create 通常非冪等，先 list/lookup 再決定是否重送。
- credential test data：所有 read 與 mutation response 的 `category=credential` value 一律是 `[REDACTED]`，不要嘗試改走其他端點取明文。
- archive / permanent `DELETE`：先依 archive 對應 endpoint 執行，並取得明確確認；archive 請求不得呼叫 `DELETE`。
