---
id: batch-assign-failed-items
name: Assign failed (or filtered) run items to an assignee
description: Assign all failed/blocked/unexecuted items in a test run to one person with one batch_update_results call.
triggers:
  - failed
  - 失敗
  - blocked
  - 未執行
  - assign fail
---

# Assign filtered run items

## Path

1. Resolve `config_id`.
2. Prefer `list_test_run_item_refs` with `test_result_filter` (e.g. `fail` / `blocked` / `null`) when the filter matches intent; paginate with skip/limit.
3. Or one `batch_update_test_run_items_by_filter` with the same closed filter + `patch.assignee_name` when all matches should get the same assignee (max 500).
4. Else collect matching `id`s then one `batch_update_results` with assignee-only updates:
   `{"id": n, "assignee_name": "<name>"}`.
5. Do not modify `test_result` unless requested. Prefer refs over full `list_test_run_items`.

If the filter is a **case-number / ticket prefix**, use skill `assign-run-items-by-case-prefix` instead.
