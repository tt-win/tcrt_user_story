# Spec: Global AI Assistant Session

## MODIFIED Requirements

### Requirement: Unified Global Assistant Session
The AI Assistant SHALL operate on global conversation sessions (`scope_type: 'global'`) by default, persisting chat continuity across workspace team switches.

#### Scenario: User switches workspace team during conversation
- **GIVEN** an active global AI Assistant conversation session
- **WHEN** the user switches workspace team in the UI navigation bar
- **THEN** the active conversation session SHALL remain open and active
- **AND** the in-progress turn SHALL NOT be terminated solely due to workspace switching.

#### Scenario: Listing conversations
- **GIVEN** a user with global conversations and historical team conversations
- **WHEN** the user opens recent conversations menu
- **THEN** global conversations and user-accessible conversations SHALL be listed without forcing team-scoped isolation.
