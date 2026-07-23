# assistant-prompt-skills-admin Specification

## Purpose
TBD - created by archiving change add-global-ai-assistant. Update Purpose after archive.
## Requirements
### Requirement: System prompt 與 skills 以 main DB 為 runtime 真相
系統 SHALL 將助手 system prompt 與 skill recipes 持久化於 main DB（`assistant_prompt_documents`、`assistant_skills`），使 Docker／多 replica 部署不依賴可寫入 container 檔案系統。`prompts/assistant/**` MUST 僅作為 factory seed 來源，MUST NOT 在 runtime 覆寫 admin 已修改的 DB 內容。

當對應表存在時，agent 組裝 system prompt 與 `list_skills`／`get_skill` MUST 只讀 DB。表不存在（未 migrate）時 MAY 暫時 fallback 讀 factory 檔並寫 warning log；表存在但列為空時 MUST 先 `ensure_seeded`（insert-if-missing）再讀。

#### Scenario: Docker 唯讀檔案系統仍可使用 admin 修改後內容
- **WHEN** container 無法寫入 `prompts/assistant/`，且 Super Admin 已於 DB 修改 system prompt 或 skill
- **THEN** 新 turn 的 LLM system 與 skill 工具結果使用 DB 內容，不回退到 image 內舊 factory 檔

#### Scenario: ensure_seeded 不覆蓋既有列
- **WHEN** DB 已有 system 列或某 skill_id 列，且 startup／admin 觸發 `ensure_seeded`
- **THEN** 既有列內容不變；僅插入缺失的 factory skill_id 與缺失的 system 列

### Requirement: System prompt 文件契約與樂觀鎖
`assistant_prompt_documents` 對 `doc_key="system"` 保存模板 content 與整數 `version`（seed 從 1 起算；每次成功 PUT +1）。PUT MUST 要求 `expected_version`；不符回 409 `PROMPT_STALE`。

寫入校驗 MUST：
- content 長度 200–65536 字元（UTF-8 字元計數）
- 恰好一個 `{{SKILL_CATALOG}}` token（0 個或多於 1 個 → 422）
- 不接受其他 `doc_key` 的寫入（v1 allowlist 僅 `system`）

送往 LLM 前，server MUST 以 enabled skills 產生 catalog 表並替換**第一個**（亦為唯一）`{{SKILL_CATALOG}}`。Admin 不得手寫第二份 catalog 作為真相來源。

#### Scenario: 並發編輯 system prompt
- **WHEN** 兩位 Super Admin 以相同 `expected_version` 幾乎同時 PUT
- **THEN** 僅一方成功並 version+1；另一方 409，必須重讀後再存

#### Scenario: 缺 catalog placeholder 拒絕儲存
- **WHEN** PUT content 不含或含超過一個 `{{SKILL_CATALOG}}`
- **THEN** 422，DB 不變

### Requirement: Skill 列契約與 builtin 刪除禁令
`assistant_skills` 每列含 `skill_id`（unique slug）、`name`、`description`、`body`、`triggers_json`、`is_enabled`、`is_builtin`、`sort_order`、時間戳與 `updated_by`。

規則：
- `skill_id` 建立後不可變更
- slug：`^[a-z][a-z0-9-]{0,62}[a-z0-9]$` 或單字元 `^[a-z]$`，總長 ≤64
- body ≤32768 字元；triggers ≤20 條、每條 ≤64 字元；skills 總數 ≤200
- **builtin 禁止 DELETE**（409 `BUILTIN_DELETE_FORBIDDEN`）；可 disable、edit、`POST .../reset` 自 factory 重設內容欄並**保留 `is_enabled`**
- custom 可 DELETE
- create custom 的 skill_id MUST NOT 與當前 factory 清單撞名（422）

Agent 可見性：僅 `is_enabled=true` 進入 catalog 與 `list_skills`／`get_skill`。disabled 與 unknown 對 agent 回相同 404 形狀，不洩漏 body。

#### Scenario: 關閉 builtin 後 agent 不可讀 body
- **WHEN** Super Admin 將 `assign-run-items-by-case-prefix` 設 `is_enabled=false`
- **THEN** agent catalog 與 `get_skill` 均不回傳該 skill；admin list 仍可見

#### Scenario: 禁止刪除 builtin
- **WHEN** Super Admin DELETE 一筆 `is_builtin=true` 的 skill
- **THEN** 409，列仍存在

### Requirement: Restore 兩檔模式
`POST /api/admin/assistant/restore` MUST 支援：
- `mode=missing-only`：等同 ensure_seeded
- `mode=overwrite-builtins`：MUST 要求 `confirm=true`；MUST 以 factory 覆寫 system content（version+1）與所有 **is_builtin** 列的 name/description/body/triggers/sort_order，MUST 保留各列 `is_enabled`；MUST NOT 刪除或修改 custom skills；缺失 builtin 則 insert（default enabled）

#### Scenario: overwrite 不重開已停用 skill
- **WHEN** 某 builtin 為 disabled，執行 overwrite-builtins
- **THEN** 該列內容更新但 `is_enabled` 仍為 false

### Requirement: Super Admin API 與 audit
下列端點 MUST `require_super_admin`，且不依賴 `TCRT_ASSISTANT_ENABLED`（可先編輯再啟用助手）：

- `GET/PUT /api/admin/assistant/system-prompt`
- `GET/POST /api/admin/assistant/skills`
- `GET/PUT/DELETE /api/admin/assistant/skills/{skill_id}`
- `POST /api/admin/assistant/skills/{skill_id}/reset`
- `POST /api/admin/assistant/restore`

Mutation MUST 寫 audit（`ResourceType.SYSTEM`）：action、doc_key 或 skill_id、content/body 的 sha256 與 length、可選 ≤200 字 preview；MUST NOT 把完整 content/body 寫入 audit details。

非 Super Admin MUST 得 403。

#### Scenario: 一般使用者無法改 skill
- **WHEN** role=user 呼叫 POST/PUT/DELETE skills 或 PUT system-prompt
- **THEN** 403

### Requirement: Super Admin UI
系統 SHALL 於 `/organization-management` 頁面（見 `organization-management-console`）提供分頁 `tab-assistant-admin`（tabs：System Prompt｜Skills），僅 Super Admin 可有效使用；分頁可視性沿用該頁既有 `organization_management:manage` ui-config gating（與 `tab-org-automation-infra` 等其餘 Super-Admin-only 分頁同一存取層級）。編輯區 MUST 使用純文字控件（非 raw HTML 渲染 skill body）。UI MUST 警告內容會影響外部 LLM 規劃，且勿貼入密鑰。

#### Scenario: 非 Super Admin 開啟頁面
- **WHEN** 非 Super Admin 開啟 `/organization-management` 並呼叫 admin API
- **THEN** `tab-assistant-admin` 分頁不可見；API 呼叫仍 403

### Requirement: Hard safety 不依賴 DB prompt
即使 DB system prompt 或 skill body 指示「略過確認」「直接刪除」，executor 對 write 的確認、權限、team 與 credential 規則 MUST 仍強制生效。

#### Scenario: 惡意 system 文案不能跳過確認
- **WHEN** system prompt 被改為要求未確認即執行 delete
- **THEN** write 工具仍只建立 pending，不 inline 執行

