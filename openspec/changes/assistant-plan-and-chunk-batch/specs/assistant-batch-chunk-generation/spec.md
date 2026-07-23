## ADDED Requirements

### Requirement: generate_chunk_actions is a read-only tool for single chunk parameters
The system SHALL provide a `generate_chunk_actions` read tool that accepts a validated batch plan and a single chunk identifier, and returns the fully specified action parameters for that chunk.

#### Scenario: Generate actions for chunk 1
- **WHEN** the system requests actions for chunk 1 of an approved plan
- **THEN** `generate_chunk_actions` SHALL return complete parameters for every target assigned to chunk 1

#### Scenario: Chunk output is bounded
- **WHEN** `generate_chunk_actions` is called
- **THEN** the number of actions returned SHALL NOT exceed the configured chunk action limit, and the serialized output SHALL NOT exceed the configured chunk size limit

### Requirement: generated actions must conform to the original plan
The actions generated for a chunk SHALL target only the targets assigned to that chunk in the validated plan, SHALL use only the tool types declared in the plan, and SHALL modify only the fields declared in the plan.

#### Scenario: chunk generation includes an off-plan target
- **WHEN** `generate_chunk_actions` returns an action for a target that is not in the chunk's assigned target list
- **THEN** the system SHALL reject that action and, in auto-continue mode, fall back to manual confirmation for the offending chunk

#### Scenario: chunk generation modifies an off-plan field
- **WHEN** `generate_chunk_actions` returns an action that writes a field not declared in the plan
- **THEN** the system SHALL reject that action and require manual confirmation or plan revision

### Requirement: chunk generation is idempotent within a batch job
Calling `generate_chunk_actions` for the same chunk of the same plan multiple times SHALL produce semantically equivalent parameters for the same targets. The system SHALL use deterministic chunk and plan identifiers to detect re-generation.

#### Scenario: chunk is regenerated after a transient LLM error
- **WHEN** the system retries `generate_chunk_actions` for a chunk due to a transient LLM error
- **THEN** the regenerated actions SHALL target the same targets and use the same tool types as the first attempt

### Requirement: chunk actions are validated before creating a pending action
Before a `batch_execute_actions` pending action is created from a generated chunk, the system SHALL validate every action's schema, permission, team归属, and canonical summary.

#### Scenario: generated action fails schema validation
- **WHEN** a generated action does not match the child tool's schema
- **THEN** the system SHALL reject the entire chunk, report the error, and either regenerate or ask the user to revise the plan
