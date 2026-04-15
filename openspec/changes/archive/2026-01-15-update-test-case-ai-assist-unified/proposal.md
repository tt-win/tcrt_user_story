# Change: Unify AI assist for test case editor fields

## Why
Field-by-field AI assist creates inconsistent wording across precondition, steps, and expected result. A single evaluation pass should keep language consistent, reduce user friction, and enable clearer before/after comparison with live Markdown preview.

## What Changes
- Replace field-scoped AI assist actions with a single unified AI assist entry point for precondition, steps, and expected result.
- Send one request containing all three fields and return revised text for each plus a single suggestions list.
- Provide a unified preview UI with side-by-side comparison (original vs revised) and live Markdown preview per field.
- Allow empty fields; AI assist leaves them empty and does not block the request.
- Provide apply-all and apply-selected controls.

## Impact
- Affected specs: test-case-editor-ai-assist
- Affected code: app/api/test_cases.py, app/templates/test_case_management.html, app/static/css/style.css, app/static/locales/*
