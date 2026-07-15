## REMOVED Requirements

### Requirement: Lark import tool for USM
The system previously allowed users to import USM (User Story Map) data from Lark multi-dimensional tables via the "匯入工具" dropdown in team management page.

**Reason**: Teams no longer manage USM structure through Lark tables; the feature has no active usage and adds unnecessary maintenance cost.

**Migration**: No migration needed. Teams that still need to populate USM data can use the text mode editor (`user_story_map.html` text pane) or manual node creation.

#### Scenario: Import tool dropdown is no longer visible
- **WHEN** user opens team management page
- **THEN** the "匯入工具" dropdown is not present in the toolbar

#### Scenario: Lark import API returns 404
- **WHEN** client calls `POST /api/usm-import/import-from-lark` or `GET /api/usm-import/lark-preview`
- **THEN** server returns HTTP 404 (endpoint removed)

#### Scenario: Import modal i18n keys cleaned up
- **WHEN** i18n system loads locale files
- **THEN** no `usm.importModal.*` or `usmImport.*` keys exist in any locale
