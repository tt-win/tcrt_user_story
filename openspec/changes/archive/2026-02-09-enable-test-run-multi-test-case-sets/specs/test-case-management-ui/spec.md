## ADDED Requirements

### Requirement: Impact warning before deleting Test Case Set
The system SHALL show a warning and require explicit confirmation before deleting a Test Case Set when that action will affect Test Runs.

#### Scenario: Delete set confirmation shows impacted Test Runs
- **WHEN** the user initiates deletion of a Test Case Set
- **THEN** the UI requests impact preview from backend
- **AND** the confirmation dialog displays impacted Test Runs and affected item counts
- **AND** deletion is not executed until the user confirms

### Requirement: Impact warning before moving Test Cases across sets
The system SHALL show a warning and require explicit confirmation before moving Test Cases to another Test Case Set when that action will affect Test Runs.

#### Scenario: Move confirmation shows impacted Test Runs
- **WHEN** the user submits a Test Case move operation to another set
- **THEN** the UI requests impact preview from backend
- **AND** the confirmation dialog displays impacted Test Runs and affected item counts
- **AND** move is not executed until the user confirms

#### Scenario: Cancel after warning keeps data unchanged
- **WHEN** the warning dialog is shown and the user cancels
- **THEN** no Test Case move is applied
- **AND** no Test Run items are removed
