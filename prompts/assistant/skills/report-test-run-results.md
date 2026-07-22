---
id: report-test-run-results
name: Report results for a test run
description: Report pass/fail/blocked/skipped (and optional assignee/comment) for many run items using batch_update_results; never loop single-item updates.
triggers:
  - report result
  - 回報結果
  - batch result
  - pass
  - fail
  - 通過
  - 失敗
---

# Report test run results

## Hard rules

1. Always use `batch_update_results` for multi-item result updates.
2. Allowed `test_result` values for the assistant tool: `pass` | `fail` | `blocked` | `skipped`.
3. You may also set `assignee_name` and/or `comment` in the same update object.
4. Resolve item **ids** from `list_test_run_items` first; never invent ids.

## Path (existing run)

1. Resolve `config_id` (`list_test_runs` / user-provided id).
2. Prefer `list_test_run_item_refs` (paginate; `search` / `test_result_filter` when helpful) to collect ids.
3. Build `updates[]` from matched ids + user-provided results.
4. Single `batch_update_results` (not N× `update_test_run_item`).
5. Optional: `set_test_run_status` with status `completed` only if the user asked to complete the run.

## Path (new run end-to-end)

1. `create_test_run_config` (wait for confirm → get new id).
2. `add_test_run_items` with case numbers.
3. Optional `set_test_run_status` → `active`.
4. `list_test_run_items` → `batch_update_results`.
5. Optional complete + report generation skills/tools.

Dependent creates must **not** be stuffed into one `batch_execute_actions` — later steps need the new config id from the previous confirm.

## Anti-patterns

- N× `update_test_run_item` for results.
- Completing/archiving the run without being asked.
