# test-run-multi-set-integrity Specification

## MODIFIED Requirements

### Requirement: Team-scoped multi-set configuration
The system SHALL store Test Run scope as a list of Test Case Set IDs and SHALL ensure every set belongs to the same team as the Test Run. This rule SHALL apply to both existing JWT APIs and app-token APIs.

#### Scenario: Accept valid same-team set scope
- **WHEN** a create or update request includes one or more Test Case Set IDs
- **AND** all IDs exist and belong to the Test Run team
- **THEN** the Test Run configuration is persisted with that complete set ID list

#### Scenario: Reject cross-team set IDs
- **WHEN** a request includes a Test Case Set ID that does not belong to the Test Run team
- **THEN** the API rejects the request with validation error

#### Scenario: App token cannot bypass team scope
- **WHEN** app token creates or updates a Test Run with a set ID from another team
- **THEN** the request SHALL be rejected
- **AND** no partial Test Run changes SHALL be persisted

### Requirement: Test Run items must stay inside configured set scope
The system SHALL only allow adding Test Run items whose source Test Case set is included in the Test Run configured set list. This rule SHALL apply to app-token batch item APIs.

#### Scenario: Reject item outside configured sets
- **WHEN** batch item creation includes a Test Case from a set not listed in Test Run scope
- **THEN** that item is rejected and the response reports the scope mismatch

#### Scenario: App token batch reports item-level mismatch
- **WHEN** app token batch item creation contains both valid and out-of-scope Test Cases
- **THEN** response SHALL report item-level success/failure
- **AND** out-of-scope items SHALL NOT be created

### Requirement: Automatic cleanup for out-of-scope items
The system SHALL automatically remove existing Test Run items once their source Test Case Set no longer belongs to that Test Run scope, including app-token writes that change Test Run set scope or move Test Cases across sets.

#### Scenario: Test Run scope removes a set
- **WHEN** a Test Run update removes one or more Test Case Set IDs from its configured scope
- **THEN** existing Test Run items from those removed sets are deleted from that Test Run

#### Scenario: Team deletes a Test Case Set
- **WHEN** a Test Case Set is deleted from a team
- **THEN** all Test Run items referencing Test Cases from that set are removed from Test Runs that include those items

#### Scenario: Test Case moves to set outside Test Run scope
- **WHEN** a Test Case is moved to another Test Case Set
- **AND** that target set is not in a Test Run configured scope that currently contains this Test Case
- **THEN** the corresponding Test Run item is removed from that Test Run

#### Scenario: App token receives cleanup summary
- **WHEN** app token write causes automatic cleanup
- **THEN** response SHALL include cleanup summary equivalent to the JWT API response

### Requirement: Impact preview for destructive operations
The system SHALL provide backend impact-preview results before destructive operations so UI or app-token clients can display impacted Test Runs.

#### Scenario: Preview before deleting Test Case Set
- **WHEN** UI requests preview for deleting a Test Case Set
- **THEN** API returns impacted Test Runs and per-run affected item counts

#### Scenario: Preview before moving Test Cases across sets
- **WHEN** UI requests preview for moving Test Cases to another set
- **THEN** API returns impacted Test Runs and per-run affected item counts

#### Scenario: App token can request impact preview
- **WHEN** app token has the admin scope required for the corresponding destructive operation (`test_case:admin` or `test_run:admin`) and requests impact preview
- **THEN** response SHALL include impacted Test Runs and per-run affected item counts

### Requirement: Cleanup summary in write responses
The system SHALL return final cleanup summary in write responses for operations that remove out-of-scope Test Run items, including app-token write responses.

#### Scenario: Write response includes final impact
- **WHEN** deletion or move operation is committed
- **THEN** API response includes final removed item count and impacted Test Runs

#### Scenario: App token write includes final impact
- **WHEN** app token commits deletion or move operation
- **THEN** API response SHALL include final removed item count and impacted Test Runs
