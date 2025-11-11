# Test Run Management Template Analysis

## Overview
The `test_run_management.html` file is a large Jinja2 template (~5737 lines) that manages test run configurations and sets. It includes embedded CSS and JavaScript for creating, editing, and managing test runs.

## File Structure

### Jinja2 Template Blocks
- **extends "base.html"**: Inherits from base template
- **block title**: Sets page title with i18n
- **block head**: Contains extensive inline CSS and some scripts
- **block page_title_text**: Displays page title
- **block page_subtitle_text**: Shows subtitle
- **block page_specific_actions**: Action buttons
- **block content**: Main HTML with modals and management interface
- **block scripts**: Large inline JavaScript code (~4000+ lines)

### CSS Sections (Lines ~7-1476)
Embedded CSS for:
- Test run card styling with status-based colors
- Modal forms and dialogs
- Status indicators and animations
- Responsive design
- TP ticket management UI

### JavaScript Functions (Lines ~1477-5737)
The JavaScript handles test run management with multiple functional areas:

#### UI Utilities (Lines ~1477-1615)
- `setElementVisibility(elementId, isVisible)` (Lines 1477-1513): Toggles element visibility. Parameters: elementId (string), isVisible (boolean).
- `showPermissionDenied()` (Lines 1514-1583): Shows permission denied message. No parameters.
- `onI18nEventOnce()` (Lines 1584-1588): Handles i18n initialization. No parameters.
- `onI18nEvent()` (Lines 1589-1593): Handles i18n changes. No parameters.
- `onPageShow(event)` (Lines 1594-1615): Handles page visibility. Parameters: event (PageTransitionEvent).

#### Initialization (Lines ~1616-1753)
- `initializePage()` (Lines 1616-1635): Initializes the page. No parameters.
- `bindEventListeners()` (Lines 1636-1753): Binds all event listeners. No parameters.

#### Test Run Rendering (Lines ~1754-1994)
- `rebuildTestRunConfigIndex()` (Lines 1754-1774): Rebuilds config index. No parameters.
- `filterTestRunsByStatus(runs, filterStatus)` (Lines 1775-1780): Filters runs by status. Parameters: runs (array), filterStatus (string).
- `renderTestRunOverview(filterStatus = 'all')` (Lines 1781-1794): Renders overview. Parameters: filterStatus (string).
- `renderTestRunSetCards(filterStatus)` (Lines 1795-1831): Renders set cards. Parameters: filterStatus (string).
- `summarizeSetMetrics(testRuns)` (Lines 1832-1848): Summarizes metrics. Parameters: testRuns (array).
- `createTestRunSetCard(set, filterStatus)` (Lines 1849-1929): Creates set card. Parameters: set (object), filterStatus (string).
- `renderUnassignedTestRunCards(filterStatus)` (Lines 1930-1979): Renders unassigned cards. Parameters: filterStatus (string).
- `showLoading()` (Lines 1980-1985): Shows loading. No parameters.
- `hideLoading()` (Lines 1986-1989): Hides loading. No parameters.
- `showNoConfigs()` (Lines 1990-1994): Shows no configs message. No parameters.
- `showConfigsSection()` (Lines 1995-1999): Shows configs section. No parameters.
- `createConfigCard(config)` (Lines 2000-2147): Creates config card. Parameters: config (object).

#### Status Management (Lines ~2148-2435)
- `getAddTestRunCardHtml()` (Lines 2148-2164): Gets add card HTML. No parameters.
- `getAddTestRunSetCardHtml()` (Lines 2165-2181): Gets add set card HTML. No parameters.
- `getStatusClass(status)` (Lines 2182-2191): Gets status CSS class. Parameters: status (string).
- `getStatusText(status)` (Lines 2192-2204): Gets status text. Parameters: status (string).
- `getDefaultStatusText(status)` (Lines 2205-2215): Gets default status text. Parameters: status (string).
- `getSetStatusText(status)` (Lines 2216-2229): Gets set status text. Parameters: status (string).
- `getSetStatusBadge(status)` (Lines 2230-2244): Gets status badge. Parameters: status (string).
- `toggleCustomStatusDropdown(button, configId)` (Lines 2245-2279): Toggles dropdown. Parameters: button (HTMLElement), configId (string).
- `hideCustomStatusDropdown()` (Lines 2280-2288): Hides dropdown. No parameters.
- `generateCustomStatusDropdownItems(config, dropdown)` (Lines 2289-2317): Generates dropdown items. Parameters: config (object), dropdown (HTMLElement).
- `handleCustomStatusChange(newStatus)` (Lines 2318-2324): Handles status change. Parameters: newStatus (string).
- `generateStatusDropdownItems(config)` (Lines 2325-2353): Generates status items. Parameters: config (object).
- `getStatusIcon(status)` (Lines 2354-2411): Gets status icon. Parameters: status (string).
- `refreshStatusTexts()` (Lines 2412-2435): Refreshes status texts. No parameters.

#### Modal Management (Lines ~2436-3331)
- `openConfigFormModal(configId = null, options = {})` (Lines 2436-2643): Opens config modal. Parameters: configId (string), options (object).
- `openTestRunSetFormModal(setId = null)` (Lines 2644-2845): Opens set modal. Parameters: setId (string).
- `renderTestRunSetDetail(setData, filterStatus = 'all')` (Lines 2846-2934): Renders set detail. Parameters: setData (object), filterStatus (string).
- `buildSetRunDetailRow(run, setData)` (Lines 2935-3055): Builds detail row. Parameters: run (object), setData (object).
- `openAddExistingToSetModal(setData)` (Lines 3056-3236): Opens add modal. Parameters: setData (object).
- `showConfigDetails(configId)` (Lines 3237-3269): Shows config details. Parameters: configId (string).
- `handleEditConfig(event)` (Lines 3270-3331): Handles edit event. Parameters: event (Event).

#### Configuration Details (Lines ~3332-3417)
- `createConfigDetailContent(config)` (Lines 3332-3363): Creates detail content. Parameters: config (object).
- `escapeHtml(text)` (Lines 3364-3375): Escapes HTML. Parameters: text (string).
- `updatePageTitle()` (Lines 3376-3382): Updates page title. No parameters.
- `enterTestRun(configId)` (Lines 3383-3410): Enters test run. Parameters: configId (string).
- `openCaseSelectModalWithConfirm(configId)` (Lines 3411-3417): Opens case select modal. Parameters: configId (string).
- `openCaseSelectModal(configId)` (Lines 3418-3532): Opens case select. Parameters: configId (string).

#### Case Selection (Lines ~3533-3971)
- `editBasicSettings(configId)` (Lines 3533-3674): Edits basic settings. Parameters: configId (string).
- `renderCaseList()` (Lines 3675-3716): Renders case list. No parameters.
- `wireCaseCheckHandlers()` (Lines 3717-3775): Wires check handlers. No parameters.
- `bindCaseSearchBarEvents()` (Lines 3776-3825): Binds search events. No parameters.
- `updateSelectedCount()` (Lines 3826-3831): Updates selected count. No parameters.
- `updateFilterInfo(filteredCount)` (Lines 3832-3971): Updates filter info. Parameters: filteredCount (number).

#### Deletion and TP Tickets (Lines ~3972-4393)
- `deleteTestRun(configId, name)` (Lines 3972-4019): Deletes test run. Parameters: configId (string), name (string).
- `validateTpTicketFormat(ticketNumber)` (Lines 4020-4026): Validates ticket format. Parameters: ticketNumber (string).
- `isDuplicateTicket(ticketNumber)` (Lines 4027-4031): Checks duplicate. Parameters: ticketNumber (string).
- `addTpTicket(ticketNumber)` (Lines 4032-4063): Adds TP ticket. Parameters: ticketNumber (string).
- `removeTpTicket(ticketNumber)` (Lines 4064-4072): Removes TP ticket. Parameters: ticketNumber (string).
- `renderTpTags()` (Lines 4073-4121): Renders TP tags. No parameters.
- `showTpInputError(message)` (Lines 4122-4147): Shows input error. Parameters: message (string).
- `clearTpInputError()` (Lines 4148-4161): Clears input error. No parameters.
- `initTpTicketInput()` (Lines 4162-4193): Initializes TP input. No parameters.
- `getCurrentTpTickets()` (Lines 4194-4198): Gets current tickets. No parameters.
- `setTpTickets(tickets)` (Lines 4199-4204): Sets TP tickets. Parameters: tickets (array).
- `clearAllTpTickets()` (Lines 4205-4212): Clears all tickets. No parameters.
- `initSetTpTicketInput()` (Lines 4213-4237): Initializes set TP input. No parameters.
- `addSetTpTicket(ticketNumber)` (Lines 4238-4266): Adds set TP ticket. Parameters: ticketNumber (string).
- `removeSetTpTicket(ticketNumber)` (Lines 4267-4274): Removes set TP ticket. Parameters: ticketNumber (string).
- `renderSetTpTags()` (Lines 4275-4316): Renders set TP tags. No parameters.
- `setSetTpTickets(tickets)` (Lines 4317-4322): Sets set TP tickets. Parameters: tickets (array).
- `clearAllSetTpTickets()` (Lines 4323-4328): Clears all set tickets. No parameters.
- `showSetTpInputError(message)` (Lines 4329-4347): Shows set input error. Parameters: message (string).
- `clearSetTpInputError()` (Lines 4348-4358): Clears set input error. No parameters.
- `renderSetDetailTpTags(tickets)` (Lines 4359-4393): Renders set detail tags. Parameters: tickets (array).

#### JIRA Integration (Lines ~4394-4656)
- `getOrCreateJiraTooltip()` (Lines 4394-4463): Gets or creates tooltip. No parameters.
- `hideJiraPreview()` (Lines 4464-4474): Hides preview. No parameters.
- `cancelHideTooltip()` (Lines 4475-4482): Cancels hide. No parameters.
- `displayJiraData(tooltip, ticketNumber, data)` (Lines 4483-4541): Displays JIRA data. Parameters: tooltip (HTMLElement), ticketNumber (string), data (object).
- `positionTooltip(tooltip, targetElement)` (Lines 4542-4584): Positions tooltip. Parameters: tooltip (HTMLElement), targetElement (HTMLElement).
- `openJiraTicket(ticketNumber)` (Lines 4585-4649): Opens JIRA ticket. Parameters: ticketNumber (string).
- `openJiraLink(ticketNumber)` (Lines 4650-4656): Opens JIRA link. Parameters: ticketNumber (string).

#### Form Validation (Lines ~4657-4926)
- `validateTestRunConfigForm()` (Lines 4657-4723): Validates form. No parameters.
- `validateAllTpTickets(tpTickets)` (Lines 4724-4778): Validates TP tickets. Parameters: tpTickets (array).
- `showFormValidationError(validationResult)` (Lines 4779-4830): Shows validation error. Parameters: validationResult (object).
- `clearAllFormErrors()` (Lines 4831-4850): Clears form errors. No parameters.
- `showNotification(message, type = 'info')` (Lines 4851-4926): Shows notification. Parameters: message (string), type (string).

#### Search and Utilities (Lines ~4927-5737)
- `getSearchResultStatusInfo(status, executionRate, passRate)` (Lines 4927-4938): Gets search status info. Parameters: status (string), executionRate (number), passRate (number).
- `setupQuickSearch_TPTicket()` (Lines 4939-5022): Sets up TP ticket search. No parameters.
- `debounce(func, delay)` (Lines 5023-5031): Debounces function. Parameters: func (function), delay (number).
- `highlightSearchTerm(text, searchTerm)` (Lines 5032-5096): Highlights search term. Parameters: text (string), searchTerm (string).
- `renderSearchHistory(container)` (Lines 5097-5137): Renders search history. Parameters: container (HTMLElement).
- `openQuickSearchTP()` (Lines 5138-5208): Opens TP search. No parameters.
- `closeQuickSearchTP()` (Lines 5209-5214): Closes TP search. No parameters.
- `quickSearchRenderTP(query, container)` (Lines 5215-5276): Renders TP search. Parameters: query (string), container (HTMLElement).
- `renderSearchResults(data, container, searchTerm = '')` (Lines 5277-5339): Renders search results. Parameters: data (array), container (HTMLElement), searchTerm (string).
- `buildConfigSearchItem(config, searchTerm)` (Lines 5340-5387): Builds config search item. Parameters: config (object), searchTerm (string).
- `buildSetSearchItem(set, searchTerm)` (Lines 5388-5435): Builds set search item. Parameters: set (object), searchTerm (string).
- `initNotificationSettings()` (Lines 5436-5476): Initializes notifications. No parameters.
- `ensureTeamIdInUrl_TRM(teamId)` (Lines 5477-5487): Ensures team ID in URL. Parameters: teamId (string).
- `clearNotificationSettings()` (Lines 5488-5509): Clears notifications. No parameters.
- `loadNotificationSettings(enabled, chatIds, chatNames)` (Lines 5510-5737): Loads notification settings. Parameters: enabled (boolean), chatIds (array), chatNames (array).

## Dependencies
- **Bootstrap**: UI framework
- **jQuery**: DOM manipulation
- **Custom utilities**: i18n, tooltip management

## Recent Fixes

### Fix: testRunSetDetailModal 排版重構 - 左右分布設計 (Nov 11, 2025)

**問題**:
- Test Run 名字太長時會導致旁邊的按鈕 toolbar 被擠到，版面不美觀
- 按鈕全部在一排，空間不足時會溢出
- Test Run name 和 button toolbar 會互相影響排版
- Test Run 列表中各項的排版結構不一致

**解決方案**:
重構整個 Modal Body 及 Test Run 列表的排版結構，實施一致的左右分布設計：

1. **Modal Body 上方區域重構** (Lines 1287-1325)
   - HTML 結構：使用 `testRunSetDetailHeaderContainer` 分為左右兩部分
   - 左邊（`testRunSetDetailContentSection`）: 內容區域（description, status, meta, TP tags）
   - 右邊（`testRunSetDetailActionsContainer`）: 按鈕區域（固定寬度 280px）
   - 按鈕使用 CSS Grid 2 列排列：`grid-template-columns: repeat(2, minmax(120px, 1fr))`

2. **Test Run 列表項目結構重構** (Lines 3086-3111，函數 `buildSetRunDetailRow`)
   - 修改按鈕生成邏輯：從 `d-flex flex-wrap` 改為 `testRunDetailRunActions`
   - HTML 結構：使用 `testRunDetailRunContainer` 分為左右兩部分
   - 左邊（`testRunDetailRunContent`）: Test Run 名字、狀態、指標
   - 右邊（`.testRunDetailRunActions`）: 按鈕區域（固定寬度 260px）
   - 按鈕使用 CSS Grid 2 列排列：`grid-template-columns: repeat(2, minmax(100px, 1fr))`

3. **CSS 樣式統一化** (Lines 823-939)
   - 新增容器樣式：`.testRunDetailRunContainer`、`.testRunDetailRunContent`
   - 新增按鈕容器樣式：`.testRunDetailRunActions`
   - Title 樣式保留：`#testRunSetDetailTitle`（兩行限制）
   - Modal 頂部區域樣式：`#testRunSetDetailHeaderContainer`、`#testRunSetDetailContentSection`

**程式碼修改位置**:
- HTML 結構 Modal Body: lines 1286-1326 (testRunSetDetailModal 內容區域)
- HTML 結構 Test Run 列表: lines 3086-3111 (buildSetRunDetailRow 函數返回值)
- CSS 樣式: lines 823-939 (完整的排版樣式定義)

**CSS 新增樣式詳情**:
```css
/* Modal Body 上方區域 - 左邊內容，右邊按鈕 */
#testRunSetDetailHeaderContainer {
    display: flex;
    gap: 1rem;
    align-items: flex-start;
}

#testRunSetDetailContentSection {
    flex: 1;
    min-width: 0;
}

/* 按鈕容器 - 兩排排列（2 列） */
#testRunSetDetailActionsContainer {
    flex-shrink: 0;
}

#testRunSetDetailActions {
    display: grid;
    gap: 0.5rem;
    grid-template-columns: repeat(2, minmax(120px, 1fr));
    width: 280px;
}

/* Test Run 列表項目 - 相同的左右結構 */
.testRunDetailRunContainer {
    display: flex;
    gap: 1rem;
    align-items: flex-start;
}

.testRunDetailRunContent {
    flex: 1;
    min-width: 0;
}

.testRunDetailRunActions {
    display: grid;
    gap: 0.5rem;
    grid-template-columns: repeat(2, minmax(100px, 1fr));
    width: 260px;
    flex-shrink: 0;
}
```

**HTML 結構變化**:
```html
<!-- 舊結構：內容和按鈕垂直堆疊 -->
<div class="modal-body">
    <div class="mb-3">內容區域</div>
    <div class="mb-3">按鈕區域</div>
    <div>Test Run 列表</div>
</div>

<!-- 新結構：內容左邊，按鈕右邊，同一行 -->
<div class="modal-body">
    <div class="d-flex gap-3 mb-4" id="testRunSetDetailHeaderContainer">
        <div class="flex-grow-1" id="testRunSetDetailContentSection">內容區域</div>
        <div id="testRunSetDetailActionsContainer">
            <div id="testRunSetDetailActions">按鈕（兩排）</div>
        </div>
    </div>
    <div id="testRunSetRunsContainer">Test Run 列表</div>
</div>
```

**Test Run 列表項目結構變化**:
```html
<!-- 舊結構：flex-wrap 自動換行 -->
<div class="d-flex flex-column flex-lg-row justify-content-between align-items-lg-start gap-3">
    <div class="flex-grow-1">名字、狀態、指標</div>
    <div class="d-flex flex-column align-items-lg-end gap-2 w-100 w-lg-auto">
        <div class="d-flex gap-2 flex-wrap">按鈕（自動換行）</div>
    </div>
</div>

<!-- 新結構：固定 2 列網格 -->
<div class="testRunDetailRunContainer">
    <div class="testRunDetailRunContent">名字、狀態、指標</div>
    <div class="testRunDetailRunActions">按鈕（固定兩排）</div>
</div>
```

**測試情況**:
- 短內容: 內容和按鈕在同一行
- 長內容: 內容區域拉長，按鈕保持固定寬度在右邊
- 長 title: 限制兩行顯示，不影響按鈕排列
- 按鈕佈局: 固定兩行排列，不隨寬度變化
- 響應式: Modal 寬度變化時，內容和按鈕比例自動調整

## Issues Identified
1. **Monolithic Structure**: Single file with 5737 lines mixing HTML, CSS, and JS
2. **Inline Styles**: Large embedded CSS section
3. **Inline Scripts**: ~4000+ lines of JavaScript in template
4. **Global State**: Extensive use of global variables
5. **Tight Coupling**: Direct DOM manipulation throughout
6. **No Modularization**: All functionality in one file
7. **Maintenance Difficulty**: Hard to test and modify individual features