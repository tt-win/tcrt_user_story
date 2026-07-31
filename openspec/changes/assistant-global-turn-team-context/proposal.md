## Why

AI Assistant 的 conversation 已是全域 session，但 2026-07-27 的 context-team 實作把「目前頁面 team」快照到每個 turn，並以該值過濾所有 team-scoped 工具。結果是：在無 team 的頁面只能使用 discovery 工具；在 ART 頁面也不能直接查詢 CID 的 test case sets、計數或 runs。這把全域對話重新綁回頁面導覽狀態，且將原本只應保護 write/delete 目標的限制錯誤套用到 read。

真正的全域 Assistant 應讓使用者在任何頁面查詢任一 team，並能在對話中明確指定 mutation 目標；頁面 team 不得成為 routing 或 authorization input。本專案目前的授權是**全域角色制**：`get_user_accessible_teams()` 對有效使用者回傳全部 team，`check_team_permission()` 只依角色判斷，並不存在 per-team membership isolation。此變更的安全目標因此是防止錯誤 routing、提示注入造成的目標污染與不透明 mutation，不得把既有 API 誤述為 per-team 圍堵。

## What Changes

- 移除送訊息 API 與前端的 `context_team_id`；global turn 不再快照或依賴目前頁面 team。
- 全域回合依角色提供完整工具目錄，不因缺少頁面 team 隱藏 team-scoped read/write 工具。
- 所有 global conversation 的 team-scoped tool schema 新增必填 `target_team: {id, name}`。模型必須先用 `list_teams` 取得伺服器提供的精確 pair；不得自行猜測。
- executor 將 `target_team` 視為未信任輸入：驗證 shape、team id 存在、目前 team name 一致、角色 permission 與 resource ownership，且不把 selector 轉送到既有 API。這些檢查防止錯誤目標與資源不一致，不宣稱提供目前不存在的 per-team data isolation。
- resource-resolved 工具必須驗證資源實際 team 與 `target_team` 完全一致；不一致即 fail-closed，不允許模型靠 resource id 靜默改變目標。
- read 可明確作用於任一 team，結果與 journal 記錄實際 team；不要求切換頁面。
- write/delete 在 prepare 階段解析出 authoritative target team，建立 pending action 時持久化到 `assistant_pending_actions.target_team_id`。confirm request 不接受 team 參數，且只使用 pending snapshot 重新檢權、重算 summary/fingerprint 與執行。
- 確認卡必須顯示伺服器 lookup 的 team 名稱與 id，缺任一權威 target 資訊即停用確認；team rename 觸發 stale review、team deletion 或 permission loss 使 action expire。
- 移除 `assistant_turns.context_team_id` 及 `no_team_context` 能力限制；migration 以既有 confirmation summary 安全回填尚存 pending 的 target，無法回填者 fail-closed expire。
- 全域對話 localStorage 只保留一個 global active conversation key，不再按目前頁面 team 分流。
- system prompt 改為：READ 可跨任何可存取 team；WRITE/DELETE 目標不明才反問；不得要求使用者切換 team 頁面。

## Capabilities

### New Capabilities

（無；沿用既有 Assistant conversation、agent loop、tool execution 與 confirmation capability。）

### Modified Capabilities

- `assistant-conversations`: global session 與 turn 完全脫離頁面 team；pending action 持久化 mutation target。
- `assistant-agent-loop`: global tool catalog 只依角色過濾；team-scoped 呼叫使用明確 `target_team`。
- `assistant-tool-execution`: server-resolved selector、可存取性、permission 與 resource-team equality 成為權威 routing boundary。
- `assistant-action-confirmation`: confirm 的唯一 team 來源改為 pending action 的 immutable `target_team_id`。
- `assistant-widget-ui`: active global conversation 不再按 workspace team 分流，送訊息不再傳頁面 team。

## Impact

- DB：main Alembic migration 新增 `assistant_pending_actions.target_team_id`（nullable historical column、open action 必須非空、無 FK以保留刪除後的權威 id）、`target_team_name_snapshot` 與 `target_selector_json`，並為 journal 加 `target_selector_json`；安全回填後移除 `assistant_turns.context_team_id`。
- Backend：`assistant.py`、`conversation_service.py`、`assistant_agent_service.py`、`tool_registry.py`、`tool_executor.py`、`capability_context.py` 與 model。
- Frontend：`assistant-widget.js` 的 send payload、conversation localStorage 與 team-change 行為。
- Prompt/spec/tests：移除 page-context remediation，加入 selector、duplicate/stale/mismatch/authorization/confirm adversarial coverage。
- Security：LLM 可提出 target pair，但永遠不是信任來源；server 必須核對 DB identity、角色 permission 與 resource ownership equality。因現行授權模型沒有 per-team isolation，write/delete 的主要防誤操作控制是 immutable pending target、顯示 team name+id 且 fail-closed 的確認卡、fingerprint 與 audit selector→resolved-id 取證。
