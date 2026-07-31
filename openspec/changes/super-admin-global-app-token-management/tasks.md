## 1. Specification and authorization boundary

- [ ] 1.1 Update the App Token management UI and System Administration Dashboard delta specs for Super Admin global mode
- [ ] 1.2 Add Super Admin-only global create/rotate endpoints with owner lookup and global-scope audit detail; preserve team-scoped lifecycle with explicit team-membership authorization

## 2. Shared modal implementation

- [ ] 2.1 Add an explicit global-mode controller path that loads `/api/app-tokens` without a preselected Team
- [ ] 2.2 Render server-projected owner-team metadata with stable ID fallback and add an explicit active owner-team selector for global creation
- [ ] 2.3 Route global create/revoke/rotate through the Super Admin global endpoints without mutating `currentTeam` or the modal's global context
- [ ] 2.4 Preserve team-bound Team Management and Personal Admin Dashboard behavior
- [ ] 2.5 Add all new user-visible strings to en-US, zh-CN, and zh-TW

## 3. Regression coverage

- [ ] 3.1 Add cross-team Super Admin API coverage, team-membership boundary, wrong-team IDOR coverage, non-Super Admin denial, metadata redaction, inactive-team listing, and global-scope audit assertions
- [ ] 3.2 Extend frontend contract coverage for global mode, no preselection request, owner-team display/create, mutation URLs, disabled non-active actions, secret-safe rendering, pending-mutation context pinning, and safe team-card App Token dispatch
- [ ] 3.3 Run focused App Token/Dashboard tests, JavaScript syntax check, frontend lint, i18n coverage, Ruff, and strict OpenSpec validation
- [ ] 3.4 Perform a final self-review for secret exposure, team-membership authorization, stored-XSS-safe dispatch, unrelated changes, and rollback safety
