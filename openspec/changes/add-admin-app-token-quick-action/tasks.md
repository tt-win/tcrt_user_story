## 1. Role-aware action projection

- [x] 1.1 Add the App Token quick action to Admin Personal Dashboard and Super Admin System Administration Dashboard server allowlists
- [x] 1.2 Keep User and Viewer responses free of the App Token action

## 2. Presentation and localization

- [x] 2.1 Add the shared App Token quick-action label to en-US, zh-CN, and zh-TW locales
- [x] 2.2 Verify the existing compact icon-only renderer presents the new key-icon action without layout-specific duplication

## 3. Verification

- [x] 3.1 Add API role-matrix regression coverage for Admin, Super Admin, User, and Viewer
- [x] 3.2 Add a frontend contract assertion for the action key, route, and icon
- [x] 3.3 Run targeted Dashboard tests, Ruff, frontend lint, i18n coverage, and strict OpenSpec validation

## 4. Direct modal workflow correction

- [x] 4.1 Extract the existing App Token modal markup and styles into one shared component used by Team Management and Dashboard
- [x] 4.2 Make the shared controller open a known Team directly or present an in-modal Team selector when no Team context exists
- [x] 4.3 Intercept the Dashboard `#app-token` quick action and open the modal without navigation or current-Team mutation
- [x] 4.4 Add three-locale Team-selection states and regression coverage for the shared modal workflow
- [x] 4.5 Re-run Dashboard, App Token, component, lint, i18n, Ruff, and strict OpenSpec verification
