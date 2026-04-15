## 1. Prompt 檔案化基礎 / Prompt File Foundation

- [x] 1.1 建立 `prompts/jira_testcase_helper/` 目錄並新增各 stage `.md` 模板檔 / Create `prompts/jira_testcase_helper/` and add stage `.md` templates
- [x] 1.2 將現有 helper prompt 內容從 `app/config.py` 預設常數抽離到檔案來源 / Extract helper prompt text from `app/config.py` defaults into file-backed sources
- [x] 1.3 在 prompt service 實作檔案讀取與 fallback 機制 / Implement file loading and fallback behavior in prompt service

## 2. 設定契約重整 / Configuration Contract Refactor

- [x] 2.1 精簡 `JiraTestCaseHelperStageModelConfig`，移除 `timeout` 與 `system_prompt` 欄位 / Simplify `JiraTestCaseHelperStageModelConfig` by removing `timeout` and `system_prompt`
- [x] 2.2 合併 helper models：移除 `coverage` stage 設定並保留 `analysis/testcase/audit` / Merge helper model config by removing `coverage` stage and keeping `analysis/testcase/audit`
- [x] 2.3 更新 `config.yaml.example` 與預設設定輸出，移除 inline prompts 與舊欄位 / Update `config.yaml.example` and default config output to remove inline prompts and legacy fields

## 3. Runtime 讀取路徑調整 / Runtime Resolution Updates

- [x] 3.1 更新 `JiraTestCaseHelperLLMService` 以新 model schema 解析 stage 設定 / Update `JiraTestCaseHelperLLMService` to resolve stage config from the new model schema
- [x] 3.2 將 OpenRouter chat endpoint 內聚為服務常數，移除 per-stage `api_url` 依賴 / Centralize OpenRouter chat endpoint as service constant and remove per-stage `api_url` dependency
- [x] 3.3 確認 analysis+coverage 合併流程不再依賴 `coverage` model 設定 / Ensure merged analysis+coverage flow no longer depends on `coverage` model config

## 4. AI 改寫模型配置遷移 / AI Rewrite Model Migration

- [x] 4.1 在 `ai` 區段新增 AI 改寫模型設定（例如 `ai.ai_assist.model`） / Add AI rewrite model config under `ai` section (e.g., `ai.ai_assist.model`)
- [x] 4.2 更新 `app/api/test_cases.py` 讀取 `ai.ai_assist.model`，不再依賴 `openrouter.model` / Update `app/api/test_cases.py` to read `ai.ai_assist.model` instead of `openrouter.model`
- [x] 4.3 保留 `openrouter.api_key` 作為唯一伺服器端憑證來源 / Keep `openrouter.api_key` as the only server-side credential source

## 5. 測試與相容性驗證 / Tests and Compatibility Validation

- [x] 5.1 更新 prompt service 測試，涵蓋檔案讀取、缺檔 fallback、新 config schema / Update prompt service tests for file loading, missing-file fallback, and new schema
- [x] 5.2 更新 helper LLM service 測試，驗證移除 `coverage/timeout/system_prompt` 後仍可正確呼叫 / Update helper LLM service tests to validate calls after removing `coverage/timeout/system_prompt`
- [x] 5.3 新增或更新 AI assist API 測試，驗證模型來源改為 `ai.ai_assist.model` / Add or update AI assist API tests to validate `ai.ai_assist.model` routing

## 6. 文件與收斂 / Documentation and Finalization

- [x] 6.1 更新相關開發文件，說明 prompts 目錄結構與設定責任分工 / Update docs for prompts directory structure and configuration responsibility split
- [x] 6.2 執行 targeted pytest 並確認回歸（helper prompt/LLM/API） / Run targeted pytest and confirm regression safety (helper prompt/LLM/API)
- [x] 6.3 以 `openspec status --change simplify-ai-prompt-model-config` 確認 artifacts 全部完成 / Verify all artifacts are complete via `openspec status --change simplify-ai-prompt-model-config`
