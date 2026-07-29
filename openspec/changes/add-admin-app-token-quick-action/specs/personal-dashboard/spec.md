## ADDED Requirements

### Requirement: Personal Dashboard App Token quick action SHALL be Admin-only

The server SHALL include an App Token quick action in a Personal Dashboard response only when the authenticated current user's persisted role is exactly `ADMIN`. The action MUST use the existing compact icon-only Quick Actions presentation, a translated accessible label, the key icon, and the server-allowlisted `#app-token` modal target. Clicking it MUST open the shared App Token management modal in-place without navigating away from Dashboard. When a valid preferred Team exists, the modal MUST use that server-returned Team id and name; it MUST NOT derive Team scope from URL input or mutate Dashboard preference/current Team merely by opening. `USER` and `VIEWER` responses MUST NOT include the action. Existing per-team API authorization MUST remain authoritative.

#### Scenario: Admin receives the App Token action

- **WHEN** an authenticated `ADMIN` requests `GET /api/dashboard`
- **THEN** the Personal Dashboard quick-action allowlist includes one translated App Token action with target `#app-token`

#### Scenario: Admin opens the preferred Team token modal without navigation

- **WHEN** an Admin with a valid preferred Team activates the App Token quick action
- **THEN** the current Dashboard URL remains unchanged and the shared App Token modal opens for that Team

#### Scenario: User and Viewer do not receive the App Token action

- **WHEN** an authenticated `USER` or `VIEWER` requests `GET /api/dashboard`
- **THEN** the Personal Dashboard quick-action allowlist does not contain an App Token action

#### Scenario: Dashboard modal does not grant token-management permission

- **WHEN** an Admin opens the App Token modal and attempts a team-scoped token operation
- **THEN** the existing App Token API independently verifies that user's admin permission for the requested Team
