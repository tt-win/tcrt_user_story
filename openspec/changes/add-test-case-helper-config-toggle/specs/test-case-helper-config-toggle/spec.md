# test-case-helper-config-toggle Specification

## Purpose

透過 config 控制 AI Agent Test Case Helper 入口按鈕在 Test Case Set 管理畫面的可見性。Control visibility of the AI Agent Test Case Helper entry button on the Test Case Set management page via config.

## ADDED Requirements

### Requirement: Config toggle for Test Case Helper entry visibility

The system SHALL provide a config field `ai.jira_testcase_helper.enable` (boolean) that controls whether the "AI Agent - Test Case Helper" button is shown on the Test Case Set management page.

#### Scenario: Button visible when enable is true

- **GIVEN** `ai.jira_testcase_helper.enable` is `true` or omitted (default)
- **WHEN** 使用者造訪 Test Case Set 管理畫面 / user visits the Test Case Set management page
- **THEN** 頁面頂部顯示「AI Agent - Test Case Helper」按鈕 / the "AI Agent - Test Case Helper" button is visible in the page header

#### Scenario: Button hidden when enable is false

- **GIVEN** `ai.jira_testcase_helper.enable` is `false`
- **WHEN** 使用者造訪 Test Case Set 管理畫面 / user visits the Test Case Set management page
- **THEN** 頁面不顯示「AI Agent - Test Case Helper」按鈕 / the "AI Agent - Test Case Helper" button is not rendered

#### Scenario: Default behavior preserves existing visibility

- **GIVEN** config does not specify `ai.jira_testcase_helper.enable`
- **WHEN** 系統載入 config / system loads config
- **THEN** 按鈕顯示（預設為 true）/ the button is shown (default treated as true)
