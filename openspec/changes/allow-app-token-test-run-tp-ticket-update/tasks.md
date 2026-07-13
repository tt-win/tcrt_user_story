## 1. Backend

- [x] 1.1 Update `update_app_test_run_config` in `app/api/app_test_runs.py` to persist `related_tp_tickets` (via `related_tp_tickets_json`) when the field is provided, reusing the `TestRunConfigUpdate` TP validation; leave it unchanged when the field is omitted.
- [x] 1.2 Include `related_tp_tickets` in `_serialize_config` so create/update responses expose the current tickets.

## 2. Tests

- [x] 2.1 Extend `app/testsuite/test_app_token_test_run_api.py` to cover updating `related_tp_tickets` and preserving existing tickets when the field is omitted.
- [x] 2.2 Verify with `uv run pytest app/testsuite/test_app_token_test_run_api.py -q`.

## 3. Skill Docs

- [x] 3.1 Update `tools/skills/tcrt-app/references/api-reference.md` (local, gitignored single source) so the Test Run `PUT` row lists `related_tp_tickets` as updatable and the limitation note drops it.

## 4. Verification

- [x] 4.1 Run `openspec validate allow-app-token-test-run-tp-ticket-update --strict`.
