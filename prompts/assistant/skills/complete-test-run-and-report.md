---
id: complete-test-run-and-report
name: Complete a test run and optional set report
description: Mark a test run completed (status machine) and optionally generate a run-set report.
triggers:
  - complete
  - 完成
  - report
  - 報表
---

# Complete run + report

## Path

1. Resolve `config_id` (and set id if report needed).
2. Only if user asked to finish: `set_test_run_status` with `status=completed`.
   - Status machine: draft → active → completed (server may hop draft→completed via active).
   - Prefer **one** `set_test_run_status` to `completed` after results are recorded; do not invent intermediate statuses unless the API rejects.
3. Optional: `generate_run_set_report` then `get_run_set_report` if they want the HTML report.

## Rules

- Do not complete/archive unless asked.
- Prefer dedicated status/archive tools over generic update for lifecycle.
- When finishing a run: record results first (`batch_update_results` / filter batch), **then** set status.
  Prefer sequential confirms if unsure; if using `batch_execute_actions`, put result updates **before** `set_test_run_status`.
