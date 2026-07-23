## ADDED Requirements

### Requirement: plan_batch tool is a read-only planning assistant
The system SHALL provide a `plan_batch` read tool that accepts a user goal and a list of candidate targets, and returns a lightweight batch plan with target grouping and chunk sizing.

#### Scenario: User asks to rewrite many test cases
- **WHEN** the user requests a bulk modification of many test cases
- **THEN** the assistant MAY call `plan_batch` to produce a plan before generating any write actions

#### Scenario: plan_batch output is lightweight
- **WHEN** `plan_batch` returns a plan
- **THEN** each target entry SHALL contain only an identifier, a short change summary, and group/chunk assignment; full parameters SHALL NOT be included in the plan

### Requirement: plan targets are validated against actual data
Before a plan is used for chunk generation, the system SHALL validate that each target identifier exists and belongs to the conversation's team.

#### Scenario: plan includes a non-existent test case
- **WHEN** `plan_batch` includes a target id that does not exist or is not in the conversation team
- **THEN** the system SHALL remove that target from the plan and report it to the user

### Requirement: plan supports user-defined grouping hints
The `plan_batch` tool SHALL accept optional grouping hints (e.g. by test case set, section, or ticket) and SHALL prefer grouping related targets into the same chunk when feasible.

#### Scenario: User requests grouping by section
- **WHEN** the user asks to keep test cases from the same section together
- **THEN** `plan_batch` SHALL assign targets from the same section to the same chunk when possible

### Requirement: plan output declares chunk boundaries and ordering
A batch plan SHALL declare the total number of chunks, the targets assigned to each chunk, and any ordering constraints between chunks.

#### Scenario: plan with sequential chunks
- **WHEN** the plan contains chunk A and chunk B, and chunk B logically depends on chunk A
- **THEN** the plan SHALL mark chunk B as dependent on chunk A and the system SHALL execute chunk A before chunk B

### Requirement: plan size is bounded
A single plan SHALL not exceed a configured maximum number of targets and a configured serialized size. If the user request exceeds these bounds, the system SHALL ask the user to narrow the scope.

#### Scenario: too many targets in plan
- **WHEN** the user requests to modify more targets than the configured plan maximum
- **THEN** the assistant SHALL respond with the total count and ask the user to filter or split the request
