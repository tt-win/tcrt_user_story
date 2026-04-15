## ADDED Requirements

### Requirement: Requirement Completeness Validation Gate
The system SHALL validate requirement completeness before analyze execution and MUST report missing sections and missing mandatory fields.

#### Scenario: Detect incomplete requirement sections
- **WHEN** helper receives requirement content that lacks required sections or mandatory fields
- **THEN** the system returns validation results including `missing_sections[]`, `missing_fields[]`, and `quality_level`

### Requirement: Warning Before Analyze Continuation
The system SHALL present a warning interaction before continuing from setup to analyze when requirement completeness is below accepted quality.

#### Scenario: User is warned before proceeding
- **WHEN** the user requests to continue with an incomplete requirement
- **THEN** the UI shows a warning with missing-item details and explicit options to return and fix or proceed anyway

### Requirement: Explicit Override Continuation Contract
The system SHALL allow continuation with incomplete requirement only when user confirmation is explicit and captured as override intent.

#### Scenario: User chooses proceed anyway
- **WHEN** the user confirms continuation in warning dialog
- **THEN** analyze flow continues with `override=true` and the warning snapshot is attached to the session trace

### Requirement: Override Auditability
The system SHALL persist override trace metadata for review and diagnostics.

#### Scenario: Session trace shows override decisions
- **WHEN** operators inspect helper draft/session trace data
- **THEN** they can identify override status, missing-item snapshot, actor, and timestamp for that continuation decision
