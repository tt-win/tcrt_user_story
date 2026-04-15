## Context
`app/templates/test_case_management.html` currently contains large inline CSS and JavaScript blocks, plus a small inline initialization script for the Section List. This makes the template long and hard to maintain, and mixes UI markup with behavior and styling.

## Goals / Non-Goals
- Goals: separate UI markup, CSS, and JS into dedicated files; keep existing UI and behavior intact; improve readability and future maintainability.
- Non-Goals: redesign UI/UX, change business logic, introduce a bundler/build step, or rename public/global APIs.

## Decisions
- Decision: Move the entire `<style>` block to `app/static/css/test-case-management.css` and link it in the template head.
- Decision: Move all inline `<script>` blocks (marked config, markdown hotkeys, and the main page logic) into dedicated JS files under `app/static/js`.
- Decision: Split the JS by responsibility using the existing table-of-contents sections to minimize logic edits. Final file map:
  - `app/static/js/test-case-management/core.js` (constants, globals, event listeners, markdown helpers)
  - `app/static/js/test-case-management/cache.js` (exec cache, filters storage, team/permission fetch, shared list helpers)
  - `app/static/js/test-case-management/tcg.js` (TCG editor)
  - `app/static/js/test-case-management/init.js` (initialization + loading)
  - `app/static/js/test-case-management/bulk.js` (batch operations + bulk create/copy)
  - `app/static/js/test-case-management/modal.js` (test case modal)
  - `app/static/js/test-case-management/quick-search.js` (quick search)
  - `app/static/js/test-case-management/utils.js` (shared utilities)
  - `app/static/js/test-case-management/ai-assist.js` (AI assist modal logic)
  - `app/static/js/test-case-management/markdown.js` (markdown editor)
  - `app/static/js/test-case-management/attachments.js` (attachments)
  - `app/static/js/test-case-management/tcg-tooltip.js` (TCG hover/tooltip)
  - `app/static/js/test-case-management/reference-test-case.js` (reference test case popup)
  - `app/static/js/test-case-management/bulk-edit.js` (bulk edit grid)
  - `app/static/js/test-case-management/drag-selection.js` (drag selection)
  - `app/static/js/test-case-management/section-list-init.js` (Section List init after external module load)
- Decision: Preserve existing global function names and DOM IDs/attributes so any inline handlers or external scripts keep working without changes.
- Decision: Maintain script load order explicitly in the template to avoid runtime dependency issues (marked library first, then TCM modules in the order above, then external Test Case Set/Section modules, then `section-list-init.js`).

## Risks / Trade-offs
- Splitting a large script into multiple files increases the risk of ordering mistakes; mitigate by keeping a clear load order and minimizing logic changes.
- Keeping global APIs for compatibility limits deeper modularization; acceptable for this refactor-only scope.

## Migration Plan
No data migration. Only static asset relocation and template wiring changes.

## Open Questions
None.
