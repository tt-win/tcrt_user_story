## ADDED Requirements

### Requirement: AI helper entrypoint in Test Case Set management
The system SHALL provide an `AI Agent - Test Case Helper` action in the Test Case Management page (`/test-case-management`) and MUST keep the existing page interaction patterns.

#### Scenario: Open helper wizard from management page
- **GIVEN** the user has opened Test Case Management with valid team context
- **WHEN** the user clicks `AI Agent - Test Case Helper`
- **THEN** the system opens the guided helper workflow in-page without navigating away

### Requirement: Target Test Case Set selection and creation
The system SHALL allow users to select an existing Test Case Set or create a new Test Case Set before AI processing starts.

#### Scenario: Create and select a new Test Case Set
- **GIVEN** the helper wizard is at target set step
- **WHEN** the user creates a new set and confirms selection
- **THEN** the new set becomes the target set for downstream generation and commit

### Requirement: TCG ticket input with Jira fetch
The system SHALL provide a field for TCG ticket number input and SHALL fetch Jira ticket content after user confirmation.

#### Scenario: Fetch Jira requirement content by TCG number
- **GIVEN** a valid TCG ticket number is entered
- **WHEN** the user submits ticket input
- **THEN** the system fetches requirement-related fields from Jira and shows source content summary

### Requirement: Requirement normalization and formatting by Gemini
The system SHALL use `gemini-3-flash-preview` to normalize multilingual ticket requirement content and output formatted markdown in the selected UI language context.

#### Scenario: Mixed-language ticket normalized to target locale
- **GIVEN** ticket content contains mixed Chinese and English text
- **WHEN** normalization is triggered
- **THEN** the system outputs a single coherent requirement document in current UI locale for user review

### Requirement: Language policy split by stage
The system SHALL present requirement normalization results in current UI locale for review, and SHALL generate final test cases in user-selected output locale.

#### Scenario: Review and output locales are different
- **GIVEN** current UI locale is `zh-TW` and selected output locale is `en`
- **WHEN** the helper completes requirement normalization and testcase generation
- **THEN** requirement review content is shown in Traditional Chinese and generated testcases are in English

### Requirement: Editable requirement checkpoint
The system SHALL provide a markdown editor for normalized requirement content and MUST allow user edits before analysis starts.

#### Scenario: User revises normalized requirement
- **WHEN** the user edits requirement markdown and presses submit
- **THEN** the edited content becomes the authoritative input for the next analysis phase

### Requirement: Analysis and Coverage generation checkpoint
The system SHALL run requirement Analysis and Coverage completion after requirement submission, following the reference approach in `/Users/hideman/code/test_case_agent_poc`.

#### Scenario: Analysis output is presented for user confirmation
- **WHEN** analysis and coverage generation completes
- **THEN** the system presents structured analysis items and coverage notes for review

### Requirement: Fixed default stage model mapping with config override
The system SHALL default stage model mapping to: `analysis=gemini-3-flash-preview`, `coverage=gpt-5.2`, `testcase=gemini-3-flash-preview`, `audit=gemini-3-flash-preview`; and SHALL allow override per stage via `config.yaml`.

#### Scenario: Helper uses configured stage models
- **GIVEN** `config.yaml` defines explicit model ids for helper stages
- **WHEN** the helper executes each stage
- **THEN** each stage uses the configured model for that stage

#### Scenario: Helper falls back to required defaults
- **GIVEN** helper stage model keys are missing in `config.yaml`
- **WHEN** the helper executes stages
- **THEN** analysis/testcase/audit use Gemini 3 Flash Preview and coverage uses GPT-5.2

### Requirement: Config-driven stage prompt templates
The system SHALL store helper prompt templates for `analysis`, `coverage`, `testcase`, and `audit` in `config.yaml`, with defaults aligned to the existing PoC prompt strategy.

#### Scenario: Use default prompt templates when config keys are absent
- **GIVEN** helper prompt keys are missing in `config.yaml`
- **WHEN** helper renders stage prompts
- **THEN** the system uses built-in defaults equivalent to PoC prompt rules

#### Scenario: Override one stage prompt from config
- **GIVEN** `config.yaml` overrides one stage prompt template
- **WHEN** that stage is executed
- **THEN** the helper uses overridden prompt and leaves other stage prompts on default values

### Requirement: Editable pre-test-case checkpoint
The system SHALL allow users to edit pre-test-case analysis entries before final test case generation.

#### Scenario: User adjusts pre-test-case entries
- **WHEN** the user modifies pre-test-case items and confirms
- **THEN** the modified entries are used for test case generation

### Requirement: Language-selectable test case generation
The system SHALL support output language selection for generated test cases with supported values `zh-TW`, `zh-CN`, and `en`.

#### Scenario: Generate test cases in selected language
- **GIVEN** the user selected `en` as output language
- **WHEN** generation is executed
- **THEN** generated test case title/body content is returned in English

### Requirement: Generated test cases MUST match existing Test Case model
The system SHALL produce test cases that can be mapped to existing test case fields (`test_case_number`, `title`, `precondition`, `steps`, `expected_result`, `priority`, `tcg`, `test_case_set_id`, `test_case_section_id`).

#### Scenario: Validate generated payload before commit
- **WHEN** generation finishes
- **THEN** the system validates each generated item against required model fields and blocks commit on schema mismatch

### Requirement: Test Case ID numbering rule
The system SHALL generate test case IDs as `[TCG].[middle].[tail]`, where `middle` and `tail` both increment by 10 (`010`, `020`, `030`...) from configured initial values.

#### Scenario: Middle number increments by 10 across requirement groups
- **GIVEN** initial middle number is `010`
- **WHEN** the system generates multiple requirement groups
- **THEN** generated middle numbers follow `010`,`020`,`030`...

#### Scenario: Tail number increments by 10 within one group
- **GIVEN** one requirement group contains multiple testcases
- **WHEN** IDs are assigned
- **THEN** tail numbers follow `010`,`020`,`030`... within that group

### Requirement: Section mapping and creation compliance
The system SHALL support section assignment for generated test cases and MUST create missing sections using existing section rules (same set scope, max depth, uniqueness, fallback to `Unassigned` when needed).

#### Scenario: Generated section path does not exist
- **WHEN** a generated test case references a non-existing section path
- **THEN** the system creates the section path if valid, otherwise assigns the case to `Unassigned` with warning

### Requirement: Final markdown-editable review before persistence
The system SHALL provide a final confirmation UI where users can review and edit generated test cases with markdown-capable fields before saving.

#### Scenario: User edits generated test case content before save
- **WHEN** the user edits steps/expected result in final review and confirms
- **THEN** the system persists the edited content instead of the original generated text

### Requirement: Commit and redirect behavior
The system SHALL persist confirmed test cases into the selected Test Case Set and SHALL redirect users to that set while showing newly created test cases.

#### Scenario: Successful commit redirects to target set
- **WHEN** the user confirms final submission
- **THEN** the system creates test cases in target set, redirects to that set, and highlights created cases

### Requirement: Atomic persistence for commit stage
The system SHALL execute section creation/mapping and testcase persistence in a single database transaction, and SHALL rollback all writes if any item fails.

#### Scenario: Rollback when one testcase fails to persist
- **GIVEN** commit payload contains multiple testcases
- **WHEN** one testcase violates persistence constraints during commit
- **THEN** no testcase from that commit is persisted

### Requirement: Error handling and recoverable workflow
The system SHALL provide phase-specific error messages and MUST preserve user-edited content when retrying failed normalization/analysis/generation steps.

#### Scenario: Generation phase fails and user retries
- **WHEN** generation API returns an error and user chooses retry
- **THEN** requirement edits and pre-test-case edits remain intact and generation can be retried without re-entering prior steps

### Requirement: Single configuration source for helper models
The system SHALL load helper model settings from the main `config.yaml` configuration pipeline and SHALL NOT require a standalone LLM configuration file for this workflow.

#### Scenario: System starts without standalone LLM file
- **GIVEN** the helper standalone LLM config file is absent
- **WHEN** the service starts with valid `config.yaml`
- **THEN** helper model settings are resolved from `config.yaml` and the workflow remains available

### Requirement: Unified OpenRouter routing for helper stages
The system SHALL invoke helper stage models via OpenRouter endpoints with stage-specific model IDs configured in `config.yaml`.

#### Scenario: Stage model runs through OpenRouter
- **GIVEN** helper stage model config exists in `config.yaml`
- **WHEN** analysis, coverage, testcase, and audit stages are executed
- **THEN** all four stages call OpenRouter with their mapped stage model IDs

### Requirement: Reuse existing Jira and OpenRouter integrations
The system SHALL reuse existing project integrations for Jira and OpenRouter in this workflow.

#### Scenario: Jira integration reuse
- **WHEN** helper needs ticket data
- **THEN** the implementation uses existing Jira integration service in current codebase

#### Scenario: OpenRouter integration reuse
- **WHEN** helper needs LLM chat completion
- **THEN** the implementation uses existing OpenRouter configuration pipeline and calling pattern in current codebase

### Requirement: Dedicated async Qdrant client integration
The system SHALL provide a dedicated async Qdrant client in app service layer (aligned with Jira/Lark client style), and SHALL read its connection/runtime settings from `config.yaml`.

#### Scenario: Helper uses dedicated Qdrant service client
- **WHEN** helper needs vector retrieval for related context
- **THEN** the implementation uses a shared async Qdrant service client instead of creating ad-hoc clients per request

#### Scenario: Qdrant strategy remains aligned with existing AI modules
- **WHEN** helper executes vector retrieval
- **THEN** the implementation follows existing Qdrant query/config strategy already used by current AI modules

#### Scenario: Long-running Qdrant usage does not degrade other users
- **GIVEN** multiple users trigger helper flow concurrently
- **WHEN** some requests execute long-running vector retrieval
- **THEN** connection pool, retry, timeout, and concurrency limit from `config.yaml` are applied to keep service stable for other users

### Requirement: Synchronous flow with minimized DB lock impact
The system SHALL keep helper as synchronous request/response flow and MUST minimize impact on other users by confining DB write lock duration to commit stage only.

#### Scenario: Long AI processing does not hold DB write transaction
- **WHEN** requirement normalization, analysis, coverage, testcase generation, and audit are running
- **THEN** no long-lived DB write transaction is held until final commit
