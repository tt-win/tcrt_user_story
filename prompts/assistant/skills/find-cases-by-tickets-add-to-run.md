---
id: find-cases-by-tickets-add-to-run
name: Find cases by tickets and add to a test run
description: Resolve Jira/TCG tickets to case numbers, then add them to a test run in one add_test_run_items call.
triggers:
  - by ticket
  - 票號
  - TCG
  - add to run
---

# Find cases by tickets → add to run

## Path

1. Resolve `config_id` (`list_test_runs` / user id).
2. `find_test_cases_by_tickets` with the ticket list.
3. Build `items: [{test_case_number}, …]` from results (dedupe).
4. One `add_test_run_items` (high impact — single confirmation).

## Anti-patterns

- N× single-item add.
- Inventing case numbers without find/list.
