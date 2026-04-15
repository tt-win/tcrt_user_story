## ADDED Requirements

### Requirement: Helper stage prompts MUST be loaded from Markdown files

The system SHALL load Test Case Helper stage prompt templates from `prompts/jira_testcase_helper/*.md` instead of inline text in `config.yaml`.

#### Scenario: Load prompt template for analysis stage
- **WHEN** helper prepares the analysis stage prompt
- **THEN** the prompt service reads `prompts/jira_testcase_helper/analysis.md` and uses it as the template source

### Requirement: Prompt source and model source MUST be separated

The system SHALL keep prompt content outside configuration models, and `config.yaml` SHALL only keep model-routing settings for helper stages.

#### Scenario: Parse helper configuration
- **WHEN** settings are loaded from `config.yaml`
- **THEN** `ai.jira_testcase_helper` contains model routing metadata only and does not require inline prompt text blocks

### Requirement: Missing prompt files MUST have deterministic fallback

If a required prompt file is missing or empty, the system SHALL apply a deterministic built-in machine template and MUST emit a warning log for operators.

#### Scenario: Missing testcase prompt file
- **WHEN** `prompts/jira_testcase_helper/testcase.md` is missing
- **THEN** helper continues with built-in fallback template and writes a warning indicating file fallback was applied
