## MODIFIED Requirements

### Requirement: Helper prompts MUST be loaded from Markdown files per AI stage

The system SHALL load QA AI Agent prompt templates from `prompts/jira_testcase_helper/*.md`, with separate prompt files for:
- `seed.md` or equivalent initial seed-generation prompt
- `seed_refine.md` or equivalent incremental seed-refinement prompt
- `testcase.md` for final testcase expansion

#### Scenario: Load prompt template for seed generation
- **WHEN** the helper prepares the first screen-4 seed-generation request
- **THEN** the prompt service reads the configured seed-generation markdown template instead of using inline prompt text

#### Scenario: Load prompt template for testcase generation
- **WHEN** the helper prepares screen-5 testcase generation
- **THEN** the prompt service reads `prompts/jira_testcase_helper/testcase.md` or the configured equivalent template

### Requirement: Model routing MUST separate seed generation and testcase generation

The system SHALL keep prompt content outside configuration models, and `config.yaml` SHALL define separate routing for the high-tier seed-generation model and the lower-tier testcase-generation model. The settings layer SHALL also support `.env` / process environment variables to override stage-model configuration.

#### Scenario: Parse helper configuration for staged generation
- **WHEN** settings are loaded from `config.yaml`
- **THEN** the helper can resolve distinct models for seed generation and testcase generation without embedding prompt bodies in configuration

#### Scenario: Environment variables override staged model routing
- **GIVEN** `config.yaml` contains default `ai.qa_ai_helper.models.seed` and `ai.qa_ai_helper.models.testcase` values
- **WHEN** `.env` or process environment provides `QA_AI_HELPER_MODEL_SEED` and/or `QA_AI_HELPER_MODEL_TESTCASE`
- **THEN** the helper resolves the stage models from environment values instead of the YAML defaults

#### Scenario: Unresolved placeholder fails fast
- **WHEN** `config.yaml` references `${QA_AI_HELPER_MODEL_SEED}` or `${QA_AI_HELPER_MODEL_TESTCASE}` but the environment value is missing
- **THEN** settings loading fails with a configuration error instead of treating the placeholder string as a real model name

#### Scenario: Seed refinement model falls back to seed model
- **WHEN** the helper prepares a seed-refinement request and no dedicated `seed_refine` model is configured
- **THEN** the helper uses the resolved seed-generation model for that refinement stage

#### Scenario: Default stage temperatures favor stability
- **WHEN** the helper uses its default staged-model settings without explicit temperature overrides
- **THEN** the default temperatures are `seed = 0.1`, `seed_refine = 0.0`, and `testcase = 0.0` to favor stable, low-drift output

### Requirement: Missing prompt files MUST have deterministic fallback

If a required seed-generation, seed-refinement, or testcase-generation prompt file is missing or empty, the system SHALL apply a deterministic built-in template and MUST emit a warning log for operators.

#### Scenario: Missing seed refinement prompt file
- **WHEN** the configured seed refinement prompt file is missing
- **THEN** helper continues with a built-in fallback template and writes a warning log indicating prompt fallback was applied
