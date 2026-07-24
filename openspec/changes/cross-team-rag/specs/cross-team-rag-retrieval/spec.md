# Spec: Cross-Team Knowledge RAG Retrieval

## MODIFIED Requirements

### Requirement: Authorized Cross-Team Knowledge Retrieval
The RAG retrieval engine SHALL support querying knowledge across user-authorized teams (`allowed_team_ids`).

#### Scenario: User queries cross-team test cases
- **GIVEN** a user with authorization for team 1 and team 2
- **WHEN** the user invokes knowledge search
- **THEN** search results MAY contain entities from team 1 and team 2
- **AND** search results SHALL NOT contain entities from unauthorized team 3.

#### Scenario: Dual-route retrieval
- **GIVEN** a primary team ID and allowed team IDs
- **WHEN** knowledge search is executed
- **THEN** primary team entities AND authorized cross-team entities are retrieved and merged without duplication.
