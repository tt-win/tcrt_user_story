## MODIFIED Requirements

### Requirement: agent loop recognizes batch planning tools as read-only continuation triggers
The agent loop SHALL treat `plan_batch` and `generate_chunk_actions` as read tools. After either tool returns a result, the loop MAY continue to the next iteration to process the plan or chunk, or it MAY end the turn and present the result to the user.

#### Scenario: plan_batch result ends the turn for user review
- **WHEN** `plan_batch` returns a plan
- **THEN** the agent loop MAY end the turn with a text_delta summarizing the plan and a light confirmation request, instead of immediately proceeding to chunk generation

#### Scenario: generate_chunk_actions result feeds into batch_execute_actions within the same turn
- **WHEN** `generate_chunk_actions` returns valid actions and the user has authorized auto-continue or this is the first chunk
- **THEN** the agent loop MAY continue and create a `batch_execute_actions` pending action in the same turn

## ADDED Requirements

### Requirement: batch progress events are emitted through the existing SSE event stream
The system SHALL emit batch progress events using the existing `assistant_events` table and SSE event stream. Each batch event type SHALL be distinct from existing event types and SHALL carry a payload that includes the batch job identifier and chunk identifier.

#### Scenario: batch plan ready event
- **WHEN** a batch plan is validated and ready for user review or execution
- **THEN** the system SHALL emit a `batch_plan_ready` event with the batch job id, total target count, and total chunk count

#### Scenario: batch chunk pending event
- **WHEN** a chunk's actions are generated and a `batch_execute_actions` pending action is created
- **THEN** the system SHALL emit a `batch_chunk_pending` event with the chunk id, target count, and whether auto-continue is authorized
