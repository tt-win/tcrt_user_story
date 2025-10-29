# Bulk Edit Mode Improvements

## Changes Made

### 1. 翻譯 (Translations)
**File**: `app/static/locales/zh-TW.json`

Added complete translations for bulk edit mode:
```json
"bulk": {
    "bulkMode": "大量模式",
    "bulkCreateMode": "大量新增模式",
    "bulkEditMode": "大量編輯模式"
},
"bulkEdit": {
    "title": "大量編輯模式",
    "search": "搜尋及取代",
    "searchReplace": "搜尋及取代",
    "searchText": "搜尋內容",
    "replaceText": "取代內容",
    "searchColumn": "搜尋範圍",
    "replace": "取代",
    "replaceAll": "全部取代",
    "editingCount": "編輯 {count} 筆資料",
    "changedCount": "已修改 {count} 筆",
    "noChanges": "沒有要儲存的變更",
    "saved": "儲存成功 {count} 筆",
    "saveFailed": "儲存失敗 {count} 筆",
    "dragToFill": "拖曳以填充",
    "doubleClickToEdit": "雙擊編輯",
    "selectMultiple": "按住 Ctrl/Cmd 點擊多選，Shift 點擊範圍選取",
    "copyPaste": "Ctrl+C 複製，Ctrl+V 貼上"
}
```

Also added "undo": "復原" to common translations.

### 2. 在儲存格內編輯 (In-Cell Editing)
**Changes**: CSS and JavaScript

#### CSS Updates:
- Cell input elements are pre-rendered but hidden by default
- When editing, the input becomes visible and overlays the cell content
- Cell content is hidden during editing
- Removed separate popup-style input boxes
- Added `cursor: cell` for editable cells

```css
#bulkEditModal .bulk-edit-grid td.editing .cell-content { display: none; }
#bulkEditModal .bulk-edit-grid td.editing .cell-input { display: block !important; }
#bulkEditModal .bulk-edit-grid td .cell-input { 
    display: none; 
    position: absolute; 
    top: 0; 
    left: 0; 
    width: 100%; 
    height: 100%; 
    ...
}
```

#### JavaScript Updates:
- `renderBulkEditGrid()` now pre-renders input elements for all editable cells
- `startCellEdit()` simplified to just show the input and focus it
- `finishCellEdit()` hides input and updates display
- Added `cancelCellEdit()` for Escape key
- Added `getNextEditableCell()` for Tab navigation

**Keyboard Support**:
- **Enter**: Save and exit editing
- **Escape**: Cancel editing
- **Tab**: Save and move to next cell
- **Shift+Tab**: Save and move to previous cell

### 3. Ctrl+Z 復原功能 (Undo Support)
**New Features**:

#### Undo Stack:
- `bulkEditUndoStack`: Array storing up to 50 undo actions
- Each action stores: `{ recordId, column, oldValue, newValue }`

#### Functions:
- `pushUndoState(recordId, column, oldValue, newValue)`: Adds action to undo stack
- `performUndo()`: Reverts last change and updates UI
- Undo button is enabled/disabled based on stack state

#### Keyboard Shortcut:
- **Ctrl+Z** (Windows/Linux) or **Cmd+Z** (Mac): Undo last change

**Implementation**:
```javascript
function pushUndoState(recordId, column, oldValue, newValue) {
    bulkEditUndoStack.push({ recordId, column, oldValue, newValue });
    if (bulkEditUndoStack.length > 50) {
        bulkEditUndoStack.shift(); // Keep only last 50 actions
    }
    const undoBtn = document.getElementById('bulkEditUndoBtn');
    if (undoBtn) undoBtn.disabled = false;
}
```

### 4. 清楚的 Drag-Fill 指示 (Clear Drag-Fill Indicator)
**Changes**: CSS and JavaScript

#### Visual Improvements:
- **+ symbol** displayed on drag handle using CSS `::before`
- Drag handle visible when cell is selected (not just on hover)
- Blue square with white + icon at bottom-right corner

```css
#bulkEditModal .bulk-edit-grid td .drag-handle { 
    position: absolute; 
    right: -1px; 
    bottom: -1px; 
    width: 8px; 
    height: 8px; 
    background: #0d6efd; 
    cursor: crosshair; 
    z-index: 15; 
    display: none; 
}
#bulkEditModal .bulk-edit-grid td .drag-handle::before { 
    content: '+'; 
    position: absolute; 
    top: 50%; 
    left: 50%; 
    transform: translate(-50%, -50%); 
    color: white; 
    font-size: 10px; 
    font-weight: bold; 
    line-height: 1; 
}
#bulkEditModal .bulk-edit-grid td.selected .drag-handle { 
    display: block; 
}
```

#### Drag-Fill Implementation:
Completely rewritten with proper mouse drag support:

**Three handlers**:
1. `handleDragStart(event)`: Captures drag handle mousedown
   - Stores source cell, column, and value
   - Sets drag state with affected cells set

2. `handleDragMove(event)`: Tracks mouse movement
   - Highlights cells being dragged over
   - Only affects cells in the same column
   - Visual feedback with light blue background

3. `handleDragEnd(event)`: Applies changes on mouse up
   - Copies source value to all dragged cells
   - Adds each change to undo stack
   - Updates UI and cleans up visual effects

**Features**:
- Drag vertically to copy value to multiple cells
- Visual preview during drag (light blue highlight)
- Source cell opacity reduced during drag
- Only affects cells in the same column
- Each changed cell gets its own undo entry

### 5. Additional Improvements

#### Better Cell Selection:
- Selected cells now have blue box-shadow border
- More visible selection state
- Consistent with Excel/Sheets

```css
#bulkEditModal .bulk-edit-grid td.selected { 
    background-color: #e7f3ff; 
    box-shadow: inset 0 0 0 2px #0d6efd; 
}
```

#### State Management:
- `bulkEditCurrentCell`: Tracks currently editing cell
- `bulkEditDragState`: Manages drag operation state
- Proper cleanup on modal close

#### Event Handling:
- Keyboard shortcuts don't interfere with cell editing
- Proper blur handling for cell inputs
- Tab navigation between cells

## Testing Guide

### 1. Test In-Cell Editing
1. Open bulk edit mode
2. Double-click any editable cell
3. Verify input appears **inside** the cell (not as popup)
4. Type new value
5. Press Enter → should save and exit editing
6. Press Escape → should cancel without saving
7. Press Tab → should save and move to next cell

### 2. Test Undo (Ctrl+Z)
1. Make several edits to different cells
2. Verify undo button is enabled
3. Press Ctrl+Z (or Cmd+Z on Mac)
4. Verify last change is reverted
5. Press Ctrl+Z multiple times
6. Verify all changes are reverted in reverse order
7. Verify undo button is disabled when stack is empty

### 3. Test Drag-Fill
1. Click any editable cell
2. Verify **+ symbol** appears at bottom-right corner
3. Click and hold the + handle
4. Drag down (or up) to other cells in same column
5. Verify cells highlight with light blue as you drag
6. Release mouse
7. Verify value is copied to all dragged cells
8. Press Ctrl+Z to verify undo works for drag-filled cells

### 4. Test Translations
1. Ensure browser/app is set to zh-TW locale
2. Verify "大量模式" appears in dropdown
3. Verify "大量編輯模式" option is visible
4. Verify all UI elements are properly translated
5. Check toolbar buttons and modal labels

## Summary of Files Changed

1. **app/static/locales/zh-TW.json**
   - Added bulk mode translations
   - Added bulkEdit section with all labels
   - Added "undo" to common section

2. **app/templates/test_case_management.html**
   - Updated CSS for in-cell editing
   - Enhanced drag handle visibility
   - Improved cell selection styling
   - Rewrote cell editing functions
   - Added undo functionality
   - Implemented proper drag-fill with mouse tracking
   - Added state management variables

## Git Commits

1. `228f131` - Initial bulk edit implementation
2. `fa003ee` - Added implementation documentation
3. `37682bb` - Improvements: translations, in-cell editing, undo, drag-fill

## Branch

- `feature/bulk-edit-mode`

## What's Next

The bulk edit mode is now feature-complete with:
- ✅ Excel-like in-cell editing
- ✅ Undo support (Ctrl+Z)
- ✅ Clear drag-fill indicator with + symbol
- ✅ Complete zh-TW translations
- ✅ Multi-select with Ctrl/Cmd and Shift
- ✅ Copy/paste support
- ✅ Search and replace
- ✅ Batch save to API

Ready for testing and user feedback!
