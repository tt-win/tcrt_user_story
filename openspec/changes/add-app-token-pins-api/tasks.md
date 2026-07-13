## 1. Data Model and Migration

- [x] 1.1 Add `AppTokenPin` ORM model (team-scoped, distinct from `UserPin`) with unique constraint on `(owner_team_id, entity_type, entity_id)` and an unconstrained `created_by_credential_id` (may reference either `team_app_tokens.id` or legacy `mcp_machine_credentials.id`, audit-trace only).
- [x] 1.2 Add non-destructive Alembic migration `d4e6f8a0b2c4_add_app_token_pins` chained on top of `a1b2c3d4e5f6`.
- [x] 1.3 Update `database_init.py` `MAIN_REQUIRED_TABLES` for `app_token_pins`.
- [x] 1.4 Verify migration with a disposable DB (SQLite) smoke check (upgrade/downgrade round-trip).

## 2. App Token Pins API

- [x] 2.1 Add `app/api/app_pins.py` with `GET/POST /app/teams/{team_id}/pins` and `DELETE /app/teams/{team_id}/pins/{entity_type}/{entity_id}`: entity_type validation, scope mapping (`test_case:write` for `test_case_set`, `test_run:write` for `test_run_set`/`test_run`/`adhoc_run`), read-scope gate (`test_case:read` or `test_run:read`), team access guard via `require_app_team_access`.
- [x] 2.2 Wire audit logging (allow/deny/mutation) via the existing `log_app_token_audit` helper, including `entity_type`/`entity_id` in details.
- [x] 2.3 Register the router in `app/api/__init__.py`.

## 3. Tests

- [x] 3.1 Add `app/testsuite/test_app_token_pins_api.py`: list empty/populated, create + idempotent create, delete + delete-nonexistent, scope denial per entity_type family, team scope denial, cross-team isolation (token from team A cannot see/mutate team B pins), invalid `entity_type` validation error.
- [x] 3.2 Verify with `uv run pytest app/testsuite/test_app_token_pins_api.py -q`.

## 4. Skill Docs

- [x] 4.1 Update `tools/skills/tcrt-app-token/SKILL.md` and `references/api-reference.md` with the new pin endpoints, required scopes, and example usage.

## 5. Backend + Skill Verification

- [x] 5.1 `uv run pytest app/testsuite -q` (704 passed, 6 pre-existing unrelated failures confirmed via `git log`/isolated repro, not caused by this change; no failures in `/api/pins` or app-token suites).
- [x] 5.2 `uv run ruff check app scripts database_init.py` (full-repository baseline currently has 472 pre-existing errors; modified pin files pass targeted Ruff).
- [x] 5.3 `openspec validate add-app-token-pins-api --strict`.
- [x] 5.4 Graphify incremental update.

## 6. Human-Visible Merge in Existing Pin UI

App-token pins were created successfully via the API but had no observable effect anywhere a human could see them — confirmed via read-only inspection of the real dev DB (rows existed in `app_token_pins`) — because the existing human Pin UI (`test_case_set_list.html`, `test_run_management.html`) only ever reads `/api/pins` → `UserPin`. This section makes app-token pins visible (read-only, pinned-to-top) in that existing UI without touching its mutation contract.

- [x] 6.1 Modify `list_pins` in `app/api/pins.py` to merge `AppTokenPin` rows for the team into the response and add a `token_pinned` field (per entity_type id list) marking which ids came from app tokens. `create_pin`/`delete_pin` unchanged — still `UserPin`-only.
- [x] 6.2 Modify `app/static/js/common/pin-store.js`: track a second `tokenCache` per entity_type from `token_pinned`, add `isTokenPinned(entityType, id)`, and guard `unpin()` to reject token-pinned ids.
- [x] 6.3 Modify `app/static/js/test-case-set-list/main.js` and `app/static/js/test-run-management/render.js` pin-toggle rendering: render token-pinned items as a disabled, non-interactive pinned indicator (title/aria-label = "Pinned by App Token (team-shared)") instead of a clickable toggle; guard the click handlers (`toggleSetPin`, `toggleTrmPin`) to no-op on token-pinned ids.
- [x] 6.4 Add `.pin-toggle.token-pinned` style to `test-case-set-list.css` and `test-run-management.css` using existing design tokens.
- [x] 6.5 Add `common.pinnedByAppToken` to `en-US.json`, `zh-CN.json`, `zh-TW.json`.
- [x] 6.6 Extend pin API tests to cover the `list_pins` merge (`token_pinned` field correctness, cross-team non-leak, mutation independence) — new `app/testsuite/test_pins_api.py`, 8 tests.
- [x] 6.7 Manually verify in a live browser: an app-token-created pin (real rows already exist in the dev DB for team 1 / `test_case_set` 302 and 303, sets "abcd" and "TP-5678") shows pinned-to-top with a disabled `.pin-toggle.pinned.token-pinned` indicator and correct zh-TW tooltip on the Test Case Set list page for a real logged-in team member; confirmed regular pin/unpin still works for other sets in the same view.
- [x] 6.8 Re-ran targeted Ruff for `app/api/app_pins.py` and its two test files (passes; full-repository baseline remains 472 unrelated errors), `node scripts/check-i18n-coverage.mjs` (no regression), `npm run lint` (no new warnings from the 2 edited CSS files), `openspec validate add-app-token-pins-api --strict` (valid).
