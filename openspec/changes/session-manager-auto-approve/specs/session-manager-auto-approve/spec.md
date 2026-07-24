# Spec: Session Manager Modal & Auto-Approve Mode

## ADDED Requirements

### Requirement: Batch Deletion API
The API SHALL provide an endpoint `POST /api/assistant/conversations/batch-delete` to atomically delete multiple assistant conversation sessions.

#### Scenario: User batch deletes conversations
- **GIVEN** a list of valid conversation IDs
- **WHEN** the user sends a batch delete request
- **THEN** the server SHALL cancel any active turns and delete the specified conversation records in a single transaction.

### Requirement: Auto-Approve Mode Boundary
The AI Assistant SHALL allow toggling Auto-Approve Mode for non-destructive actions while enforcing manual confirmation for high-impact actions.

#### Scenario: Auto-approve non-destructive action
- **GIVEN** Auto-Approve Mode is enabled
- **WHEN** a non-destructive tool action is proposed
- **THEN** the system SHALL automatically confirm and execute the action.

#### Scenario: Intercept high-impact action
- **GIVEN** Auto-Approve Mode is enabled
- **WHEN** a high-impact or irreversible tool action is proposed
- **THEN** the system SHALL pause and require explicit manual user confirmation.
