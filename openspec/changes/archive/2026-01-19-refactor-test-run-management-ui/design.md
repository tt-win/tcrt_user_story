## Context
`app/templates/test_run_management.html` contains a large inline `<style>` block and a long inline `<script>` block (plus `/static/js/adhoc_run_manager.js`). This mixes styling/behavior with markup and makes refactors risky.

## Goals / Non-Goals
- Goals: separate UI markup, CSS, and JS into dedicated files; keep existing UI and behavior unchanged; improve readability and future maintainability.
- Non-Goals: redesign UI/UX, change business logic, introduce a bundler/build step, or rename public/global APIs.

## Decisions
- Decision: Move the entire inline `<style>` block to `app/static/css/test-run-management.css` and link it in the template head.
- Decision: Move the inline `<script>` block to dedicated JS files under `app/static/js/test-run-management/`.
- Decision: Preserve existing global function names and DOM IDs/attributes so inline handlers and external scripts remain compatible.
- Decision: Keep `/static/js/adhoc_run_manager.js` as a separate dependency and explicitly control load order.
- Decision: Split JS by functional areas to minimize logic edits and make future changes easier. Proposed file map:
  - `app/static/js/test-run-management/core.js` (state, permissions, shared helpers, i18n hooks)
  - `app/static/js/test-run-management/init.js` (event wiring and page initialization)
  - `app/static/js/test-run-management/data.js` (API calls, data loading, caching where applicable)
  - `app/static/js/test-run-management/render.js` (overview rendering, cards, status badges)
  - `app/static/js/test-run-management/status.js` (status dropdown logic, status change)
  - `app/static/js/test-run-management/config-modal.js` (config form modal, validation, save)
  - `app/static/js/test-run-management/set-modal.js` (set form/detail modal, set operations)
  - `app/static/js/test-run-management/details.js` (config detail rendering, shared page helpers)
  - `app/static/js/test-run-management/case-select.js` (case selection modal, section tree, selection logic)
  - `app/static/js/test-run-management/tickets.js` (TP/Jira ticket inputs and tag rendering)
  - `app/static/js/test-run-management/tooltips.js` (ticket preview tooltips)
  - `app/static/js/test-run-management/validation.js` (form validation and notifications)
  - `app/static/js/test-run-management/quick-search.js` (quick search UX)
  - `app/static/js/test-run-management/notifications.js` (notification settings)
- Decision: Maintain script load order explicitly in the template: `adhoc_run_manager.js` first, then the modules in dependency order, then `init.js` last.

## Risks / Trade-offs
- Splitting a large script into multiple files increases the risk of ordering mistakes; mitigate by keeping a clear load order and minimizing logic changes.
- Maintaining global APIs limits deeper modularization; acceptable for refactor-only scope.

## Migration Plan
No data migration. Only static asset relocation and template wiring changes.

## Open Questions
None.
