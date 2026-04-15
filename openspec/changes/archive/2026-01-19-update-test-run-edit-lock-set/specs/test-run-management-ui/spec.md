# test-run-management-ui Specification

## Purpose
Define the Test Run management UI behavior for editing Test Run configurations and items.

## ADDED Requirements
### Requirement: Read-only Test Case Set in config edit mode
When editing an existing Test Run configuration, the system SHALL display the current Test Case Set as read-only text and MUST NOT require re-selection.

#### Scenario: Edit configuration keeps original set
- **WHEN** the user opens the Test Run configuration in edit mode
- **THEN** the Test Case Set is shown as read-only and the original set_id remains unchanged

### Requirement: Read-only Test Case Set in test case edit mode
When editing Test Run test cases, the system SHALL display the current Test Case Set as read-only text and MUST prevent switching to another set.

#### Scenario: Edit test cases keeps set locked
- **WHEN** the user edits Test Run test cases
- **THEN** the Test Case Set is read-only and the case list is filtered by the original set
