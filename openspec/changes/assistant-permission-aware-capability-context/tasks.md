## 1. 能力類別推導

- [x] 1.1 在 `app/services/assistant/` 新增能力類別映射：以工具名／模組歸類為 test case 寫入、test case set/section 寫入、test run 與 run item 寫入、pins 寫入、批次寫入、其他寫入等類別
- [x] 1.2 實作 `derive_withheld_capabilities(all_tools, allowed_tools)`：由 registry 全集減去回合過濾後集合，回傳去重後的類別清單（穩定排序）
- [x] 1.3 新增 registry 層測試：每個 `is_write()` 為真的工具都能映射到一個類別，未覆蓋即失敗

## 2. capability context 組裝

- [x] 2.1 實作 `build_capability_context(role, scope_type, team_id, team_name, withheld)`：輸出含 scope／role／allowed／withheld／reason（`global_scope`、`role_insufficient`）／remediation 的 zh-TW 區塊，並以「本回合權威事實、優先於一般性描述」開頭
- [x] 2.2 處理兩原因並存：全域對話且角色不足時同時標明，並說明切到 team 對話後仍需 write 權限
- [x] 2.3 具備權限的角色不輸出受限敘述（withheld 為空時只陳述 scope 與允許權限）
- [x] 2.4 將區塊長度控制在設計約束內（類別摘要、不列舉工具名），並以測試斷言上限

## 3. 接入 agent loop

- [x] 3.1 在 `_run_llm_loop`（`app/services/assistant/assistant_agent_service.py`）於取得 base system prompt 後 append capability context，使用該回合已算出的過濾後工具集合
- [x] 3.2 確認 per-turn 內容不進入 `content_store` 的 system prompt process cache（快取邊界之外組裝）
- [x] 3.3 確認 confirm continuation 回合同樣附加 capability context

## 4. factory system prompt 措辭修正

- [x] 4.1 修改 `prompts/assistant/system.md`「嚴格範圍限制」段：保留離題拒絕，改為「工具目錄缺少的 TCRT 寫入操作須依 capability context 歸因為 scope 或角色權限」
- [x] 4.2 明確禁止兩種回答：聲稱系統無此功能／不可能；以「請改用網頁介面」作為權限不足的補救
- [x] 4.3 確認既有 DB 內自訂 prompt 無需 migration（append 注入不依賴 token），並驗證 `assemble_system_prompt_text` 相關測試未被破壞

## 5. `describe_capabilities` local 工具

- [x] 5.1 在 `app/services/assistant/tools_misc.py` 宣告工具：`method=LOCAL`、`execution_mode=local`、`team_check=none`、`PermissionType.READ`、`risk_level=read`、projection 涵蓋 scope／role／allowed_permissions／withheld_capabilities／reason／remediation
- [x] 5.2 在 `tool_executor._run_local_read_tool` 加 handler 分支，回傳與 capability context 同源的結構化事實
- [x] 5.3 將 `role`／scope 傳入 `_run_local_read_tool`（呼叫端已具備 `role`）
- [x] 5.4 確認該工具進入 discovery-only 目錄（全域對話可用），且不出現在 `batch_execute_actions` 的 child enum

## 6. 測試

- [x] 6.1 新增 `app/testsuite/test_assistant_capability_context.py`：VIEWER＋team → 含 role／withheld／`role_insufficient`／補救；USER＋team → 無受限敘述
- [x] 6.2 測試全域對話 → 含 `global_scope`；全域＋VIEWER → 兩原因並存
- [x] 6.3 測試快取不污染：同一 process 連續組裝 VIEWER 與 ADMIN 回合，各自正確且互不洩漏
- [x] 6.4 測試管理員自訂 prompt（無任何 token）仍取得 capability context
- [x] 6.5 測試 `describe_capabilities`：三種角色的回傳內容、全域對話可用、不打 loopback
- [x] 6.6 回歸：`uv run pytest app/testsuite/test_assistant_permissions.py app/testsuite/test_assistant_content_store_admin.py app/testsuite/test_assistant_context_opt.py app/testsuite/test_assistant_tool_registry.py app/testsuite/test_assistant_skills.py -q` → 120 passed；`test_assistant_tool_registry` 2 項失敗（`EXPECTED_TOOL_COUNT=72` 已過時、attachment 路由比對）在本變更前即為紅燈，未在本變更範圍內處理

## 7. 收尾驗證

- [x] 7.1 `uv run ruff check app/services/assistant app/testsuite/test_assistant_capability_context.py` 通過（repo-wide `ruff check app scripts database_init.py` 有 360 項既有錯誤，非本變更引入）
- [x] 7.2 逐檔執行 `app/testsuite/test_assistant_*.py`（合併執行會撞到既有測試隔離缺陷，見 `assistant-global-turn-team-context` 變更記錄）：全部通過，僅 2 個變更前既有紅燈（`test_assistant_tool_registry.py`）
- [x] 7.3 `openspec validate assistant-permission-aware-capability-context --strict`
- [ ] 7.4 以 VIEWER 帳號在 team 對話實測「建立 test case set」與追問「是不是我權限不夠」，確認回答歸因正確且未引導至網頁介面（待人工於運行中服務驗證，超出本次程式碼變更範圍）
