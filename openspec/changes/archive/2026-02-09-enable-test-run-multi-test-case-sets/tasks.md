## 1. Data model and API contracts

- [x] 1.1 Add additive DB columns/migration support for Test Run multi-set scope in `test_run_configs`.
- [x] 1.2 Extend Test Run config schemas and conversion logic to read/write `test_case_set_ids`.
- [x] 1.3 Add backend validation for same-team set IDs on create/update and reject empty set scope.
- [x] 1.4 Enforce item creation guard: only allow Test Cases whose `test_case_set_id` is in config scope.
- [x] 1.5 Implement automatic cleanup when Test Run scope removes set IDs (delete affected Test Run items and return cleanup summary).
- [x] 1.6 Implement automatic cleanup when a Test Case Set is deleted (remove affected Test Run items).
- [x] 1.7 Implement automatic cleanup when a Test Case moves to a set outside a Test Run scope.
- [x] 1.8 Record cleanup operations in audit/log context for traceability.
- [x] 1.9 Add impact-preview APIs for:
  - Test Case Set deletion.
  - Test Case move across sets.
- [x] 1.10 Ensure write APIs return final cleanup summary (impacted Test Runs + removed counts).

## 2. Test Run Management UI

- [x] 2.1 Replace single-set selector with multi-set selection in config modal (create + edit).
- [x] 2.2 Update case selection modal to load cases across configured sets and provide per-set filter.
- [x] 2.3 Preserve case selection state while switching set filter and submitting batch create/update.
- [x] 2.4 Update helper texts, warnings, and i18n keys for multi-set terminology and cleanup result feedback.

## 3. Test Case Set / Test Case Management impact warning UI

- [x] 3.1 In Test Case Set delete flow, fetch impact preview and show impacted Test Runs before final confirmation.
- [x] 3.2 In Test Case move-to-set flow, fetch impact preview and show impacted Test Runs before final confirmation.
- [x] 3.3 Ensure canceling confirmation makes no data changes.
- [x] 3.4 Add i18n strings for impact warning, impacted run list, and confirmation copy.

## 4. Test Run Execution UI

- [x] 4.1 Update execution config loading to consume multi-set scope from config response.
- [x] 4.2 Load and merge section trees from all configured set IDs before rendering section filters.
- [x] 4.3 Keep existing section fallback hydration compatible when some items lack section metadata.
- [x] 4.4 Ensure execution page reflects post-cleanup item list and remains stable.

## 5. Validation and regression checks

- [x] 5.1 Add/adjust backend tests for config create/update validations, item scope enforcement, and cleanup summary responses.
- [x] 5.2 Add/adjust backend tests for impact-preview endpoints (delete set preview, move preview).
- [x] 5.3 Add/adjust tests for backward compatibility with legacy single-set records.
- [x] 5.4 Add/adjust backend tests for all cleanup triggers (set removed from scope, set deleted, test case moved out of scope).
- [x] 5.5 Run targeted tests: `pytest app/testsuite/test_test_run_set_api.py app/testsuite/test_test_run_item_update_without_snapshot.py`.
- [x] 5.6 Run strict OpenSpec validation: `openspec validate enable-test-run-multi-test-case-sets --strict --no-interactive`.
- [x] 5.7 Manual regression: create/edit multi-set Test Run, execute cases, section filtering, and result updates.
- [x] 5.8 Manual regression: verify impact warning UI shows impacted Test Runs before delete/move confirmation.
