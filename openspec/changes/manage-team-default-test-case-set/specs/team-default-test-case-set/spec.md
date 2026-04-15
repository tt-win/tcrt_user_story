## ADDED Requirements

### Requirement: Admin can set team default Test Case Set
The system SHALL allow users with admin privileges to designate an existing Test Case Set as the default for their team.

#### Scenario: Admin sets a new default
- **WHEN** an admin selects an existing Test Case Set to be the default
- **THEN** the system updates the set to be the default
- **AND** the previous default set is no longer the default

### Requirement: Default Set must have an Unassigned section
The system MUST ensure that any Test Case Set designated as default has an "Unassigned" section, creating one if it doesn't exist.

#### Scenario: Set as default creates Unassigned section if missing
- **WHEN** an admin sets a Test Case Set without an "Unassigned" section as default
- **THEN** the system creates an "Unassigned" section in that set before marking it as default

### Requirement: Unified default resolution
The system MUST use a single shared backend logic to resolve the default Test Case Set for a team.

#### Scenario: Fallback uses unified default
- **WHEN** a system process (like Test Case creation without a set, or adhoc resolution) requires a default set
- **THEN** it resolves to the current default set using the unified logic
