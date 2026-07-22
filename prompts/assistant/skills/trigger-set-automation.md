---
id: trigger-set-automation
name: Trigger or cancel automation on a run set
description: run_automation / cancel_automation_run with explicit user intent; high impact confirmation.
triggers:
  - automation
  - 自動化
  - CI
  - trigger
---

# Trigger set automation

1. Resolve test run set id (`list_test_run_sets`).
2. Optional: `list_automation_runs` to check existing status.
3. User must clearly ask to trigger → `run_automation`.
4. Cancel only with clear intent → `cancel_automation_run`.

Never trigger automation as a side effect of reporting results.
