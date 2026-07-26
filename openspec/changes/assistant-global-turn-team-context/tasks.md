## 1. Schema 與快照持久化

- [x] 1.1 在 `alembic/` 新增 revision：`assistant_turns` 加 `context_team_id`（Integer、nullable、FK `teams.id` ON DELETE SET NULL、index），SQLite 以 `batch_alter_table` 實作，並提供 downgrade
- [x] 1.2 更新 `app/models/database_models.py` 的 `AssistantTurn` 欄位定義
- [x] 1.3 檢查 `database_init.py`／bootstrap／測試 fixture 是否需同步（新欄位 nullable，不需回填）
- [x] 1.4 SQLite disposable DB 已驗 upgrade+downgrade（欄位／FK SET NULL／index 皆正確）；**MySQL 8 / PostgreSQL 16 尚未驗證**（本機無可用實例，列為待驗證）

## 2. API 與 turn 建立

- [x] 2.1 `POST /conversations/{id}/messages` 新增 `context_team_id: Optional[int] = Form(None)`
- [x] 2.2 以 `permission_service.get_user_accessible_teams` 驗證；不可存取即 422，且不建立 turn
- [x] 2.3 在 TurnStart Tx 內把快照寫入 turn（`conversation_service` 建立 turn 的路徑）
- [x] 2.4 確認 `context_team_id` 不進入任何 LLM 可控 schema、不寫入 event payload 的可控欄位

## 3. 有效 team 解析（單一來源）

- [x] 3.1 新增 `effective_team(conversation, turn)` helper：team 對話取 `conversation.team_id`，全域取 `turn.context_team_id`
- [x] 3.2 `tool_executor.resolve_team` 的 `inject` 分支改用有效 team
- [x] 3.3 `check_permission` 改以有效 team 檢權；有效 team 為空時只允許 `team_check=none` 的 read 工具
- [x] 3.4 `run_read_tool` / `prepare_write_tool` 的 team 比對：team 對話維持等值比對；全域對話改為「resolved team ∈ 可存取清單 且 該 team 檢權通過」
- [x] 3.5 loopback 的 `team_id` 注入與 journal／`AssistantToolExecution.team_id` 改記實際生效 team
- [x] 3.6 檢查 `validate_batch_actions` 的 child 動作沿用同一有效 team 規則

## 4. Agent 迴圈與 capability context

- [x] 4.1 `tools_for_turn` 改為接受有效 team：全域＋有 context team → 依角色 `filter_by_permission`；無 context team → `discovery_only`
- [x] 4.2 `capability_context`：新增 `NO_TEAM_CONTEXT` 原因取代全域情境的 `GLOBAL_SCOPE`，補救改為「在介面選定目標 team 的工作區後重試」
- [x] 4.3 capability context 與 `describe_capabilities` 回報本回合 context team（名稱＋id）
- [x] 4.4 `prompts/assistant/system.md` 加入「指名 team 與 context team 不一致必須消歧」規則，並移除前一變更留下的全域限制描述

## 5. 確認流程

- [x] 5.1 移除 `app/api/assistant.py` confirm 端點的全域 `SCOPE_INVALID` 硬拒，改以 pending → turn 快照解析有效 team
- [x] 5.2 有效 team 為空／team 已刪除／該 team 權限失效 → 原子 expire、清 payload、寫 synthetic result
- [x] 5.3 `build_confirmation_summary` 加入目標 team 名稱（伺服器 lookup、經 projection），並納入 fingerprint 輸入
- [x] 5.4 驗證 fingerprint 變更路徑：目標資源換 team 時走 `CONFIRMATION_STALE`，不誤執行

## 6. 前端與 i18n

- [x] 6.1 `assistant-widget.js` 送出訊息時附帶目前工作區 team 作為 `context_team_id`
- [x] 6.2 確認卡渲染目標 team 名稱
- [x] 6.3 無工作區 team 時的提示文案；三語系同步 `app/static/locales/{en-US,zh-CN,zh-TW}.json`
- [x] 6.4 `node --check app/static/js/assistant-widget.js`、`npm run lint`、`node scripts/check-i18n-coverage.mjs`

## 7. 測試

- [x] 7.1 turn 快照：帶入可存取 team → 快照寫入；不可存取 → 422；缺值 → NULL
- [x] 7.2 有效 team 解析：全域＋context team 的 `inject` 工具注入正確 team；無 context team 的 write 一律被拒且不發 loopback
- [x] 7.3 `resolve` 類：全域對話對可存取的其他 team 資源放行、對不可存取 team 資源拒絕；team 對話維持等值比對
- [x] 7.4 confirm：全域對話可成功執行；確認後切換工作區不改變目標 team；有效 team 為空／權限失效 → expire
- [x] 7.5 確認卡 summary 含 team 名稱且計入 fingerprint（team 變動 → `CONFIRMATION_STALE`）
- [x] 7.6 capability context：`no_team_context` 取代 `global_scope`；VIEWER＋context team → `role_insufficient`
- [x] 7.7 端對端：全域對話以 admin 角色在 context team `ART` 建立 test case set（含確認卡）成功
- [x] 7.8 回歸：**逐檔**執行 17 個 `test_assistant_*.py` 全部通過（含新檔 14 passed），只有 3 個變更前既有的失敗：`test_assistant_data_boundary.py::test_delete_test_case_attachment_accepts_a_real_string_target`、`test_assistant_tool_registry.py` 2 項。
      合併成一次執行會卡死在 `test_assistant_filter_batch.py::test_batch_update_by_filter_endpoint_mutates`（aiosqlite 連線跨 event loop 重用），**已用 `git stash` 在未修改的 HEAD 上以同一組 8 個檔案重現同樣的卡死**，屬既有測試隔離缺陷，不在本變更範圍

## 8. 收尾驗證

- [x] 8.1 `uv run ruff check app scripts database_init.py`（至少不新增錯誤）
- [ ] 8.2 `uv run pytest app/testsuite -q`
- [x] 8.3 `openspec validate assistant-global-turn-team-context --strict`
- [ ] 8.4 手動驗證：admin 在 ART 工作區於全域對話建立 test case set 成功；VIEWER 同樣操作被正確歸因為權限不足
