---
id: create-run-and-add-cases
name: Create a test run and add cases
description: Create a test run config, then add cases by number; dependent steps must wait for the new config id after confirm.
triggers:
  - create run
  - 建立 test run
  - 新增 run
  - add cases to run
---

# Create test run + add cases

## Path

1. If the user named a test case set / run set, resolve ids with `list_test_case_sets` / `list_test_run_sets` first.
2. `create_test_run_config` with `name` (+ optional `test_case_set_ids` array, description, environment fields).
   Do **not** pass singular `set_id` — the create schema only accepts `test_case_set_ids`.
3. After confirm succeeds and you have `config_id`:
   - `add_test_run_items` with `{"items":[{"test_case_number":"TC-…"}, …]}`  
     **or** rely on scope from `test_case_set_ids` if that already populated items.
4. Optional `set_test_run_status` → `active` if the user wants it started.

## Hard rules

- Do **not** put create + add-items in the same `batch_execute_actions` (add needs the new id).
- Prefer one `add_test_run_items` with the full list over many single-item calls.
- Archive ≠ delete: see `archive-not-delete`.
