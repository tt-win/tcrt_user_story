# Tasks: QA AI Helper Team Prompt Profiles

執行原則（適用全部任務）：
- 嚴格依編號順序執行；**1.1 必須在修改任何模板或 `qa_ai_helper_prompt_service.py` 之前完成**。
- 精確欄位定義、注入演算法、API 契約、選用語意都在 `design.md`（D1–D7），任務內只寫錨點與步驟；實作前先讀 design.md。
- 文中行號為撰寫時的參考值（「約 N 行」），以函式／類別名為準。
- 每完成一項任務就把 `- [ ]` 改成 `- [x]`；每組結束跑一次該組的驗證指令。
- 不改動與任務無關的程式；既有測試除了任務明列的調整外不得修改。

## 1. Golden fixtures 與 prompt 組裝層（先固定現狀，再動模板）

- [x] 1.1 建 golden fixture 產生器並產生 fixtures（**改模板前做，這是零回歸基準**）
  - 新檔 `app/testsuite/qa_ai_helper_prompt_golden.py`，檔案開頭複製 `test_qa_ai_helper_prompt_service.py` 第 1–8 行的 `PROJECT_ROOT` sys.path bootstrap。
  - 定義 `GOLDEN_STAGES = ("seed", "seed_refine", "testcase", "repair")`、`GOLDEN_FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "qa_ai_helper" / "prompts"`，以及 `GOLDEN_REPLACEMENTS`（固定值，覆蓋各模板全部 placeholder）：
    - `seed`: `output_language="繁體中文"`, `section_summary_json='{"golden":"section_summary"}'`, `requirement_plan_json='{"golden":"requirement_plan"}'`, `generation_items_json='[{"golden":"generation_item"}]'`
    - `seed_refine`: `output_language="繁體中文"`, `seed_items_json='[{"golden":"seed_item"}]'`, `seed_comments_json='[{"golden":"seed_comment"}]'`
    - `testcase`: `output_language="繁體中文"`, `min_steps="3"`, `min_preconditions="1"`, `section_summary_json='{"golden":"section_summary"}'`, `shared_constraints_json="[]"`, `selected_references_json="[]"`, `generation_items_json='[{"golden":"generation_item"}]'`
    - `repair`: `output_language="繁體中文"`, `min_steps="3"`, `min_preconditions="1"`, `invalid_outputs_json='[{"golden":"invalid_output"}]'`, `validator_errors_json='[{"golden":"validator_error"}]'`
  - 提供 `render_stage(stage)`（用 `QAAIHelperPromptService(Settings().ai.qa_ai_helper)` 渲染，prompt_dir 用預設即 repo 的 `prompts/jira_testcase_helper`）與 `regenerate()`（建目錄、把四個 stage 渲染結果寫入 `{stage}.golden.txt`，encoding utf-8）；`if __name__ == "__main__": regenerate()`。
  - 執行 `python app/testsuite/qa_ai_helper_prompt_golden.py`。
  - 驗證：`ls app/testsuite/fixtures/qa_ai_helper/prompts/` 有四個 `.golden.txt`；`grep -L "golden" app/testsuite/fixtures/qa_ai_helper/prompts/*.txt` 無輸出（每個 fixture 都含 golden 替換值）。**此後不得再執行 `regenerate()` 覆蓋 fixtures**。
- [x] 1.2 四個模板與四段 fallback 加插槽
  - `prompts/jira_testcase_helper/{seed,seed_refine,testcase,repair}.md`：各在 `輸出 schema:` 那一行的正上方插入獨立一行 `{team_style_block}`（不加其他空行；repair.md 是插在「輸出限制：只輸出單一 JSON 物件。」之後、`輸出 schema:` 之前）。
  - `app/services/qa_ai_helper_prompt_service.py` 的 `FALLBACK_PROMPTS`：seed / seed_refine / testcase / repair 四段字串中，各在 `"輸出 schema:\n"` 片段之前插入 `"{team_style_block}\n"`。
  - inspection 兩個模板不動。
- [x] 1.3 `qa_ai_helper_prompt_service.py` 注入邏輯（規格見 design D2，含函式碼草稿）
  - 模組層加常數 `_TEAM_STYLE_GUARD_HEADER` 與函式 `build_team_style_block(instructions: str) -> str`（框架文字逐字依 design D1）。
  - `render_stage_prompt` 加 keyword 參數 `team_style_text: Optional[str] = None`；values 迴圈忽略 replacements 中的 `team_style_block` key；所有既有替換完成後依「非空→框架注入／空→連同換行移除佔位行」處理插槽。
- [x] 1.4 contract version 升 v2
  - `app/config.py` 約 297 行 `prompt_contract_version: str = "qa-ai-helper.prompt.v1"` 改為 `"qa-ai-helper.prompt.v2"`；同檔約 666 行對照 dict 內的 `"qa-ai-helper.prompt.v1"` 同步改。
  - `grep -rn "prompt.v1" app/` 確認除歷史 migration／文件外無殘留；有引用舊值的測試一併更新。
- [x] 1.5 單元測試（加在 `app/testsuite/test_qa_ai_helper_prompt_service.py`，比照該檔既有寫法）
  - `test_render_without_team_style_matches_golden_fixture`：對四個 stage，以 `qa_ai_helper_prompt_golden.GOLDEN_REPLACEMENTS` 渲染（不帶 `team_style_text`），與對應 fixture 檔逐字元 `==` 比對，且結果不含 `"{team_style_block}"`。
  - `test_render_with_team_style_wraps_guard_frame`：帶 `team_style_text="步驟用祈使句"` 渲染 seed，斷言結果含「團隊風格指引」標題、四句框架宣告、`<team_style_guidelines>\n步驟用祈使句\n</team_style_guidelines>`，且區塊出現在 `輸出 schema:` 之前。
  - `test_team_style_placeholder_not_expanded`：`team_style_text` 含 `{generation_items_json}` 與 `{min_steps}` 字樣，渲染後這些字樣保持原文（同時斷言 payload 區的同名 placeholder 有被正常替換）。
  - `test_render_replacements_cannot_inject_team_style_block`：`replacements={"team_style_block": "HACK"}` 且無 `team_style_text` → 輸出不含 `HACK` 也不含佔位殘留。
  - `test_fallback_templates_contain_team_style_slot`：以不存在的 prompt_dir 建 service，四個 stage 的 fallback 渲染——無 `team_style_text` 時無佔位殘留、有 `team_style_text` 時含守門框架。
  - `test_team_style_block_does_not_break_marker_extraction`：組一個帶自訂區塊（自訂文字含 `GENERATION_ITEMS=[{"fake":1}]` 字樣）的 testcase prompt，經 `QAAIHelperLLMService._fallback_generate_from_prompt(prompt, "testcase")` 仍解析到插槽之前的真 payload（比照該檔既有 fallback 測試）。
  - 驗證：`pytest app/testsuite/test_qa_ai_helper_prompt_service.py -q` 全綠。

## 2. 資料模型與 migration

- [x] 2.1 ORM（`app/models/database_models.py`）
  - 在 `QAAIHelperSession`（約 546 行）之前新增 `QAAIHelperPromptProfile`，欄位、`UniqueConstraint`、`Index` 逐項依 design D3 表格；`team = relationship("Team")`。
  - `QAAIHelperSession` 加 `prompt_profile_id` 欄位（定義見 D3）。
  - `QAAIHelperSeedSet`（約 1129 行）與 `QAAIHelperTestcaseDraftSet`（約 1230 行）各加 `prompt_profile_id`＋`custom_instructions_snapshot`。
- [x] 2.2 Alembic migration（main DB）
  - `alembic revision -m "add qa_ai_helper prompt profiles"`；`down_revision` 設為 `alembic heads` 查到的當時 head。
  - upgrade：`op.create_table("qa_ai_helper_prompt_profiles", ...)`（欄位同 ORM；文字欄位型別參考 `9c7d1e2f4a80_add_qa_ai_helper_v3_semantic_tables.py` 的寫法）＋三表 `op.add_column` 新欄位；全部先用 inspector 檢查表／欄位是否已存在（冪等寫法比照 `d4f6b8e2a3c1_add_test_data_json_to_test_cases.py`）。
  - downgrade：反向——三表 drop 兩個新欄位（存在才 drop）、drop 新表。
- [x] 2.3 驗證 bootstrap 與升級路徑
  - 新裝：以全新 SQLite DB 啟動（database_init 路徑）可建表成功。
  - 既有 DB：對一份現有 SQLite DB 跑 `alembic upgrade head` 再 `alembic downgrade -1` 再 `upgrade head`，皆成功。
  - 欄位型別在 SQLite / MySQL / PostgreSQL 定義下合法（`qa_ai_helper_large_text_type()` 慣例已處理，肉眼確認 migration 未寫死 dialect 專屬型別）。
- [x] 2.4 Pydantic models（`app/models/qa_ai_helper.py`）
  - 模組層常數 `TEAM_STYLE_INSTRUCTIONS_MAX_CHARS = 2000`。
  - 新增：`QAAIHelperPromptProfileCreateRequest`（name 必填 1–100 strip、description 選填、seed_instructions / testcase_instructions 選填 strip→None、長度 ≤ 常數、`model_validator` 兩段不可皆空、`is_default: bool = False`）、`QAAIHelperPromptProfileUpdateRequest`（同 create 但**無** `is_default`）、`QAAIHelperPromptProfileSetDefaultRequest`（`is_default: bool`）、`QAAIHelperPromptProfileResponse`（全欄位，`from_attributes`）、`QAAIHelperPromptProfileListResponse`（`profiles: List[...]`）。
  - 既有 model 加 `prompt_profile_id: Optional[int] = None`：`QAAIHelperSessionCreateRequest`、`QAAIHelperNoTicketSessionRequest`、`QAAIHelperTestcaseGenerateRequest`（約 330 行）、`QAAIHelperSessionResponse`（約 524 行）。
  - `QAAIHelperSeedSetResponse`（約 726 行）與 `QAAIHelperTestcaseDraftSetResponse`（約 769 行）加 `prompt_profile_id: Optional[int] = None` 與 `custom_instructions_snapshot: Optional[str] = None`（from_attributes 會自動帶出 ORM 新欄位）。

## 3. Profile CRUD API

- [x] 3.1 新 router `app/api/qa_ai_helper_prompt_profiles.py`
  - `APIRouter(prefix="/teams/{team_id}/qa-ai-helper/prompt-profiles", tags=["qa-ai-helper"])`；整體結構（imports、`require_team_admin`、`_ensure_team_exists`、`run_read/run_write` 用法）比照 `app/api/automation_environments.py`；`require_team_admin` 在本檔定義自己的一份（同語意：全域 Admin / Super Admin，403 detail `{"code": "INSUFFICIENT_PERMISSION", ...}`）。
  - 端點與狀態碼逐項依 design D6 表格：GET list（權限用 `from app.api.qa_ai_helper import _verify_team_write_access` 重用）、POST create（201）、PUT update、DELETE、POST set-default。
  - DELETE 在同一 write transaction 內先把 `qa_ai_helper_sessions` / `qa_ai_helper_seed_sets` / `qa_ai_helper_testcase_draft_sets` 中 `prompt_profile_id = 該 id` 的列 UPDATE 為 NULL，再刪 profile（不依賴 DB ondelete，理由見 design D3）。
  - 註冊：`app/api/__init__.py` import 新 router 並在 `qa_ai_helper_router`（約 75 行）之後 `include_router`。
- [x] 3.2 儲存驗證
  - 同名檢查：create / update 先 `SELECT` 同 team 同名（update 排除自身）→ 命中回 409 detail `{"code": "PROMPT_PROFILE_NAME_DUPLICATE", "message": ...}`。
  - set-default 語意（design D6）：true → 同 transaction 先清全 team `is_default` 再設目標；false → 只清目標。create 帶 `is_default=true` 同樣互斥。
  - 名稱長度／指引長度／兩段皆空由 2.4 的 Pydantic 驗證處理（422），router 不重複驗。
- [x] 3.3 API 測試（新檔 `app/testsuite/test_qa_ai_helper_prompt_profiles_api.py`，client／auth fixture 比照 `test_qa_ai_helper_api.py`）
  - CRUD happy path：create → list → update → delete，欄位往返正確。
  - 驗證規則：同名 409、兩段皆空 422、超長 422、name 空 422。
  - 權限：一般成員（非 admin）create/update/delete/set-default 皆 403、list 200；admin 全通；team 不存在 404。
  - default 互斥：A 預設 → B set-default(true) → 重新 list 確認只有 B 是 default；B set-default(false) → 無 default。
  - 刪除後引用清空：建 profile → 建 session 帶該 profile（或直接寫入 session 列）→ delete profile → session 的 `prompt_profile_id` 為 NULL。
  - 驗證:`pytest app/testsuite/test_qa_ai_helper_prompt_profiles_api.py -q` 全綠。

## 4. 產生流程整合（v3 flow，`app/services/qa_ai_helper_service.py`）

- [x] 4.1 session 建立帶入預設／指定 profile
  - service 加兩個 sync helper：`_team_default_prompt_profile_id_sync(sync_db, team_id) -> Optional[int]`（查 `is_default=True`）與 `_resolve_team_prompt_profile_sync(sync_db, team_id, profile_id) -> QAAIHelperPromptProfile`（不存在或 team 不符 → `raise ValueError("找不到 prompt profile")`）。
  - `start_session()`（約 2691 行）：依 design D4 表格——request 未帶欄位（`"prompt_profile_id" not in request.model_fields_set`）→ 用 team default；帶了 → 驗證後用請求值——寫入新 session 的 `prompt_profile_id`。
  - `start_no_ticket_session()`（約 2771 行）：簽名加 `prompt_profile_id: Optional[int] = None, prompt_profile_id_provided: bool = False`，同樣邏輯；`app/api/qa_ai_helper.py` 的 `create_no_ticket_session` endpoint 傳入 `request.prompt_profile_id` 與 `"prompt_profile_id" in request.model_fields_set`。
  - workspace response 驗證：建 session 後回應 JSON 的 `session.prompt_profile_id` 正確（`QAAIHelperSessionResponse` 已於 2.4 加欄位，from_attributes 自動帶出）。
- [x] 4.2 `generate_seed_set()`（約 3289 行）
  - 簽名加 `prompt_profile_id: Optional[int] = None, prompt_profile_id_provided: bool = False`；`app/api/qa_ai_helper.py` 的 `generate_seed_set` endpoint（約 280 行）傳入 `request.prompt_profile_id if request else None` 與 `bool(request and "prompt_profile_id" in request.model_fields_set)`。
  - 依 design D4 解析 `effective_id` 與注入文字（`seed_instructions`）；reuse 提前返回路徑不套用、不更新。
  - `_call_seed_batch` 內的 `render_stage_prompt(..., team_style_text=注入文字)`（每一批都帶）。
  - `_persist` write transaction 內：seed_set 建構加 `prompt_profile_id=effective_id, custom_instructions_snapshot=注入文字或 None`（約 3450 行的 `QAAIHelperSeedSet(...)`）；帶欄位時 `session.prompt_profile_id = effective_id`；telemetry payload（約 3508 行）加 `"prompt_profile_id": effective_id`。
- [x] 4.3 `refine_seed_set()`（約 3658 行）
  - 讀取所屬 seed set 的 `custom_instructions_snapshot`（read_snapshot.seed_set 已含此欄位）→ `render_stage_prompt("seed_refine", ..., team_style_text=快照值)`（約 3713 行）。**不回查 profile。**
  - refine 的 telemetry payload 加 `"prompt_profile_id": seed_set 的 prompt_profile_id`。
- [x] 4.4 `generate_testcase_draft_set()`（約 3906 行）
  - 已收到整個 `request: QAAIHelperTestcaseGenerateRequest`，直接在 service 內以 `"prompt_profile_id" in request.model_fields_set` 判斷；解析 `effective_id` 與注入文字（`testcase_instructions`），其餘同 4.2：render（約 3974 行）帶 `team_style_text`、draft_set 落兩欄、session 更新、telemetry payload 加 key。
- [x] 4.5 整合測試（加在 `app/testsuite/test_qa_ai_helper_api.py`，比照既有 generate 測試 monkeypatch `llm_service.call_stage` 攔截 prompt）
  - 帶 profile 產生 seed：攔到的每批 prompt 皆含守門框架與 `seed_instructions`；seed set 落 `prompt_profile_id`＋快照；session 選擇更新；telemetry（若該檔有驗 payload 的先例則一併驗）。
  - profile 修改後 refine：先以 profile 產生 seed set → 改 profile 的 `seed_instructions` → refine → 攔到的 prompt 用的是**舊**快照文字。
  - `prompt_profile_id: null` 明確不使用：prompt 不含守門框架字樣。
  - 帶他 team 的 profile id → 404。
  - 無 profile 全流程：攔到的 prompt 與 golden fixture 邏輯一致（不含 `{team_style_block}` 殘留、不含守門框架），既有測試全數不改仍綠。
  - 驗證：`pytest app/testsuite/test_qa_ai_helper_api.py -q` 全綠。

## 5. 前端

- [x] 5.1 「風格設定」管理 modal
  - `app/templates/qa_ai_helper.html`：入口按鈕 `qaHelperPromptProfilesBtn`（放 Screen 1 `qaHelperLoadTicketCard` 的工具列附近）＋modal `qaHelperPromptProfilesModal`（列表：名稱、預設徽章、編輯／刪除／設預設；表單：name、description、兩個 textarea `maxlength="2000"` 含字數提示）。互動結構比照 automation-hub environments settings modal。
  - `app/static/js/qa-ai-helper/main.js`：state 加 `promptProfiles: []`；`loadPromptProfiles()`（GET prompt-profiles，失敗時靜默設空陣列）於 session／team 初始化後呼叫；modal 的 CRUD 呼叫 3.1 的端點，409 顯示同名錯誤文案。
  - 入口顯示條件：`window.AuthClient.getUserInfo()` 的 `role` 在 `['admin','super_admin']` 才顯示（比照 `test-case-set-list/main.js` 約 480 行的 isAdmin 判斷）；後端 403 仍為最終防線。
  - `app/static/css/qa-ai-helper.css` 補 modal 需要的樣式（儘量沿用既有 class）。
- [x] 5.2 Screen 1 兩個建立表單加 profile 下拉
  - `qaHelperLoadTicketCard` 表單加 `qaHelperCreateProfileSelect`、`qaHelperNoTicketCard` 表單加 `qaHelperNoTicketProfileSelect`；第一個 option `value=""` 文案「系統預設（不使用自訂指引）」，其後列出 profiles，預選 `is_default` 的那組（無 default → 第一項）。
  - `main.js` 建 session 的兩個 POST（`/sessions`、`/sessions/no-ticket`）body 一律帶 `prompt_profile_id`（`""` → `null`，其餘轉整數）。
- [x] 5.3 Screen 3 / Screen 4 產生動作旁加 profile 下拉
  - Seed（Screen 3）：`qaHelperStartSeedReviewBtn` 所在 action 區旁加 `qaHelperSeedProfileSelect`；Testcase（Screen 4）：`qaHelperStartTestcaseReviewBtn` 旁加 `qaHelperTestcaseProfileSelect`。初始值取 workspace 的 `session.prompt_profile_id`；change 事件只更新前端狀態、不打 API。
  - `generateSeedSet()`（約 2194 行）與 `generateTestcaseDraftSet()`（約 2399 行）的 `body: JSON.stringify({...})` 加 `prompt_profile_id`（下拉的 `""` → `null`）。
  - 顯示既有 set 用過的 profile：seed set／draft set 摘要區顯示名稱——以 `set.prompt_profile_id` 從 `state.promptProfiles` 對照；id 為 null 且 `custom_instructions_snapshot` 非空 → 顯示「已套用自訂指引（profile 已刪除）」文案；兩者皆空 → 顯示「系統預設」。
- [x] 5.4 i18n（`app/static/locales/{zh-TW,zh-CN,en-US}.json` 的 `qaAiHelper` 區塊，zh-TW 約 2769 行）
  - 新增 `qaAiHelper.promptProfiles.*` keys（三份 locale 同步）：`manageButton`、`manageTitle`、`listEmpty`、`addProfile`、`editProfile`、`deleteProfile`、`deleteConfirm`、`name`、`description`、`seedInstructions`、`seedInstructionsHelp`、`testcaseInstructions`、`testcaseInstructionsHelp`、`charCount`、`defaultBadge`、`setDefault`、`unsetDefault`、`systemDefault`、`selectLabel`、`deletedProfileApplied`、`saveSuccess`、`deleteSuccess`、`nameDuplicate`。
  - 驗證：三份 locale 的 key 集合一致（可用 `python -c` 快速比對三檔 `qaAiHelper.promptProfiles` 子樹 key）。

## 6. 驗證與收尾

- [x] 6.1 `pytest app/testsuite -q` 全綠。實測：578 passed, 18 skipped；另有 8 項失敗經 `git stash` 比對確認為分支無關的既有問題（`test_db_access_guardrails`／`test_container_deployment_p1`／`test_qdrant_client_service`／`test_team_statistics_helper_*`／`test_version_refresh`／`test_qa_ai_helper_models::test_settings_loader_expands_qa_ai_helper_model_placeholders`），本次改動零新增失敗。
- [ ] 6.2 手動 A/B 驗證：同一張真實 ticket，無 profile 與示範 profile（兩段指引都填，例如「步驟用祈使句、expected_results 以『系統應』開頭」）各跑完整流程（plan → seed → refine → testcase → commit）。確認：輸出 JSON 結構與 validator 行為無退化、seed/testcase 數量一致、風格指引在產出中有體現、seed set 與 draft set 詳情帶 profile 資訊。記錄結論（貼在 PR 或 change 目錄筆記）。**尚未執行**——已在瀏覽器對 dev 環境（team_id=1）做過輕量驗證：套用 alembic migration 到既有 DB、建立/設定預設/刪除 profile、建立 no-ticket session 確認 `prompt_profile_id` 正確帶入且事後清除測試資料；4.5 的自動化整合測試已用 monkeypatch 驗證 seed/testcase/refine 三階段的注入與快照機制。但完整 plan→seed→refine→testcase→commit 搭配真實 Jira ticket 與真實 LLM 輸出的人工比對尚未執行。
- [ ] 6.3 UI 手動驗證：一般成員看不到風格設定入口且直接呼叫寫入 API 被 403、可在下拉選 profile；admin 可完整管理（含設／取消預設、刪除後既有 set 顯示「已刪除」文案）；三語系切換文案正確。**部分完成**——已於瀏覽器驗證 admin 視角：入口顯示、新增／字數即時計數／設定與取消預設（含背景下拉即時同步）／刪除。一般成員視角的 403 與可見性、三語系實際切換顯示、刪除後 set 顯示「已刪除」文案未逐項人工驗證（403／權限矩陣已由 `test_qa_ai_helper_prompt_profiles_api.py::test_member_write_forbidden_but_can_list` 等自動化測試覆蓋；三語系 key 集合一致已由指令化比對確認）。
- [x] 6.4 `openspec validate qa-ai-helper-custom-prompt-profiles` 通過；artifacts 描述與最終實作一致（如實作中有偏離，先回頭改 design/spec 再收尾）。
