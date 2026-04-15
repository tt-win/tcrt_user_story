# Change: Refactor remaining templates for asset separation

## Why
Inline CSS and JS in multiple templates makes maintenance and future refactors harder. We will align the remaining pages with the existing refactor pattern used for test case management, test run management, and test run execution.

## What Changes
- Extract inline CSS/JS from remaining `app/templates/*.html` pages into `app/static/css` and `app/static/js`.
- Preserve UI, behavior, and script load order; keep global names intact.
- Update templates to reference the extracted assets.

## Impact
- Affected specs: `template-asset-separation`
- Affected code: remaining templates under `app/templates/` excluding `base.html`, `_partials/`, `components/`, and already-refactored pages.
- Out of scope: shared templates and previously refactored pages.
