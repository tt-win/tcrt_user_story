## Why

目前 Test Case Helper 的 prompts 與 models 混在 `config.yaml`，造成設定檔過長且維護成本高。尤其 analysis 與 coverage 已是合併流程，仍維持雙模型與多段 prompt 設定會增加理解與誤設風險。

## Purpose

將 prompt 與 model 設定責任切分：`config.yaml` 僅保留必要模型路由，prompt 改由獨立 `.md` 檔管理。  
Split responsibilities so `config.yaml` keeps model routing only, while prompts are managed in dedicated Markdown files.

## What Changes

- 將 Test Case Helper 各階段 prompt 由 `config.yaml` 移出，改為讀取 `prompts/` 目錄下的 `.md` 檔案。
- 精簡 `ai.jira_testcase_helper.models`：移除 `coverage` 模型設定，改以單一 `analysis` 模型承接 analysis+coverage 合併階段。
- 將原本放在 `openrouter` 區段的「AI 改寫」模型設定移至 `ai` 區段，統一 AI 模型設定入口。
- 移除 helper stage model 中未必要設定（`timeout` 與 `system_prompt`）的配置介面，避免無效設定累積。

## Requirements

### Requirement: Prompt file source replaces YAML inline prompts

- **GIVEN** 系統啟動並載入 Helper 設定 / system bootstraps helper config
- **WHEN** Helper 需要任一階段 prompt 模板 / helper requests stage prompt template
- **THEN** 系統 SHALL 從 `prompts/*.md` 載入模板，且不再要求 `config.yaml` 內嵌 prompt 內容

### Requirement: Unified AI model configuration location

- **GIVEN** 需要取得 AI 改寫或 Helper 的模型設定 / model config is requested
- **WHEN** 讀取設定來源 / reading configuration
- **THEN** 系統 SHALL 以 `ai` 區段為模型設定來源，`openrouter` 僅保留 API key 與連線必要資訊

### Requirement: Remove redundant helper model fields

- **GIVEN** Helper stage model config 被解析 / helper stage model config is parsed
- **WHEN** 系統初始化 / system initialization
- **THEN** 系統 SHALL NOT 依賴 `timeout` 與 `system_prompt` 欄位；analysis+coverage SHALL 使用單一 analysis model 設定

## Non-Functional Requirements

- 設定結構可讀性提升：新增團隊成員可在單一位置理解模型路由。
- 維護性提升：prompt 文案變更不需編輯大型 YAML 區塊。
- 相容性要求：既有 Helper flow 與 AI 改寫 API 行為不變（除設定來源調整）。

## Capabilities

### New Capabilities

- `helper-prompt-file-loading`: 定義 Helper prompt 必須由 `prompts/` 目錄之 `.md` 檔案載入與管理。

### Modified Capabilities

- `jira-ticket-to-test-case-poc`: 調整 prompt/model 設定契約，改為檔案化 prompt、單一 analysis 模型、移除冗餘設定欄位。
- `test-case-editor-ai-assist`: 調整 AI 改寫模型設定來源，從 `openrouter.model` 轉為 `ai` 區段管理。

## Impact

- 受影響範圍：`app/config.py`、`app/services/jira_testcase_helper_prompt_service.py`、`app/services/jira_testcase_helper_llm_service.py`、`app/api/test_cases.py`、`config.yaml.example`、測試檔。
- 新增資產：`prompts/` 目錄與各階段 `.md` prompt 檔。
- 文件/規格：需同步更新 OpenSpec delta specs 與測試以反映新設定契約。
