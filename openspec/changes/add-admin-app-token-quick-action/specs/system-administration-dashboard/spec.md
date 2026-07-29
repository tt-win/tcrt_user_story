## ADDED Requirements

### Requirement: System Administration Dashboard SHALL expose the App Token management action

The server SHALL include an App Token quick action in the System Administration Dashboard allowlist for `SUPER_ADMIN`. The action MUST use the existing compact icon-only Quick Actions presentation, a translated accessible label, the key icon, and the server-allowlisted `#app-token` modal target. Clicking it MUST open the shared App Token management modal in-place without navigating away from Dashboard. Because the System Administration Dashboard has no preferred Team, the modal MUST require an explicit Team selection before requesting or mutating token data, and MUST NOT read or mutate `currentTeam`. The Dashboard action MUST NOT bypass existing App Token management authorization.

#### Scenario: Super Admin receives the App Token action

- **WHEN** an authenticated `SUPER_ADMIN` requests `GET /api/dashboard`
- **THEN** the System Administration Dashboard quick-action allowlist includes one translated App Token action with target `#app-token`

#### Scenario: Super Admin selects Team inside the modal

- **WHEN** a Super Admin activates the App Token quick action
- **THEN** the current Dashboard URL remains unchanged, the shared App Token modal opens with a Team selector, and no team-scoped token request occurs before selection

#### Scenario: Destination keeps its authorization boundary

- **WHEN** the Super Admin selects a Team and manages its App Tokens in the modal
- **THEN** the target route and API continue to apply their existing authenticated Super Admin or team-admin authorization checks
