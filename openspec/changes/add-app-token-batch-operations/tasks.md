## 1. Shared sync helpers (behavior-preserving extraction)

- [x] 1.1 Extract the JWT `/batch` closure body in `app/api/test_cases.py` into module-level `run_test_case_batch_operation_sync(sync_db, team_id, operation, actor_label)`; rewire the JWT route.
- [x] 1.2 Extract the JWT `/bulk_clone` closure body into `run_bulk_clone_sync(sync_db, team_id, request)`; rewire the JWT route.
- [x] 1.3 Extract the per-item update block of JWT `/batch-update-results` in `app/api/test_run_items.py` into `apply_batch_item_update_sync(sync_db, item, upd, source, changed_by_id, changed_by_name)`; rewire the JWT route.

## 2. App-token endpoints

- [x] 2.1 Add `POST /api/app/teams/{team_id}/test-cases/batch-operations` in `app/api/app_test_cases.py` (`delete` → `test_case:admin`, update ops → `test_case:write`), calling the shared function with `principal.audit_actor`; audit with operation + counts.
- [x] 2.2 Add `POST /api/app/teams/{team_id}/test-cases/bulk-clone` (`test_case:write`), calling `run_bulk_clone_sync`; audit with created count.
- [x] 2.3 Add `POST /api/app/teams/{team_id}/test-run-configs/{config_id}/items/batch-update-results` in `app/api/app_test_runs.py` (`test_run:execute`), reusing `BatchUpdateResultRequest` and the shared per-item helper; audit with success/error counts.

## 3. Tests

- [x] 3.1 `test_app_token_test_case_api.py`: batch update_priority success, delete denied with write-only scope then allowed with admin, unsupported operation → 400, bulk-clone success + duplicate rejection.
- [x] 3.2 `test_app_token_test_run_api.py`: batch-update-results multi-item success, missing execute scope → 403, per-item error reporting for unknown item id.
- [x] 3.3 Run JWT regressions covering the extracted logic (`uv run pytest app/testsuite/test_test_run_multi_set_api.py -q` plus the suites hitting `/batch` and `batch-update-results`).

## 4. Skill docs (local, gitignored)

- [x] 4.1 Add the three endpoints (scopes, body shapes) to `tools/skills/tcrt-app/references/api-reference.md`.
- [x] 4.2 Add a batch workflow example (batch-operations + batch-update-results) to `api-usage-guide.md`.

## 5. Verification

- [x] 5.1 `uv run pytest app/testsuite/test_app_token_test_case_api.py app/testsuite/test_app_token_test_run_api.py -q`.
- [x] 5.2 `uv run ruff check` on touched backend files (no new F-class errors).
- [x] 5.3 `openspec validate add-app-token-batch-operations --strict`.
