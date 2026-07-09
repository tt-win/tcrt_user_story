# helper-team-prompt-profiles Specification

## Purpose

記錄 QA AI Helper Team Prompt Profile / 自訂風格功能的退役契約。系統不再讓團隊建立、選用或套用自訂風格指引；既有資料表與欄位可作為 legacy schema 暫留，但 runtime 不得再把這些資料用於 prompt、API response、telemetry 或 UI。

## Requirements

### Requirement: QA AI Helper MUST NOT expose custom style profile management

系統 SHALL NOT 掛載 `GET|POST|PUT|DELETE /teams/{team_id}/qa-ai-helper/prompt-profiles` 或 `POST /teams/{team_id}/qa-ai-helper/prompt-profiles/{profile_id}/set-default`。既有 `qa_ai_helper_prompt_profiles` 資料表若已存在，僅視為 legacy data，不提供 runtime CRUD。

#### Scenario: Prompt profile routes are retired
- **WHEN** client 呼叫任何 `/teams/{team_id}/qa-ai-helper/prompt-profiles` 管理端點
- **THEN** 系統回傳 404，且不建立、修改或刪除 profile 資料

### Requirement: Generation MUST ignore retired prompt profile inputs

Session 建立、no-ticket session 建立、seed generation 與 testcase generation SHALL 忽略 legacy `prompt_profile_id` request 欄位。系統 SHALL NOT 查詢 team default profile、解析 profile id、注入團隊風格指引、更新 session 的 profile 選擇、或在新 testcase draft set 寫入 profile snapshot。

#### Scenario: Legacy profile id on testcase generation is ignored
- **WHEN** client 在 testcase generation request 送出 `prompt_profile_id`
- **THEN** 系統正常依既有 seed 產生 testcase draft set
- **AND** prompt 不含 `{team_style_block}`、`團隊風格指引` 或任何 profile 指引文字
- **AND** response 的 `session` 與 `testcase_draft_set` 不含 `prompt_profile_id` 或 `custom_instructions_snapshot`

#### Scenario: Legacy profile id on seed generation is ignored
- **WHEN** client 在 seed generation request 送出 `prompt_profile_id`
- **THEN** 系統正常產生 seed set
- **AND** seed prompt 不含 `{team_style_block}` 或團隊風格指引
- **AND** seed set response 不含 profile metadata

### Requirement: Prompt rendering MUST strip legacy team style placeholders

`QAAIHelperPromptService.render_stage_prompt` SHALL strip legacy `{team_style_block}` placeholders from prompt files and fallback templates. Callers SHALL NOT be able to inject custom style content by passing a `team_style_block` replacement key.

#### Scenario: Legacy placeholder is removed
- **WHEN** a loaded prompt template still contains `{team_style_block}`
- **THEN** rendered output removes that placeholder line

#### Scenario: Replacement cannot reintroduce custom style content
- **WHEN** replacements include `team_style_block`
- **THEN** rendered output ignores that replacement

### Requirement: QA AI Helper UI MUST NOT show custom style controls

QA AI Helper 頁面 SHALL NOT 顯示「風格設定」入口、profile 管理 modal、或 testcase 產生按鈕旁的 profile 下拉選單。前端 SHALL NOT 呼叫 retired `/prompt-profiles` endpoints，且 locale SHALL NOT 保留 `qaAiHelper.promptProfiles.*` 使用者可見文案。

#### Scenario: Custom style controls are absent
- **WHEN** 使用者開啟 QA AI Helper 頁
- **THEN** 不顯示任何自訂風格管理或選用 UI
- **AND** 初始化流程不呼叫 `/qa-ai-helper/prompt-profiles`
