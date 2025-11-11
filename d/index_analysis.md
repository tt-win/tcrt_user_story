# Index (Team List) Page Analysis

## Overview
The `index.html` file (~345 lines) is a Jinja2 template that serves as the main dashboard/home page. It displays a list of teams that the user belongs to and provides UI for creating new teams. It's the entry point for the application.

## File Structure

### Jinja2 Template Blocks
- **extends "base.html"**: Inherits from base template
- **block title**: Sets page title
- **block page_title_text**: Displays "Team Management"
- **block page_subtitle_text**: Shows subtitle
- **block content**: Main content area with teams container
- **block scripts**: Contains inline JavaScript code

### Main Sections
- **Teams Container**: Displays team cards in a grid layout
- **Create Team Modal**: Modal for creating new teams
- **Create Team Card**: Card to create first team (empty state) or add more teams

### JavaScript Functions

#### Initialization (Lines ~60-120)
- `initPage()`: Initializes page, loads teams list
- `loadTeams()`: Fetches teams from API
- `renderTeams()`: Renders team cards

#### Team Management (Lines ~120-200)
- `goToTeamManagement()`: Navigates to team management page
- `selectTeam(teamId)`: Selects and enters team
- `openTeamModal()`: Opens create team modal
- `closeTeamModal()`: Closes create team modal

#### UI Rendering (Lines ~200-280)
- `renderTeamCards(teams)`: Renders team card grid
- `getCreateTeamCard()`: Generates empty state create card
- `getAddTeamCard()`: Generates add team card when teams exist

## Recent Fixes

### Fix: Unify Add Card Button Text (Nov 11, 2025)

**Problem**:
- Create team button text was inconsistent: "新增第一個團隊" when empty, "新增更多團隊" when teams exist
- Other pages (Test Run, Test Run Set, Test Case Set) all used simple "新增 [資源]" format
- Inconsistent UX across application

**Solution**:

1. **Empty State Create Team Card** (Line 131)
   - Changed from: `data-i18n="team.createFirstTeam">新增第一個團隊`
   - Changed to: `data-i18n="team.createTeam">新增團隊`
   - i18n key updated: team.createFirstTeam → team.createTeam
   - i18n hint key: team.createFirstTeamHint (unchanged)

2. **Add Team Card (when teams exist)** (Line 214)
   - Changed from: `data-i18n="team.addMoreTeams">新增更多團隊`
   - Changed to: `data-i18n="team.addTeams">新增團隊`
   - i18n key updated: team.addMoreTeams → team.addTeams
   - i18n hint key updated: team.addMoreTeamsHint → team.addTeamsHint

**Code Changes**:
- index.html, Line 131: Updated i18n key and text
- index.html, Line 214-215: Updated i18n keys and text

**Consistency Applied**:
- Team Management (index.html): "新增團隊" ✓
- Test Run (test_run_management.html): "新增 Test Run" ✓
- Test Run Set (test_run_management.html): "新增 Test Run Set" ✓
- Test Case Set (test_case_set_list.html): "新增測試案例集合" ✓

All add cards now use consistent format: "新增[資源類型]"

**HTML Structure Before**:
```html
<!-- Empty state -->
<h5 class="text-primary mb-2" data-i18n="team.createFirstTeam">新增第一個團隊</h5>

<!-- With teams -->
<h6 class="text-primary mb-1"><span data-i18n="team.addMoreTeams">新增更多團隊</span></h6>
```

**HTML Structure After**:
```html
<!-- Empty state -->
<h5 class="text-primary mb-2" data-i18n="team.createTeam">新增團隊</h5>

<!-- With teams -->
<h6 class="text-primary mb-1"><span data-i18n="team.addTeams">新增團隊</span></h6>
```

## Issues Identified
1. **Monolithic Structure**: Single file mixing HTML, CSS, and JS
2. **Inline Scripts**: JavaScript logic embedded in template
3. **Global State**: Team data stored globally
4. **No Error Handling**: Limited error messages for API failures
5. **Hardcoded Text**: Some UI text still hardcoded instead of i18n keys
