## Context

Dashboard quick actions are server-built `DashboardQuickAction` allowlists and the shared frontend renderer displays them as an equal-width icon-only rail with translated `title` and `aria-label`. App Token lifecycle UI already exists as a Team Management modal and its APIs independently enforce per-team admin or Super Admin authorization. A route-only shortcut is insufficient because it leaves the user on `/team-management` without opening that workflow.

## Goals / Non-Goals

**Goals:**

- Project an App Token action only for `ADMIN` and `SUPER_ADMIN`.
- Reuse the existing compact Dashboard action renderer and the existing App Token modal lifecycle.
- Open App Token management in-place on Dashboard without changing the page URL.
- Keep authorization server-authoritative at both the Dashboard projection and destination API.
- Cover the role matrix and three locales with automated checks.

**Non-Goals:**

- Create a second App Token page or duplicate token-management UI.
- Change App Token scopes, lifecycle APIs, permission policy, storage, or schema.
- Add a preferred Team to the Super Admin system dashboard.

## Decisions

1. **Filter actions while assembling the Dashboard response.** Personal Dashboard appends the action only when the persisted current-user role resolves to `admin`; System Administration Dashboard includes it because that response is already exclusive to `super_admin`. This avoids trusting localStorage or client-side role checks.
2. **Extract one reusable App Token modal component.** Team Management and Dashboard include the same Jinja component, stylesheet, and controller. This preserves one lifecycle implementation rather than copying modal markup or token mutations.
3. **Represent the action as the allowlisted `#app-token` modal target.** The Dashboard renderer intercepts this fixed server value and opens the shared controller instead of assigning `window.location`; other quick actions keep their existing navigation behavior.
4. **Resolve Team context by Dashboard type.** Personal Admin passes the already server-validated preferred Team to the controller and cannot enter the Team-picker path before completing the required Dashboard preference. System Super Admin explicitly enables Team selection, so the same modal lazily loads visible Teams and requires a selection. It does not read or mutate `currentTeam` or create a Super Admin preference.
5. **Use one shared i18n key and `fa-key`.** Both dashboards describe the same action. The existing compact renderer supplies icon-only layout, accessible name, tooltip, keyboard behavior, and equal-width filling.
6. **Keep API authorization unchanged.** Opening the modal grants no capability; every list/create/rotate/revoke request continues through the existing team-admin or Super Admin guards.

## Risks / Trade-offs

- **[Risk] A non-manager receives a sensitive navigation hint.** → Assert exact role projection in API tests; no client-only filtering.
- **[Risk] Extracted UI drifts between Team Management and Dashboard.** → Both pages include the exact same component, CSS, and controller.
- **[Risk] Super Admin has no Team context.** → Open the modal immediately with a Team selector and make no token request until the user explicitly selects one.
- **[Risk] A stale or forged Team id reaches the controller.** → Personal Team comes from the current Dashboard response; the API still independently rejects unauthorized Team operations.
- **[Risk] More icons could compress the compact rail.** → Reuse its equal-width responsive layout and accessible tooltip contract; add a source-level frontend assertion for the action.

## Migration Plan

Deploy as an additive Dashboard response plus shared presentation extraction; no migration or data backfill is required. Roll back by restoring the Team Management-local modal and removing the Dashboard include/interception. Existing App Tokens and their authorization are unaffected.

## Open Questions

None.
