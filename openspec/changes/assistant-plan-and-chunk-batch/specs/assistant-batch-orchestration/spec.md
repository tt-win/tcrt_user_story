## ADDED Requirements

### Requirement: chunk orchestrator executes chunks according to the validated plan
The system SHALL provide a chunk orchestrator that iterates over the chunks in a validated batch plan, generates actions for each chunk, creates a `batch_execute_actions` pending action per chunk, and waits for user confirmation before execution unless auto-continue is authorized.

#### Scenario: First chunk requires manual confirmation
- **WHEN** the orchestrator creates the first chunk's pending action
- **THEN** it SHALL emit a `confirmation_required` event and wait for the user to confirm before executing the chunk

#### Scenario: Auto-continue skips confirmation for homogeneous chunks
- **WHEN** the user has authorized auto-continue for the batch job and the next chunk is homogeneous with the authorized scope
- **THEN** the orchestrator MAY create and execute the chunk's pending action without a new user confirmation step

#### Scenario: Orchestrator pauses on plan deviation
- **WHEN** a generated chunk deviates from the validated plan
- **THEN** the orchestrator SHALL pause auto-continue and require manual confirmation or plan revision

### Requirement: batch progress events are emitted for every state change
The system SHALL emit the following SSE event types during a batch job: `batch_plan_ready`, `batch_chunk_generated`, `batch_chunk_pending`, `batch_chunk_executed`, `batch_completed`, `batch_paused`, and `batch_cancelled`.

#### Scenario: User reconnects during a batch job
- **WHEN** a subscriber reconnects with the current turn's cursor
- **THEN** the system SHALL replay all persisted batch progress events in sequence

#### Scenario: Chunk execution finishes
- **WHEN** a chunk's `batch_execute_actions` reaches a terminal state
- **THEN** the system SHALL emit a `batch_chunk_executed` event with the chunk identifier, total target count, succeeded count, failed count, and skipped count

### Requirement: only one batch job may be active per conversation at a time
If a conversation already has an active batch job, the system SHALL either pause the existing job or reject the new batch request until the existing job completes or is cancelled.

#### Scenario: user starts a second batch job
- **WHEN** the user requests a new batch modification while another batch job is still active
- **THEN** the system SHALL inform the user about the active job and ask whether to cancel it before starting the new one

### Requirement: batch job state is recoverable after restart
The system SHALL persist enough batch job state in existing assistant_messages and assistant_events to resume or terminate a batch job after an application restart.

#### Scenario: restart occurs between chunks
- **WHEN** the application restarts after chunk 3 of a 10-chunk job
- **THEN** the system SHALL read the persisted progress summary and either continue chunk 4 (if auto-continue is still authorized and valid) or pause and wait for user instruction

### Requirement: users can stop an active batch job
The system SHALL provide explicit controls to pause, cancel, or skip to a specific chunk of an active batch job. Cancellation SHALL discard pending unexecuted chunks but SHALL NOT undo already executed chunks.

#### Scenario: user cancels after chunk 2
- **WHEN** the user cancels the batch job after chunk 2 has executed
- **THEN** the system SHALL emit `batch_cancelled`, leave chunk 1 and 2 results in place, and discard chunks 3 through 10
