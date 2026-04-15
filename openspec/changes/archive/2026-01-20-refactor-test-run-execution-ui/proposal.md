# Change: Refactor Test Run Execution page assets

## Why
The Test Run Execution template embeds multiple inline CSS/JS blocks, which makes the page difficult to navigate and refactor safely. Separating concerns improves maintainability while preserving existing behavior.

## What Changes
- Extract inline styles into a dedicated stylesheet under `app/static/css`.
- Extract inline scripts into dedicated JS files under `app/static/js/test-run-execution/`, keeping public/global APIs intact.
- Keep the template focused on HTML structure and asset wiring (no inline CSS/JS).

## Impact
- Affected specs: test-run-execution-ui (update)
- Affected code: `app/templates/test_run_execution.html`, new assets under `app/static/css` and `app/static/js/test-run-execution/`
