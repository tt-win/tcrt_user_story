## 1. Asset Separation
- [x] 1.1 Extract inline CSS into `app/static/css/test-run-management.css` and link it from the template head.
- [x] 1.2 Extract inline JS into `app/static/js/test-run-management/` modules, keeping global names intact.
- [x] 1.3 Keep `/static/js/adhoc_run_manager.js` and ensure load order is preserved.

## 2. Template Cleanup
- [x] 2.1 Remove inline `<style>` and `<script>` blocks from `app/templates/test_run_management.html`.
- [x] 2.2 Add explicit `<link>`/`<script>` tags in the template in the correct order.

## 3. Validation
- [x] 3.1 Manual: page layout, cards, and modals render as before.
- [x] 3.2 Manual: permissions, status changes, set/config CRUD, case selection, ticket tags, and quick search work without console errors.
