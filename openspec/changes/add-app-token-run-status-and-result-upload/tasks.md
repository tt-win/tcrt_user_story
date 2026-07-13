## 1. Shared status-transition helper

- [x] 1.1 Add `apply_config_status_transition_sync(config_db, new_status)` to `app/services/test_run_set_status.py` (state machine + `start_date`/`end_date` side-effects + `updated_at`; raises `ValueError` on illegal transition).
- [x] 1.2 Rewire JWT `PUT .../{config_id}/status` in `app/api/test_run_configs.py` to call the helper (behaviour unchanged), translating `ValueError` to HTTP 400.

## 2. App-token status endpoint

- [x] 2.1 Add `PUT /api/app/teams/{team_id}/test-run-configs/{config_id}/status` in `app/api/app_test_runs.py` (`test_run:write`), reusing `StatusChangeRequest`; recalculate parent set status; audit; return `_serialize_config`.

## 3. App-token result-file upload endpoint

- [x] 3.1 Add `POST /api/app/teams/{team_id}/test-run-configs/{config_id}/items/{item_id}/upload-results` in `app/api/app_test_runs.py` (`test_run:execute`), multipart, storing under `test-runs/{team}/{config}/{item}/` and updating `execution_results_json` / `result_files_*` / `upload_history_json` to match the JWT schema; audit (file count only).

## 4. Portable client multipart (local, gitignored)

- [x] 4.1 Add `--file field=@path` (repeatable) to `tools/skills/tcrt-app/scripts/tcrt_api.sh` via curl `form`, mutually exclusive with `--data`, with char-safety on field/path and existence check.
- [x] 4.2 Add `--file field=@path` (repeatable) to `tools/skills/tcrt-app/scripts/tcrt_api.py` building a `multipart/form-data` body, mutually exclusive with `--data`.

## 5. Skill docs (local, gitignored)

- [x] 5.1 Document the two new endpoints in `tools/skills/tcrt-app/references/api-reference.md`.
- [x] 5.2 Add status-transition and result-upload examples (incl. `--file`) to `api-usage-guide.md` and `SKILL.md`.

## 6. Tests and verification

- [x] 6.1 Extend `app/testsuite/test_app_token_test_run_api.py`: status transition legal (draft→active→completed), illegal transition → 400, and result upload success / missing-execute-scope 403 / item-not-found 404.
- [x] 6.2 Run `uv run pytest app/testsuite/test_app_token_test_run_api.py -q` and a JWT `/status` regression (`uv run pytest app/testsuite/test_test_run_multi_set_api.py -q` or the status-covering suite).
- [x] 6.3 `node --check` is N/A; run `sh -n tools/skills/tcrt-app/scripts/tcrt_api.sh` and `python3 -m py_compile tools/skills/tcrt-app/scripts/tcrt_api.py` for client syntax.
- [x] 6.4 `uv run ruff check app/api/app_test_runs.py app/api/test_run_configs.py app/services/test_run_set_status.py`.
- [x] 6.5 `openspec validate add-app-token-run-status-and-result-upload --strict`.
