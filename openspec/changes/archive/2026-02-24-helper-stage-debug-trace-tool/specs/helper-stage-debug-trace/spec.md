## ADDED Requirements

### Requirement: Stage Debug Runner Contract
The system SHALL provide a unified debug runner that executes Helper stages in order and persists one artifact file per stage.

#### Scenario: Execute full stage debug flow
- **WHEN** engineer runs the debug runner for a ticket
- **THEN** the runner writes stage artifacts for requirement_ir, analysis, coverage, testcase, audit, and final_testcase

### Requirement: Independent Stage Function Execution
The system SHALL expose one function per stage and SHALL allow running a single stage by reading the required prior-stage artifact files.

#### Scenario: Replay only coverage stage
- **GIVEN** requirement_ir and analysis artifacts already exist
- **WHEN** engineer triggers only the coverage stage function
- **THEN** the tool reads prior artifacts and writes a new coverage artifact without rerunning earlier stages

### Requirement: Full LLM Trace Persistence
The system SHALL persist complete stage evidence including prompt and raw LLM response for every LLM-involved stage.

#### Scenario: Capture raw response on parse failure
- **GIVEN** a stage returns malformed JSON from LLM
- **WHEN** the stage artifact is written
- **THEN** the artifact SHALL include prompt, raw response, parse error message, and retry metadata

### Requirement: Formatted Stage Presentation
The system SHALL provide a formatted view function that renders a selected stage artifact in a complete, human-readable layout.

#### Scenario: Render stage artifact for review
- **WHEN** engineer requests formatted output for an existing stage artifact
- **THEN** the tool SHALL print structured sections for inputs, prompt, raw response, parsed payload, and errors

### Requirement: Non-Repository Output Storage
The system SHALL store debug tools output under git-ignored paths and SHALL NOT require committing generated artifacts.

#### Scenario: Generate local-only artifacts
- **WHEN** debug runner writes artifacts
- **THEN** generated files are saved in `.tmp/helper-debug-runs/<run-id>/` and excluded from git tracking
