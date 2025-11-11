# Test Case Set List Analysis

## Overview
The `test_case_set_list.html` file (~1048 lines) is a Jinja2 template that displays the list of test case sets for a team. It allows users to view, create, edit, and delete test case sets, as well as create test runs from sets.

## File Structure

### Jinja2 Template Blocks
- **extends "base.html"**: Inherits from base template
- **block title**: Sets page title
- **block page_title_text**: Displays "Test Case Sets"
- **block page_subtitle_text**: Shows subtitle
- **block page_specific_actions**: Contains action buttons (create set, home link)
- **block content**: Main content area with test case set cards container
- **block scripts**: Contains inline JavaScript code

### JavaScript Functions

#### Rendering Functions (Lines ~254-337)
- `renderTestCaseSets()` (Lines 255-321): Renders test case set cards and add card. Parameters: none. Returns: updates DOM
- `getAddTestCaseSetCardHtml()` (Lines 324-337): Generates HTML for add card. Parameters: none. Returns: HTML string

#### Modal Management (Lines ~340-450)
- `showCreateSetModal()` (Lines 340-349): Shows create set modal. Parameters: none
- `showEditSetModal(setId, name, description)` (Lines 351-361): Shows edit set modal. Parameters: setId (number), name (string), description (string)
- `showDeleteConfirm(setId, name)` (Lines 450-456): Shows delete confirmation. Parameters: setId (number), name (string)

#### API Operations (Lines ~340-450)
- `submitSetForm()` (Lines 363-430): Submits set creation/update. Parameters: none. Makes API call to POST/PUT
- `confirmDelete()` (Lines 458-500): Confirms deletion. Parameters: none. Makes API call to DELETE
- `loadTestCaseSets()` (Lines 225-252): Loads sets from API. Parameters: none. Makes API call to GET

#### Navigation & Utilities (Lines ~500-600)
- `navigateToSet(setId)` (Lines 500-510): Navigates to test case management for set. Parameters: setId (number)
- `openSetCaseSelectModal(setId)` (Lines 512-600): Opens modal to select test cases for creating test run. Parameters: setId (number)

## Dependencies
- **Bootstrap**: UI framework for modals and cards
- **FontAwesome**: Icon library
- **i18n**: Internationalization system
- **AuthClient**: Custom authentication/fetch wrapper

## Recent Fixes

### Fix: Add 'Create Test Case Set' Card to Set List (Nov 11, 2025)

**Problem**:
- Test Case Set list page had no visual card to create new sets, unlike Team, Test Run Set, and Test Run pages
- Users had to click button in page header to create new sets
- No consistent UI pattern across similar pages

**Solution**:

1. **Modified renderTestCaseSets() Function** (Lines 255-321)
   - When no sets exist: show only the add card
   - When sets exist: show all set cards followed by add card at the end
   - Uses `getAddTestCaseSetCardHtml()` to generate add card

2. **Added getAddTestCaseSetCardHtml() Function** (Lines 324-337)
   - Returns HTML for add card with:
     - Dashed border style: `border: 2px dashed var(--tr-border-light)`
     - Transparent background: `background-color: transparent`
     - Clickable: `onclick="showCreateSetModal()"`
     - Plus icon in dashed circle (48px × 48px)
     - Localized title: `i18n.addSet || '新增測試案例集合'`
     - Localized hint: `i18n.createSetHint || '建立新的測試案例集合'`

**Code Changes**:
- Lines 255-321: Modified renderTestCaseSets() to include add card
- Lines 324-337: New getAddTestCaseSetCardHtml() function

**HTML Structure**:
```html
<!-- Old: Static list of set cards only -->
<div class="row" id="testCaseSetsContainer">
  <!-- Set cards only -->
</div>

<!-- New: Set cards + add card at end -->
<div class="row" id="testCaseSetsContainer">
  <!-- Set cards -->
  <div class="col-md-6 col-lg-4 mb-4">
    <div class="card h-100 add-test-case-set-card text-center">
      <div class="card-body d-flex flex-column justify-content-center">
        <div class="text-primary rounded-circle" style="border: 2px dashed var(--tr-primary);">
          <i class="fas fa-plus"></i>
        </div>
        <h6 class="text-primary mb-1">新增測試案例集合</h6>
        <small class="text-muted">建立新的測試案例集合</small>
      </div>
    </div>
  </div>
</div>
```

**CSS Styling**:
```css
.add-test-case-set-card {
  cursor: pointer;
  border: 2px dashed var(--tr-border-light);
  background-color: transparent;
}

.add-test-case-set-card .rounded-circle {
  border: 2px dashed var(--tr-primary);
}
```

**User Experience**:
- Card appears at the end of existing sets or as the only card when no sets exist
- Clicking card opens create set modal (same as header button)
- Consistent with design pattern used in test_run_management.html (Team Run Sets and Test Run cards)
- Visual indication that user can add more sets without scrolling to header

**File Line Count Change**: 1023 → 1048 lines (+25 lines)
- Added getAddTestCaseSetCardHtml() function: +14 lines
- Modified renderTestCaseSets() to integrate add card: +11 lines

## Recent Fixes (Continued)

### Fix: Unify Add Card Button Text Across All Pages (Nov 11, 2025)

**Problem**:
- Add card button text was "新增測試案例集合", inconsistent with other pages using "新增 Test Run Set", "新增 Test Run", etc.

**Solution**:
- Test Case Set card already uses: `i18n.addSet || '新增測試案例集合'`
- This is consistent with new unified format: "新增[資源類型]"
- No code change needed, text was already correct

**Consistency Verified**:
- Team Management (index.html): "新增團隊" ✓
- Test Run (test_run_management.html): "新增 Test Run" ✓
- Test Run Set (test_run_management.html): "新增 Test Run Set" ✓
- Test Case Set (test_case_set_list.html): "新增測試案例集合" ✓

All add cards now use consistent format: "新增[資源類型]"

## Issues Identified
1. **Monolithic Structure**: Single file with 1048 lines mixing HTML, CSS, and JS
2. **Direct DOM Manipulation**: All rendering done with string templates
3. **Global State**: Sets data stored in global testCaseSets array
4. **No Error Handling**: Limited error handling in async operations
5. **Inline Styles**: Some inline styles in add card HTML
