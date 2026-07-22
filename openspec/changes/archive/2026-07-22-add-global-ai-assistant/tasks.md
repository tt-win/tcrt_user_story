# Tasks: add-global-ai-assistant

## 1. 工具矩陣（registry 實作硬前置；以 OpenAPI exact path/schema 為準）

- [x] 1.1 完成 `tool-matrix.md` Registry 封閉契約：OpenAPI exact route/schema、精確 projection、`resource_team_check` resolver；逐 mutation 定義保守 outcome allowlist、deterministic confirmation/stable target/count/warning 與 sensitive metadata
- [x] 1.2 確認 executor 強制權限檢查與 `resolve` 欄 team 歸屬驗證覆蓋全部 64 工具；registry 缺 metadata 即 fail startup

## 2. Config 與資料模型（已完成雛形，待 1.1 後定稿）

- [x] 2.1 在 `app/config.py` 新增 `AssistantConfig`（**enabled 預設 False**、全欄位 `TCRT_ASSISTANT_*` env override＋上下限夾制、`payload_encryption_key`、global/per-user/per-worker active-turn limits）並掛進 `AIConfig`
- [x] 2.2 在 `app/models/database_models.py` 新增九張表 ORM：conversations（conversation_key、scope/source team、fenced lease、message/turn counters）、turns（turn_seq、request_fingerprint、event/message cursors、admission release CAS）、events、messages（server-normalized tool pairing）、pending_actions（雙欄參數、execution deadline/keys、canonical summary＋stable fingerprint、無 raw result sink）、tool_executions（不可重用 source_conversation_key）、uploaded_files（SHA-256＋relative_path）、rate_limit_buckets（user/hour 原子 quota）、runtime_counters（跨 worker in-flight admission）；補 unique/index/FK/checks
- [x] 2.3 建立 main alembic migration（upgrade/downgrade），以 disposable DB 驗證 SQLite 升降級
- [x] 2.4 實作 `app/services/assistant/conversation_service.py`（conversation_key、scope_type/team tombstone 唯讀、per-user 過濾、冪等鍵＋request fingerprint、turn_seq、原子 quota/runtime admission reservation、admission release CAS/reconciliation、owner/recovery-CAS lease fencing、pending 終態 synthetic result、server-generated execution/LLM keys、journal、event/message seq、relative attachment metadata）——functional smoke test 17/17 通過（idempotent replay/reuse、admission限流、lease、pending/confirm/cancel CAS、recovery job）
- [x] 2.5 實作 Assistant sensitive-payload helper（`app/services/assistant/crypto.py`：32-byte key validation；AES-256-GCM versioned envelope＋AAD execution/tool；roundtrip 與 AAD mismatch 已驗證）；registry sensitive_input_paths/classifier 整合留待 3.1/3.2；credential 值於 pending 前拒絕留待 executor（3.3）

## 3. 工具目錄與 loopback 執行

- [x] 3.1 實作 `tool_registry.py`（`AssistantTool` dataclass 含 risk/projection/team_check/confirmation 元資料；載入時驗證名稱唯一、DELETE 預設 irreversible 且僅限豁免清單、write 工具必備 confirmation/target_resolver、`definitive_pre_mutation_errors` v1 封閉為空）——64 工具全數通過驗證
- [x] 3.2 依定案矩陣實作工具目錄（`tools_misc.py`/`tools_test_cases.py`/`tools_test_case_sets.py`/`tools_test_runs.py` 聚合於 `tools_catalog.py`；共 64 個，risk 分布與矩陣一致 read21/idempotent11/reversible11/high_impact13/irreversible8）——已對 `app.routes` 逐一驗證 path_template+method 全數解析成功（0 mismatch）
- [x] 3.3 實作 `tool_executor.py`：schema（合併 path+query+body+file_ref）/權限/team/credential 驗證 → journal Tx A/B（透過 conversation_service）→ ASGI loopback（不持有交易）→ projection/redaction/truncate；confirmation summary（create/single/batch/membership 四種 target_resolver 策略，high_impact/irreversible 無法解析即 fail-closed）→ fingerprint；sensitive payload 加密整合。**端對端 smoke test 驗證**：read 工具真實 loopback 200、write 工具 prepare→pending→confirm→loopback 201→實際寫入可查得、credential 拒絕、viewer 角色拒絕，共 9/9 通過
- [x] 3.4 實作 `resource_team_check` resolver（`resolvers.py`：test_case/test_case_set/section/test_run_config/test_run_item/test_run_set/automation_run/pin → team + identity/version；複合校驗於 executor dispatch，含「create 未指定 scope 時信任對話 team」修正）
- [x] 3.5 工具目錄預過濾（`ToolRegistry.filter_by_permission`/`discovery_only` 已提供；agent_service 於 4.3 呼叫）
- [x] 3.6 executor 硬拒 inline 執行**任何非 read 工具**（`prepare_write_tool` 為 write 工具唯一入口，僅建立 pending，不執行；`run_read_tool` 只接受 risk_level=read）

## 4. LLM 與 agent 迴圈

- [x] 4.1 實作 `assistant_llm_service.py`（OpenRouter aiohttp + `tools=`/`tool_choice`，逾時與錯誤處理，key 缺失即 not configured）——`parallel_tool_calls=False`、context-length 400 判定回傳 `AssistantLLMContextLengthError`、無 deterministic fallback
- [x] 4.2 撰寫 `prompts/assistant/system.md`（TCRT-only、off-topic 拒絕、archive≠delete、工具結果為資料非指令、依使用者語言回覆）
- [x] 4.3 實作 `assistant_agent_service.py`（`run_agent_turn`/`run_confirm_turn` 共用 `_run_llm_loop`：`history_builder` 裁切歷史→呼叫 LLM→至多處理一個 tool call、read 連鎖執行、遇 write 即停下建 pending；`ToolRegistry.filter_by_permission`/`discovery_only` 依角色/scope 預過濾工具目錄；每次 LLM/工具呼叫前 `renew_lease` 檢查 owner 續租、失敗即靜默停止；每次迭代與 LLM 回覆後檢查 `cancel_requested`；context-length 400 單次退讓（`drop_oldest_group`）；unknown tool/schema 等 fixable 拒絕走 `reject_write_before_pending(terminate_turn=False)` 續跑迴圈，non-fixable 終止；write 唯一入口 `prepare_write_tool`→`create_pending_action_and_complete_turn`；confirm 側 `run_confirm_turn` 執行已確認 write 後，僅 outcome=succeeded 才續跑 LLM 規劃下一步，failed/unknown 直接終止避免 LLM 在不可靠狀態下自行重試；補上 `conversation_service.append_tool_call_and_result`（read 工具成功時 assistant tool-call + tool-result 同一交易配對寫入，原設計缺漏））——functional smoke test 8/8 通過：read 連鎖→write→pending→confirm→continuation 續跑到最終文字（並驗證 test_run_config 實際落地）、max_iterations 終止、unknown tool 可恢復續跑、cancel 於 LLM 呼叫前生效、viewer 角色的 write 工具被目錄預過濾。**已知簡化**：lease owner 驗證與後續 event/message 寫入未強制同一交易（僅以獨立 `renew_lease` 呼叫作 liveness 防線；各終態寫入本身仍有 CAS 保護，不影響資料正確性，但非 spec 逐字要求的最嚴格實作）

## 5. API 端點

- [x] 5.1 `GET /api/assistant/availability`（enabled+permission 合併、fail-closed）——`config.enabled and llm.is_configured()`；同一 gate 複用於所有 endpoint 開頭的 `_require_enabled`
- [x] 5.2 對話 API：list/create/delete（進行中 turn 回 409）、`GET .../messages`（依 turn_seq→message_seq、含工具執行與確認狀態含 unknown、turn→conversation→user 過濾）——新增 `conversation_service.load_conversation_history_view`（join turn 取得 turn_seq/turn_key、left-join 目前 pending action 狀態/摘要）與 `list_uploaded_files_for_conversation`；delete 先查附檔清單再刪 DB 再刪實體檔
- [x] 5.3 `POST .../conversations/{id}/messages`（multipart、client_message_id＋request fingerprint；同 ID 不同 payload 409；先取得 per-worker slot，TurnStart 原子 quota bucket＋message_count＋global/user admission＋lease＋turn_seq＋turn；unique loser rollback 不扣 quota/admission；附檔 SHA-256/relative path；detached runner＋DB-tail SSE）——**修正**：`start_turn` 原本只用 `IntegrityError` 判斷 unique race loser，實測發現同 client_message_id 併發時有一路徑會先在 lease CAS 失敗（`AdmissionDeniedError`）而非 turn unique constraint；已改為兩者皆觸發「重新查詢既有 turn→fingerprint 相符即 replay，查無則原樣拋出」，避免誤判真正的 admission 拒絕
- [x] 5.4 `POST .../turns/{key}/stop`（cancel_requested）；SSE subscriber 以 `(turn_key, after_seq)` 從 DB gap-free tail 到 terminal，disconnect 不取消 runner、跨 worker 可續傳——`GET .../turns/{turn_key}/events?after_seq=` 供斷線重連；`_tail_turn_events` 0.5s poll＋~15s keepalive
- [x] 5.5 `POST .../actions/{id}/confirm|cancel`：重播既有 continuation 僅 DB-tail；新 confirm 先 non-blocking 取得 per-worker slot，再重驗權限/scope/resource 與 stable identity/version/membership fingerprint（變更→CONFIRMATION_STALE 重新確認）；Tx A 原子 fenced lease＋continuation turn/turn_seq＋admission＋CAS(fingerprint)＋execution deadline＋journal；slot/Tx 失敗不認領 pending；Tx B outcome；所有無真實 result 終態清 payload＋synthetic pairing——重驗邏輯解密 execution_payload 取回 path/query/body_params 重跑 schema/permission/scope/team/summary/fingerprint；新增 `conversation_service.update_pending_summary_cas`（fingerprint 改變時 CAS 更新摘要+409）與 `expire_pending_now`（權限/scope/summary 失效時 CAS expire+synthetic result）；`tool_executor.combined_schema` 由 module-private 改公開供 API 層重用；confirm 側同樣有 `IntegrityError`/`AdmissionDeniedError` 併發 race 重查 continuation 的修正
- [x] 5.6 在 `app/api/__init__.py` 註冊 router；Pydantic models 放 `app/models/assistant.py`——另在 `app/main.py` 新增全域 `AssistantError → HTTPException` exception handler（endpoint 直接呼叫 `get_conversation_owned` 等擁有權檢查時漏接會变成 500，改用全域 handler 統一轉換，避免每個 endpoint 各自 try/except 遺漏）

**驗證**：`smoke_assistant_api.py`（14 檢查：availability/建立/列表/刪除/訊息歷史/送訊息 read-chain→write→pending/幂等重播/confirm→執行→continuation/重複 confirm 重播/取消/stop 中途取消/斷線重連 replay/跨使用者隔離 404）、`smoke_race.py`（5 併發相同 client_message_id 只建立 1 個 turn、quota 只扣 1 次）、`smoke_confirm_race.py`（5 併發 confirm 同一 pending action 只實際執行 1 次）均通過；`ruff check app scripts database_init.py`、`openspec validate --strict` 通過。**未跑**：`pytest app/testsuite`（本次改動未觸及既有測試涵蓋範圍，未執行全套回歸）。

## 6. 檔案上傳與 retention

- [x] 6.1 訊息端點支援附檔：server-random stored name 存 `assistant_tmp/{conversation_key}/`，DB 保存 SHA-256＋safe relative_path、重用 containment helper；大小/數量限制；內容不進 LLM——已隨 5.3 一併實作（`app/services/assistant/attachment_storage.py` 重用 `app/services/attachment_storage.py` 的 root/containment；新增 `AssistantConfig.upload_retention_hours`，預設 24h，獨立於 conversation `retention_days`）；已於 smoke test 以真實 multipart 附檔驗證存檔+idempotent replay 不重存
- [x] 6.2 實作 `upload_test_case_attachment`、`upload_run_item_results` 工具（file_ref 驗證＋multipart loopback）——兩工具 registry 宣告已存在（3.2）；本次補上執行路徑：`_run_llm_loop` 在 write 分支對 `multipart_file_param` 工具先 fail-fast 解析 `file_ref`（`conversation_service.get_uploaded_file_owned` 限本 turn，不存在即 fixable 拒絕、不建立 pending）；`tool_executor.prepare_write_tool` 新增 `resolved_file_ref` 參數存進 `execution_payload["file_ref"]`（僅存 `{turn_id, attachment_index}` 參照，原始 bytes 不落 DB）；`run_confirm_turn` 於呼叫 loopback 前依 file_ref 重新讀取磁碟內容（`attachment_storage.resolve_stored_path`），檔案已不存在時直接標 failed 收尾（非 unknown，因確定從未送出 loopback）；`execute_confirmed_write`/`_loopback` 新增 `multipart_file` 參數組出 httpx multipart 請求；confirm 端點的 schema 重驗證需以 `file_ref` 的 attachment_index 合成字串通過 required 檢查。**過程中發現並修正一個既有（3.3 遺留）bug**：`tool_executor._build_path` 用 `str.format()` 組 request path，但 4 個工具（`list_test_case_attachments`/`upload_test_case_attachment`/`delete_test_case_attachment`/`remove_item_bug_ticket`）的 `path_template` 含 Starlette route converter 語法（`{test_case_id:int}`、`{ticket_number:path}`），`str.format` 不認得 `:converter` 部分會拋 `ValueError`；因先前 smoke test 從未實際呼叫這 4 個工具的 loopback 才未被發現。修正：組路徑前先以正規表示式剝除 `:converter` 只留 `{name}`。——functional smoke test 4/4 通過（invalid file_ref fixable 拒絕不建 pending、valid file_ref 建立 pending、confirm 後 multipart loopback 200 且 test case attachments_json 實際寫入、`list_test_case_attachments` 路徑轉換器修正後可正常讀取），另以獨立煙霧測試驗證 7 支既有 smoke script 對 `_build_path` 修正無回歸
- [x] 6.3 scheduler retention job（過期對話/relative 暫存檔/無 DB row 的 orphan temp files/rate buckets、逾時 pending＋synthetic result、execution deadline＋lease 雙過期的孤兒 executing → recovery-key fencing → unknown、admission release/reconciliation）——新增 `app/services/assistant/retention.py`（`AssistantRetentionManager`，仿 `automation/background.py` 的兩條獨立 asyncio ticker：60s recovery loop 呼叫既有 `recover_orphan_turns`/`recover_orphan_executing_pending`/`expire_stale_pending`；600s purge loop 呼叫新增的 `conversation_service.purge_expired_conversations`（跳過仍有 running turn/executing pending 者，回傳其附檔 relative_path 供刪實體檔）、`purge_expired_uploaded_files`（獨立於對話刪除，`upload_retention_hours` 到期即清）、`purge_expired_rate_limit_buckets`、`reconcile_admission_counters`（以 `admission_released=false` turns 為權威重建 global/per-user runtime counter，修正非預期崩潰造成的計數漂移））；已在 `app/main.py` 的既有 leader-election 背景服務啟停流程掛上/卸下（僅 `AssistantConfig.enabled=true` 時啟動，避免功能關閉時仍跑無用 ticker）——functional smoke test 6/6 通過（orphan turn 因 lease 過期收斂為 failed、逾期 pending 標 expired 且清 payload、超過 retention_days 的對話被刪、過期附檔 DB row 被清、過期 rate-limit bucket 被清而未動到當前小時 bucket、人為造成漂移的 global admission counter 被重建為正確值）

## 7. 前端 widget（視覺與狀態規格見 `ui-design.md`；完整可運行範例見 `ui-mock.html`）

- [x] 7.1 建立 `app/static/css/assistant-widget.css`（依 `ui-design.md`＋`ui-mock.html`；class 加 `tcrt-assistant-` 前綴、全用 TCRT `var(--tr-*)` token）——含 FAB/panel/z-index/兩級確認卡/工具活動/composer 等全部 mock 狀態；`stylelint` 僅既有慣例允許的 `#fff`（white-on-color）警告，`npm run lint` 通過
- [x] 7.2 建立 `app/static/js/assistant-widget.js` 骨架（IIFE、availability gating＋cache、mount/destroy、開關與焦點管理）；SSE parser/確認卡狀態機/取消流程抽成純函式模組——純函式（`parseSSEChunk`/`parseSseEventId`/`confirmTier`/`formatConfirmTargetLine`/`turnStateReducer`/`pendingActionRenderMode`/`resolvedBadgeClass`/`escapeHtml`）宣告於檔案頂層（IIFE 之外）供 `vm.runInContext` 測試存取，仿 `bulk-test-data.test.mjs`
- [x] 7.3 `base.html` 加入 css/js；三語系 locale 加 `assistant` namespace（含 registry canonical action/warning keys，三語 coverage gate）——65 個 `assistant.action.*`（覆蓋全部 read/write/composite 工具）＋3 個 `assistant.warning.*`＋widget UI 文案，三語系皆補齊，`check-i18n-coverage.mjs` 0 missing/0 hardcoded
- [x] 7.4 對話 plumbing（list/resume/create/delete、歷史渲染含 seq 續傳、per-team localStorage、teamChanged → stop+切換對話）——`tcrt_assistant_conv_team_<id>`/`tcrt_assistant_conv_global` 記住每個 scope 最近對話；`GET /conversations` 無法直接篩 global scope，前端以 `scope_type`/`team_id` 客戶端過濾；`teamChanged`/`teamCleared` 監聽觸發 stop + 切換
- [x] 7.5 SSE client 與串流 markdown（fetch+getReader、lazy-load marked+DOMPurify、rAF 節流、escape fallback）——`marked@4.3.0`+`dompurify@3.0.6`（pinned CDN）延遲載入，失敗維持 `escapeHtml` 純文字 fallback；連結加 `target=_blank rel=noopener`（`DOMPurify.addHook`）；`text_delta` 目前後端每 turn 僅送一次完整文字（v1 非串流 completion），前端以可累加 buffer 設計保留未來真串流的擴充空間
- [x] 7.6 停止流程（顯式 stop API；「停止中」→「已取消」兩段狀態）——`turnStateReducer` 明確區分 stopping/cancelled 兩態，node:test 覆蓋
- [x] 7.7 確認卡（僅渲染 server canonical summary i18n keys；缺欄 fail-closed；composer 鎖定、confirm/cancel＋DB-tail SSE、resume pending）——`target_label`/`target_id` 一律先 `escapeHtml` 才嵌入樣板，不當 HTML/i18n key 解譯；`warning_key` 由前端依 `risk_level` 推導（summary payload 本身不含 registry 的 `warning_key` 屬性）
- [x] 7.8 附件選取/拖放、錯誤重試（以 client_message_id 重播）、FAB 未讀、a11y（Enter/Shift+Enter/IME、Esc、aria）——拖放未實作（僅檔案選取按鈕，`<input type=file multiple>`），其餘皆完成；error-bubble 重試沿用同一 client_message_id 重新呼叫 sendMessage

**已知簡化／未盡事項**（誠實記錄）：附件僅支援點擊選取，未實作拖放區；`GET /conversations` 無 `scope_type=global` 專屬篩選參數，改由前端撈 `limit=20` 後客製過濾（極端情況下近期對話較多時，global 對話可能被擠出視窗外而不在歷史下拉中顯示）；未做真實瀏覽器互動驗證（見 8.10）。

## 8. 測試與驗證

- [x] 8.1 `test_assistant_tool_registry.py`：名稱唯一、DELETE 必 irreversible、路由解析、OpenAPI request contract、server-fixed operation 與低風險 schema 不含 scope/delete 欄位；response model/fixture 巢狀 sentinel 驗證 projection 只輸出 exact JSON path allowlist——9 項通過
- [x] 8.2 `test_assistant_permissions.py`：權限矩陣（含無 in-handler 檢查端點的 executor 強制檢查；逐工具至少一個授權案例）——64 工具皆逐一 parametrize 驗證 VIEWER/USER/SUPER_ADMIN 三種角色 x risk hierarchy，共 66 項通過
- [x] 8.3 `test_assistant_data_boundary.py`：credential 不入 LLM/messages/SSE/journal；pending 無 raw result sink；projection→redaction→truncate；credential 寫入／覆寫拒絕時保存 redacted paired history；prompt injection 無法影響 canonical confirmation summary——6 項通過。**過程中發現並修正兩個真實 bug**：(1) `update_test_case`/`delete_test_case` 的 `target_resolver="single"` 缺 `resource_team_resolver`，導致這兩個工具的確認卡永遠 fail-closed（完全無法使用）；已補上 `resource_team_resolver="test_case"`（不影響其 `team_check="inject"` 的 scope 驗證邏輯）。(2) write 工具的拒絕/成功路徑（`reject_write_before_pending`／`create_pending_action_and_complete_turn`／`append_tool_call_and_result`）先前把 LLM 原始 `call.arguments`（可能含 credential 明文）直接存進 `tool_calls_json`，違反「credential 原值不得進 messages」——已改為在 `conversation_service.py` 這三個持久化方法內統一套用 `apply_credential_redaction`（defense-in-depth，不依賴每個呼叫端各自記得遮罩）
- [x] 8.4 `test_assistant_agent_loop.py`：mock loop/caps/cancel；disconnect 不取消 detached runner；跨 worker DB replay-then-live 無 gap；stale lease owner/recovery race 被 fencing；execution deadline 不誤用 pending TTL；exchange-group character budget/context 400 單次退讓不拆 tool pair；normalized missing/reused provider IDs；read→write／多 call 防禦與隔離——12 項通過（service 層直接驅動 `run_agent_turn`，disconnect/跨 worker replay 移至 8.6 的 HTTP 層驗證）
- [x] 8.5 `test_assistant_confirmation_flow.py`：非 read inline 拒絕；server canonical summary＋stable identity/version/membership fingerprint；pending/confirm transactions；CAS/recovery races；normalized IDs；pre-pending rejection與cancel/expire/unknown synthetic pairing；mutation 2xx vs allowlisted 4xx vs timeout/cancel/transport/5xx outcome；execution payload 清除；unknown/fenced lease；兩級卡與 ownership——8 項通過，含 5 併發 confirm race／CONFIRMATION_STALE／unknown outcome（`_loopback` 拋例外）
- [x] 8.6 `test_assistant_conversations_api.py`：隔離、scope_type/team tombstone 唯讀、刪除 409、同 ID 同 fingerprint 重播／不同 fingerprint 409、turn_seq→message_seq、relative attachments、fresh global seed＋user counter first-use savepoint race、跨 conversation/worker 原子 quota＋global/user admission、terminal/recovery release once與以 unreleased turns 為權威的 reconciliation、message/confirm per-worker slot、unique loser不扣 quota/admission、sub-resource team 拒絕——8 項通過（含 5 併發相同 client_message_id race、per-worker slot=0 強制 503、跨 team sub-resource 拒絕）
- [x] 8.7 journal 稽核測試（source_conversation_key 刪除後可查且 SQLite ID 重用不混淆、attempt/確認/unknown、參數遮罩、mutation fail-closed）——4 項通過。**過程中發現並修正第三個 credential 遮罩缺口**：`start_read_tool_journal` 的 `arguments_json` 先前由呼叫端未遮罩的 `body_params` 直接序列化存入；已在該方法內對傳入的 JSON 字串統一 parse→`apply_credential_redaction`→re-serialize
- [x] 8.8 前端 `node:test`：SSE parser（跨 chunk/多事件/殘缺行）、確認卡狀態機、取消流程——19 項通過（`app/testsuite/js/assistant-widget.test.mjs`）
- [ ] 8.9 全套驗證：`uv run pytest app/testsuite -q`、`uv run ruff check app scripts database_init.py`、`node --check`、`npm run lint`、`node scripts/check-i18n-coverage.mjs`、`openspec validate add-global-ai-assistant --strict`
- [ ] 8.10 E2E 手驗（dev server）：FAB→查詢→建 run 回報→刪除確認卡→viewer 唯讀→off-topic 拒絕→停止/取消→credential 遮罩肉眼確認——**環境無無頭瀏覽器工具**（Chrome MCP 斷線、未裝 Playwright）；已徵詢使用者，選擇「稍後自行手動測試」。已完成輕量替代驗證：啟動 dev server 以 curl 確認 `assistant-widget.css`/`.js` 皆 200 且正確 content-type、`base.html` 渲染確實含兩個新增 tag、`/api/assistant/availability` 未帶認證回 401（非 500）。真實瀏覽器互動（開關面板、確認卡點擊、markdown 渲染、a11y 鍵盤操作）待使用者自行驗證

## 9. 寫入工具結果可見性修正

- [x] 9.1 confirm continuation 在 loopback 前發出 `tool_started`，且 succeeded/failed/unknown 的 `tool_finished` 皆帶投影後權威結果
- [x] 9.2 recovery 路徑原子寫入 terminal SSE event，orphan executing 額外寫入 `tool_finished(outcome=unknown)`，確保 DB-tail 可結束
- [x] 9.3 history API 序列化 tool result 與 pending outcome，widget 重載後重建 succeeded/failed/unknown 結果卡
- [x] 9.4 widget 即時呈現 write `tool_finished.result`，confirm 改為確認中→依權威 outcome settle，API 失敗從 history 恢復；三語 i18n/a11y 完整
- [x] 9.5 新增 create set/run/run set、failed/unknown、empty/failing LLM、confirm stale、history reload、recovery terminal 的後端與前端回歸測試
- [x] 9.6 完成獨立紅隊對抗性審查，修正其提出的所有 P0/P1 與任何會導致結果漏報/假成功/串流不終止的問題

## 10. 同一要求多動作一次確認

- [x] 10.1 更新設計與 delta specs：所有參數完整的 write、逐項摘要／stable fingerprint、順序執行、新 ID 相依限制與 unknown-stop 語意
- [x] 10.2 實作 `batch_execute_actions` composite registry 工具、逐子動作 schema／權限／team／credential 驗證、一次 pending 與 confirm executor
- [x] 10.3 widget 顯示完整 escaped 目標清單，並更新 system prompt 引導模型只提交已解析的明確目標
- [x] 10.4 新增 schema、去重、跨 team、stale、順序、部分成功／unknown-stop、單次確認與結果呈現測試
- [x] 10.5 完成 OpenSpec／lint／targeted tests／graphify update，並由獨立紅隊重複審查至無 P0/P1

## 11. 背景版本更新不得清除使用者輸入

- [x] 11.1 將背景版本變更由強制 reload 改為顯示使用者主動更新按鈕
- [x] 11.2 新增前端測試，驗證偵測新版本不呼叫 reload 且不提前 acknowledge timestamp

## 12. 寫入結果精簡與 confirm 時序修正

- [x] 12.1 更新設計與 delta specs：結果只顯示具 a11y 的狀態圖示，confirm continuation 不輸出 terminal 純文字
- [x] 12.2 將即時與歷史 write result 改為 icon-only，不渲染 projection payload 或狀態文字
- [x] 12.3 confirm succeeded 後仍允許新 tool call，但抑制 terminal text，避免「已完成」後又顯示「準備執行」
- [x] 12.4 新增前後端回歸測試並完成 targeted gates
- [x] 12.5 獨立紅隊反覆審查至無 P0/P1，完成 graphify 與工作紀錄

## 13. 動作容器與狀態圖示合併

- [x] 13.1 更新設計與 delta spec：工具活動、確認摘要與結果共用同一容器，圖示固定於標題右側
- [x] 13.2 合併 live/history 渲染路徑，移除獨立結果氣泡與文字狀態 badge
- [x] 13.3 新增前端回歸測試並完成 targeted UI gates
- [x] 13.4 自我審查、graphify 與工作紀錄

## 14. 工具動作名稱完整翻譯

- [x] 14.1 盤點 registry 全部 read/write/composite 工具與三語 `assistant.action` 覆蓋缺口
- [x] 14.2 補齊全部工具的明確三語動作名稱，未知工具改用翻譯過的泛用名稱，不顯示 method identifier
- [x] 14.3 動態工具步驟支援語言切換即時重譯，並新增 registry-to-locale 完整覆蓋測試
- [x] 14.4 完成 targeted gates、自我審查、graphify 與工作紀錄

## 15. 對話標題自動摘要

- [x] 15.1 更新 delta specs：`assistant-conversations` 新增對話標題自動摘要 Requirement（CAS 語意、fallback、不覆蓋使用者自訂標題），`assistant-widget-ui` 新增近期對話清單顯示標題 Requirement
- [x] 15.2 新增 `title_service.generate_title`（借用既有 `AssistantLLMService`，空 tools）與 `prompts/assistant/title.md`
- [x] 15.3 `ConversationService` 新增 `_capture_first_turn_key_for_title`／`set_title_if_absent`／`maybe_generate_title`，並將背景觸發（以 `conversation_key` 為 CAS 鍵，避免 SQLite PK 重用）接入全部 5 個會終結首個 turn 的路徑（`complete_turn_release_lease`、`create_pending_action_and_complete_turn`、`reject_write_before_pending`、`recover_orphan_turns`、`recover_orphan_executing_pending`），維持各函式既有對外回傳契約不變
- [x] 15.4 新增回歸測試：一般文字首輪生成標題、使用者自訂標題不被覆蓋、LLM 未設定/失敗 fallback 截斷、write-first 首輪仍能 fallback 生成標題、5 個終結路徑的觸發/不觸發、`generate_title` 對非預期例外的 fallback（紅隊發現的 P0）
- [x] 15.5 完成 targeted gates（ruff／pytest／openspec validate）、獨立紅隊反覆審查至無 P0/P1、graphify update 與工作紀錄

## 16. 新對話資料範圍提示改為一次性 toast

- [x] 16.1 更新 delta spec：移除面板固定 scope note 橫幅描述，新增「新對話的資料範圍提示」Requirement（僅新/空對話顯示一次、自動淡出、隨捲動移出視野）
- [x] 16.2 移除 `mount()` 內固定的 `.tcrt-assistant-scope` 橫幅與其 CSS；新增 `addScopeNoticeToast()`，於 `renderHistoryMessages` 偵測到對話尚無訊息時插入訊息串列頂端，沿用既有 `assistant.scopeNotice`／`assistant.scopeDataEgress` 三語文案（無新增 i18n key）
- [x] 16.3 新增 `.tcrt-assistant-scope-toast` 淡出動畫（`transitionend` 後移除節點），對話有新訊息時隨既有捲動邏輯自然移出視野
- [x] 16.4 完成 targeted gates（`node --check`、widget JS 測試、stylelint、i18n coverage、openspec validate）

## 17. 附件上傳未串接進 LLM 對話語境

- [x] 17.1 更新 delta spec：`assistant-conversations`「聊天附檔暫存與並發冪等」補上「LLM 必須被告知本回合可用的 file_ref」與「file_ref 不可跨 turn 引用」兩條規則與對應 scenario
- [x] 17.2 新增 `ConversationService.load_attachments_for_turn`，僅查單一 turn_id（比照 `_resolve_file_ref` 的 turn 範圍，不做跨 turn 彙整）
- [x] 17.3 `history_builder.py` 的 `_message_to_openai`／`build_exchange_groups`／`build_llm_messages` 新增可選 `attachments_by_turn` 參數，把附件清單（file_ref、原始檔名、content_type）附加到對應 turn 的 user 訊息「送給 LLM 的內容」，不寫回持久化的 `AssistantMessage.content`
- [x] 17.4 `_run_llm_loop`（`run_agent_turn`／`run_confirm_turn` 共用）在迴圈外查一次本 turn 附件並傳入 `build_llm_messages`
- [x] 17.5 新增回歸測試：驗證 LLM 收到的 messages 含附件清單、前端歷史仍顯示原始使用者輸入、file_ref 不可跨 turn 引用；順帶修復 `test_assistant_confirmation_flow.py` 既有 `test_repeat_confirm_replays_without_reexecuting` 被背景標題生成汙染 `fake.calls` 的潛在 flaky 風險（`confirm_db` fixture 統一關閉背景標題生成)
- [x] 17.6 完成 targeted gates（ruff／pytest／openspec validate）、獨立紅隊反覆審查兩輪皆無 P0/P1、工作紀錄

## 18. path 參數型別誤宣告導致的工具執行失敗（黃色警告不刪除）

- [x] 18.1 更新 delta spec：`assistant-tool-execution` 新增「path 參數型別必須對應真實端點型別」Requirement 與對應 scenario
- [x] 18.2 `AssistantTool` 新增 `path_param_schemas` 欄位（預設空字典，不影響既有工具），`to_llm_schema()` 改用該欄位覆寫預設 `"type": "integer"`；registry 驗證新增 typo 防呆（`path_param_schemas` 鍵須為 `path_params` 子集）
- [x] 18.3 修正 3 個使用者/紅隊發現的字串型 path 參數：`delete_test_case_attachment.target`、`remove_item_bug_ticket.ticket_number`、`unpin_entity.entity_type`（沿用既有 body schema 的 enum)
- [x] 18.4 新增通用 registry drift 測試：以 `inspect.signature` 交叉比對所有 loopback 工具的 path 參數宣告型別與真實 FastAPI endpoint 的 Python 型別註記；此測試額外揪出 4 個先前未被回報的同源 bug（`get_test_case`／`update_test_case`／`delete_test_case`／`move_test_case_scope` 的 `record_id`，真實端點是字串,可能是 Lark record id `item.lark_record_id or str(item.id)`），一併修正
- [x] 18.5 修正因型別修正而破壞的既有測試（`record_id` 從 int 改傳 str）、新增端到端測試驗證 `delete_test_case_attachment` 帶真實字串檔名可成功建立 pending（不再是 schema_invalid）
- [x] 18.6 紅隊反覆審查揪出「schema 型別修正後,同一套 record_id 解析語意必須貫穿整條 pipeline」的三處遺漏,逐一修正並各補一個用真正非數字 lark_record_id 的回歸測試（`str(int)` 偽裝的測試無法揪出這類 bug,已記取教訓)：
  - `resolvers.resolve_test_case_team`（team 驗證,原本查無 lark_record_id 會誤判 team_mismatch)
  - `resolvers.resolve_test_case_identity`（confirmation summary,原本查無會讓 update 退化成 target_type=unknown、delete/move 直接 confirmation_summary_unresolvable)
  - `tool_executor.check_update_overwrites_existing_credential`（design D8 credential 覆寫保護,原本查無會靜默回 False——fail-open,嚴重度高於前兩處的「拒絕」）
  - `resolve_test_case_ref_team` 收斂為委派 `resolve_test_case_team`,消除原本兩份幾乎重複的解析邏輯
- [x] 18.7 完成 targeted gates（ruff／pytest／openspec validate）、獨立紅隊反覆審查四輪皆已收斂（前三輪各修正一個真實問題,第四輪確認已修正的部分無殘留問題）、工作紀錄
- [ ] 18.8（已知後續、本次刻意不做，紀錄供下次接續）：`preview_move_test_set_impact`／`batch_update_test_cases`／`batch_move_test_cases`／`batch_delete_test_cases` 的 `record_ids` 陣列仍宣告 `s_array(s_int())`,同一 bug class 尚未涵蓋批次工具——對 Lark 同步 test case 目前會乾淨 schema_invalid 拒絕（非本次修法引入的新風險,維持既有「無法操作」現況),但要讓批次操作也支援 Lark record id,需同時重構 `tool_executor.py` `build_confirmation_summary` 批次分支目前假設 `record_ids` 全為整數的排序/型別邏輯,範圍超出本次「附件刪除」bug 的直接修復,留待下次獨立處理。

## 19. 附件上傳無圖示/連結/進度回饋

- [x] 19.1 更新 delta specs：`assistant-conversations` 補上 `attachments_saved` 事件、歷史 `attachments` 欄位、下載端點擁有權比對、24h 保存期取捨的 scenario；`assistant-widget-ui` 新增「附件上傳狀態與可下載連結」Requirement
- [x] 19.2 後端：附件存檔迴圈跑完、`spawn_reserved` 之前發出 `attachments_saved` SSE 事件（只含實際保存成功的附件）；新增下載端點（沿用 `get_turn_owned`／`get_uploaded_file_owned`，`Content-Disposition` 強制 attachment）；`MessageHistoryItem`／`load_conversation_history_view` 新增 `attachments` 欄位
- [x] 19.3 前端：`addUserBubble` 支援附件圖示（pending/done/failed 三態，`role=status` 與 aria-label／title），`sendMessage()` 送出當下立即顯示 pending 狀態、拿到 turn_key 後補下載連結、收到 `attachments_saved` 事件後轉 done、失敗時全部轉 failed；`renderHistoryMessages` 讀取歷史 `attachments` 欄位直接呈現 done 狀態；順手補上 `UPLOAD_TOO_LARGE` 錯誤碼的三語 i18n（之前會 fallback 顯示未在地化英文原文）
- [x] 19.4 新增後端測試（`attachments_saved` 事件內容、歷史 `attachments` 欄位、下載端點成功／404／跨使用者拒絕）
- [x] 19.5 完成 targeted gates（ruff／pytest／node --check／widget JS 測試／stylelint／i18n coverage／openspec validate）；前端 DOM 邏輯因本機 Playwright 瀏覽器快取損壞，本輪未能實際瀏覽器視覺驗證，僅程式碼追蹤＋自動化測試＋紅隊審查

## 20. 附件 pill 對比度不足與單獨傳附件 422

- [x] 20.1 使用者回報附件上傳 pill 顏色太不明顯（半透明白底疊加深色主題背景，對比度不足）：`assistant-widget.css` 的 `.tcrt-assistant-attach-pill` 改用既有狀態色 design token（`--tr-primary-light/dark`、`--tr-success-light/dark`、`--tr-danger-light/dark`），與其他狀態 chip 視覺一致
- [x] 20.2 使用者回報「單獨傳附件（不輸入文字）直接失敗」：根因為 `app/api/assistant.py` 的 `POST /conversations/{id}/messages` 端點 `text: str = Form(...)` 宣告為必填，與檔案一起送出的 multipart 請求中空字串 `text` 被 python-multipart 解析為欄位缺失，回 422 `Field required`；改為 `text: str = Form("")`（下游 `len(text)`／fingerprint／history 皆已相容空字串）
- [x] 20.3 新增回歸測試 `test_attachment_only_message_with_empty_text_succeeds`（以 `git stash` 回退修法確認測試會失敗，還原後確認通過）
- [x] 20.4 完成 targeted gates：`ruff check app/api/assistant.py`（clean）、`pytest app/testsuite -k assistant`（176 passed）

## 21. System prompt / skills DB 化 + Super Admin CRUD

- [x] 21.1 OpenSpec：`assistant-prompt-skills-admin` capability、design D12、agent-loop skill 改 DB、proposal capability 列表
- [x] 21.2 ORM + migration（`assistant_prompt_documents.version`、`assistant_skills`）+ factory seed insert-if-missing
- [x] 21.3 `content_store` service：ensure_seeded／restore／CRUD／assemble system prompt／enabled catalog
- [x] 21.4 Agent + local tools 改讀 DB；`batch_update_results` 已支援 assignee-only 保持
- [x] 21.5 Admin API `/api/admin/assistant/*` + audit + Super Admin only
- [x] 21.6 頁面 `/assistant-admin` + 選單入口 + 三語 i18n
- [x] 21.7 擴充 factory skills；測試（seed、CRUD 授權、version、disable 404、overwrite 保留 enabled）
- [x] 21.8 gates + 紅隊對抗式審查收斂（savepoint seed、confirm 必填等）
