## ADDED Requirements

### Requirement: Team statistics page SHALL provide QA Helper analytics tab
The system SHALL provide a dedicated `QA AI Agent - Test Case Helper` tab in Team Statistics, and MUST load helper analytics without requiring page reload.

#### Scenario: Open helper analytics tab in team statistics
- **GIVEN** the user has admin-level access to Team Statistics
- **WHEN** the user switches to the QA Helper tab
- **THEN** the system loads helper analytics data for the selected date range and team filter
- **THEN** the UI shows visible sections for progress, token/cost, and stage metrics

### Requirement: System SHALL show account-ticket progress for helper sessions
The system SHALL provide per-account and per-ticket progress for helper sessions, including current phase and session status.

#### Scenario: Render account-ticket progress list
- **WHEN** helper analytics data is returned
- **THEN** each record includes user identity, ticket key, current phase, and session status
- **THEN** records can be filtered by team/date and remain scoped to selected teams

### Requirement: System SHALL provide token usage and estimated cost summary
The system SHALL aggregate token usage and estimate cost using the fixed Google Vertex pricing table provided by product requirement.

#### Scenario: Use fixed Google Vertex tiered rates
- **WHEN** the analytics API calculates estimated cost
- **THEN** it MUST use USD per 1M tokens with threshold `200,000` for each token category
- **THEN** rates MUST be:
  - `Input`: `<=200K` = `2`, `>200K` = `4`
  - `Output`: `<=200K` = `12`, `>200K` = `18`
  - `Cache Read`: `<=200K` = `0.20`, `>200K` = `0.40`
  - `Cache Write`: `0.375` (fixed)
  - `Input Audio`: `<=200K` = `2`, `>200K` = `4`
  - `Input Audio Cache`: `<=200K` = `0.20`, `>200K` = `0.40`

#### Scenario: Calculate estimated cost from token usage
- **GIVEN** helper analytics includes token usage by model and token type
- **WHEN** the analytics API computes cost
- **THEN** the response includes estimated cost for input, output, cache read, and cache write token categories
- **THEN** the response includes total estimated cost and pricing metadata version

#### Scenario: Display estimate disclaimer
- **WHEN** the helper analytics tab renders token/cost data
- **THEN** the UI marks all cost values as estimated and non-billing

### Requirement: System SHALL provide stage duration and output metrics
The system SHALL report stage-level duration and output quantities for helper workflow phases.

#### Scenario: Show stage metrics for analysis and generation outcomes
- **WHEN** helper stage telemetry is aggregated
- **THEN** the response includes phase duration metrics (count, avg, p95, max)
- **THEN** the response includes output counts for pre-testcase and testcase generation

### Requirement: System SHALL expose helper analytics through admin statistics API
The system SHALL provide a dedicated admin endpoint for helper analytics aligned with existing Team Statistics filter semantics.

#### Scenario: Query helper analytics API with range filters
- **WHEN** the client calls helper analytics endpoint with days or start/end date and team filter
- **THEN** the backend validates the range using existing statistics constraints
- **THEN** the endpoint returns progress, token/cost, and stage metrics in one response payload
