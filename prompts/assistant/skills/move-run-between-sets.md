---
id: move-run-between-sets
name: Move a test run between run sets
description: Move or detach a test run config using move_run_between_sets.
triggers:
  - move run
  - 搬 run
  - 換 set
---

# Move run between sets

1. Resolve config id and target set id (`list_test_run_sets` / list runs).
2. One `move_run_between_sets` with `target_set_id` (or null to detach if supported by schema).
3. Confirm once; do not delete/recreate the run.
