## 1. Asset Separation
- [x] 1.1 Extract inline CSS into `app/static/css/test-case-management.css` and link it from the template head.
- [x] 1.2 Extract inline JS into the planned `app/static/js/test-case-management/` modules, keeping global names intact.
- [x] 1.3 Move the Section List inline initialization into a dedicated module loaded after external scripts.

## 2. Template Cleanup
- [x] 2.1 Remove inline `<style>` and `<script>` blocks from `app/templates/test_case_management.html`.
- [x] 2.2 Add explicit `<link>`/`<script>` tags in the template in the correct order.

## 3. Validation
- [x] 3.1 Manual: page layout, controls, and modals render as before.
- [x] 3.2 Manual: search/filter, create/edit, bulk operations, attachments, TCG hover/preview, and AI assist work without console errors.
