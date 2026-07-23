## ADDED Requirements

### Requirement: per-action outcomes are recorded in the batch execution journal
When `batch_execute_actions` executes, the system SHALL record the outcome of each child action in `assistant_tool_executions.result_payload_json` under a `per_action_outcomes` key.

#### Scenario: first two actions succeed and third times out
- **WHEN** `batch_execute_actions` executes three child actions and the third action times out
- **THEN** `result_payload_json` SHALL contain outcomes for the first two actions as `succeeded` and the third as `unknown`

#### Scenario: replay does not re-execute already recorded actions
- **WHEN** the system resumes a chunk using a new `batch_execute_actions` pending action
- **THEN** any child action whose outcome is already recorded as `succeeded` or `failed` SHALL NOT be included in the resumed batch

### Requirement: chunk resume creates a new batch_execute_actions pending with remaining actions
After a chunk reaches `unknown` due to a partial execution, the system SHALL create a new `batch_execute_actions` pending action containing only the child actions that have not yet reached a definitive outcome.

#### Scenario: resume after partial execution
- **WHEN** a 5-action chunk has outcomes `succeeded, succeeded, unknown, pending, pending`
- **THEN** the resumed batch SHALL contain only the last two actions, and the third action SHALL be treated as unknown and excluded from the resumed batch

### Requirement: resumed batches preserve execution semantics
A resumed batch SHALL preserve the original ordering of child actions, the same execution_key lineage, and the same tool_timeout deadline from the original confirmation.

#### Scenario: resumed batch keeps original order
- **WHEN** the original chunk executed actions A, B, C in order and C was unknown
- **THEN** the resumed batch SHALL execute only C, not reorder or add new actions

### Requirement: manual intervention is required for ambiguous outcomes
Any child action with outcome `unknown` SHALL NOT be automatically retried. The system SHALL report the unknown action to the user and recommend using read tools to verify the actual state before deciding whether to retry.

#### Scenario: action outcome is unknown
- **WHEN** a child action ends in `unknown`
- **THEN** the system SHALL emit a `batch_chunk_executed` event that marks the action as unknown and provides guidance for verification
