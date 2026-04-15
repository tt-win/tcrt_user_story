## 1. Asset Separation
- [x] 1.1 Extract inline CSS into `app/static/css/test-run-execution.css` and link it from the template head.
- [x] 1.2 Extract inline JS into `app/static/js/test-run-execution/` modules, keeping global names intact.
- [x] 1.3 Keep external libs (`marked`, `DOMPurify`, `Chart.js`, `chartjs-plugin-datalabels`, `assignee-selector.js`) and ensure load order is preserved.

## 2. Template Cleanup
- [x] 2.1 Remove inline `<style>` and `<script>` blocks from `app/templates/test_run_execution.html`.
- [x] 2.2 Add explicit `<link>`/`<script>` tags in the template in the correct order.

## 3. Validation
- [x] 3.1 Manual: page layout, panels, and modals render as before.
- [x] 3.2 Manual: filters, execution actions, comments/markdown, attachments/test results, charts/reports, and JIRA tooltips work without console errors.
