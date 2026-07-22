# Tool Matrix: add-global-ai-assistant

依 2026-07-21 web JWT router 實際盤點制定，並已對 FastAPI OpenAPI 實際路由校驗（見末節「OpenAPI 路徑校驗」）。本矩陣是 registry 實作的契約（design D10）；path 為完整 template（`{team_id}` 由 executor 注入）。**registry path template 必須精確匹配 OpenAPI（含尾斜線與 path converter）**，並由測試 8.1 對 `app.routes` 逐一驗證。

## 通則

- **Perm**：executor 於每次執行前以 `check_team_permission` 強制驗證（必要防線）。「端點檢查」欄標示被呼叫端點自身是否有 in-handler 權限檢查（❌ = 無，僅靠 executor）。Perm 對齊端點實際要求。
- **Risk / 確認**：**只有 `read` 免確認可 inline 執行；所有 write 一律走 pending confirmation**（2026-07-21 使用者拍板，防 prompt injection）。確認卡兩級：`idempotent_write` / `reversible_write` 輕量卡，`high_impact` / `irreversible` 警告卡。executor 硬拒 inline 執行任何非 read 工具。
- **DELETE 規則**：HTTP DELETE 預設 `irreversible`；豁免需明文列於「例外」節，registry 驗證測試比對豁免清單。
- **team_id**：一律由 executor 從對話綁定注入 path，不出現在任何工具參數 schema。
- **Team 驗證欄**：`inject`＝path 含 `{team_id}` 由 executor 注入即足；`resolve`＝path 不含 team_id 或操作可能跨 team 的 sub-resource，executor 須以 `resource_team_check` resolver 驗證資源實際 team == 對話 team（design D2 / spec assistant-tool-execution）。
- **Projection**：allowlist；未列欄位不外送。凡含 `test_data` 一律先過 `redact_credential_test_data`。
- **Error mapping**：所有工具套用通則——401→終止回合（session 過期）、403→權限不足說明、404→資源不存在、409→衝突、422→參數/狀態不符、5xx→伺服器錯誤；response body 先經遮罩管線。「特殊錯誤」欄僅列偏離通則者。
- **Mutation outcome certainty**：上述 error mapping 僅直接適用 read。mutation 在 loopback 開始後遇 timeout、cancellation、transport error、無 response 或任何 5xx，一律標 `unknown` 且不重試。每個 mutation 在 task 1.1 必須另外定案 `definitive_pre_mutation_errors` 4xx allowlist；只有端點契約與測試能證明副作用尚未開始者可標 failed，未列者保守 unknown。
- **Confirmation summary**：每個 mutation 在 task 1.1 必須定義 server-side confirmation template（tool label i18n key、target resolver、affected-count resolver、warning i18n keys）。LLM prose 不得成為確認摘要；high_impact/irreversible resolver 失敗即不建立 pending。
- **Sensitive inputs**：每個 mutation 明文宣告 `sensitive_input_paths`（無則 `[]`）與必要的具名 deterministic classifier；禁止以 LLM 或模糊 key-name 猜測。命中時套用 Assistant AES-GCM envelope，credential test_data 仍在 pending 前直接拒絕。
- **固定 operation 與風險不可降級**：共用 endpoint 的 registry 工具可以 server-side 固定 `operation`，但固定值不得出現在 LLM schema。單一工具 schema MUST NOT 同時暴露不同 risk 的 operation/欄位；載入測試需驗證 higher-risk fields 只存在於對應 high_impact/irreversible 工具。
- **credential 寫入限制**：2.5 create_test_case、2.6 update_test_case、2.9 bulk_create_test_cases 的 `test_data` 若含 `category=credential` 且帶非空 value，executor 拒絕並引導改用 UI。此外 **2.6 update_test_case 為 test_data 完整覆寫**：當帶 `test_data` 且既有 case 或 incoming 含 credential 時，executor 拒絕該 test_data 更新（其他欄位放行），避免遮罩結果覆寫清空既有 credential（spec assistant-data-boundary）。
- **共用 projection**：
  - `TC-LIST`＝`record_id, test_case_number, title, priority, test_result, assignee.name, test_case_set_id, test_case_section_id, section_name, section_path, tcg[].text, tcg[].text_arr, updated_at`；by-tickets route 另允許 `jira_tickets[]`。executor 可把 `record_id→id`、`assignee.name→assignee_name`、tcg text values→`tcg_tickets[]` 正規化，但不得讀其他 source path。
  - `TC-DETAIL`＝TC-LIST ＋ `precondition, steps, expected_result, test_data[].{id,name,category,value}, attachments[].{name,size,type}`；`test_data.value` 先套 credential redaction，`attachments.file_token`/二進位內容不允許。
  - `TRC`＝`id, name, description, set_id, set_name, test_case_set_ids[], test_version, test_environment, build_number, related_tp_tickets[], status, start_date, end_date, total_test_cases, executed_cases, passed_cases, failed_cases, created_at, updated_at`。
  - `ITEM`＝`id, config_id, test_case_number, title, priority, test_result, assignee_name, executed_at, execution_duration, attachment_count, execution_result_count, comment, created_at, updated_at`；comment 依 tool-result char cap 截斷，不允許 `attachments[]`、`execution_results[]`、email。
  - `TRS`＝`id, name, description, status, archived_at, related_tp_tickets[], created_at, updated_at, test_run_count, automation_covered_case_count, test_runs[].{id,name,set_id,set_name,test_case_set_ids,test_environment,build_number,test_version,related_tp_tickets,status,execution_rate,pass_rate,total_test_cases,executed_cases,passed_cases,start_date,end_date,created_at}`。list response 沒有的欄位省略，不以其他欄位替代。
  - `RUN`＝`id, test_run_set_id, script_group_id, script_group_name, status, triggered_by, branch, environment, report_url, started_at, finished_at, duration_ms, error_summary, created_at, updated_at`；明文排除 `inputs, external_run_id, external_run_url, tcrt_correlation_id, ci_correlation_id, workflow_id, runner_label` 與原始 log。
  - `SET`＝`id, name, description, is_default, test_case_count, created_at, updated_at`；`SECTION`＝`id, test_case_set_id, name, description, parent_section_id, level, sort_order, created_at, updated_at`。
  - `PAGE`＝`skip, limit, total, has_next, next_cursor`（source response 有才保留）；`IMPACT`＝`impacted_item_count, trigger, target_test_case_set_id, source_test_case_set_id, impacted_test_runs[].{config_id,config_name,removed_item_count}`；`CLEANUP`＝`removed_item_count, trigger, affected_test_case_set_ids[], target_test_case_set_id, source_test_case_set_id, impacted_test_runs[].{config_id,config_name,removed_item_count}`。
  - `ERR`＝`status, detail`，detail 必須先經遮罩管線；任何 validation context、stack、request body、headers 不允許。

## 1. Discovery / Pins / Skills（全域對話：1.1 + 1.5–1.6；其餘需 team 綁定）

| # | 工具 | Method Path | 參數綁定 | Perm | 端點檢查 | Team | Risk | 冪等 | Projection / 特殊錯誤 |
|---|---|---|---|---|---|---|---|---|---|
| 1.1 | list_teams | GET /api/teams/ | — | READ | auth-only | — | read | ✔ | id, name, description, test_case_count |
| 1.2 | list_pins | GET /api/pins | query: team_id（注入） | READ | auth-only | inject | read | ✔ | entity_type→ids, token_pinned |
| 1.3 | pin_entity | POST /api/pins | body: entity_type, entity_id（team_id 注入） | WRITE | auth-only | resolve（entity_id 屬 team） | idempotent_write | ✔ | success, already_pinned |
| 1.4 | unpin_entity | DELETE /api/pins/{entity_type}/{entity_id} | path＋query team_id 注入 | WRITE | auth-only | resolve | idempotent_write（**豁免**） | ✔ | success, deleted |
| 1.5 | list_skills | LOCAL（in-process） | — | READ | n/a | none | read | ✔ | skills[], count；來源 `prompts/assistant/skills/*.md` |
| 1.6 | get_skill | LOCAL（in-process） | query/arg: skill_id | READ | n/a | none | read | ✔ | skill_id, name, description, triggers, body；未知 id → 404 |

## 2. Test Cases（`/api/teams/{team_id}/testcases`）

| # | 工具 | Method Path | 參數綁定 | Perm | 端點檢查 | Team | Risk | 冪等 | Projection / 特殊錯誤 |
|---|---|---|---|---|---|---|---|---|---|
| 2.1 | list_test_cases | GET .../testcases | query: search, priority_filter, test_result_filter, assignee_filter, tcg_filter, set_id, sort_by, sort_order, skip, limit | READ | ✔ READ | inject（set_id 選填→resolve） | read | ✔ | TC-LIST[]＋page |
| 2.2 | count_test_cases | GET .../testcases/count | query: 同上篩選 | READ | ✔ READ | inject | read | ✔ | total |
| 2.3 | get_test_case | GET .../testcases/{record_id} | path: record_id | READ | ✔ READ | inject | read | ✔ | TC-DETAIL |
| 2.4 | find_test_cases_by_tickets | GET .../testcases/by-tickets | query: tickets（CSV） | READ | auth-only | inject | read | ✔ | record_id, number, title, priority, jira_tickets |
| 2.5 | create_test_case | POST .../testcases | body: TestCaseCreate | WRITE | ✔ WRITE | inject（set/section resolve） | reversible_write | ✘ | TC-DETAIL / 409 dup number |
| 2.6 | update_test_case | PUT .../testcases/{record_id} | path＋body: TestCaseUpdate 排除 test_case_set_id/test_case_section_id | WRITE | ✔ WRITE | inject | idempotent_write | ✔ | TC-DETAIL（不觸發 scope cleanup） |
| 2.7 | delete_test_case | DELETE .../testcases/{record_id} | path | WRITE | ✔ WRITE | inject | **irreversible** | ✔ | （204） |
| 2.8 | move_test_case_scope | PUT .../testcases/{record_id} | path＋body: 僅 test_case_set_id/test_case_section_id | WRITE | ✔ WRITE | inject＋resolve target | **high_impact** | ✔ | TC-DETAIL＋cleanup_summary |
| 2.9 | bulk_create_test_cases | POST .../testcases/bulk_create | body: items[], test_case_set_id?, test_case_section_id? | WRITE | auth-only | inject（set/section resolve） | **high_impact** | ✘（dup 中止整批） | success, created_count, duplicates, errors |
| 2.10 | bulk_clone_test_cases | POST .../testcases/bulk_clone | body: items[]（source→new number） | WRITE | auth-only | resolve（source 屬 team） | **high_impact** | 部分成功 | cloned/errors 摘要 |
| 2.11 | preview_move_test_set_impact | POST .../testcases/impact-preview/move-test-set | body: record_ids, target_test_set_id | **WRITE** | ✔ WRITE | resolve（record＋target set 屬 team） | read | ✔ | ImpactPreview 摘要 |
| 2.12 | list_test_case_attachments | GET .../testcases/{test_case_id}/attachments | path | READ | ❌ | resolve | read | ✔ | files（name/size）, count |
| 2.13 | upload_test_case_attachment | POST .../testcases/{test_case_id}/attachments | path＋multipart: file_ref→files[] | WRITE | ❌ | resolve | reversible_write | ✘ | uploaded, files（name/size）/ 409 cross-team |
| 2.14 | delete_test_case_attachment | DELETE .../testcases/{test_case_id}/attachments/{target} | path | WRITE | ❌ | resolve | **irreversible** | ✔ | deleted, remaining |
| 2.15 | batch_update_test_cases | POST .../testcases/batch | body: operation∈{update_priority,update_tcg}, record_ids, operation-specific update_data | WRITE | auth-only | inject（records 屬 team） | **high_impact** | 部分成功 | processed, success, error_count, error_messages |
| 2.16 | batch_move_test_cases | POST .../testcases/batch | body: operation∈{update_section,update_test_set}, record_ids, operation-specific update_data | WRITE | auth-only | resolve（records＋target 屬 team） | **high_impact** | 部分成功 | processed, success, error_count, error_messages, cleanup_summary |
| 2.17 | batch_delete_test_cases | POST .../testcases/batch | body: record_ids；executor 固定 operation=delete | WRITE | auth-only | inject（records 屬 team） | **irreversible** | 部分成功 | processed, success, error_count, error_messages |

## 3. Test Case Sets / Sections

| # | 工具 | Method Path | 參數綁定 | Perm | 端點檢查 | Team | Risk | 冪等 | Projection / 特殊錯誤 |
|---|---|---|---|---|---|---|---|---|---|
| 3.1 | list_test_case_sets | GET /api/teams/{team_id}/test-case-sets | — | READ | auth＋team-exists | inject | read | ✔ | SET[] |
| 3.2 | get_test_case_set | GET /api/teams/{team_id}/test-case-sets/{set_id} | path | READ | auth-only | inject＋resolve | read | ✔ | SET＋sections tree＋counts |
| 3.3 | create_test_case_set | POST /api/teams/{team_id}/test-case-sets | body: name, description | WRITE | auth＋team-exists | inject | reversible_write | ✘ | SET |
| 3.4 | update_test_case_set | PUT /api/teams/{team_id}/test-case-sets/{set_id} | path＋body | WRITE | auth＋team-exists | inject＋resolve | idempotent_write | ✔ | SET |
| 3.5 | preview_delete_test_case_set_impact | GET /api/teams/{team_id}/test-case-sets/{set_id}/impact-preview | path | READ | auth＋team-exists | inject＋resolve | read | ✔ | ImpactPreview / 400 default set |
| 3.6 | delete_test_case_set | DELETE /api/teams/{team_id}/test-case-sets/{set_id} | path | WRITE | auth＋team-exists | inject＋resolve | **irreversible** | ✔ | cleanup_summary, moved_test_case_count |
| 3.7 | list_test_case_sections | GET /api/test-case-sets/{set_id}/sections | path | READ | auth＋set-exists | **resolve**（set 屬 team） | read | ✔ | SECTION tree |
| 3.8 | create_test_case_section | POST /api/test-case-sets/{set_id}/sections | body: name, description, parent_id? | WRITE | auth＋set-exists | **resolve** | reversible_write | ✘ | SECTION |
| 3.9 | update_test_case_section | PUT /api/test-case-sets/{set_id}/sections/{section_id} | path＋body | WRITE | auth＋set-exists | **resolve** | idempotent_write | ✔ | SECTION |
| 3.10 | delete_test_case_section | DELETE /api/test-case-sets/{set_id}/sections/{section_id} | path | WRITE | auth＋set-exists | **resolve** | **irreversible** | ✔ | （204） |

## 4. Test Run Configs / Items（`/api/teams/{team_id}/test-run-configs`；**多為 ❌ 無檢查，executor 檢查為唯一防線**）

| # | 工具 | Method Path | 參數綁定 | Perm | 端點檢查 | Team | Risk | 冪等 | Projection / 特殊錯誤 |
|---|---|---|---|---|---|---|---|---|---|
| 4.1 | list_test_runs | GET .../test-run-configs | query: status_filter? | READ | ❌ | inject | read | ✔ | TRC[] |
| 4.2 | get_test_run | GET .../test-run-configs/{config_id} | path | READ | ❌ | inject＋resolve | read | ✔ | TRC |
| 4.3 | create_test_run_config | POST .../test-run-configs | body: TestRunConfigCreate | WRITE | ❌ | inject（scope resolve） | reversible_write | ✘ | TRC |
| 4.4 | update_test_run_config | PUT .../test-run-configs/{config_id} | path＋body（schema 排除 status/test_case_set_id/test_case_set_ids） | WRITE | ❌ | inject＋resolve | idempotent_write | ✔ | TRC（不觸發 scope cleanup） |
| 4.5 | set_test_run_status | PUT .../test-run-configs/{config_id}/status | body: status ∈ {draft, active, completed} | WRITE | ❌ | inject＋resolve | reversible_write | ✔（狀態機） | TRC / 422 非法轉移 |
| 4.6 | archive_test_run | PUT .../test-run-configs/{config_id}/status（status=archived 固定） | path | WRITE | ❌ | inject＋resolve | **high_impact** | ✔ | TRC |
| 4.7 | delete_test_run_config | DELETE .../test-run-configs/{config_id} | path | WRITE | ❌ | inject＋resolve | **irreversible** | ✔ | （204，連 items） |
| 4.8 | restart_test_run | POST .../test-run-configs/{config_id}/restart | body: mode(all/failed/pending), name? | WRITE | ❌ | inject＋resolve | **high_impact** | ✘ | new_config_id, created_count |
| 4.9 | list_test_run_items | GET .../test-run-configs/{config_id}/items | query: search, test_result_filter, executed_only, sort, skip, limit | READ | ❌ | inject＋resolve | read | ✔ | ITEM[] |
| 4.10 | add_test_run_items | POST .../test-run-configs/{config_id}/items | body: items[] | WRITE | auth-only | inject＋resolve | **high_impact** | 部分成功（skip dup） | created_count, skipped_duplicates, errors |
| 4.11 | update_test_run_item | PUT .../test-run-configs/{config_id}/items/{item_id} | path＋body | WRITE | auth-only | inject＋resolve | idempotent_write | ✔ | ITEM |
| 4.12 | batch_update_results | POST .../test-run-configs/{config_id}/items/batch-update-results | body: updates[]（每筆 `id` 必填；可含 `test_result` / `assignee_name` / `comment`；允許 assignee-only） | WRITE | auth-only | inject＋resolve | **high_impact** | 部分成功 | processed/success/error_count, error_messages |
| 4.13 | delete_test_run_item | DELETE .../test-run-configs/{config_id}/items/{item_id} | path | WRITE | ❌ | inject＋resolve | **irreversible** | ✔ | （204） |
| 4.14 | upload_run_item_results | POST .../test-run-configs/{config_id}/items/{item_id}/upload-results | path＋multipart: file_ref→files[] | WRITE | ❌ | inject＋resolve | reversible_write | ✘ | uploaded_files（name/size） |
| 4.15 | get_run_statistics | GET .../test-run-configs/{config_id}/items/statistics | path | READ | ❌ | inject＋resolve | read | ✔ | counts, execution_rate, pass_rate, bug 數 |
| 4.16 | list_item_bug_tickets | GET .../test-run-configs/{config_id}/items/{item_id}/bug-tickets | path | READ | ❌ | inject＋resolve | read | ✔ | ticket_number[] |
| 4.17 | add_item_bug_ticket | POST .../test-run-configs/{config_id}/items/{item_id}/bug-tickets | body: ticket_number | WRITE | ❌ | inject＋resolve | reversible_write | ✘ | BugTicket / 400 dup |
| 4.18 | remove_item_bug_ticket | DELETE .../test-run-configs/{config_id}/items/{item_id}/bug-tickets/{ticket_number} | path | WRITE | ❌ | inject＋resolve | idempotent_write（**豁免**） | ✔ | （204） |
| 4.19 | update_test_run_scope | PUT .../test-run-configs/{config_id} | path＋body: 僅 test_case_set_ids（不暴露 deprecated singular 欄） | WRITE | ❌ | inject＋resolve current/target sets | **high_impact** | ✔ | TRC＋cleanup_summary |

## 5. Test Run Sets / Automation（`/api/teams/{team_id}/test-run-sets`）

| # | 工具 | Method Path | 參數綁定 | Perm | 端點檢查 | Team | Risk | 冪等 | Projection / 特殊錯誤 |
|---|---|---|---|---|---|---|---|---|---|
| 5.1 | list_test_run_sets | GET .../test-run-sets | query: include_archived? | READ | ❌ | inject | read | ✔ | TRS[] |
| 5.2 | get_test_run_set | GET .../test-run-sets/{set_id} | path | READ | ❌ | inject＋resolve | read | ✔ | TRS＋members |
| 5.3 | create_test_run_set | POST .../test-run-sets | body: name, description | WRITE | auth-only | inject | reversible_write | ✘ | TRS |
| 5.4 | update_test_run_set | PUT .../test-run-sets/{set_id} | body（schema 排除 status） | WRITE | auth-only | inject＋resolve | idempotent_write | ✔ | TRS |
| 5.5 | archive_test_run_set | POST .../test-run-sets/{set_id}/archive | path | WRITE | ❌ | inject＋resolve | **high_impact** | ✔ | TRS |
| 5.6 | delete_test_run_set | DELETE .../test-run-sets/{set_id} | path | WRITE | auth-only | inject＋resolve | **irreversible** | ✔ | （204，連 configs/files） |
| 5.7 | add_runs_to_set | POST .../test-run-sets/{set_id}/members | body: config_ids[] | WRITE | ❌ | inject＋resolve（set＋configs） | reversible_write | ✔ | TRS detail |
| 5.8 | move_run_between_sets | POST .../test-run-sets/members/{config_id}/move | body: target_set_id?（null=detach） | WRITE | ❌ | **resolve**（config＋target set） | idempotent_write | ✔ | TRC summary |
| 5.9 | generate_run_set_report | POST .../test-run-sets/{set_id}/generate-html | path | WRITE | ❌ | inject＋resolve | reversible_write | ✔（覆寫） | report_id, report_url |
| 5.10 | get_run_set_report | GET .../test-run-sets/{set_id}/report | path | READ | ❌ | inject＋resolve | read | ✔ | exists, report_url |
| 5.11 | list_automation_runs | GET .../test-run-sets/{set_id}/runs | query: status, branch, environment, cursor, limit | READ | auth-only | inject＋resolve | read | ✔ | RUN[] |
| 5.12 | run_automation | POST .../test-run-sets/{set_id}/run-automation | body: suite_id?, environment? | WRITE | auth-only | inject＋resolve | **high_impact** | ✘（觸發 CI） | triggered_suite_ids, run_ids / 422、502 |
| 5.13 | cancel_automation_run | POST .../test-run-sets/{set_id}/runs/{run_id}/cancel | path | WRITE | auth-only | inject＋resolve（run∈set） | **high_impact** | ✔ | RUN / 409 終態 |
| 5.14 | reconcile_automation_run | POST .../test-run-sets/{set_id}/runs/{run_id}/reconcile | body: external_run_id? | WRITE | auth-only | inject＋resolve（run∈set） | idempotent_write | ✔ | RUN |

## 6. Internal Composite（無公開 endpoint）

| # | 工具 | Method Path | 參數綁定 | Perm | Team | Risk | 執行／結果 |
|---|---|---|---|---|---|---|---|
| 6.1 | batch_execute_actions | COMPOSITE（executor internal） | actions[2..50]: tool_name（全部 loopback write enum）, arguments（依 child schema） | WRITE＋逐 child permission | resolve（逐 child，全部屬 conversation team） | dynamic summary 取 child 最高風險（registry 守門宣告 irreversible） | 依確認卡順序 loopback；單一總 deadline；逐 child projection；ambiguous 即停止並整批 unknown |

contract test MUST 比對 child `tool_name` enum 精確等於 registry 全部 loopback write 工具，且不含 composite 自己或 read 工具；未來新增任一 write 即自動納入 schema 並由測試鎖定。每個 child 仍執行原工具 schema、permission、team、credential/sensitive、summary/fingerprint、multipart file_ref 驗證。

## DELETE 豁免（downgrade 理由）

| 工具 | 理由 |
|---|---|
| unpin_entity（1.4） | 僅移除自己的 UserPin 關聯，pin_entity 可完全復原；不觸碰業務資料 |
| remove_item_bug_ticket（4.18） | 僅移除 ticket 關聯，add_item_bug_ticket 以相同 ticket_number 可完全復原 |

registry 驗證測試以此清單為準：DELETE 工具 risk_level ≠ irreversible 者必須出現在豁免表。

## v1 排除清單（明文不提供）

| 端點 | 排除理由 |
|---|---|
| POST /testcases/staging/upload | UI 專用暫存流程；助手附件走 2.13 |
| GET .../test-case-sets/{set_id}/export-csv | 檔案下載且 **CSV 匯出不遮罩 credential**（既有行為）；引導使用者用 UI |
| PUT .../test-case-sets/{set_id}/default | 變更預設 set（ADMIN-only 且影響全 team 預設行為）；v1 精簡 |
| POST /test-case-sets/validate-name、sections reorder/move | UI 輔助操作 |
| by-number 附件端點群 | 與 2.12–2.14 重複（NO-auth 面更大） |
| GET /test-run-configs/{id}/sync | **GET 但有寫入副作用**（重算並落統計），不適合暴露給 LLM |
| /test-runs/{config_id}/records*（legacy Lark） | tcrt-app 對齊面為 test_run_items；legacy Lark 面不納入 |
| items comment / result-history / bug-tickets summary、test-results 檔案端點 | v1 精簡（comment 可經 4.11/4.12 帶入） |
| /test-run-sets/from-test-cases、/search/tp、config-level generate-html、automation-covered-cases | v1 精簡 |
| 跨團隊 lookup | web JWT 面不存在此端點（僅 App Token/MCP 有）；v1 以 team 綁定對話＋2.1/2.4 覆蓋 |

## 盤點確認的既有現況（矩陣依據）

1. web test case 回應**不遮罩** `test_data`（list/detail/by-number 皆然）→ 本矩陣所有 TC projection 強制過 `redact_credential_test_data`。
2. `test_run_configs.py` 全部、多數 `test_run_items.py`、附件與 section 端點**無 in-handler 權限檢查**，且 section 端點**不驗證 set 屬於哪個 team** → executor 強制權限檢查為必要防線、`resolve` 欄工具須做 team 歸屬驗證。
3. `preview_move_test_set_impact` 端點實際要求 **WRITE**（test_cases.py:873），矩陣 Perm 對齊為 WRITE（risk 仍 read，不改資料）。
4. audit 覆蓋不均（pins、configs、多數 items 無業務 audit）→ 歸因與不遺漏由 `assistant_tool_executions` journal 承擔（design D9）。
5. 工具總數：**67**（64 個 loopback 工具＋2 個 local skill 工具＋1 個 internal composite；loopback 分布 read 21、idempotent_write 11、reversible_write 11、high_impact 13、irreversible 8；local skill：`list_skills` / `get_skill` 為 read + team_check=none；2 個 DELETE 豁免降級為 idempotent_write）。同 endpoint 的 2.6/2.8、2.15–2.17、4.4/4.19 以互斥 schema 與 server-fixed operation 拆分，較低風險工具不得接受 scope/delete 欄位。Recipe 檔放在 `prompts/assistant/skills/`，system prompt 注入 catalog；多步驟操作優先 `get_skill` 再執行。

## OpenAPI 路徑校驗（2026-07-21，對 `app.main.app` 實際路由）

已確認全部目標端點存在，並發現 registry 實作必須精確處理的路徑細節：

- **collection 端點尾斜線不一致**（同一 router 內也不同，registry 必須逐一照抄）：
  - **有尾斜線**：`GET /api/teams/`、`.../testcases/`（list/create/2.1/2.5）、`.../test-run-configs/`（4.1/4.3）、`.../test-run-configs/{config_id}/items/`（4.9/4.10）、`.../test-run-sets/`（5.1/5.3）
  - **無尾斜線**：`.../test-case-sets`（3.1/3.3）、`/api/pins`（1.2/1.3）、`/api/test-case-sets/{set_id}/sections`（3.7/3.8）
- **path converter**：附件 int 分支為 `.../testcases/{test_case_id:int}/attachments`（2.12–2.14 用 int-only 分支，另有 `{record_key}`/`{test_case_number}` 分支不採用）；bug-ticket 刪除為 `.../bug-tickets/{ticket_number:path}`（4.18）。loopback 實際 URL 帶具體值即可，但 registry template 與 route 解析測試須用帶 converter 的原始 path。
- 校驗方式（供測試 8.1）：`app import` 成功、可列舉 `app.routes` 的 `path`/`methods`，registry 每個工具 path template 必須能對映一條實際路由與對應 HTTP method。

## Registry 封閉契約（task 1.1 / 1.2 定案）

### Route 與 request schema

- 表內 `.../testcases` 是 `/api/teams/{team_id}/testcases` 的純排版縮寫；`.../test-run-configs` 與 `.../test-run-sets` 同理。表列 collection `/` 代表實際尾斜線且 MUST 保留。附件 route template MUST 使用 `{test_case_id:int}`，bug ticket delete MUST 使用 `{ticket_number:path}`；registry contract test 比對 Starlette `route.path` 原字串，不接受 redirect 後等價。
- 每列 path/query 參數以該 exact route 的 OpenAPI parameters 為完整 allowlist，移除 executor-owned `team_id`；body 以該 route `requestBody` component schema 為完整 allowlist。registry 生成 assistant-specific schema 時 MUST 設 `additionalProperties=false`，不得沿用 Pydantic 預設忽略未知欄位。無 requestBody 的 route 不接受 body。
- 既有 component schema 對應：TestCaseCreate/Update、BulkCreateRequest、BulkCloneRequest、TestCaseBatchOperation、MoveTestCaseSetImpactPreviewRequest、TestCaseSetCreate/Update、TestCaseSectionCreate/Update、TestRunConfigCreate/Update、StatusChangeRequest、RestartRequest、BatchCreateRequest、TestRunItemUpdate、BatchUpdateResultRequest、BugTicketRequest、TestRunSetCreate/Update、TestRunSetMembershipCreate/Move、AutomationRunReconcileRequest、PinCreate；multipart 只接受 `file_ref`，executor 轉成 route 的 files 欄位。測試 MUST 將 registry schema 與 `app.openapi()` component 欄位逐一比對。
- 變體覆寫是封閉差集/子集：2.6 = TestCaseUpdate − `{test_case_set_id,test_case_section_id}`；2.8 = 僅 `{test_case_set_id,test_case_section_id}`；2.15 operation enum 僅 `{update_priority,update_tcg}`；2.16 僅 `{update_section,update_test_set}`；2.17 不暴露 operation/update_data，executor 固定 `operation=delete`；4.4 = TestRunConfigUpdate − `{status,test_case_set_id,test_case_set_ids}`；4.19 僅 `{test_case_set_ids}`。其他工具不得自行增刪 OpenAPI 欄位。

### Team resolver（全部 `resolve` 列的唯一實作）

- `test_case(record_id)` → `TestCaseLocalDB.team_id`；批次先解析每個 record，任一跨 team/不存在即整個 pending fail-closed（不得只跳過跨 team item）。
- `test_case_set(set_id)` → `TestCaseSetDB.team_id`；`section(section_id)` → `TestCaseSectionDB.test_case_set_id` → set.team_id，並驗證 path set_id 相同。
- `test_run_config(config_id)` → `TestRunConfigDB.team_id`；`test_run_item(item_id)` → item.config_id → config.team_id，並驗證 path config_id 相同。
- `test_run_set(set_id)` → set.team_id；`automation_run(run_id)` → run.test_run_set_id → set.team_id，並驗證 path set_id 相同；move/membership 同時解析 source config 與 target set。
- `pin(entity_type,entity_id)` 僅接受 registry enum，依 type 分派上述 resolver；未知 type fail-closed。create/bulk/scope 類的 target set/section/config IDs 必須逐一解析且全等於 conversation team。

### Mutation outcome、確認與 sensitive metadata

- v1 所有 mutation 的 `definitive_pre_mutation_errors = []`。因此 journal started commit 後只有 2xx 是 succeeded；任何 4xx/5xx/timeout/cancel/transport/no-response 全部 unknown 且不重試。schema/permission/team/credential 等 loopback 前拒絕不建立 journal attempt，依 paired synthetic validation-result 契約處理。這是刻意保守的封閉預設，日後要新增 4xx allowlist 必須附 endpoint「副作用尚未開始」測試並修改本矩陣。
- 每個 mutation 的 template 由 risk 固定：`assistant.action.<tool_name>` label；idempotent/reversible 使用 `assistant.warning.confirm_write`，high_impact 使用 `assistant.warning.high_impact`，irreversible 使用 `assistant.warning.irreversible`。target resolver 依上節取 immutable business key（case number、set/config/run/item ID 加 created_at）與 `updated_at`/row version；create 以 parent stable identity＋canonical requested name；batch 以排序後全體 target stable identities digest。affected_count 單筆為 1、batch/list 為輸入去重後數量；delete set/config/run-set 與 scope move另包含 server-side child/membership digest及 cleanup 預估。任一 high_impact/irreversible target/version/membership 解析失敗即 fail-closed。
- `sensitive_input_paths=[]` 適用所有工具；例外不是把 secret 加密後送出，而是 `create_test_case`、`update_test_case`、`bulk_create_test_cases` 套具名 classifier `reject_credential_test_data_value`，命中即在 pending 前拒絕並只保存 redacted paired history。若日後新增允許持久化的 sensitive path，才啟用 AES-GCM envelope，且必須先修改本矩陣。
- output projection 以表內共用 projection 的 exact JSON path allowlist 為準；`＋cleanup_summary` 只套 `CLEANUP`，`ImpactPreview 摘要` 只套 `IMPACT`，`＋page` 只套 `PAGE`。未明列 path 一律丟棄，錯誤 payload 只保留遮罩後 `status,detail`。registry test 以 response model/fixture 遞迴加入 sentinel 欄位，驗證 projected output 僅含 allowlist paths，避免巢狀 object 漏放。

### Coverage 結論

矩陣每列都明示 Perm 與 Team 策略；`inject` 只允許 executor-owned team path，所有 `resolve` 依上節 resolver。registry 載入測試 MUST 逐 67 工具驗證 schema、permission、risk、projection、resolver、confirmation metadata、sensitive metadata；64 個 loopback 工具另驗 route，2 個 local skill 工具驗 in-process handler（不走 route），internal composite 驗完整 child enum；任一缺漏使應用啟動失敗。此契約完成 task 1.1/1.2 的設計定案，後續是照表實作與測試，不再保留實作者自行選擇的安全決策。
