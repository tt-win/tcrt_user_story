# Test Case Management Template Analysis

## Overview
The `test_case_management.html` file is a monolithic Jinja2 template (~11,895 lines) that combines HTML structure, inline CSS styling, and extensive JavaScript functionality for managing test cases. The file violates separation of concerns principles, making it difficult to maintain and debug.

## File Structure

### Jinja2 Template Blocks
- **extends "base.html"**: Inherits from the base template
- **block title**: Sets page title to "測試案例管理 - Test Case Repository Web Tool"
- **block head**: Contains external script includes (Marked.js), inline scripts for markdown configuration and hotkeys, and extensive inline CSS styles
- **block page_title_text**: Displays "測試案例管理"
- **block page_subtitle_text**: Shows subtitle about test case management features
- **block page_specific_actions**: Contains action buttons (add test case, bulk mode dropdown, refresh, navigation)
- **block content**: Main HTML content including:
  - Loading progress indicator
  - Search/filter card
  - Test cases display area
  - Multiple modal dialogs for editing, batch operations, etc.
- **block scripts**: Contains ~9,000+ lines of inline JavaScript code

### CSS Sections (Lines ~127-664)
The inline CSS includes:
- **Layout Styles**: Fixed positioning, flexbox layouts for responsive design
- **Component Styles**: Modal styling, pagination, TCG tags, bulk edit grids
- **Interactive Elements**: Hover effects, quick edit inputs, markdown editor toolbar
- **Section Cards**: Styling for test case sections with indentation and collapse states
- **Modal-Specific Styles**: Custom styling for various modals (bulk create, bulk edit, etc.)
- **Responsive Design**: Media queries for different screen sizes
- **Utility Classes**: TCG tags, attachment styling, form controls

### JavaScript Functions (Lines ~1619-11895)
The JavaScript code is organized into several functional areas. Below is a detailed breakdown with line numbers, parameters, and specifications for each function.

#### Cache Management (Lines ~1624-1720)
- `setExecCachedTestCase(testCaseNumber, data)` (Lines 1624-1633): Caches test case execution details. Parameters: testCaseNumber (string), data (object). Stores data in IndexedDB with team isolation.
- `removeExecCachedTestCase(testCaseNumber)` (Lines 1634-1643): Removes cached execution data. Parameters: testCaseNumber (string). Cleans up IndexedDB cache.
- TCG cache variables and functions for JIRA ticket information caching with 24-hour expiry.
- Test cases list caching functions with IndexedDB integration and 1-hour TTL.

#### Filtering and Search (Lines ~1769-1907)
- `getTcmFiltersStorageKey()` (Lines 1769-1776): Returns localStorage key for filter persistence. No parameters. Returns string key with team isolation.
- `saveTcmFiltersToStorage(filters)` (Lines 1777-1791): Persists filter settings. Parameters: filters (object with search/filter values). Stores in localStorage.
- `loadTcmFiltersFromStorage()` (Lines 1792-1808): Loads saved filter preferences. No parameters. Returns filter object or null.
- `clearTcmFiltersInStorage()` (Lines 1809-1816): Clears persisted filters. No parameters. Removes localStorage entry.
- `restoreTcmFiltersToUI()` (Lines 1817-1841): Applies saved filters to UI elements. No parameters. Returns boolean indicating if filters were restored.
- `computeFilteredTestCases(list)` (Lines 1842-1890): Applies current filters to test case list. Parameters: list (array of test cases). Returns filtered array.
- `applyCurrentFiltersAndRender()` (Lines 1891-1907): Updates UI with filtered results. No parameters. Triggers re-rendering and pagination update.

#### Sorting (Lines ~1926-1996)
- `updateTcmSortIndicators()` (Lines 1908-1925): Updates sort direction indicators in UI. No parameters. Updates arrow indicators in table headers.
- `updateTcmPlaceholders()` (Lines 1926-1939): Updates input placeholders with i18n. No parameters. Ensures translated placeholders.
- `parseNumberSegments(str)` (Lines 1940-1947): Parses numeric segments from string. Parameters: str (string). Returns array of numbers.
- `compareByNumericParts(aStr, bStr)` (Lines 1948-1957): Compares strings by numeric parts. Parameters: aStr, bStr (strings). Returns comparison result.
- `getFirstTCGNumber(tc)` (Lines 1958-1968): Extracts first TCG number from test case. Parameters: tc (test case object). Returns string.
- `compareTestCaseField(a, b, field)` (Lines 1969-1987): Compares test cases by specific field. Parameters: a, b (test case objects), field (string). Returns comparison result.
- `sortTestCaseList(list, field, order = 'asc')` (Lines 1988-1995): Sorts test case array. Parameters: list (array), field (string), order ('asc'|'desc'). Modifies array in place.
- `sortFilteredTestCases()` (Lines 1996-1999): Sorts filtered test cases. No parameters. Applies current sort settings.

#### Section Management (Lines ~2001-2517)
- `isUnassignedSectionIdValue(sectionId)` (Lines 2001-2007): Checks if section ID is unassigned. Parameters: sectionId (string). Returns boolean.
- `groupTestCasesBySection(testCases)` (Lines 2008-2077): Groups test cases by section. Parameters: testCases (array). Returns grouped object.
- `buildSectionPath(section, allSections)` (Lines 2078-2103): Builds hierarchical path for section. Parameters: section (object), allSections (array). Returns path array.
- `determineSectionLevel(testCase, sectionId)` (Lines 2104-2113): Determines section level for test case. Parameters: testCase (object), sectionId (string). Returns level number.
- `deriveSectionLevelFromPath(path)` (Lines 2114-2119): Derives level from path array. Parameters: path (array). Returns level number.
- `getDisplaySectionName(sectionGroup)` (Lines 2120-2126): Gets display name for section group. Parameters: sectionGroup (object). Returns string.
- `sortSectionIds(sectionIds, grouped)` (Lines 2127-2168): Sorts section IDs. Parameters: sectionIds (array), grouped (object). Returns sorted array.
- `mapAttrToField(attr)` (Lines 2169-2180): Maps HTML attribute to field name. Parameters: attr (string). Returns field string.
- `mapFieldToAttr(field)` (Lines 2181-2192): Maps field name to HTML attribute. Parameters: field (string). Returns attr string.
- `handleSectionSort(sectionId, fieldKey)` (Lines 2353-2364): Handles section sorting. Parameters: sectionId (string), fieldKey (string). Updates sort state.
- `toggleSectionCollapse(sectionId)` (Lines 2365-2391): Toggles section collapse state. Parameters: sectionId (string). Updates UI and state.
- `saveChildrenCollapseState(parentSectionId)` (Lines 2392-2436): Saves child section collapse states. Parameters: parentSectionId (string). Persists state.
- `restoreChildrenCollapseState(parentSectionId)` (Lines 2437-2460): Restores child collapse states. Parameters: parentSectionId (string). Applies saved state.
- `collapseChildSections(parentSectionId)` (Lines 2461-2489): Collapses child sections. Parameters: parentSectionId (string). Updates UI.
- `findSectionParentId(sectionId)` (Lines 2490-2517): Finds parent section ID. Parameters: sectionId (string). Returns parent ID or null.

#### UI Rendering (Lines ~2193-2352)
- `renderTestCaseRow(testCase)` (Lines 2193-2266): Generates HTML for test case row. Parameters: testCase (object). Returns HTML string.
- `renderSectionBlockHTML(sectionGroup, rowsHtml)` (Lines 2267-2352): Creates section container HTML. Parameters: sectionGroup (object), rowsHtml (string). Returns HTML string.
- `renderTestCasesTable()` (Lines 3913-3966): Main table rendering function. No parameters. Updates DOM with current data.

#### CRUD Operations (Lines ~5590-6474)
- `showTestCaseModal(testCase = null)` (Lines 5590-5874): Shows test case edit modal. Parameters: testCase (object, optional). Populates and displays modal.
- `viewTestCase(id)` (Lines 5895-5904): Views test case in read-only mode. Parameters: id (number/string). Opens modal in view mode.
- `deleteTestCase(id)` (Lines 5980-6474): Deletes test case. Parameters: id (number/string). Shows confirmation and performs deletion.

#### Batch Operations (Lines ~4211-7440)
- `openTestCaseBatchCopyModal()` (Lines 4211-4246): Opens batch copy modal. No parameters. Initializes modal state.
- `bindBatchCopyModalEvents()` (Lines 4247-4331): Binds events for batch copy modal. No parameters. Sets up event listeners.
- `getBatchCopySelectedIndexes()` (Lines 4332-4338): Gets selected row indexes. No parameters. Returns array of indexes.
- `renderBatchCopyTable()` (Lines 4339-4397): Renders batch copy table. No parameters. Updates modal table.
- `validateFullNumberForBatch(num)` (Lines 4398-4407): Validates test case number. Parameters: num (string). Returns boolean.
- `markInternalDuplicates()` (Lines 4408-4422): Marks duplicate entries. No parameters. Updates UI indicators.
- `onSaveBatchCopy()` (Lines 4423-4534): Saves batch copy operation. No parameters. Performs API calls and updates.
- `populateBatchTestSets()` (Lines 7086-7136): Populates test set dropdown in batch modify modal. No parameters. Fetches test sets and updates UI.
- `performTestCaseBatchModify()` (Lines 7138-7393): Performs batch modification of test cases. No parameters. Supports multiple operations (update_tcg, update_priority, update_section, update_test_set). **Includes section list refresh after test set/section changes (Lines 7358-7366)**.
- Bulk create functions for text-based batch creation with CSV parsing and validation.

#### Markdown Editing (Lines ~27-123)
- `applyMarkdownFormat(textarea, format)` (Lines 27-89): Applies markdown formatting. Parameters: textarea (HTMLTextAreaElement), format ('bold'|'italic'|'underline'). Modifies textarea content.
- `setupMarkdownHotkeys(textarea)` (Lines 99-123): Sets up keyboard shortcuts. Parameters: textarea (HTMLTextAreaElement). Adds event listeners.

#### TCG Integration (Lines ~3375-3625)
- `handleModalTCGOutsideClick(event)` (Lines 3375-3425): Handles clicks outside TCG modal. Parameters: event (MouseEvent). Closes dropdown.
- `renderModalTCGDisplay()` (Lines 3426-3442): Renders TCG display in modal. No parameters. Updates DOM.
- `updateModalTCGDisplay()` (Lines 3443-3446): Updates TCG display. No parameters. Refreshes tags.
- `handleModalTCGSearchKeydown(event)` (Lines 3447-3534): Handles TCG search input. Parameters: event (KeyboardEvent). Performs search.
- `shouldUpdateTCGCache()` (Lines 3535-3625): Checks if cache needs update. No parameters. Returns boolean.

#### Modal Management (Lines ~5590-5874)
- Modal functions for showing, hiding, and managing various dialogs including test case editing, batch operations, and confirmations.

#### Event Handling (Lines ~3967-4210)
- `bindEvents()` (Lines 3967-4210): Sets up all event listeners. No parameters. Comprehensive event binding for the page.

#### Utility Functions (Lines ~3011-3966)
- `setElementVisibility(elementId, isVisible)` (Lines 3011-3048): Toggles element visibility. Parameters: elementId (string), isVisible (boolean). Updates CSS display.
- `hasTestCasePermission(permissionKey)` (Lines 3049-3054): Checks user permissions. Parameters: permissionKey (string). Returns boolean.
- `disableEditingFeatures()` (Lines 3055-3085): Disables editing UI. No parameters. Updates button states.
- `renderTestCaseActions(testCase)` (Lines 3086-3374): Renders action buttons for test case. Parameters: testCase (object). Returns HTML string.
- Progress and status update functions for loading indicators.
- Internationalization and text utility functions.

## Dependencies
- **Marked.js**: For markdown rendering and editing
- **Bootstrap**: UI framework for modals, buttons, forms
- **jQuery**: DOM manipulation (assumed available)
- **TRCache**: Custom IndexedDB wrapper for caching
- **AppUtils**: Utility functions (getTeamIdForCache, etc.)
- **i18n**: Internationalization system

## Issues Identified
1. **Monolithic Structure**: Single file with 11,886 lines mixing HTML, CSS, and JS
2. **Inline Styles**: ~500 lines of CSS embedded in HTML
3. **Inline Scripts**: ~9,000+ lines of JavaScript in template
4. **Global State**: Many global variables and functions
5. **Tight Coupling**: Direct DOM manipulation throughout
6. **No Modularization**: All functionality in one namespace
7. **Maintenance Difficulty**: Hard to test, debug, or modify individual features

## Recent Fixes

### Fix: Section List Not Refreshing After Batch Operations (Nov 11, 2025)

**Issue**: In the `performTestCaseBatchModify()` function (lines 7138-7393), when test cases were moved to different Test Case Sets or Sections, the section list sidebar did not refresh to show updated test case counts. The counts would only update after a manual page refresh.

**Impact**: Users could not see immediate updates to test case counts in the section list after batch operations, leading to confusion about data state.

**Root Cause**: The function would refresh the main test case table via `loadTestCases()` (line 7356) but did not trigger a refresh of the separate `TestCaseSectionList` component which maintains cached section data.

**Fix**: Added section list refresh logic (lines 7358-7366) that:
1. Checks if `modifyTestSet` OR `modifySection` operations were performed
2. Verifies that `window.testCaseSectionList` exists and has `loadSections` method
3. Calls `await window.testCaseSectionList.loadSections({ reloadTestCases: false })`
4. This forces re-calculation of test case counts from the backend API

**Code Location**: `performTestCaseBatchModify()` function in `app/templates/test_case_management.html`, lines 7352-7370

**Implementation Details**:
```javascript
setTimeout(async () => {
    try {
        clearTestCasesCache(); // Line 7355
        await loadTestCases(false, null, true); // Line 7356 - Main table refresh

        // Lines 7358-7366 - New section list refresh logic
        if ((modifyTestSet || modifySection) && typeof window.testCaseSectionList !== 'undefined' && window.testCaseSectionList?.loadSections) {
            console.log('[TCM] Refreshing section list after batch modify (test set or section changed)');
            try {
                await window.testCaseSectionList.loadSections({ reloadTestCases: false });
            } catch (error) {
                console.warn('刷新 Section List 失敗:', error);
            }
        }
    } catch (error) {
        console.warn('背景同步資料失敗:', error);
    }
}, 1000);
```

**Function Signature**: `async function performTestCaseBatchModify()` - No parameters
**Related Operations Supported**:
- `update_tcg` - Updates TCG references (lines 7252-7264)
- `update_priority` - Updates priority (lines 7265-7278)
- `update_section` - Updates section (lines 7292-7310) **Triggers section list refresh**
- `update_test_set` - Updates test set (lines 7312-7330) **Triggers section list refresh**

**Related Components**:
- `TestCaseSectionList.loadSections()` method (test-case-section-list.js, line 1139)
- `TestCaseSectionService.get_tree_structure()` method (test_case_section_service.py, line 93)
- API endpoint: `GET /teams/{team_id}/test-case-sets/{set_id}/sections` (test_case_sections.py, lines 120-138)