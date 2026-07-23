## 1. Foundation

- [ ] 1.1 Add `plan_batch` and `generate_chunk_actions` tool definitions in `app/services/assistant/tools_batch_planning.py`
- [ ] 1.2 Register new tools in `app/services/assistant/tools_catalog.py` and verify registry contract tests pass
- [ ] 1.3 Update system prompt template in `app/services/assistant/content_store.py` to guide LLM toward `plan_batch` for large bulk operations
- [ ] 1.4 Add assistant config fields for batch planning thresholds (plan max targets, chunk action limit, chunk size limit, auto-continue risk allowlist)

## 2. Plan Generation and Validation

- [ ] 2.1 Implement `plan_batch` tool execution: accept goal and candidate targets, return lightweight plan with chunk assignments
- [ ] 2.2 Add target validation: verify each plan target exists and belongs to the conversation team using existing read tools/boundaries
- [ ] 2.3 Enforce plan size guardrails and return clear error when user scope is too large
- [ ] 2.4 Emit `batch_plan_ready` event with validated plan summary
- [ ] 2.5 Add unit tests for plan generation, validation, and size guardrails

## 3. Chunk Generation

- [ ] 3.1 Implement `generate_chunk_actions` tool execution: accept plan and chunk id, return fully specified actions for that chunk
- [ ] 3.2 Add structural validation: generated actions must match chunk target list, tool types, and field scope declared in the plan
- [ ] 3.3 Enforce chunk action count and serialized size guardrails
- [ ] 3.4 Emit `batch_chunk_generated` event after successful generation
- [ ] 3.5 Add unit tests for chunk generation, validation, and guardrails

## 4. Chunk Orchestration and Auto-Continue

- [ ] 4.1 Implement chunk orchestrator that iterates over plan chunks and creates one `batch_execute_actions` pending per chunk
- [ ] 4.2 Emit `batch_chunk_pending` event when a chunk pending action is created
- [ ] 4.3 Implement auto-continue authorization: capture user opt-in during first chunk confirm, bind to batch_job_id and JWT session
- [ ] 4.4 Implement auto-continue structural checks: only homogeneous chunks within authorized scope skip confirmation
- [ ] 4.5 Implement pause/cancel/skip controls and emit `batch_paused` / `batch_cancelled` events
- [ ] 4.6 Add unit tests for orchestrator state machine, auto-continue authorization, and control commands

## 5. Batch Execution Journal and Resume

- [ ] 5.1 Extend `_execute_batch_actions` in `app/services/assistant/tool_executor.py` to record per-action outcomes in `result_payload_json`
- [ ] 5.2 Implement chunk resume logic: identify unexecuted child actions from journal and create a new `batch_execute_actions` pending with remaining actions
- [ ] 5.3 Ensure resumed batches preserve original action order, execution_key lineage, and tool timeout deadline
- [ ] 5.4 Emit `batch_chunk_executed` event with per-chunk outcome counts
- [ ] 5.5 Add unit and integration tests for partial execution and resume

## 6. Batch Size Guardrail for Direct batch_execute_actions

- [ ] 6.1 Add action count and total parameter size checks in `tool_executor.validate_batch_actions`
- [ ] 6.2 Return fixable `batch_too_large` error when guardrail is exceeded, with message pointing to `plan_batch`
- [ ] 6.3 Add unit tests for guardrail triggers and fixable error messages

## 7. Agent Loop Integration and Events

- [ ] 7.1 Update `app/services/assistant/assistant_agent_service.py` to handle `plan_batch` / `generate_chunk_actions` results and emit batch progress events
- [ ] 7.2 Ensure batch progress events are persisted in `assistant_events` and replayed on SSE reconnect
- [ ] 7.3 Ensure batch progress events coexist with existing `message_start`, `text_delta`, `tool_started`, `tool_finished`, `confirmation_required`, `done`, `cancelled`, `error` events
- [ ] 7.4 Add integration tests for full plan → chunk → confirm → resume event flow

## 8. Skill Recipe and i18n

- [ ] 8.1 Update skill recipe catalog to prefer `plan_batch` + `generate_chunk_actions` for large bulk test case operations
- [ ] 8.2 Add batch progress related keys to `app/static/locales/en-US.json`, `zh-CN.json`, and `zh-TW.json`
- [ ] 8.3 Run `node scripts/check-i18n-coverage.mjs` and fix any missing keys

## 9. Verification

- [ ] 9.1 Run `uv run pytest app/testsuite/test_assistant*.py -q` and fix failures
- [ ] 9.2 Run `uv run ruff check app/services/assistant app/api/assistant.py` and fix lint errors
- [ ] 9.3 Run `openspec validate assistant-plan-and-chunk-batch --strict` and resolve issues
- [ ] 9.4 Run `node --check` on any modified JS files
