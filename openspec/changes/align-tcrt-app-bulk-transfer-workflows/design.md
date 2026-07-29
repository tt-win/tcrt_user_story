## Context

`/api/app/*` 是 TCRT 對外 mutation 的 canonical namespace，`tools/skills/tcrt-app` 則是沒有 MCP write tool 時供 AI Agent 使用的可攜 client。現況有四種不同但容易混淆的資料配置操作：Test Case 建立／複製／搬移、Test Case Section 指派、Test Run Config 的 Test Case Set scope，以及 Test Run Config 對 Test Run Set 的 membership。現有 skill 只列出部分 endpoint，且未把 cleanup、status recalculation、idempotency 與 unsupported operations 組成可安全執行的工作流。

跨 Test Case Set 搬移會同步刪除不再符合 Test Run scope 的既有 Run Items。這些資料無法由 API 自動完整還原，因此 impact preview 與使用者確認是必要操作邊界。Test Run membership 搬移不刪除 Run Items，但若只重算目標 Set，來源 Set 可能留下 stale status。

## Goals / Non-Goals

**Goals:**

- 讓單筆與批次 Test Case 跨 Set 搬移具有相同 target Section、guarded preview、cleanup 與 response 語意，並關閉 preview→mutation TOCTOU。
- 提供最多 100 個 Test Run Config 的原子 batch move/detach，以 expected membership 防止 last-write-wins，並統一所有 production membership 寫入路徑的來源／目標 Set 狀態重算。
- 讓 AI Agent 可由 task index 找到 Test Case Set 建立、批次建立、搬移、複製、驗證及復原指引，且每個 recipe 使用實際可呼叫的 payload。
- 以 OpenSpec、版本控制與 focused tests 建立 API ↔ skill 的同步護欄。

**Non-Goals:**

- 不新增 Test Case Section tree 的跨 Set 搬移／reorder API。
- 不提供 Test Run Item 跨 Test Run Config 的 move/copy API；`POST .../items` 仍是建立 execution membership。
- 不新增批次永久刪除 Test Run／Test Run Set，也不改變 archive 與 delete 的既有差異。
- 不改變 App Token scope 名稱、token 管理流程、資料庫 schema 或既有 read response projection。
- 不同步或刪除 `.opencode/` 等本機工具安裝狀態；`tools/skills/tcrt-app` 是唯一 canonical source。

## Decisions

### 1. Test Case move 使用 guarded preview 與原子 mutation

新增 `POST /api/app/teams/{team_id}/test-cases/impact-preview/move-test-set`，request 為 1–100 個去重保序的 `record_ids`（本地 id、`lark_record_id` 或 case number）與正整數 `target_test_set_id`，並拒絕 extra fields。端點要求 `test_case:write` 與 `test_run:read`：response 包含 Run 名稱，不得繞過 Test Run read boundary。端點先原子解析 team、target Set 與所有 records，再呼叫 scope service，不寫入業務資料。

Response 除 impact detail 外回傳 canonical `case_ids`、`case_numbers`、`source_test_case_set_ids` 與 `impact_fingerprint`。Fingerprint 是不含秘密的 SHA-256，綁定 team、canonical cases 及其 Set/Section、target Set、相關 Test Run scope，以及每個 impacted Run Item 的「deletion snapshot digest」。Deletion snapshot 以穩定序列化包含 Run Item 的每個 persisted column（含 result、assignee、attachments/execution results/upload history JSON 與 timestamps）與其全部 result-history child rows 的每個 persisted column；因此同 id 內容更新、comment/history 新增或新 item 都會改變 fingerprint。它是 optimistic precondition，不是授權 token，response 不暴露 deletion snapshot 內容。Preview 與 mutation 的 allow/deny 均寫 App Token audit，audit 只記錄 canonical ids、target、fingerprint 與 counts，不寫 token/credential 或 Run Item 內容。

新增 `POST /api/app/teams/{team_id}/test-cases/move-test-set`，要求 `test_case:write` 與 `test_run:read`，使用同一 typed request 再加必填 `impact_fingerprint`。Server 在一個 transaction 中依 config id、item id 的穩定順序先鎖定相關 TestRunConfig parent rows，再鎖定案例、現有 Run Item 與 history rows，然後重查完整 deletion snapshot 並重算 fingerprint。MySQL/PostgreSQL 使用 stable-order `SELECT ... FOR UPDATE`；SQLite 必須在任何 snapshot read 前透過 data-access boundary 取得 `BEGIN IMMEDIATE` 或等價、可跨 process 的 writer serialization，不可依賴 SQLite 上無效的 row lock。

所有 production Run Item create paths 必須共用同一 config-scope concurrency protocol：App Token batch create、JWT batch create、rerun clone 與 from-test-cases/generated run 都先取得上述 config parent lock/SQLite writer serialization，然後重讀 config scope 與 case Set，最後才 insert。Move-first 時 create 必須等待後重驗並拒絕 out-of-scope insert；create-first 時 move 必須重查 deletion snapshot 並因 fingerprint 改變而回 409。不符時回 409 `APP_TOKEN_IMPACT_CHANGED` 且零寫入，符合時才原子更新 Set/Section 與 cleanup。App Token 的 generic `PUT` 或 `batch-operations:update_test_set` 若要改變 Set，回 400 `APP_TOKEN_VALIDATION_ERROR` 並導向 guarded endpoint；同 Set 重送是 no-op 且保留現有 Section。

替代方案是只在 skill 以 list API 推估；這無法可靠重現 legacy scope fallback 與 per-run item 計數，因此不採用。

### 2. 單筆與批次案例搬移共享明確的 target Section 規則

跨 Set 搬移時：單筆 guarded request 若明確提供屬於目標 Set 的 `target_section_id`，使用該 Section；批次或未指定時使用目標 Set 的 root `Unassigned`。共用 helper 查詢 `parent_section_id IS NULL AND name='Unassigned'`，以目標 Set row lock 序列化 legacy missing create；若已有多個 root duplicate，回 409 `APP_TOKEN_INTEGRITY_CONFLICT` 不擅自合併。只改 Section 時必須仍在目前 Set 內。

Guarded response 回傳 `success=true`、以 canonical ids 計算的 `processed_count`、`moved_count`、`unchanged_count`、`case_ids`、`case_numbers`、`target_test_case_set_id`、ordered `placements[]` 與 final `cleanup_summary`。每個 placement 固定包含 `case_id`、`previous_test_case_set_id`、`previous_section_id`、`target_test_case_set_id`、final `target_section_id` 與 `changed`；因此 unchanged case 與 changed case 即使最終 Section 不同也無歧義。已在 target Set 的案例為 unchanged，保留現有 Section、不 cleanup。跨 Set 且指定 Section 的單筆搬移可在一次 guarded request 完成；批次指定 Section 要先 guarded Set move，再做同 Set `update_section`。第二步失敗時保留在 Unassigned，read-back 後只重試 Section step，不反向搬回假裝 rollback。

替代方案是維持單筆 PUT 的舊行為並只文件化批次路徑；這會保留跨 Set/Section 不一致資料與 OpenSpec 違約，因此不採用。

### 3. Test Run batch relocation 是 all-or-nothing membership mutation

新增 `POST /api/app/teams/{team_id}/test-run-sets/members/batch-move`：

```json
{"config_ids":[12,13],"target_set_id":7,"expected_memberships":[{"config_id":12,"set_id":5},{"config_id":13,"set_id":null}]}
```

`target_set_id` 是「必填但可為 null」：明確 null 表示批次移出成 unassigned，缺欄或 typo 為 422，不得當 detach。Typed model 拒絕 extra fields；`config_ids` 必須有 1–100 個正整數，去重後保留順序；`expected_memberships` 必須對每個 canonical config 各有一筆，`set_id` 同樣必填可 null。Server 在任何寫入前驗證所有 config、expected source 與 non-null target 均屬 path team，並在 transaction row lock 後比對實際 membership；預期不符回 409 `APP_TOKEN_STATE_CHANGED`。重送相同目標且 precondition 仍符合時是安全 no-op。Archived target Set 維持既有相容行為，允許成為 target。

Response 固定包含 `success=true`、`processed_count`、`moved_count`、`unchanged_count`、`target_set_id`、`config_ids`、`affected_set_ids` 與 `movements[]`。Counts 以 canonical ids 計算；`affected_set_ids` 只含實際 membership 改變者的 non-null previous/target ids，sorted unique，全批 no-op 為 `[]` 且不重算；`movements[]` 以 request 順序列出 `config_id`、`previous_set_id`、`target_set_id`、`changed`，可供人工 forward recovery。

Schema/type/range/extra-field errors 使用 FastAPI 422。Body 中 missing/cross-team config 或 Set reference 回 400 `APP_TOKEN_VALIDATION_ERROR`；missing path resource 回 404 `APP_TOKEN_RESOURCE_NOT_FOUND`；precondition 不符回 409 `APP_TOKEN_STATE_CHANGED`。全部均在 mutation 前完成。

替代方案是要求 Agent 迴圈呼叫單筆 `/move`；這會增加 partial completion 與 timeout 重試歧義，因此不採用。

### 4. 所有 membership 寫入共用同一 relocation core

建立一個同步 transaction relocation core，完整收斂 production 中 `attach_config_to_set` / `detach_config_from_set` 的所有 call sites：App Token 與 JWT config create、Set `initial_config_ids`、add-members、single/batch move/detach、rerun clone、from-test-cases/generated runs 與 config deletion。Helper 以排序後 config/set ids 鎖定 rows，預先驗證，記錄 previous Set，執行 mutation，最後對「實際改變者」的所有 non-null previous/target Set 各重算正好一次；caller 移除重複 recalculation。

既有 `/{set_id}/members` 改為 typed attach-only shortcut：body exact shape 為 `{"config_ids":[12,13],"expected_memberships":[{"config_id":12,"set_id":null},{"config_id":13,"set_id":null}]}`，只接受 read-back 時為 unassigned 或 already-target 的 configs。若 expected source 本就是其他 Set，回 400 `APP_TOKEN_VALIDATION_ERROR` 並指示 batch-move；若 transaction 現況與 expected 不符，回 409 `APP_TOKEN_STATE_CHANGED`。兩者均零寫入。單筆 `/move` exact body 為 `{"target_set_id":7,"expected_source_set_id":5}`，detach 為 `{"target_set_id":null,"expected_source_set_id":5}`；兩欄都必填可 null、extra forbid，response 保持既有 `TestRunConfigSummary`。Test Run Set create 的 `initial_config_ids` 隱含 expected source 皆為 null；transaction 內任一已 assigned 回 409 `APP_TOKEN_STATE_CHANGED` 並 rollback 整個 create，不留空 Set。

Create 與 add-members response 的 `membership_summary` SHALL 永遠存在，並使用與 batch-move response 同一 `MembershipMutationSummary` model：`success`、`processed_count`、`moved_count`、`unchanged_count`、`target_set_id`、canonical `config_ids`、sorted `affected_set_ids` 與 ordered `movements[]`。Create 的 empty/omitted `initial_config_ids` 回 target=new Set id、counts 為 0、arrays 為 `[]`；add-members already-target 計入 unchanged。

Membership mutation audit 記錄 canonical config ids、target 及 per-config previous→target mapping，足以人工逆向搬移；不記錄 token 或非必要內容。

### 5. Skill recipes 以 read → preview → confirm → mutate → verify 為標準流程

對跨 Test Case Set 搬移，Agent 必須先讀取並解析目標、呼叫 impact preview；若 `impacted_item_count > 0`，必須向使用者重述 canonical 案例清單／數量、目標 Set、會移除的 Run Item 數與受影響 Run，取得明確確認後以同一 fingerprint mutation。若為 0 且使用者已明確要求精確搬移，可直接執行。409 時重做 preview/確認，不用舊 fingerprint。Timeout/5xx 後先 read-back；若 placement 符合，只能回報「final state verified; original outcome and cleanup count unknown」，不可宣稱原請求成功，也不可把重試的 unchanged 當成原結果。

對 Test Run membership，Agent 一律以 `GET .../test-runs?include_archived=true` 的 `sets[].test_runs[].id` 與 `unassigned[].id` 取得 config id/current Set，不猜 config 有 `set_id`。`/{set_id}/members` 只能用在 read-back 證實所有 config 位於 `unassigned[]` 的情境；任何已歸組或 mixed batch 一律使用 `/members/batch-move`。Mutation 後也使用 `include_archived=true` 讀取驗證，避免 archived target/source 從預設 projection 消失。

### 6. Skill 明確記錄建立、複製與搬移的組合語意

- 建立 Test Case Set 後呼叫 `GET .../test-case-sections?set_id=<new_id>&roots_only=true&include_empty=true`，先驗證 `filters.set_not_found=false`，再選 `name=="Unassigned" && parent_section_id==null`。
- 批次建立 Test Cases 可在每個 item 指定 `test_case_set_id`／`test_case_section_id`。
- `bulk-clone` 保留來源 Set／Section；要把 clone 放到其他 Set，必須以請求中的新 case numbers read-back，再走 guarded preview + move，不假設 clone response 有 ids；需指定 section 時再走同 Set `update_section`。
- Legacy `update_test_set` 的 `update_data.test_set_id` 只保留為解析後回 400 的相容 shape，不是可執行 Agent recipe；Agent 必須使用 guarded top-level fields。同 Set `update_section` 的 key 仍是 `update_data.section_id`。
- Run Item batch create 不是跨 config 搬移，文件不得使用「move」描述。

Assignee exact contract 僅適用 Test Run Item `POST /test-run-configs/{config_id}/items`、`PUT /test-run-configs/{config_id}/items/{item_id}` 與 `POST /test-run-configs/{config_id}/items/batch-update-results`。Structured Lark snapshot 用 `{"assignee":{"id":"ou_...","name":"...","en_name":null,"email":"..."}}`，`id` 或 normalized email 至少一個來自使用者／可信上游；name-only legacy 用 `{"assignee_name":"Alice"}`；clear 使用 `{"assignee":null}` 或 `{"assignee_name":null}` 其中一種，不混用。`assignee_user_id` 為 422/零寫入。App Token 沒有 contact lookup，Agent 不得由 name 猜 id/email；structured 僅保存 Lark snapshot，不連結 local user。Test Case create/update 不支援此 assignee workflow，skill 不得對 Test Case 送出或宣稱保存這些欄位。

Unsupported matrix 必須逐項列出：Section tree cross-Set move/reorder 無 API，只能逐 case guarded Set move 後同 Set section move；Run Item cross-config move/copy 無 API，`POST .../items` 是建立；batch permanent delete Runs/Sets 無 API，只能逐一永久刪除並取得明確確認；`bulk-clone` 無 directly-to-target-set，必須 clone/read-back/guarded move。

### 7. Canonical skill 可追蹤且可自我驗證

`.gitignore` 只對 `tools/skills/tcrt-app/SKILL.md` 與兩個 exact reference paths 加 negation，不解禁其他 Markdown 或本機 `.env`。`README.md` 保留為 human packaging metadata，但不是 Agent contract 必要檔；本變更不新增 `agents/openai.yaml`，因為此 repo bundle 由現有 skill loader 以 `SKILL.md` 發現。Focused contract test 以 `git ls-files` 驗證必要檔已追蹤，並驗證 endpoint、payload key、安全關鍵字、unsupported matrix 與移除錯誤敘述。

三個 transport 將 base URL 限制為 http/https origin（無 userinfo、query、fragment，path 僅可為空或 `/`）。`check` 在 stderr 穩定輸出 `[tcrt-app] TCRT_BASE_URL=<origin>` 再輸出 `HTTP <status>`，stdout 僅 response body，永不顯示 token；Skill 不再呼籲 `echo $TCRT_*`。Windows 範例僅保證在 PowerShell prompt 執行，不宣稱 cmd.exe 可直接複製單引號 JSON。

## Risks / Trade-offs

- [案例搬移 cleanup 無法自動還原] → fingerprint 綁定精確 preview + material-impact confirmation + transaction 內重驗 + mutation 後驗證；skill 明確禁止 timeout 後盲目重送，不宣稱 read-back 可還原 cleanup。
- [batch move all-or-nothing 使單一錯誤阻擋整批] → response 使用穩定 validation error，Agent 先 list 驗證 ids；選擇原子性以避免半套 membership。
- [新增 batch endpoint 與 `/members` 能力重疊] → `/members` 僅允許經 read-back 證實的 unassigned attach，`batch-move` 處理已歸組、mixed batch 與 detach；兩者共用 core。
- [並行 membership relocation] → expected membership + 穩定順序 row locks + 同 transaction recalculation；沖突回 409 不覆寫新狀態。
- [additive response 可能影響嚴格 client] → 既有欄位與 status code 不變；新摘要為額外欄位，官方文件標示 additive。
- [tracked skill docs 受全域 `*.md` ignore 影響] → 使用精確 negation 並以 `git check-ignore` 驗證，不擴大到其他工具狀態。
- [PowerShell 無本機 runtime 可驗證] → 保留靜態 parser／人工 review 證據為待驗證，POSIX 與 Python clients 執行 focused checks。

## Migration Plan

1. 先加入共用 helper、additive endpoints 與 focused API tests；不碰真實資料。
2. 更新 canonical skill、官方 API reference 與 project docs，加入 contract test。
3. 執行 OpenSpec strict validation、focused tests、Ruff、skill transport checks、全 repo gates 與 `graphify update .`。
4. 部署不需 migration；新 skill 只在 server 已包含 guarded case move／batch membership endpoint 時宣告完整能力。舊 App Token client 的 cross-Set generic update 與 untyped membership body 需改用新 typed/precondition contract。
5. 回退程式碼不需 schema downgrade；已完成 membership 搬移可依 audit mapping 人工 forward-recover。已 cleanup 的 Run Items 無法完整還原，回退程式碼不會回復業務資料。

## Open Questions

無。任何紅隊發現的未定義 scope、payload、partial-failure、重試、回應或 rollback 情境都必須先回寫本設計與 delta specs，清零後才進入實作。
