## ADDED Requirements

### Requirement: Session Manager Entry in Helper Modal

The system SHALL provide a Session Manager entry button in the AI Agent - Test Case Helper modal, positioned to the right of the "Start Over" button.

#### Scenario: User opens session manager from helper modal

- **WHEN** the user clicks the Session Manager button in the helper modal footer
- **THEN** the helper modal MUST be hidden and the Session Manager modal MUST be shown

### Requirement: Session Manager Split Layout with Ticket-Aware List

The Session Manager modal SHALL use a left-right split layout aligned with the helper modal visual language. The left panel MUST show session list items including ticket key and timestamp-based session label.

#### Scenario: Session list renders ticket and timestamp label

- **WHEN** the Session Manager modal loads sessions
- **THEN** each list item MUST display the related JIRA ticket key (or an explicit empty fallback)
- **THEN** each list item MUST display a timestamp-based label derived from session time metadata

### Requirement: Resume Any Selected Session

The system SHALL allow users to resume any selected session from the Session Manager modal.

#### Scenario: Resume selected session and continue progress

- **WHEN** the user selects a session and executes Resume
- **THEN** the Session Manager modal MUST close
- **THEN** the helper modal MUST reopen with the selected session loaded at its current phase and saved drafts

### Requirement: Batch Session Deletion

The system SHALL support multi-select and batch deletion for selected helper sessions.

#### Scenario: Delete selected sessions

- **WHEN** the user selects multiple sessions and confirms batch delete
- **THEN** the system MUST delete all selected sessions in one operation
- **THEN** the session list MUST refresh and exclude deleted sessions

### Requirement: One-Click Session Cleanup

The system SHALL provide one-click cleanup to remove all visible helper sessions for the active team context.

#### Scenario: Clear all sessions

- **WHEN** the user confirms one-click cleanup
- **THEN** the system MUST delete all visible sessions for that team
- **THEN** the Session Manager modal MUST show an empty-state list after refresh

### Requirement: Session Manager Close Restores Helper Modal

The system SHALL restore helper modal visibility when Session Manager modal is closed without a page refresh.

#### Scenario: Close manager and return to helper modal

- **WHEN** the user closes the Session Manager modal
- **THEN** the helper modal MUST become visible again in the same browser context
