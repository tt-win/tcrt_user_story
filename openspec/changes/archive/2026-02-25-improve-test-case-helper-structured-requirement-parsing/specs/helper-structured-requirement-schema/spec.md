## ADDED Requirements

### Requirement: Standardized Requirement Section Schema
The system SHALL parse helper requirement input into a standardized section contract containing:
- `menu_paths[]`
- `user_story_narrative.{as_a,i_want,so_that}`
- `criteria.items[]`
- `technical_specifications.items[]`
- `acceptance_criteria.scenarios[]`
- `api_paths[]`
- `references[]`

#### Scenario: Parse Jira wiki formatted requirement
- **WHEN** helper receives requirement text using Jira wiki headings and bullet structures
- **THEN** the system produces `structured_requirement` with normalized section fields

### Requirement: User Story Narrative Field Extraction
The system SHALL extract `As a`, `I want`, and `So that` as distinct structured fields and MUST preserve original semantic intent.

#### Scenario: Extract As a / I want / So that fields
- **WHEN** the narrative section contains `As a`, `I want`, and `So that` entries
- **THEN** the system maps them to `user_story_narrative` subfields without collapsing them into a single text blob

### Requirement: Acceptance Scenario Decomposition
The system SHALL decompose acceptance criteria into scenario objects with explicit `given[]`, `when[]`, `then[]`, and `and[]` segments.

#### Scenario: Convert Given-When-Then into structured scenarios
- **WHEN** requirement acceptance content includes scenario-style statements
- **THEN** each scenario is stored as a separate structured item with `when` and `then` clauses preserved for downstream testing

### Requirement: Stable Requirement Key Generation
The system SHALL assign stable requirement identifiers (`requirement_key`) for parsed requirement units and MUST carry them into downstream artifacts.

#### Scenario: Rebuild does not drift requirement keys
- **WHEN** the same normalized requirement content is re-parsed within a session
- **THEN** generated `requirement_key` values remain stable so pre-testcase and testcase mapping does not drift

### Requirement: Requirement-Rich Pre-testcase Context
The system SHALL produce requirement-rich context for each pre-testcase entry, including:
- `requirement_context.summary`
- `requirement_context.spec_requirements[]`
- `requirement_context.verification_points[]`
- `requirement_context.expected_outcomes[]`

#### Scenario: Pre-testcase entry keeps requirement and verification intent
- **WHEN** analysis and coverage are transformed into pre-testcase entries
- **THEN** each entry contains requirement/spec/verification context directly instead of requiring ref-only lookup
