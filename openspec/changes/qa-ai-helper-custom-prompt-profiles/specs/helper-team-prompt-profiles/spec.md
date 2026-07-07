# Capability: Helper Team Prompt Profiles

## Purpose

規範 QA AI Helper 的 **Team Prompt Profile**：team 級多組自訂風格指引的資料模型、CRUD API 與權限、產生時擇一選用的請求語意，以及落庫快照與 telemetry 的可追溯契約。自訂內容僅套用於 **testcase 展開階段**（`testcase_instructions`），僅能影響產出的格式與風格；Test Case Seed 的產出不提供自訂。prompt 組裝層的插槽、注入與守門契約見 `helper-prompt-file-loading`。（`repair` stage 僅存在於現行 UI 已不使用的 legacy 產生路徑：模板保留空插槽、不納入 profile 套用範圍。）

## ADDED Requirements

### Requirement: System MUST provide a per-team prompt profile catalog

系統 SHALL 提供資料表 `qa_ai_helper_prompt_profiles` 儲存 team 級、多組的 prompt profile，欄位如下：

- `id`：整數 PK
- `team_id`：FK → `teams.id`，NOT NULL，indexed
- `name`：VARCHAR(100) NOT NULL；同一 team 內 SHALL 唯一（DB 層 SHALL 有 `(team_id, name)` unique constraint，API 層 SHALL 先行檢查並回 409）
- `description`：TEXT，nullable
- `testcase_instructions`：TEXT——testcase 展開階段注入的指引
- `is_default`：BOOLEAN，NOT NULL，預設 false
- `created_by_user_id`、`updated_by_user_id`：FK → `users.id`，nullable
- `created_at`、`updated_at`：timestamps

指引欄位 SHALL 沿用 `qa_ai_helper_large_text_type()` 慣例。儲存驗證 SHALL 為：`name` 去頭尾空白後 1–100 字元；`testcase_instructions` 去頭尾空白後 SHALL NOT 為空；長度上限 2,000 字元（常數 `TEAM_STYLE_INSTRUCTIONS_MAX_CHARS`）。

#### Scenario: 建立有效 profile
- **WHEN** team admin 以唯一名稱與非空 `testcase_instructions` 呼叫 `POST /teams/{team_id}/qa-ai-helper/prompt-profiles`
- **THEN** 系統以 201 建立該 profile 並回傳完整內容（含指引原文與 `is_default`）

#### Scenario: 同名 profile 被拒絕
- **WHEN** 建立或改名後與同 team 既有 profile 名稱重複
- **THEN** 系統回傳 409，錯誤內容含可辨識代碼 `PROMPT_PROFILE_NAME_DUPLICATE`

#### Scenario: 指引為空被拒絕
- **WHEN** 儲存的 profile `testcase_instructions` 去頭尾空白後為空（或未提供）
- **THEN** 系統回傳 422 拒絕儲存

#### Scenario: 指引超過長度上限被拒絕
- **WHEN** `testcase_instructions` 超過 2,000 字元
- **THEN** 系統回傳 422 並在錯誤訊息提示上限

### Requirement: Profile management MUST be restricted to team admins

Profile 的建立、更新、刪除與設定預設 SHALL 僅限 Admin 與 Super Admin 角色（語意同 automation environments 的 `require_team_admin`：檢查全域角色）；非以上角色呼叫寫入 API SHALL 回 403。列表讀取 SHALL 開放具該 team write 權限的成員（供選用 UI 使用）。

#### Scenario: 一般成員無法修改 profile
- **WHEN** 非 Admin / Super Admin 的成員呼叫建立、更新、刪除或設預設 API
- **THEN** 系統回傳 403

#### Scenario: 一般成員可列出 profile
- **WHEN** 具 team write 權限的成員呼叫 `GET /teams/{team_id}/qa-ai-helper/prompt-profiles`
- **THEN** 系統回傳該 team 全部 profiles（含名稱、指引、`is_default`）

### Requirement: Team default profile MUST be exclusive per team

每個 team SHALL 至多一組 `is_default=true` 的 profile。`POST /prompt-profiles/{id}/set-default`（body `{"is_default": true|false}`）為 true 時 SHALL 在同一 transaction 內先取消該 team 全部 profile 的 default 再設定目標；為 false 時 SHALL 僅取消目標（team 回到無預設狀態）。create 帶 `is_default=true` 時 SHALL 執行相同互斥。

#### Scenario: 設定新預設取消舊預設
- **WHEN** team admin 將 profile B 設為預設而 profile A 原為預設
- **THEN** B 成為該 team 唯一預設，A 的 `is_default` 變為 false

#### Scenario: 取消預設
- **WHEN** team admin 對目前的預設 profile 呼叫 set-default 且 `is_default=false`
- **THEN** 該 team 不再有預設 profile，新 session 的預設選擇為「不使用自訂指引」

#### Scenario: 新 session 預設帶入 team 預設 profile
- **WHEN** 使用者建立新 QA AI Helper session（ticket 或 no-ticket）、請求未帶 `prompt_profile_id` 欄位，且該 team 有預設 profile
- **THEN** session 的 `prompt_profile_id` 設為該預設 profile，且使用者後續可改為其他 profile 或「不使用自訂指引」

### Requirement: Only testcase generation MAY apply a selected profile; seed generation MUST NOT

`qa_ai_helper_sessions` SHALL 有 `prompt_profile_id` 欄位（nullable、引用 `qa_ai_helper_prompt_profiles.id`）記錄目前選擇。session 建立請求與 generate testcase 請求 SHALL 接受選填 `prompt_profile_id` 欄位，語意為三態：

- 請求**未包含**該欄位 → 沿用既有規則（session 建立時用 team default；產生時用 session 目前選擇）
- 包含且值為 profile id → 更新 session 目前選擇為該 profile 後，以該 profile 產生
- 包含且值為 null → 明確「不使用自訂指引」，session 目前選擇更新為 null

單次 testcase 產生 SHALL 僅套用一組 profile。指定的 profile 不存在或不屬於該 team 時 SHALL 回 404。沿用既有 set 的提前返回路徑（未 force_regenerate）SHALL 不產生、不注入、不更新選擇。

**generate seed 請求 SHALL NOT 解析、套用或記錄任何 `prompt_profile_id`**——即使請求 body 帶入此欄位（例如與 testcase 請求共用同一 request model），seed 產生流程 SHALL 忽略之；seed 產出的行為與本 capability 導入前完全一致。

#### Scenario: 以選定 profile 產生 testcase
- **WHEN** session 目前選擇為 profile P，使用者觸發 testcase generation
- **THEN** 該次 testcase 產生呼叫的 prompt 皆注入 P 的 `testcase_instructions`

#### Scenario: 產生時切換 profile
- **WHEN** generate testcase 請求帶入與 session 目前選擇不同的 `prompt_profile_id`
- **THEN** session 目前選擇更新為新值，且本次產生使用新 profile

#### Scenario: 不使用自訂指引
- **WHEN** generate testcase 請求帶 `prompt_profile_id: null`
- **THEN** prompt 不注入任何團隊風格指引，且 session 目前選擇更新為 null

#### Scenario: 指定不屬於該 team 的 profile
- **WHEN** generate testcase 請求帶入其他 team 的 profile id
- **THEN** 系統回傳 404，不執行產生

#### Scenario: seed 產生忽略 profile 欄位
- **WHEN** generate seed 請求帶入任何 `prompt_profile_id` 值
- **THEN** 系統正常產生 seed，不解析該欄位、不注入任何團隊風格指引、不更新 session 的 `prompt_profile_id`、seed set 不記錄任何 profile 關聯

### Requirement: Generated testcase draft sets MUST snapshot the applied profile and injected instructions

`qa_ai_helper_testcase_draft_sets` SHALL 有 `prompt_profile_id`（nullable）與 `custom_instructions_snapshot`（nullable TEXT）欄位，於產生新 testcase draft set 的同一 write transaction 內寫入：`prompt_profile_id` ＝ 本次套用的 profile id；`custom_instructions_snapshot` ＝ 本次**實際注入**的 `testcase_instructions` 原文（未注入——profile 該欄位為空——則為 NULL）。刪除 profile 時系統 SHALL 於同一 transaction 將 sessions 與 testcase_draft_sets 兩表引用該 profile 的 `prompt_profile_id` 清為 NULL（應用層執行，不依賴 DB ondelete），快照文字 SHALL 保留。workspace API 回應中的 testcase draft set SHALL 帶出這兩個欄位。**`qa_ai_helper_seed_sets` SHALL NOT 有這兩個欄位**——seed 產出不追溯 profile。

#### Scenario: testcase draft set 落快照
- **WHEN** 以 profile P 產生 testcase draft set
- **THEN** 該 draft set 記錄 P 的 id 與當時 `testcase_instructions` 的原文

#### Scenario: 刪除 profile 不影響追溯
- **WHEN** profile 在產生後被刪除
- **THEN** 相關 draft set 的 `prompt_profile_id` 變為 NULL，但指引文字快照保留可查

### Requirement: Generation telemetry MUST record the applied profile for the testcase stage only

testcase stage 的 telemetry event payload SHALL 記錄 `prompt_profile_id`（未套用時為 null）。seed / seed_refine 兩個 stage 的 telemetry payload SHALL NOT 包含 `prompt_profile_id` 欄位——這兩個 stage 與 profile 機制無關。

#### Scenario: telemetry 可追溯 profile
- **WHEN** 以 profile P 完成一次 testcase generation
- **THEN** 對應 telemetry event 的 payload 含 P 的 id

### Requirement: QA AI Helper UI MUST expose profile management and selection for testcase generation only

QA AI Helper 頁面 SHALL 提供：

1. 「風格設定」管理介面（modal）：profile 列表、新增、編輯、刪除、設定／取消預設；`testcase_instructions` 輸入框含 2,000 字元上限與字數提示；入口僅對 Admin / Super Admin 顯示（後端 403 仍為最終防線）。
2. Profile 選用下拉：Screen 4（testcase 產生動作旁）一處，第一個選項固定為「系統預設（不使用自訂指引）」。**Screen 1（session 建立表單）與 Screen 3（seed 產生動作旁）SHALL NOT 提供 profile 選用 UI**——因為 session 建立與 seed 產生皆不消費使用者於此處的選擇來影響 seed 產出；session 建立時仍在後端silently 帶入 team 預設 profile 供之後的 testcase 產生使用，但不在 Screen 1 呈現選擇介面。
3. 既有 testcase draft set SHALL 顯示產生時套用的 profile 名稱；profile 已被刪除但快照存在時顯示「已套用自訂指引（profile 已刪除）」語意的文案。

文案 SHALL 使用 `qaAiHelper.*` i18n key 並同步 `zh-TW`、`zh-CN`、`en-US` 三份 locale。

#### Scenario: 管理介面僅 admin 可操作
- **WHEN** 一般成員開啟 QA AI Helper 頁
- **THEN** 不顯示風格設定入口（或其寫入動作被後端以 403 擋下）

#### Scenario: 產生前可切換 profile
- **WHEN** 使用者於 Screen 4（產生 testcase 前）變更下拉選擇並觸發產生
- **THEN** 產生請求帶入新選擇、本次產生套用之，且 session 目前選擇同步更新

#### Scenario: 切換 profile 不自動觸發產生
- **WHEN** 使用者僅變更下拉選擇
- **THEN** 系統只更新前端選擇狀態，不自動發起產生請求或 LLM 呼叫
