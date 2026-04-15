## ADDED Requirements

### Requirement: Helper workflow SHALL persist stage-level telemetry for analytics
The system SHALL persist stage-level telemetry for QA Helper runs so team analytics can aggregate usage and performance consistently.

#### Scenario: Record telemetry when helper stage completes
- **WHEN** a helper stage (analysis, pretestcase generation, testcase generation, commit) completes
- **THEN** the system stores session_id, team_id, user_id, ticket_key, phase, start/end time, and duration
- **THEN** the system stores available token usage breakdown and model identifier

#### Scenario: Record telemetry when helper stage fails
- **WHEN** a helper stage fails
- **THEN** the system still writes telemetry with failure status and measured duration
- **THEN** the failure telemetry remains queryable by team analytics API

### Requirement: Helper telemetry SHALL include output cardinality for generation stages
The system SHALL record output counts for pre-testcase and testcase generation stages.

#### Scenario: Store output counts after generation stage
- **WHEN** the helper stage produces pre-testcase entries or final testcases
- **THEN** telemetry stores corresponding output counts for downstream aggregation
- **THEN** team analytics can compute total and per-stage output volume without re-parsing draft payload

### Requirement: Helper telemetry SHALL be backward compatible with existing session APIs
The system SHALL keep existing helper session lifecycle APIs and resume behavior functional while telemetry is introduced.

#### Scenario: Existing helper session operations remain available
- **WHEN** telemetry persistence is enabled
- **THEN** start/read/update/generate/commit helper APIs continue returning existing contract fields
- **THEN** no new telemetry field is required from existing helper API clients
