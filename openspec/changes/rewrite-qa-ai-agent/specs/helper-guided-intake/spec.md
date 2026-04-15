## ADDED Requirements

### Requirement: Ticket input screen MUST remain sessionless until submission

The system SHALL open the QA AI Agent on a ticket-input screen, and MUST NOT create a persisted helper session until the user submits a ticket key.

#### Scenario: Entry button opens screen 1 without a session
- **WHEN** the user clicks the QA AI Agent entry
- **THEN** the UI opens screen 1 (`載入需求單`) and no persisted session record exists yet

### Requirement: Ticket submission MUST create a new helper session

The system SHALL create a brand-new helper session only after the user submits a ticket key on screen 1.

#### Scenario: Submitting a ticket creates a session
- **WHEN** the user enters a ticket key on screen 1 and clicks `載入需求單內容`
- **THEN** the system creates a new session, stores the ticket key, and routes the user to screen 2

### Requirement: Restart MUST clear the current in-progress session before the next submission

The system SHALL treat `重新開始` as a destructive reset for the current in-progress helper session, and SHALL return the user to screen 1 before the next ticket submission creates a new session.

#### Scenario: Restart clears the unfinished session and returns to screen 1
- **WHEN** the user clicks `重新開始` before the flow has committed results
- **THEN** the current helper session data is deleted, the UI returns to screen 1, and the next ticket submission creates a new session

#### Scenario: Completed session is not destructively restarted from screen 7
- **WHEN** the user reaches screen 7 after a successful commit
- **THEN** the UI offers starting a new flow instead of deleting the already committed session record

### Requirement: Screen 2 MUST render read-only ticket markdown

The system SHALL convert Jira markup into markdown for screen 2 display, and MUST keep the ticket content read-only on that screen.

#### Scenario: Jira content is shown without inline editing
- **WHEN** screen 2 (`需求單內容確認`) is rendered
- **THEN** the ticket description is shown as converted markdown and the user cannot edit the raw ticket content there

### Requirement: Guided intake parser MUST prepare downstream structured data

The system SHALL normalize the loaded ticket into a `qa_ai_helper_preclean.py`-compatible structured payload for downstream section and verification planning.

#### Scenario: Parser output is prepared after ticket load
- **WHEN** the system loads a valid Jira ticket into screen 2
- **THEN** it prepares structured sections for `User Story Narrative`, `Criteria`, `Technical Specifications`, and `Acceptance Criteria` for screen 3 consumption

## REMOVED Requirements

### Requirement: Ticket fetch MUST support optional comment inclusion
**Reason**: The revised screen-1 flow only asks for `Ticket Number`; comment-fetch toggles are no longer part of the primary journey.
**Migration**: If comment support is needed later, it should be added as a separate optional extension without changing the session-creation rule.

### Requirement: Guided intake MUST support multilingual raw source resolution
**Reason**: The new intake flow focuses on a single read-only ticket confirmation step and does not ask the user to resolve multilingual source blocks before planning.
**Migration**: Keep parser normalization compatible with current ticket formats, but do not surface a multilingual source-resolution workflow in the new helper.
