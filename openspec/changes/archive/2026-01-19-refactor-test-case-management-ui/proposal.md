# Change: Refactor Test Case Management page assets

## Why
The Test Case Management template embeds a large amount of inline CSS and JavaScript, which makes the page harder to navigate, review, and extend safely. Separating concerns improves maintainability while keeping behavior unchanged.

## What Changes
- Extract inline page styles into a dedicated stylesheet under `app/static/css`.
- Extract inline page scripts into dedicated JS files under `app/static/js`, keeping public/global APIs intact.
- Keep the template focused on HTML structure and asset wiring (no inline CSS/JS).

## Impact
- Affected specs: test-case-management-ui (new)
- Affected code: `app/templates/test_case_management.html`, new assets under `app/static/css` and `app/static/js`
