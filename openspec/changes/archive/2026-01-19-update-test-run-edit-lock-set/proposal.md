# Change: Lock Test Case Set on Test Run edit

## Why
Editing a Test Run after creation should not require re-selecting the Test Case Set. Allowing changes introduces inconsistency and confusion, especially when existing Test Run items already belong to a specific set.

## What Changes
- In Test Run config edit mode, replace the Test Case Set selector with a read-only display of the current set.
- In Test Run test-case edit mode, show the current Test Case Set as read-only and prevent switching.
- Keep existing set_id and filtering behavior; do not prompt for re-selection.

## Impact
- Affected specs: test-run-management-ui (new)
- Affected code: app/templates/test_run_management.html, app/static/locales/* (if new labels are required)
