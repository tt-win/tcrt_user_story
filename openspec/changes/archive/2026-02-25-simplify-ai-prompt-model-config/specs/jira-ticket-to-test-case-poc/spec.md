## MODIFIED Requirements

### Requirement: LLM Test Case Generation

The system SHALL use a requirement-contract-first multi-stage process to generate comprehensive test cases based on:
- standardized `structured_requirement` context
- structured `requirement_ir` context
- analysis and coverage outputs with stable requirement trace keys
- ticket metadata and configured prompt/model strategy

#### Configuration
- **Model Routing**: Stage-specific models from `ai.jira_testcase_helper.models` (`analysis`, `testcase`, `audit`), where `analysis` is the single model for merged analysis+coverage
- **Prompt Source**: Stage prompts from `prompts/jira_testcase_helper/*.md` files (not inline `config.yaml` blocks)
- **Temperature**: Stage-specific values from `ai.jira_testcase_helper.models`
- **Removed Config Fields**: `timeout` and `system_prompt` SHALL NOT be required in helper model configuration
- **Test Case Quantity**: Determined by stage-1 entry count (1:1 mapping)
- **Three-Phase Process**:
  1. **Requirement Contract Phase**: parser/validator produces `structured_requirement` and completeness result
  2. **IR + Analysis + Coverage Phase**: pipeline generates requirement IR, and uses merged analysis+coverage output in one analysis stage contract
  3. **Generation + Audit Phase**: pipeline generates testcases and performs audit correction

#### Scenario: Generate test cases from requirement-contract-first workflow
- **WHEN** the system executes helper analyze and generate stages
- **THEN** it returns structured test cases that are traceable to stable requirement keys and requirement-rich pre-testcase context

#### Scenario: Resolve helper prompt and model contracts
- **WHEN** the helper runtime resolves stage prompt and model settings
- **THEN** prompts are read from `prompts/jira_testcase_helper/*.md` and model routing is resolved from `ai.jira_testcase_helper.models` without requiring `coverage`, `timeout`, or `system_prompt` config fields
