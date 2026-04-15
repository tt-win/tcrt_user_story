## 1. Inventory
- [x] 1.1 Confirm the in-scope templates and inline CSS/JS blocks to extract (exclude shared templates and already-refactored pages).

## 2. Asset Separation (per page)
- [x] 2.1 Refactor `adhoc_test_run_execution.html` (extract inline CSS/JS to `app/static/css/adhoc-test-run-execution.css` and `app/static/js/adhoc-test-run-execution.*`, preserve load order).
- [x] 2.2 Refactor `audit_logs.html` (extract inline CSS/JS to `app/static/css/audit-logs.css` and `app/static/js/audit-logs-inline.js`).
- [x] 2.3 Refactor `first_login_setup.html` (extract inline CSS/JS to `app/static/css/first-login-setup.css` and `app/static/js/first-login-setup.js`).
- [x] 2.4 Refactor `index.html` (extract inline CSS/JS to `app/static/css/index.css` and `app/static/js/index.js`).
- [x] 2.5 Refactor `login.html` (extract inline CSS/JS to `app/static/css/login.css` and `app/static/js/login-inline.js` if needed).
- [x] 2.6 Refactor `profile.html` (extract inline CSS/JS to `app/static/css/profile.css` and `app/static/js/profile-inline.js` if needed).
- [x] 2.7 Refactor `system_setup.html` (extract inline CSS/JS to `app/static/css/system-setup.css` and `app/static/js/system-setup.js`).
- [x] 2.8 Refactor `system_setup_standalone.html` (extract inline CSS/JS to `app/static/css/system-setup-standalone.css` and `app/static/js/system-setup-standalone.js`).
- [x] 2.9 Refactor `team_management.html` (extract inline CSS/JS to `app/static/css/team-management.css` and `app/static/js/team-management/*`, preserve existing external scripts).
- [x] 2.10 Refactor `team_statistics.html` (extract inline CSS/JS to `app/static/css/team-statistics.css` and `app/static/js/team-statistics-inline.js`).
- [x] 2.11 Refactor `test_case_reference.html` (extract inline CSS/JS to `app/static/css/test-case-reference.css` and `app/static/js/test-case-reference.js`).
- [x] 2.12 Refactor `test_case_set_list.html` (extract inline CSS/JS to `app/static/css/test-case-set-list.css` and `app/static/js/test-case-set-list/*`).
- [x] 2.13 Refactor `user_story_map.html` (extract inline CSS/JS to `app/static/css/user-story-map.css` and `app/static/js/user-story-map-inline.js`, preserve ReactFlow/Monaco load order).
- [x] 2.14 Refactor `user_story_map_popup.html` (extract inline CSS/JS to `app/static/css/user-story-map-popup.css` and `app/static/js/user-story-map-popup-inline.js`).

## 3. Validation
- [x] 3.1 Manual: each refactored page renders the same UI and behavior with no console errors.
- [x] 3.2 Manual: i18n, modals, charts, and external CDN libraries still work with the updated load order.
