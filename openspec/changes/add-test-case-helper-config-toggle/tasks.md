# Tasks: AI Agent Test Case Helper Config Toggle

## 1. Config 設定

- [x] 1.1 在 `JiraTestCaseHelperConfig` 新增 `enable: bool = True` 欄位
- [x] 1.2 在 `config.yaml.example` 的 `ai.jira_testcase_helper` 區塊加入 `enable: true` 註解說明

## 2. 後端 Template Context

- [x] 2.1 修改 `test_case_set_list` 路由，從 `settings.ai.jira_testcase_helper.enable` 取得值並傳入 template context 為 `ai_helper_enabled`

## 3. 前端條件渲染

- [x] 3.1 在 `test_case_set_list.html` 以 `{% if ai_helper_enabled %}` 包裹 `openAiHelperFromSetListBtn` 按鈕區塊

## 4. 驗證

- [x] 4.1 新增或更新測試：`enable=true` 時按鈕存在於 HTML；`enable=false` 時按鈕不存在
- [x] 4.2 執行 `pytest app/testsuite -q` 確認無回歸
