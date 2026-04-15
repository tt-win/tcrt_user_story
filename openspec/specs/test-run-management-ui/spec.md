# test-run-management-ui Specification

## Purpose
Refactor Test Run Management page to use external static assets while preserving all existing functionality including permissions, status changes, set/config management, and search flows.

## Requirements
### Requirement: Read-only Test Case Set in config edit mode
When editing an existing Test Run configuration, the system SHALL allow updating the Test Case Set scope as a multi-select list instead of enforcing a read-only single set.

#### Scenario: Edit configuration updates allowed set scope
- **WHEN** the user opens Test Run configuration in edit mode
- **THEN** the UI displays multi-select Test Case Set scope for that Test Run
- **AND** the submitted payload includes all selected set IDs
- **AND** the backend rejects invalid set IDs that do not belong to the same team

### Requirement: Read-only Test Case Set in test case edit mode
When editing Test Run test cases, the system SHALL allow selecting cases across all configured Test Case Sets and SHALL NOT force a single locked set.

#### Scenario: Edit test cases across configured sets
- **WHEN** the Test Run is configured with multiple Test Case Sets
- **THEN** the case selection modal loads cases from all configured sets
- **AND** the user can filter visible cases by one set without losing current selections

### Requirement: Multi-set scope selection in create flow
The system SHALL require selecting one or more Test Case Sets when creating a Test Run and SHALL keep selection within the current team.

#### Scenario: Create Test Run with multiple sets
- **WHEN** the user creates a new Test Run and selects multiple Test Case Sets
- **THEN** the Test Run is created successfully with all selected set IDs recorded
- **AND** empty selection is rejected with a user-visible validation message

### Requirement: Automatic item cleanup on set-scope reduction
The system SHALL automatically remove invalidated Test Run items when set scope is reduced during Test Run edit flow.

#### Scenario: Remove set and prune affected items
- **WHEN** the user removes a Test Case Set from Test Run scope in edit mode
- **AND** existing Test Run items still belong to that removed set
- **THEN** the save succeeds with the new set scope
- **AND** Test Run items from removed sets are deleted from that Test Run
- **AND** the UI receives and shows a cleanup summary (removed item count)

### Requirement: Dedicated assets for Test Run Management
The system SHALL load Test Run Management styles and scripts from dedicated static files and keep the template markup free of inline CSS/JS beyond asset wiring.

#### Scenario: Page loads with external assets
- **WHEN** the user opens the Test Run Management page
- **THEN** the page loads the dedicated CSS/JS assets and renders without inline style/script blocks

### Requirement: Functional parity after asset refactor
The system SHALL preserve existing Test Run Management behaviors for permissions, status changes, set/config management, and search flows after the refactor.

#### Scenario: Core flows remain available
- **WHEN** the user views the page, updates statuses, edits configurations, and uses search
- **THEN** the UI responds as before with no missing controls or errors
