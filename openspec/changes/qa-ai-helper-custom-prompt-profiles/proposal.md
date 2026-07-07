# Change: QA AI Helper Team Prompt Profiles（分層注入式自訂 prompt）

## Why

QA AI Helper 產生 Test Case 的 prompt 目前是固定的（`prompts/jira_testcase_helper/testcase.md`），各團隊無法讓產出貼近自己的用詞、格式與詳細程度習慣，使用者已明確反應此需求。直接開放改整份 prompt 會破壞 pipeline 依賴的硬規則（JSON-only 輸出、`item_index` / `seed_reference_key` 追蹤欄位、數量對齊），因此需要一個「可自訂風格、不可動合約」的分層機制。**Test Case Seed 的產出不需要自訂**——自訂風格僅適用於 testcase 展開階段。

## What Changes

- **Prompt 模板加固定插槽**：`testcase.md`（含 `qa_ai_helper_prompt_service.py` 內對應的 `FALLBACK_PROMPTS` 條目）新增一行 `{team_style_block}` 佔位，位置在「`輸出 schema:` 那一行的正上方」。系統合約層（輸出語言、範圍限制、追蹤欄位、test_data 規則、JSON schema）維持不可自訂。`seed.md`、`seed_refine.md` **不加插槽、不參與此機制**。`repair.md` 同步加插槽以維持模板一致，但該 stage 僅存在於 UI 已不使用的 legacy 產生路徑，維持空注入、行為不變。
- **Team Prompt Profile（多組、擇一）**：新增 team 級資料表 `qa_ai_helper_prompt_profiles` 與 CRUD API（`/teams/{team_id}/qa-ai-helper/prompt-profiles`：list / create / update / delete / set-default）。每組 profile 含單一欄位 `testcase_instructions`（必填、非空、上限 2,000 字元），每 team 可設至多一組預設。管理（寫入）限全域 Admin / Super Admin 角色（即本 repo automation environments 的 `require_team_admin` 語意）；列表（讀取）開放具 team write 權限成員。
- **產生時擇一套用**：`qa_ai_helper_sessions.prompt_profile_id` 記錄目前選擇（session 建立時預設帶入 team 預設 profile，供之後的 testcase 產生使用）；generate testcase 請求可帶選填 `prompt_profile_id`（帶 `null` = 明確不使用；未帶欄位 = 沿用 session 目前選擇）。**generate seed 請求不解析、不套用任何 profile**——seed 產生的行為與插槽機制導入前完全一致。
- **守門注入**：自訂內容由程式包上固定守門框架（宣告「僅限格式與風格、與上方規則衝突時以上方規則為準」，以 `<team_style_guidelines>` 標記包覆）後注入；於所有其他 placeholder 替換完成後才注入以防 `{...}` 二次展開。未選 profile（或 stage 本就不支援插槽）時佔位行整行移除或原本就不存在，**組出的 prompt 與現行版本逐字元相同**。
- **可追溯快照**：`qa_ai_helper_testcase_draft_sets` 加 `prompt_profile_id` 與 `custom_instructions_snapshot`（產生當下實際注入的指引文字）；testcase stage 的 telemetry payload 補記 `prompt_profile_id`。`qa_ai_helper_seed_sets` 不加這兩欄——seed 產出無須追溯 profile。`QAAIHelperConfig.prompt_contract_version` 由 `qa-ai-helper.prompt.v1` 升 `qa-ai-helper.prompt.v2`。
- **前端**：QA AI Helper 頁新增「風格設定」管理 modal（僅 Admin 顯示入口，比照 Automation Hub environments settings 的互動模式，表單僅含一段指引欄位）；Screen 4（Test Case 產生按鈕旁）新增 profile 下拉，第一項固定「系統預設（不使用自訂指引）」；切換下拉僅更新選擇、不自動觸發產生。Screen 1（session 建立）與 Screen 3（seed 產生）不提供 profile 選擇 UI——因為兩者都不消費 profile。i18n 三份 locale 同步。

**非目標（Out of scope）**
- Test Case Seed 產出的自訂風格（僅 testcase 展開階段可自訂）。
- 多組指引同時疊加套用（本次擇一；疊加視後續需求另開 change）。
- MAGI council inspection（requirement plan 階段）的 role focus 自訂。
- 組裝後 prompt 預覽／試產、YAML 匯入匯出、per-profile 品質統計面板（列為後續 Phase 2 候選）。
- Legacy 產生路徑（`/sessions/{id}/generate`）的 profile 套用與落庫。
- Audit log（profile CRUD 不寫 audit_service，如需可後補）。

**風險與緩解**
- *自訂指引壓壞輸出結構* → 守門框架＋既有 normalize / `validate_merged_drafts` / repair 迴圈全部不動，schema 錯誤仍會被修或擋下；上線前以真實 ticket 做無 profile / 有 profile 的 A/B 驗證。
- *影響既有團隊產出* → golden test 保證無 profile 時 testcase / repair 兩個 stage prompt 逐字元不變（fixture 於改模板前先建）；seed / seed_refine 模板完全未變動，無需 golden 保證。
- *token 預算膨脹* → 指引上限 2,000 字元（≈ 500–800 tokens），落在現行 generation budget（12,000 prompt tokens）安全範圍內；只有 testcase 這單一 LLM 呼叫會帶指引，不隨 seed 批次數放大。
- *placeholder injection* → 自訂文字於所有 placeholder 替換完成後才注入，並有單元測試覆蓋。

## Capabilities

### New Capabilities
- `helper-team-prompt-profiles`: Team 級 Prompt Profile 的資料模型、CRUD 與權限、產生時擇一選用（session 目前選擇＋請求覆寫語意）、單一 `testcase_instructions` 指引僅套用於 testcase 展開階段、落庫快照與 telemetry 追溯契約。

### Modified Capabilities
- `helper-prompt-file-loading`: prompt 組裝契約新增 `{team_style_block}` 插槽，**僅適用於 `testcase` 與 `repair` 兩個 stage**——插槽位置（`輸出 schema:` 行正上方）、注入時機（所有 placeholder 替換後）、守門框架由程式固定提供、無 profile 時佔位行整行移除且輸出與現行逐字元相同。`seed`／`seed_refine` 模板與其渲染輸出不受此 change 影響。

## Impact

- **資料庫（main DB）**：新表 `qa_ai_helper_prompt_profiles`（單一 `testcase_instructions` 欄位）；`qa_ai_helper_sessions` 加 `prompt_profile_id`；`qa_ai_helper_testcase_draft_sets` 加 `prompt_profile_id`＋`custom_instructions_snapshot`（沿用 `qa_ai_helper_large_text_type()`）。`qa_ai_helper_seed_sets` 不變動。Alembic migration 為 additive、nullable-only，可安全 rollback（downgrade 只 drop 新表新欄）。刪除 profile 的引用清除由應用層在同 transaction 內執行（不依賴 SQLite 的 FK enforcement）。
- **後端**：`app/services/qa_ai_helper_prompt_service.py`（守門框架＋插槽渲染）、`app/services/qa_ai_helper_service.py`（`generate_testcase_draft_set` 的 profile 解析、session 選擇、快照、telemetry；`generate_seed_set`／`refine_seed_set` 不變動）、`app/models/database_models.py`、`app/models/qa_ai_helper.py`（新 Pydantic models＋既有 request/response 加欄位）、新 router `app/api/qa_ai_helper_prompt_profiles.py`（註冊於 `app/api/__init__.py`）。
- **Prompt 檔**：`prompts/jira_testcase_helper/{testcase,repair}.md` 加佔位行；`seed.md`、`seed_refine.md` 不變動；`app/config.py` 的 `prompt_contract_version` 升 v2。
- **前端**：`app/templates/qa_ai_helper.html`（Screen 4 profile 下拉＋管理 modal）、`app/static/js/qa-ai-helper/main.js`、`app/static/css/qa-ai-helper.css`、`app/static/locales/{zh-TW,zh-CN,en-US}.json`。
- **測試**：`app/testsuite/qa_ai_helper_prompt_golden.py`（golden fixture 產生器，僅涵蓋 testcase／repair）、`app/testsuite/fixtures/qa_ai_helper/prompts/`（golden fixtures）、`test_qa_ai_helper_prompt_service.py`（golden＋注入規則＋seed 不支援插槽的回歸保證）、`test_qa_ai_helper_prompt_profiles_api.py`（CRUD／權限）、`test_qa_ai_helper_api.py`（testcase 產生流程帶 profile、快照落庫；seed 產生流程確認不套用 profile）。
- **相容性**：無 profile 行為與現行完全一致；舊 session 不受影響（欄位 nullable）。MCP read API、automation hub、legacy 產生路徑、seed 產生流程不受影響。
