---
id: restart-failed-run
name: Restart failed (or pending) items into a new run
description: Use restart_test_run with mode failed|pending|all instead of manually cloning cases.
triggers:
  - restart
  - 重跑
  - failed only
---

# Restart failed run items

1. Resolve source `config_id` (the existing run to copy from).
2. One `restart_test_run` with `mode` = `failed` | `pending` | `all` (and optional name).
   - This **creates a new** config (`new_config_id`); it does not flip the source status.
   - Prefer `mode=failed` when the user only wants failed/retest items; `all` copies everything.
   - If the source is in a Test Run Set, the new run is attached to the **same set**.
3. After confirm, report `new_config_id`, `created_count`, and `set_id` from the result.

Do not manually list failed items and create a new run unless restart is unavailable.
Do not use `set_test_run_status` for “重跑/restart” — that only changes lifecycle status.
