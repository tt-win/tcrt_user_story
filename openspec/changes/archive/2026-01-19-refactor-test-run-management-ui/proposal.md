# Change: Refactor Test Run Management page assets

## Why
The Test Run Management template embeds extensive inline CSS and JavaScript, making the page harder to navigate and extend safely. Separating concerns improves maintainability while preserving existing behavior.

## What Changes
- Extract inline page styles into a dedicated stylesheet under `app/static/css`.
- Extract inline page scripts into dedicated JS files under `app/static/js/test-run-management/`, keeping public/global APIs intact.
- Keep the template focused on HTML structure and asset wiring (no inline CSS/JS).

## Impact
- Affected specs: test-run-management-ui (update)
- Affected code: `app/templates/test_run_management.html`, new assets under `app/static/css` and `app/static/js/test-run-management/`
