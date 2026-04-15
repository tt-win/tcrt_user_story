## MODIFIED Requirements

### Requirement: Format validation MUST gate transition from screen 2 to screen 3

The system SHALL validate the parsed ticket structure before the user can enter the verification workspace, and MUST require at least:
- `User Story Narrative`
- `Criteria`
- `Acceptance Criteria`

`Technical Specifications` MAY be empty, but if present it SHALL be preserved for screen 3 reference.

#### Scenario: Missing required sections block progression
- **WHEN** the parsed ticket is missing `User Story Narrative`, `Criteria`, or `Acceptance Criteria`
- **THEN** the system shows the missing sections on screen 2 and does not allow navigation to screen 3

#### Scenario: Missing user-story narrative fields block progression
- **WHEN** `User Story Narrative` exists but one or more of `As a`, `I want`, or `So that` are empty after parsing
- **THEN** the system reports the missing narrative fields on screen 2 and does not allow navigation to screen 3

#### Scenario: Unnamed acceptance scenario blocks progression
- **WHEN** the parser emits an Acceptance Criteria scenario named `Unnamed Scenario`
- **THEN** the system treats that scenario as invalid, surfaces the parser error on screen 2, and blocks navigation to screen 3

#### Scenario: Incomplete gherkin clauses block progression
- **WHEN** any Acceptance Criteria scenario is missing `Given`, `When`, or `Then`
- **THEN** the system reports the missing clauses for that scenario on screen 2 and does not allow navigation to screen 3

#### Scenario: Missing technical specifications do not block progression
- **WHEN** the parsed ticket has no `Technical Specifications`
- **THEN** the system marks that area as empty reference content but still allows progression if the other required sections are valid

#### Scenario: Parser errors are surfaced to the user
- **WHEN** the parser cannot normalize one or more required sections from the ticket
- **THEN** the system returns validation feedback with missing sections, parser errors, and the reason the workflow cannot continue

## REMOVED Requirements

### Requirement: Explicit Override Continuation Contract
**Reason**: The new screen-2 gate does not allow users to override missing required sections and continue.
**Migration**: Invalid tickets must be corrected at the ticket source or reloaded later; the helper does not proceed with `unknown` or override markers.

### Requirement: Override Auditability
**Reason**: There is no longer an override path for missing required sections in the new design.
**Migration**: Keep only current-flow validation results needed by V3 sessions; do not preserve or migrate legacy override or legacy validation statistics.
