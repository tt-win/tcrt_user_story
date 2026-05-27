## ADDED Requirements

### Requirement: Session Display Naming Uses Timestamp Labels

The system SHALL present helper session names using timestamp-based labels instead of serial-number naming in user-facing session management surfaces.

#### Scenario: Session labels are timestamp-based

- **WHEN** the system renders helper session items in session management UI
- **THEN** the displayed session name MUST be formatted from session timestamp metadata
- **THEN** serial-number naming MUST NOT be used as the primary user-facing session label

### Requirement: Session Management APIs for Lifecycle Control

The system SHALL provide helper session lifecycle APIs for listing, deleting one session, deleting selected sessions, and clearing all sessions in a team context.

#### Scenario: Client performs lifecycle operations

- **WHEN** the client calls session lifecycle endpoints with valid team write permission
- **THEN** the backend MUST return list and deletion results scoped to that team
- **THEN** deleted sessions MUST no longer be resumable by helper session retrieval endpoints

## MODIFIED Requirements

### Requirement: Existing Helper UI Preservation

The system SHALL preserve existing Test Case Helper UI architecture and interaction assets as the primary baseline, and MUST only introduce minimal UI changes required by the new requirement flow and session management lifecycle.

#### Scenario: Apply new flow without rebuilding helper UI

- **WHEN** the new requirement validation, warning flow, and session manager integration are implemented
- **THEN** the implementation reuses the existing three-step helper modal, interaction patterns, and core components instead of rebuilding the UI from scratch

#### Scenario: Session manager integration keeps helper experience coherent

- **WHEN** the user switches between helper modal and session manager modal
- **THEN** the helper workflow state remains recoverable and continues from the selected or current session
- **THEN** modal switching MUST NOT require full-page reload
