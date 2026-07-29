## MODIFIED Requirements

### Requirement: Automatic cleanup for out-of-scope items
The system SHALL automatically remove existing Test Run items once their source Test Case Set no longer belongs to that Test Run scope. App-token Test Case cross-Set moves SHALL use a guarded mutation that verifies the preview fingerprint and updates target Set, valid target Section, and cleanup in one transaction. Generic App Token single/batch update routes SHALL NOT bypass this guard.

Every production Run Item create path SHALL participate in the same config-scope concurrency protocol as guarded moves: lock/serialize the config before scope validation, reread scope and case Set after the lock, then insert. PostgreSQL/MySQL SHALL use stable-order parent row locks; SQLite SHALL acquire `BEGIN IMMEDIATE` or equivalent cross-process writer serialization before any snapshot read.

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

#### Scenario: App token guarded single move receives cleanup summary
- **WHEN** app token guarded mutation moves one Test Case to a different Set
- **THEN** response SHALL include cleanup summary equivalent to batch/JWT behavior
- **AND** the Test Case SHALL NOT retain a Section from the previous Set

#### Scenario: App token guarded batch receives cleanup summary
- **WHEN** app token guarded batch move causes automatic cleanup
- **THEN** response SHALL include cleanup summary equivalent to the JWT API response

#### Scenario: Concurrent item create cannot escape scope validation
- **WHEN** Run Item create races a guarded cross-Set case move
- **THEN** exactly one operation SHALL establish the serialized state first
- **AND** the waiting operation SHALL reread scope/items and either reject the out-of-scope create or reject the stale fingerprint

### Requirement: Impact preview for destructive operations
The system SHALL provide backend impact-preview results before destructive operations so UI or app-token clients can display impacted Test Runs. App-token Test Case move preview SHALL require `test_case:write` plus `test_run:read`, return an impact fingerprint, and the corresponding mutation SHALL revalidate that fingerprint in its transaction; delete preview SHALL continue to require the corresponding admin capability.

#### Scenario: Preview before deleting Test Case Set
- **WHEN** UI requests preview for deleting a Test Case Set
- **THEN** API returns impacted Test Runs and per-run affected item counts

#### Scenario: Preview before moving Test Cases across sets
- **WHEN** UI or app-token client requests preview for moving Test Cases to another set
- **THEN** API returns impacted Test Runs and per-run affected item counts
- **AND** performs no mutation

#### Scenario: App token move preview uses write and Run read scopes
- **WHEN** app token has `test_case:write` and `test_run:read` and requests impact preview
- **THEN** response SHALL include impacted Test Runs and per-run affected item counts

#### Scenario: Concurrent change invalidates preview
- **WHEN** relevant case, scope, or item state changes between preview and mutation
- **THEN** mutation SHALL return 409 and SHALL NOT move cases or delete Run Items

#### Scenario: App token delete preview keeps admin scope
- **WHEN** app token requests preview for a destructive delete operation
- **THEN** API SHALL require the admin scope used by that delete

## ADDED Requirements

### Requirement: Test Run Set membership changes SHALL keep every affected Set status current

Every production Test Run Config membership attach, move, detach, initial membership, generated/rerun membership, or deletion SHALL use the shared relocation core, collect all non-null previous and target Test Run Set IDs for memberships that actually changed, and recalculate each such Set exactly once after mutation in the same transaction. External relocation requests SHALL validate expected previous membership under stable-order row locks before mutation.

#### Scenario: Batch move leaves a source Set with completed members
- **WHEN** one or more configs move from source Set A to target Set B
- **THEN** both A and B SHALL have status recalculated from their remaining/current members

#### Scenario: Batch detach affects multiple source Sets
- **WHEN** one request detaches configs that previously belonged to different Sets
- **THEN** every distinct previous Set SHALL be recalculated exactly once

#### Scenario: Config create and rerun also maintain target status
- **WHEN** App Token or JWT config create, rerun clone, generated run, or initial membership attaches a config
- **THEN** the shared relocation core SHALL update membership and recalculate the changed target Set exactly once

#### Scenario: Config deletion maintains previous Set status
- **WHEN** a config with membership is deleted
- **THEN** the shared relocation core SHALL detach it and recalculate the previous Set exactly once in the deletion transaction
