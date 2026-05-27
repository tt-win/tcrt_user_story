# add-automation-hub — Handoff Notes

> Last sync: 2026-05-19
> Branch context: archived OpenSpec change. The implementation is in the working tree, with several pre-existing unrelated changes present.

## TL;DR

- The archived `add-automation-hub` task list is now treated as complete. This follow-up corrected the post-archive gaps found during verification.
- Fixed gaps: Smart Scan is now persisted and asynchronous (`202 + scan_run_id + GET status`), repo scan uses AST/content validation and config hashing, inbound webhooks have per-token rate limiting, outbound webhook deliveries are persisted with history/replay/audit, script preview has `Run now`, and iframe report mode now falls back to external-link mode when embedding fails or times out.
- Targeted ruff is clean for the touched automation/MCP files.
- Targeted tests pass:
  - `uv run pytest app/testsuite/test_automation_smart_scan_service.py app/testsuite/test_automation_webhook_service.py -q` → 21 passed
  - `uv run pytest app/testsuite/test_automation_smart_scan_service.py app/testsuite/test_automation_webhook_service.py app/testsuite/test_automation_run_service.py app/testsuite/test_automation_local_git_storage.py app/testsuite/test_mcp_automation.py -q` → 44 passed
  - `uv run pytest app/testsuite -k "automation or mcp" -q` → 105 passed

## Corrections Added After Archive

### Smart Scan

- New DB table: `automation_smart_scan_runs`.
- New response model: `AutomationSmartScanStartResponse`.
- `POST /api/teams/{team_id}/automation-scripts/smart-scan` now returns `202 Accepted` with `scan_run_id`, `status`, and `status_url`.
- `GET /api/teams/{team_id}/automation-scripts/smart-scan/{scan_run_id}` returns persisted status, progress, result, and error summary.
- `SmartScanService` validates candidate test files by content:
  - Python uses `ast` to detect `test_*` functions and `Test*` classes.
  - JS/TS uses test runner markers such as `test(`, `it(`, and `describe(`.
  - helper/resource files under the test tree are excluded as false positives.
- Scan result includes `scan_config_hash`; run rows retain the pending hash and final hash.

### Webhooks

- New DB table: `automation_webhook_deliveries`.
- Inbound public webhook endpoint enforces an in-memory per-token token bucket and returns `429` with `Retry-After` when exhausted.
- Outbound delivery now records request body, response body/error, status code, duration, delivery id, and timestamps.
- Webhook config UI has a recent-deliveries modal and replay button.
- `send_test_ping` now uses the same delivery path as lifecycle events, so manual test pings are visible in delivery history too.
- Failed deliveries write a best-effort audit event with `WEBHOOK_DELIVERY_FAILED`.

### Runs / Result UI

- Script preview rows now expose a `Run now` button.
- The existing run modal supports both suite and single-script execution.
- Report iframe mode opens a modal first, then falls back to a new tab and downgrades the runtime embed mode to `link` when the iframe fails or times out.

### Ruff Cleanup

- Removed unused imports in automation/MCP-adjacent files.
- `app/main.py` and `test_mcp_automation.py` keep their intentional delayed imports with `# ruff: noqa: E402`.

## Key Files

- `app/services/automation/smart_scan_service.py`
- `app/api/automation_scripts.py`
- `app/models/automation_smart_scan.py`
- `app/services/automation/webhook_service.py`
- `app/api/automation_webhooks.py`
- `app/api/automation_webhooks_public.py`
- `app/models/automation_webhook.py`
- `app/static/js/automation-hub/smart-scan/main.js`
- `app/static/js/automation-hub/suites/main.js`
- `app/static/js/automation-hub/runs/main.js`
- `app/static/js/automation-hub/webhooks/main.js`
- `alembic/versions/a8f2d6c9e0b1_add_automation_scan_and_delivery_tables.py`

## Verification Commands

```bash
jq empty app/static/locales/en-US.json app/static/locales/zh-TW.json app/static/locales/zh-CN.json

node --check app/static/js/automation-hub/suites/main.js
node --check app/static/js/automation-hub/runs/main.js
node --check app/static/js/automation-hub/smart-scan/main.js
node --check app/static/js/automation-hub/webhooks/main.js

uv run ruff check \
  app/api/mcp.py app/config.py app/main.py \
  app/models/automation_link.py \
  app/services/automation/providers/github_storage.py \
  app/testsuite/test_automation_local_git_storage.py \
  app/testsuite/test_automation_run_service.py \
  app/testsuite/test_mcp_automation.py \
  app/api/automation_scripts.py app/api/automation_webhooks.py app/api/automation_webhooks_public.py \
  app/models/automation_smart_scan.py app/models/automation_webhook.py \
  app/services/automation/smart_scan_service.py app/services/automation/webhook_service.py \
  app/testsuite/test_automation_smart_scan_service.py app/testsuite/test_automation_webhook_service.py

uv run pytest \
  app/testsuite/test_automation_smart_scan_service.py \
  app/testsuite/test_automation_webhook_service.py \
  app/testsuite/test_automation_run_service.py \
  app/testsuite/test_automation_local_git_storage.py \
  app/testsuite/test_mcp_automation.py -q

uv run pytest app/testsuite -k "automation or mcp" -q
```

## Remaining Risk

- Full browser/manual E2E still depends on real provider credentials and CI/result-provider infrastructure.
- The test run still emits existing project-wide deprecation warnings unrelated to this change.
- The inbound rate limiter is process-local. It is acceptable for this v1 implementation, but a multi-worker deployment should move it to Redis or another shared limiter.
