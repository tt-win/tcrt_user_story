# Proposal: AI Agent Test Case Helper Config Toggle

## Why

部署者需要能透過 config 開關控制 AI Agent Test Case Helper 入口的可見性。當環境不需此功能（例如未配置 LLM、或僅作展示用途）時，應能隱藏該按鈕，避免使用者看到無法使用的入口。Deployers need a config toggle to control visibility of the AI Agent Test Case Helper entry. When the feature is not needed (e.g., no LLM configured, demo-only deployment), the button should be hidden to avoid exposing non-functional UI.

## What Changes

- 在 `config.ai.jira_testcase_helper` 新增 `enable` 布林欄位（預設 `true`）
- Test Case Set 管理畫面（`test_case_set_list.html`）的「AI Agent - Test Case Helper」按鈕依 config 顯示或隱藏
- `config.yaml.example` 與 `JiraTestCaseHelperConfig` 加入 `enable` 欄位
- 後端 API 在 `enable=false` 時可選擇拒絕請求或保持可用（建議：入口隱藏即可，後端仍可被內部驗證使用）

## Capabilities

### New Capabilities

- `test-case-helper-config-toggle`: 透過 config 控制 AI Agent Test Case Helper 入口按鈕的可見性。When `ai.jira_testcase_helper.enable` is true, the Test Case Set management page shows the helper button; when false, the button is hidden.

### Modified Capabilities

- （無既有 spec 需修改；`ai-assist-ui-exposure-control` 主要涵蓋 AI rewrite 編輯入口，非 Test Case Helper）

## Impact

- `config.yaml` / `config.yaml.example`
- `app/config.py`（`JiraTestCaseHelperConfig`）
- `app/main.py`（`test_case_set_list` 傳入 `ai_helper_enabled` context）
- `app/templates/test_case_set_list.html`（條件渲染 `openAiHelperFromSetListBtn`）
