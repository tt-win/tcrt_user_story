# Test Case Section List Analysis

## Overview
The `test-case-section-list.js` file is a JavaScript class module (~2029 lines) that handles the sidebar section list functionality for test case management. It provides a hierarchical tree view of test case sections with drag-and-drop, editing, and CRUD operations. It supports cascading deletion of child sections in edit list mode.

## File Structure

### Class Definition (Lines ~1-2029)
- `TestCaseSectionList` class with comprehensive section management functionality

### Constructor and Initialization (Lines ~1-150)
- `constructor(options)`: Initializes the class with team_id, test_case_set_id, and DOM element references
- `init()`: Sets up event listeners, loads initial data, injects styles
- `injectStyles()`: Dynamically injects CSS for section list styling

### Data Management (Lines ~151-350)
- `loadSections()`: Fetches section data from API and updates internal state
- `refresh()`: Reloads section data and re-renders the tree
- `getSections()`: Returns current sections data
- `setSections(sections)`: Updates sections data and triggers re-render

### Rendering and UI (Lines ~351-800)
- `render()`: Main rendering function that builds the hierarchical section tree
- `renderSection(section, level)`: Renders individual section with indentation and controls
- `renderSectionControls(section)`: Renders action buttons (edit, delete, add child)
- `updateSectionDisplay()`: Updates the DOM with current sections
- `showLoading()`, `hideLoading()`: Loading state management

### Drag and Drop Functionality (Lines ~801-1100)
- `handleDragStart(event, section)`: Initiates drag operation
- `handleDragOver(event)`: Handles drag over events for drop zones
- `handleDrop(event, targetSection)`: Processes drop operations and updates section hierarchy
- `handleDragEnd(event)`: Cleans up after drag operation
- `enableDragAndDrop()`, `disableDragAndDrop()`: Toggles drag functionality

### CRUD Operations (Lines ~1101-1700)
- `createSection(parentId, name)`: Creates new section under specified parent
- `editSection(sectionId)`: Shows inline edit form for section name
- `updateSection(sectionId, newName)`: Updates section name via API
- `deleteSection(sectionId)`: Deletes section and handles child sections (immediate deletion via API)
- `markSectionAndChildrenForDelete(sectionId)` (Lines 1113-1122): Recursively marks section and all child sections for deletion (edit list mode)
- `unmarkSectionAndChildrenForDelete(sectionId)` (Lines 1127-1136): Recursively unmarks section and all child sections from deletion (edit list mode)
- `toggleSectionDelete(sectionId)` (Lines 1141-1162): Toggles deletion mark in edit list, including all child sections (cascading delete)
- `moveSection(sectionId, newParentId, newPosition)`: Moves section in hierarchy

### Event Handling (Lines ~1629-1928)
- `bindEvents()`: Sets up all DOM event listeners
- `onSectionClick(event, section)`: Handles section selection
- `onSectionDoubleClick(event, section)`: Handles section editing trigger
- `onAddChildClick(event, section)`: Handles add child section
- `onDeleteClick(event, section)`: Handles section deletion
- `onCollapseToggle(event, section)`: Handles expand/collapse

### Utility Functions (Lines ~1929-2029)
- `findSectionById(id)`: Finds section by ID in hierarchy
- `getSectionPath(section)`: Gets full path from root to section
- `validateSectionName(name)`: Validates section name input
- `escapeHtml(text)`: HTML escaping utility
- `debounce(func, delay)`: Debouncing utility for API calls

## Key Methods Details

### Constructor
- **Parameters**: options (object) - team_id, test_case_set_id, container_element, callbacks
- **Purpose**: Initializes class properties and DOM references

### init()
- **Parameters**: None
- **Purpose**: Sets up the module - loads data, binds events, injects styles
- **Side Effects**: Modifies DOM, makes API calls

### render()
- **Parameters**: None
- **Purpose**: Builds complete section tree HTML and updates DOM
- **Logic**: Recursively renders sections with proper indentation and hierarchy

### handleDrop(event, targetSection)
- **Parameters**: event (DragEvent), targetSection (object)
- **Purpose**: Processes drag-and-drop operations
- **Logic**: Validates drop target, updates hierarchy, saves changes via API

### createSection(parentId, name)
- **Parameters**: parentId (string), name (string)
- **Purpose**: Creates new section under specified parent
- **Logic**: Validates input, makes API call, updates local state, re-renders

## Dependencies
- **DOM APIs**: Standard web APIs for element manipulation and events
- **Fetch API**: For AJAX calls to backend APIs
- **Custom Utilities**: AppUtils (showLoading, showError, showSuccess), i18n for translations
- **CSS**: Dynamic style injection for section list appearance

## Issues Identified

### Structural Issues
1. **Monolithic Class**: Single class with 2001 lines handling all section list functionality
2. **Mixed Concerns**: Data fetching, DOM manipulation, event handling, and business logic in one class
3. **Tight Coupling**: Direct DOM manipulation and API calls mixed with business logic
4. **Global State**: Class maintains internal state that could be externalized

### Code Quality Issues
5. **Large Methods**: Some methods exceed 100 lines with multiple responsibilities
6. **Inline Event Handlers**: Event binding logic scattered throughout methods
7. **Hardcoded Selectors**: DOM element selection using hardcoded IDs/classes
8. **No Error Boundaries**: Drag operations and API failures can break the entire interface

### Performance/Maintainability
9. **No Virtualization**: Renders all sections at once, potential performance issues with large hierarchies
10. **Frequent Re-renders**: Entire tree re-rendered on any change
11. **Memory Leaks**: Event listeners not properly cleaned up
12. **No Abstraction**: Direct API calls without service layer abstraction

### Testing/Debugging
13. **Hard to Test**: Large class with DOM dependencies and side effects
14. **No Separation**: Business logic mixed with presentation logic
15. **Global Dependencies**: Relies on global utilities and DOM state

### Security/Maintenance
16. **XSS Prevention**: Uses escapeHtml but inconsistent across all DOM insertions
17. **Input Validation**: Limited validation on user inputs
18. **API Security**: No request validation or rate limiting
19. **Code Duplication**: Similar patterns repeated for different operations

## Recent Fixes

### Fix: Cascading Delete for Child Sections in Edit List Mode (Nov 11, 2025)

**Problem**: In the edit list mode (編輯列表), when a parent section was marked for deletion, only that parent section was deleted. Child sections of the deleted parent were not automatically deleted, potentially leaving orphaned sections in the hierarchy.

**Solution**: Implemented cascading delete logic in the edit list deletion mechanism:
- Added `markSectionAndChildrenForDelete(sectionId)` method (Lines 1113-1122): Recursively marks a section and all its child sections for deletion
- Added `unmarkSectionAndChildrenForDelete(sectionId)` method (Lines 1127-1136): Recursively unmarks a section and all its child sections
- Modified `toggleSectionDelete(sectionId)` method (Lines 1141-1162): Now uses the cascading mark/unmark methods

**Code Location**: `TestCaseSectionList` class in `app/static/js/test-case-section-list.js`, lines 1110-1162

**Implementation Details**:
```javascript
// Mark section and all children for deletion
markSectionAndChildrenForDelete(sectionId) {
  this.sectionsToDelete.add(sectionId);
  const section = this.findSection(sectionId);
  if (section) {
    const children = this.getChildSections(section);
    for (const child of children) {
      this.markSectionAndChildrenForDelete(child.id); // Recursive call
    }
  }
}

// Unmark section and all children when canceling deletion
unmarkSectionAndChildrenForDelete(sectionId) {
  this.sectionsToDelete.delete(sectionId);
  const section = this.findSection(sectionId);
  if (section) {
    const children = this.getChildSections(section);
    for (const child of children) {
      this.unmarkSectionAndChildrenForDelete(child.id); // Recursive call
    }
  }
}

// Updated toggle logic
toggleSectionDelete(sectionId) {
  // ... Unassigned check ...
  if (this.sectionsToDelete.has(sectionId)) {
    this.unmarkSectionAndChildrenForDelete(sectionId); // Cascading unmark
  } else {
    this.markSectionAndChildrenForDelete(sectionId); // Cascading mark
  }
  // Re-render list
}
```

**How It Works**:
1. When a user marks a parent section for deletion in edit list mode, all its child sections (recursively) are automatically marked for deletion
2. When the user saves changes (via `saveReorder()`), all marked sections (parent and children) are deleted via the API
3. If a user toggles off a deletion mark, all child sections are also unmarked
4. The UI updates to show all marked sections with a "待刪除" (marked for deletion) badge

**Related Methods**:
- `getChildSections(section)` (Line 1188-1193): Retrieves immediate children of a section
- `findSection(sectionId)` (Line 1169): Finds a section by ID across the hierarchy
- `saveReorder()` (Line 1891+): Processes deletion of all marked sections and saves reorder

### Fix: Section List Not Refreshing After Batch Test Set/Section Changes (Nov 11, 2025)

**Problem**: When test cases were moved to a different Test Case Set or Section via batch operations, the section list sidebar did not update the test case counts immediately. The counts would only update after a manual page refresh or when navigating away and back.

**Root Cause**: The batch modification operation (`performTestCaseBatchModify()` function in `test_case_management.html`, lines 7138-7393) would call `loadTestCases()` to refresh the main test case table, but did not trigger a refresh of the `TestCaseSectionList` component which maintains its own cached section data with test case counts.

**Solution**: Added explicit refresh call to `window.testCaseSectionList.loadSections()` in the batch modify success handler (lines 7358-7366), triggered when:
- `modifyTestSet` flag is true (test cases moved to different set), OR
- `modifySection` flag is true (test cases moved to different section)

**Code Changes**:
- Function: `performTestCaseBatchModify()` in `app/templates/test_case_management.html` (lines 7138-7393)
- Added section list refresh logic after `loadTestCases()` completion (lines 7358-7366):
  ```javascript
  // 如果修改了 Test Set 或 Section，需要刷新 Section List 以更新 test case 計數
  if ((modifyTestSet || modifySection) && typeof window.testCaseSectionList !== 'undefined' && window.testCaseSectionList?.loadSections) {
      console.log('[TCM] Refreshing section list after batch modify (test set or section changed)');
      try {
          await window.testCaseSectionList.loadSections({ reloadTestCases: false });
      } catch (error) {
          console.warn('刷新 Section List 失敗:', error);
      }
  }
  ```
- This calls `loadSections()` method with `reloadTestCases: false` to avoid redundant test case reloading

**Integration Points**:
- Calls `window.testCaseSectionList.loadSections()` - Method from `TestCaseSectionList` class (test-case-section-list.js, line 1139)
- `loadSections()` method internally calls `TestCaseSectionService.get_tree_structure()` via API endpoint: `GET /api/teams/{team_id}/test-case-sets/{set_id}/sections`

**Backend Endpoint** (`app/api/test_case_sections.py`, lines 120-138):
- Endpoint: `GET /{set_id}/sections`
- Calls `TestCaseSectionService.get_tree_structure(set_id)` which calculates test case counts using:
  ```python
  self.db.query(TestCaseLocal.test_case_section_id, func.count(TestCaseLocal.id).label('count'))
      .filter(TestCaseLocal.test_case_section_id.in_(section_ids))
      .group_by(TestCaseLocal.test_case_section_id).all()
  ```
- Counts automatically reflect current `test_case_section_id` values in database