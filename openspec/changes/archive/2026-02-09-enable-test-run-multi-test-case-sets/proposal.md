## Why

Current Test Run behavior is still effectively single-set at the workflow level:
- Test Run creation/edit flows require selecting one Test Case Set.
- Test Run item selection is filtered by one `set_id`.
- Test Run Execution only preloads section trees from one set.

This creates friction for teams that execute one release verification across multiple functional areas that are already split into multiple Test Case Sets. The current workaround requires creating multiple Test Runs and manually coordinating execution/reporting.

We need a full implementation so one Test Run can include multiple Test Case Sets, while still enforcing that all selected sets belong to the same team as the Test Run.

## What Changes

- Add multi-set scope to Test Run configuration (store and expose a set ID list rather than a single implicit set scope).
- Update Test Run Management UI to select/manage multiple Test Case Sets and to support case selection across configured sets.
- Enforce backend integrity rules so item creation/update only accepts Test Cases from the configured set list and same team.
- Automatically remove out-of-scope Test Run items when:
  - A Test Case Set is removed from a Test Run scope.
  - A Test Case Set itself is deleted.
  - A Test Case is moved to a Test Case Set that is not included by that Test Run scope.
- Before deleting a Test Case Set or moving Test Cases to another set, show an impact warning and require explicit user confirmation.
- In the warning UI, list impacted Test Runs and item impact counts so operators can make an informed decision.
- Update Test Run Execution UI to load and merge section trees from multiple sets for filtering/grouping.
- Keep backward compatibility for existing single-set Test Runs by treating existing data as a one-item set list.

## Capabilities

### New Capabilities
- `test-run-multi-set-integrity`: Define backend data model and API validation rules for multi-set Test Runs constrained to one team.

### Modified Capabilities
- `test-run-management-ui`: Replace single-set assumptions with multi-set selection and cross-set case selection in management flows.
- `test-run-execution-ui`: Support section/filter hydration when a Test Run spans multiple Test Case Sets.
- `test-case-management-ui`: Add impact-warning confirmation UX for set deletion and cross-set move operations.

## Impact

- Affected specs:
  - New: `test-run-multi-set-integrity`
  - Modified: `test-run-management-ui`, `test-run-execution-ui`
- Affected backend areas:
  - `app/models/database_models.py`
  - `app/models/test_run_config.py`
  - `app/api/test_run_configs.py`
  - `app/api/test_run_items.py`
  - `app/api/test_case_sets.py`
  - `app/api/test_cases.py`
  - `database_init.py`
- Affected frontend areas:
  - `app/templates/test_run_management.html`
  - `app/templates/test_case_set_list.html`
  - `app/static/js/test-run-management/*.js`
  - `app/static/js/test-run-execution/*.js`
  - `app/static/js/test-case-set-list/main.js`
  - `app/static/js/test-case-management/modal.js`
  - `app/static/locales/*.json`
- Validation impact:
  - API tests for config create/update, out-of-scope item auto-removal, item creation constraints, and impact-preview endpoints
  - UI/manual regression for management and execution flows
