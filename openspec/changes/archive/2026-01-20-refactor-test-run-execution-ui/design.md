## Context
`app/templates/test_run_execution.html` contains several inline `<style>` blocks and multiple inline `<script>` blocks (including Markdown helpers, execution logic, charts, and test result uploads). External dependencies include `marked`, `DOMPurify`, `Chart.js`, `chartjs-plugin-datalabels`, and `/static/js/assignee-selector.js`.

## Goals / Non-Goals
- Goals: separate UI markup, CSS, and JS into dedicated files; keep existing UI and behavior unchanged; improve readability and future maintainability.
- Non-Goals: redesign UI/UX, change business logic, introduce a bundler/build step, or rename public/global APIs.

## Decisions
- Decision: Move all inline `<style>` blocks to `app/static/css/test-run-execution.css` and link it in the template head.
- Decision: Move inline `<script>` blocks into dedicated JS files under `app/static/js/test-run-execution/`.
- Decision: Preserve existing global function names and DOM IDs/attributes so inline handlers and external scripts remain compatible.
- Decision: Keep external dependencies (`marked`, `DOMPurify`, `Chart.js`, `chartjs-plugin-datalabels`, `assignee-selector.js`) as separate assets with explicit load order.
- Decision: Split JS by functional areas to minimize logic edits and clarify responsibility. Proposed file map:
  - `app/static/js/test-run-execution/core.js` (globals, permissions/state, markdown hotkeys, marked config)
  - `app/static/js/test-run-execution/init.js` (DOMContentLoaded wiring, page initialization)
  - `app/static/js/test-run-execution/data.js` (API calls, loading configs/items)
  - `app/static/js/test-run-execution/filters.js` (filter panel, search, sorting)
  - `app/static/js/test-run-execution/sections.js` (section tree, section filters/grouping)
  - `app/static/js/test-run-execution/render.js` (list rendering, row updates)
  - `app/static/js/test-run-execution/results.js` (test results upload/preview manager)
  - `app/static/js/test-run-execution/tickets.js` (bug ticket management and summaries)
  - `app/static/js/test-run-execution/tooltips.js` (JIRA/tooltip behaviors)
  - `app/static/js/test-run-execution/reports.js` (charts/report generation)
  - `app/static/js/test-run-execution/utils.js` (shared helpers)
- Decision: Maintain script load order explicitly in the template: external libraries first, `assignee-selector.js`, then execution modules in dependency order, and `init.js` last.

## Risks / Trade-offs
- Splitting a large script into multiple files increases the risk of ordering mistakes; mitigate by keeping a clear load order and minimizing logic changes.
- Maintaining global APIs limits deeper modularization; acceptable for refactor-only scope.

## Migration Plan
No data migration. Only static asset relocation and template wiring changes.

## Open Questions
None.
