## ADDED Requirements

### Requirement: Canonical tcrt-app skill SHALL be complete and versioned

`tools/skills/tcrt-app` SHALL 是唯一 canonical source，且 MUST 納入版本控制的 `SKILL.md`、`references/api-reference.md`、`references/api-usage-guide.md`、POSIX shell client、PowerShell client、Python fallback 與無秘密的 `.env.example`。真實 `.env` MUST 維持 ignored；`.opencode/` 等安裝或快取副本 SHALL NOT 作為契約真相來源。現有 `README.md` MAY 保留作為 human packaging metadata，但不是 Agent contract 的必要資源。

#### Scenario: Fresh checkout contains an operable skill
- **WHEN** 使用者取得只包含版本控制檔案的 repository checkout
- **THEN** `tools/skills/tcrt-app/SKILL.md` 與兩份 references 存在
- **AND** Agent 可由該 bundle 找到 transport、設定、安全與 API 工作流

### Requirement: Task index SHALL expose creation and transfer workflows

Workflow guide 的第一層 task index SHALL 直接列出 Test Case Set 建立、Test Case 批次建立、Test Case 跨 Set／Section 搬移、Test Run Config 批次掛入／搬移／移出 Test Run Set，以及 Test Run Item 批次建立與結果回報。Agent SHALL 先讀對應 recipe，再於需要精確 schema 時讀 API reference。

#### Scenario: Agent needs to create a Test Case Set
- **WHEN** Agent 收到建立 Test Case Set 並放入多筆案例的任務
- **THEN** task index 直接導向「建立 Set → 取得 Unassigned Section → batch create 或 batch move → verify」recipe

#### Scenario: Agent needs to relocate multiple Test Runs
- **WHEN** Agent 收到把多個 Test Run 搬到另一個 Test Run Set 或移出成 unassigned 的任務
- **THEN** task index 直接導向 explicit batch-move recipe
- **AND** 不要求 Agent 迴圈呼叫單筆 move

### Requirement: Test Case transfer recipes SHALL use exact executable contracts

Skill SHALL 明確記錄 guarded move 使用 top-level `record_ids`、`target_test_set_id` 與 preview 回傳的 `impact_fingerprint`，搬到目標 root `Unassigned` 並回傳 cleanup summary；不得指導 App Token Agent 使用 generic `update_test_set`。`update_section` 使用 `update_data.section_id` 且僅能在同一 Test Case Set 內搬移。批次跨 Set 且指定 Section 的工作流 SHALL 分成 guarded Set move 與同 Set Section move 兩步並逐步驗證；第二步失敗時只重試 Section step。單筆跨 Set 且指定 Section SHALL 使用 guarded move 的 `target_section_id` 原子完成。

#### Scenario: Batch move cases to another Set
- **WHEN** Agent 要把多筆案例搬到另一個 Test Case Set
- **THEN** recipe 使用 `POST .../test-cases/impact-preview/move-test-set`
- **AND** mutation 使用 `POST .../test-cases/move-test-set` 並傳回原 preview 的 `impact_fingerprint`
- **AND** 以 response `target_test_case_set_id` 與每個 `placements[].target_section_id` 解讀 final placement，最後以 filtered list/detail 驗證新 Set 與 cleanup summary

#### Scenario: Batch move cases within one Set
- **WHEN** Agent 要把多筆案例移至同 Set 的另一 Section
- **THEN** recipe 使用 `update_section` 與 `update_data.section_id`
- **AND** 明確說明 cross-Set Section id 會被拒絕

### Requirement: Test Run membership recipes SHALL distinguish attach move and detach

Skill SHALL 區分：建立 config 時的 `set_id`、建立 Set 時的 `initial_config_ids`、`/{set_id}/members` 的 unassigned-only batch attach、`/members/batch-move` 的 explicit batch relocation/detach，以及 `/members/{config_id}/move` 的單筆操作。所有 recipe SHALL 在 mutation 前後以 `GET .../test-runs?include_archived=true` 驗證 membership：current membership 來自 `sets[].test_runs[].id` 與 `unassigned[].id`，不假設 config 有 `set_id`。External move/attach SHALL 使用 exact expected-source body。

#### Scenario: Batch attach unassigned Test Runs
- **WHEN** read-back 證實多個 config 全部位於 `unassigned[]` 且要加入既有 Set
- **THEN** Agent 使用 `/{set_id}/members` 與 `config_ids[]`
- **AND** body 使用 `{"config_ids":[12,13],"expected_memberships":[{"config_id":12,"set_id":null},{"config_id":13,"set_id":null}]}` 等 exact expected-null mapping
- **AND** 檢查 response membership summary 與 read-back

#### Scenario: Mixed or grouped batch uses explicit relocation
- **WHEN** 任一 config 已在某 Set 或 batch 混合 grouped/unassigned configs
- **THEN** Agent 一律使用 `/members/batch-move`
- **AND** 不使用 `/{set_id}/members` 隱式覆寫來源

#### Scenario: Batch detach Test Runs
- **WHEN** 多個 config 要移出任何 Test Run Set
- **THEN** Agent 使用 `/members/batch-move` 與 `target_set_id:null`
- **AND** 不將永久刪除 endpoint 當作 detach

#### Scenario: Single move or detach uses required nullable fields
- **WHEN** Agent 搬移 config 12 從 Set 5 到 Set 7
- **THEN** body SHALL 為 `{"target_set_id":7,"expected_source_set_id":5}`
- **AND** detach SHALL 明確使用 `{"target_set_id":null,"expected_source_set_id":5}`

#### Scenario: Archived target remains visible during verification
- **WHEN** source 或 target Test Run Set 為 archived
- **THEN** pre/post read-back SHALL 使用 `include_archived=true`

### Requirement: Material cleanup SHALL require preview and confirmation

跨 Test Case Set 搬移 SHALL 遵循 read → preview → confirm → guarded mutate → verify。當 preview 的 `impacted_item_count` 大於零，skill MUST 在 mutation 前向使用者重述 canonical 案例範圍、目標 Set、受影響 Test Runs 與將移除的 Run Item 數量，並取得該 fingerprint 範圍的明確確認。Mutation MUST 使用同一 `impact_fingerprint`；409 後重做 preview 與確認。Timeout 或 5xx 後 MUST 先 read-back，不得盲目重送。若 placement 吻合，Agent 僅可回報「final state verified; original outcome and cleanup count unknown」，不得宣稱原請求成功或 cleanup count 已知。

#### Scenario: Preview reports destructive Run Item cleanup
- **WHEN** impact preview 回報一或多個 Run Item 將被移除
- **THEN** Agent 暫停 mutation 並取得該精確影響範圍的確認

#### Scenario: Preview reports zero impact
- **WHEN** 使用者已明確要求精確案例與目標 Set，且 preview 為零影響
- **THEN** Agent 可執行搬移並在完成後驗證

### Requirement: Copy and item-creation semantics SHALL not be mislabeled as moves

Skill SHALL 說明 `bulk-clone` 保留來源 Test Case Set／Section；跨 Set 複製須 clone 後再搬移 clone。`POST .../test-run-configs/{config_id}/items` SHALL 描述為在目標 Test Run 建立 execution items，不得宣稱會從其他 Test Run 移走既有 items。

#### Scenario: Copy cases into a different Set
- **WHEN** Agent 要複製多筆案例到不同 Set
- **THEN** recipe 先 bulk-clone，再以請求中的新 case numbers read-back，對新案例執行 preview 與 guarded Set move
- **AND** 不承諾單一 clone request 可指定 target Set

### Requirement: Unsupported transfer matrix SHALL be explicit

Skill SHALL 明列以下無直接 API 的情境：Section tree cross-Set move/reorder（只能逐 case guarded Set move 再 same-Set Section move）；Run Item cross-config move/copy（`POST .../items` 是建立）；batch permanent delete Test Runs/Sets（只能逐一且每次需明確永久刪除確認）；`bulk-clone` directly-to-target-set（必須 clone/read-back/guarded move）。Agent SHALL NOT 猜測未存在 endpoint 或把建立誤報為搬移。

#### Scenario: Agent receives an unsupported transfer request
- **WHEN** 使用者要求 Section tree cross-Set move、Run Item cross-config move/copy、batch permanent delete，或 clone directly to target Set
- **THEN** Agent SHALL 指出直接 API 不存在並使用文件化的可行組合流程
- **AND** SHALL NOT 猜測 endpoint 或把 create 說成 move

### Requirement: Assignee guidance SHALL preserve the App Token identity boundary

Skill SHALL 將 assignee guidance 限定於 App Token Test Run Item create、single update 與 `batch-update-results` endpoints。Exact payload：structured Lark snapshot 使用 `{"assignee":{"id":"ou_...","name":"...","en_name":null,"email":"..."}}`，`id` 或 normalized email 至少一個必須來自使用者或可信上游；name-only legacy 使用 `{"assignee_name":"Alice"}`；clear 使用恰一種 representation 的 null，不混用。App Token 無 contact lookup，Agent SHALL NOT 由 name 猜 id/email。Structured payload 僅儲存 Lark snapshot，不連結 local user。`assignee_user_id` SHALL 回 422 且零寫入，read snapshot SHALL 維持最小 projection。Test Case create/update SHALL 明列不支援此 assignee workflow。

#### Scenario: Agent assigns by structured Lark identity
- **WHEN** caller 已有可驗證的 Lark id 或 email payload
- **THEN** Agent 可送 structured `assignee`
- **AND** 不加入 local user id

#### Scenario: Agent does not apply Run Item assignee to Test Cases
- **WHEN** 使用者要求對 Test Case 寫入 assignee
- **THEN** Agent SHALL 說明 App Token Test Case create/update 不支援此契約
- **AND** SHALL NOT 送出或宣稱已保存 assignee payload

### Requirement: Skill contract SHALL be automatically validated

Repository tests SHALL 驗證 skill 文件含必要 endpoint、payload key、安全流程、unsupported matrix 與 canonical source 宣告，且 SHALL 拒絕「App Token 不支援 Test Case Set／Section 搬移」等與現行 API 矛盾的敘述。Tests SHALL 以 `git ls-files` 驗證 `SKILL.md` 與兩份 references 已追蹤。三個 transport SHALL 拒絕非 http/https origin 或含 userinfo/query/fragment/non-root path 的 base URL；`check` SHALL 在 stderr 先輸出 `[tcrt-app] TCRT_BASE_URL=<origin>` 再輸出 `HTTP <status>`，stdout 僅 response body，不顯示 token。Skill SHALL NOT 指導 `echo $TCRT_*` 取得 provenance，Windows 命令範例 SHALL 明定為 PowerShell prompt，不宣稱 cmd.exe 單引號 JSON 相容。

#### Scenario: API documentation drifts
- **WHEN** 必要 endpoint、payload 或 safety phrase 從 canonical skill 移除或改錯
- **THEN** focused skill contract test 失敗

#### Scenario: Check mode reports provenance safely
- **WHEN** 任一 transport 執行 `check`
- **THEN** stderr 包含 resolved base URL 與 HTTP status
- **AND** stdout 仍只包含 response body
- **AND** token 不出現在輸出
