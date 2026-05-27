## ADDED Requirements

### Requirement: Display default Test Case Set indicator
The Test Case Management UI SHALL clearly indicate which Test Case Set is currently the default for the team.

#### Scenario: Default set is visually marked
- **WHEN** a user views the list of Test Case Sets
- **THEN** the set that is currently the default displays a distinct visual indicator (e.g., a "Default" badge)

### Requirement: Admin UI for changing default set
The Test Case Management UI SHALL provide an action for admins to set a specific Test Case Set as the default.

#### Scenario: Admin clicks set as default
- **WHEN** an admin clicks the "Set as Default" action on a non-default Test Case Set
- **THEN** the system prompts for confirmation explaining that existing test cases will not be moved
- **AND** upon confirmation, the set becomes the new default and the UI updates to reflect the change

#### Scenario: Non-admin cannot change default
- **WHEN** a non-admin user views the list of Test Case Sets
- **THEN** the "Set as Default" action is not visible or is disabled
