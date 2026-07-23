## MODIFIED Requirements

### Requirement: batch_execute_actions SHALL record per-action outcomes
`batch_execute_actions` SHALL remain a single composite tool with one overall outcome (`succeeded`, `failed`, or `unknown`). The executor MUST additionally record the outcome of each child action inside `assistant_tool_executions.result_payload_json` under `per_action_outcomes`.

#### Scenario: full success
- **WHEN** every child action in the batch returns a clear 2xx
- **THEN** the overall outcome is `succeeded` and `per_action_outcomes` lists every action as `succeeded`

#### Scenario: partial execution before timeout
- **WHEN** two child actions return 2xx and the third action times out
- **THEN** the overall outcome is `unknown`, `per_action_outcomes` marks the first two as `succeeded` and the third as `unknown`, and the system does not retry the third action automatically

## ADDED Requirements

### Requirement: batch_execute_actions is rejected when it is too large for a single LLM response
When `batch_execute_actions` is prepared with an action count or total serialized parameter size exceeding configured guardrail thresholds, the executor SHALL reject it with a fixable `batch_too_large` error and instruct the model to use `plan_batch` instead.

#### Scenario: 50 actions with very large parameters
- **WHEN** `batch_execute_actions` contains 50 actions and the total serialized parameter size exceeds the configured limit
- **THEN** the executor SHALL reject the tool call with a fixable error and a message pointing to `plan_batch`

#### Scenario: small batch still allowed
- **WHEN** `batch_execute_actions` contains 5 actions within the size limit
- **THEN** the executor SHALL process it normally without requiring `plan_batch`
