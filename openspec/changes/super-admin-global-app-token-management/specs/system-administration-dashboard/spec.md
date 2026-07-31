# system-administration-dashboard Delta Specification

## MODIFIED Requirements

### Requirement: System Administration Dashboard SHALL expose the App Token management action

The server SHALL include an App Token quick action in the System Administration Dashboard allowlist for `SUPER_ADMIN`. The action MUST use the existing compact icon-only Quick Actions presentation, a translated accessible label, the key icon, and the server-allowlisted `#app-token` modal target. Clicking it MUST open the shared App Token management modal in-place without navigating away from Dashboard. Because the System Administration Dashboard is system-scoped, the modal MUST enter explicit global mode, immediately request the Super Admin all-token metadata list, display owner-team identity (including a stable id fallback), and MUST NOT require a Team selection, read or mutate `currentTeam`, or issue a team-scoped list request before rendering the global list. Create MUST use the Super Admin global create endpoint with an explicit owner team; rotate MUST use the Super Admin global rotate endpoint that resolves owner server-side; revoke MUST use the Super Admin global revoke endpoint. All routes MUST retain server authorization and audit behavior.

#### Scenario: Super Admin receives the App Token action

- **WHEN** an authenticated `SUPER_ADMIN` requests `GET /api/dashboard`
- **THEN** the System Administration Dashboard quick-action allowlist includes one translated App Token action with target `#app-token`

#### Scenario: Super Admin opens the global token modal

- **WHEN** a Super Admin activates the App Token quick action
- **THEN** the current Dashboard URL remains unchanged
- **AND** the shared App Token modal opens in global mode
- **AND** it requests `GET /api/app-tokens` without a preselected Team
- **AND** no team-scoped token list request or `currentTeam` mutation occurs

#### Scenario: Global list identifies owner teams without exposing secrets

- **WHEN** the global list returns tokens from multiple teams, including a token owned by an inactive team
- **THEN** the modal displays each token's owner team identity or stable owner id and metadata-only fields
- **AND** raw token and token hash are absent from both the response projection and rendered list

#### Scenario: Destination keeps its authorization boundary

- **WHEN** the Super Admin creates, rotates, or revokes a token from global mode
- **THEN** the target route SHALL be `POST /api/app-tokens`, `POST /api/app-tokens/{token_id}/rotate`, or `DELETE /api/app-tokens/{token_id}` respectively, and each route SHALL apply a `require_super_admin()` guard
- **AND** global audit details SHALL identify the global management scope
- **AND** a forged client-side global-mode flag does not grant a non-Super Admin access to all-team metadata or mutations
