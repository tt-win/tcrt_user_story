function tt(key, fb){try{if(window.i18n && window.i18n.isReady && window.i18n.isReady()){const v=window.i18n.t(key);if(v && v!==key) return v;}}catch(_){ }return fb;}

document.addEventListener('DOMContentLoaded', async () => {
    const { Handsontable } = window;
    if (!Handsontable) {
        console.error('Handsontable not loaded');
        return;
    }

    const pathParts = window.location.pathname.split('/');
    const runId = pathParts[pathParts.indexOf('adhoc-runs') + 1];

    const dom = {
        runName: document.getElementById('runNameDisplay'),
        sheetTabs: document.getElementById('sheetTabsContainer'),
        addSheet: document.getElementById('addSheetBtn'),
        addRow: document.getElementById('addRowBtn'),
        saveStatus: document.getElementById('saveStatus'),
        backBtn: document.getElementById('backToMgmtBtn'),
        gridHost: document.getElementById('adhocGrid'),
    };

    let hot = null;
    let currentRun = null;
    let currentSheetId = null;
    let autoSaveTimer = null;
    let assigneeOptions = [];
    let deletedItemIds = new Set();
    let isSaving = false;
    let isPendingSave = false;

    const PRIORITY = ['High', 'Medium', 'Low'];
    const RESULT = ['', 'Passed', 'Failed', 'Retest', 'Not Available', 'Pending', 'Not Required'];

    const buildColumns = () => {
        const hasAssignees = assigneeOptions.length > 0;
        const assigneeSource = hasAssignees
            ? function (_query, process) { process(Array.isArray(assigneeOptions) ? assigneeOptions : []); }
            : undefined;
        return [
            { data: 'test_case_number', title: 'Test Case Number', width: 140 },
            { data: 'title', title: 'Title', width: 260 },
            { data: 'priority', title: 'Priority', width: 110, type: 'dropdown', source: PRIORITY, renderer: priorityRenderer },
            { data: 'precondition', title: 'Precondition', width: 220 },
            { data: 'steps', title: 'Steps', width: 240 },
            { data: 'expected_result', title: 'Expected Result', width: 240 },
            { data: 'test_result', title: 'Result', width: 140, type: 'dropdown', source: RESULT, renderer: resultRenderer },
            hasAssignees
                ? { data: 'assignee_name', title: 'Assignee', width: 180, type: 'dropdown', source: assigneeSource, strict: false, allowInvalid: true, trimDropdown: false }
                : { data: 'assignee_name', title: 'Assignee', width: 180, type: 'text' },
            { data: 'comments', title: 'Comments', width: 220 },
            { data: 'bug_list', title: 'Bug List', width: 180 }
        ];
    };

    // Move listeners to bottom or after definitions
    // ... definitions ...

    // Helper function to setup listeners
    function setupListeners() {
        dom.addSheet?.addEventListener('click', onAddSheet);
        dom.addRow?.addEventListener('click', onAddRow);
        const reportsBtn = document.getElementById('reportsBtn');
        if (reportsBtn) {
            reportsBtn.addEventListener('click', () => {
                console.info('Opening Ad-hoc Charts & Reports');
                openReports();
            });
        } else {
            console.warn('reportsBtn not found');
        }
        const exportHtmlBtn = document.getElementById('exportHtmlBtn');
        if (exportHtmlBtn) {
            exportHtmlBtn.addEventListener('click', exportHtmlReport);
        }
    }

    // ... (rest of the file) ...

    await loadRun();
    await loadAssignees();
    setupListeners(); // Call it here

    async function loadRun() {
        try {
            const resp = await window.AuthClient.fetch(`/api/adhoc-runs/${runId}`);
            if (!resp.ok) throw new Error(tt('adhoc.loadFailed','Failed to load run'));
            currentRun = await resp.json();

            const runName = currentRun.name || `Ad-hoc Run ${runId}`;
            if (dom.runName) {
                dom.runName.textContent = runName;
                dom.runName.removeAttribute('data-i18n');
            }
            document.title = `${runName} - Ad-hoc Test Run`;
            if (currentRun.team_id && dom.backBtn) {
                dom.backBtn.href = `/test-run-management?team_id=${currentRun.team_id}`;
            }

            // Handle case where no sheets exist after deletion
            if (!currentRun.sheets || currentRun.sheets.length === 0) {
                currentRun.sheets = [];
                if (hot) {
                    hot.destroy();
                    hot = null;
                    dom.gridHost.innerHTML = '<div class="text-center mt-5 text-muted">No sheets. Click "+" to add one.</div>';
                }
                dom.sheetTabs.innerHTML = '';
                return;
            }

            renderTabs();
            const firstSheetId = currentRun.sheets[0].id;
            // If currentSheetId is invalid (e.g. deleted), switch to first
            const targetSheet = currentSheetId && currentRun.sheets.find(s => s.id == currentSheetId) ? currentSheetId : firstSheetId;
            
            if (targetSheet) {
                switchToSheet(targetSheet);
            }
        } catch (e) {
            console.error(e);
            if (dom.runName) {
                dom.runName.textContent = 'Load failed';
                dom.runName.removeAttribute('data-i18n');
            }
        }
    }

    function renderTabs() {
        if (!dom.sheetTabs) return;
        dom.sheetTabs.innerHTML = '';
        if (!currentRun?.sheets) return;
        currentRun.sheets.sort((a, b) => a.sort_order - b.sort_order);

        currentRun.sheets.forEach(sheet => {
            const tab = document.createElement('div');
            tab.className = `sheet-tab ${sheet.id == currentSheetId ? 'active' : ''}`;
            tab.style.position = 'relative';

            const name = document.createElement('span');
            name.className = 'tab-name';
            name.textContent = sheet.name;

            // Container for buttons
            const btnContainer = document.createElement('span');
            btnContainer.className = 'ms-2 d-flex align-items-center';

            const rename = document.createElement('button');
            rename.className = 'btn btn-link btn-sm p-0 text-secondary';
            rename.innerHTML = '<i class="fas fa-edit"></i>';
            rename.title = 'Rename sheet';
            rename.style.fontSize = '0.85rem';
            rename.style.lineHeight = '1';

            const delBtn = document.createElement('button');
            delBtn.className = 'btn btn-link btn-sm p-0 ms-2 text-danger';
            delBtn.innerHTML = '<i class="fas fa-trash-alt"></i>';
            delBtn.title = 'Delete sheet';
            delBtn.style.fontSize = '0.85rem';
            delBtn.style.lineHeight = '1';

            const startRename = () => {
                if (tab.dataset.editing === 'true') return;
                tab.dataset.editing = 'true';
                const tabWidth = tab.getBoundingClientRect().width;
                const tabHeight = tab.getBoundingClientRect().height;
                
                tab.style.width = `${tabWidth}px`;
                tab.style.minWidth = `${tabWidth}px`;
                
                // Hide content with visibility to keep size
                name.style.visibility = 'hidden';
                btnContainer.style.visibility = 'hidden';

                const input = document.createElement('input');
                input.type = 'text';
                input.className = 'form-control form-control-sm';
                input.value = sheet.name;
                
                // Absolute positioning to cover the tab
                input.style.position = 'absolute';
                input.style.left = '0';
                input.style.top = '0';
                input.style.width = '100%';
                input.style.height = '100%';
                input.style.padding = '0 6px';
                input.style.fontSize = '13px';
                input.style.lineHeight = '1.2';
                input.style.boxSizing = 'border-box';
                input.style.borderRadius = '6px 6px 0 0'; // Match tab border radius
                input.style.zIndex = '10';
                
                tab.appendChild(input);
                input.focus();
                input.select();

                const commit = async () => {
                    tab.dataset.editing = 'false';
                    if (input.parentNode === tab) tab.removeChild(input);
                    tab.style.width = '';
                    tab.style.minWidth = '';
                    name.style.visibility = '';
                    btnContainer.style.visibility = '';
                    
                    const newName = input.value.trim();
                    if (!newName || newName === sheet.name) {
                        name.textContent = sheet.name;
                        return;
                    }
                    name.textContent = newName;
                    await renameSheet(sheet.id, newName);
                };
                
                const cancel = () => {
                    tab.dataset.editing = 'false';
                    if (input.parentNode === tab) tab.removeChild(input);
                    tab.style.width = '';
                    tab.style.minWidth = '';
                    name.style.visibility = '';
                    btnContainer.style.visibility = '';
                };

                input.addEventListener('keydown', (e) => {
                    if (e.key === 'Enter') { e.preventDefault(); commit(); }
                    if (e.key === 'Escape') { e.preventDefault(); cancel(); }
                });
                input.addEventListener('blur', commit);
            };

            tab.addEventListener('click', (e) => {
                // Prevent switching if clicking input or during edit
                if (tab.dataset.editing === 'true' && e.target.tagName === 'INPUT') return;
                if (tab.dataset.editing === 'true') return;
                switchToSheet(sheet.id);
            });
            
            name.addEventListener('dblclick', (e) => { e.stopPropagation(); startRename(); });
            rename.addEventListener('click', (e) => { e.stopPropagation(); startRename(); });
            
            delBtn.addEventListener('click', async (e) => {
                e.stopPropagation();
                if (confirm(tt('adhoc.confirmDeleteSheet', 'Are you sure you want to delete this sheet?'))) {
                    await deleteSheet(sheet.id);
                }
            });

            btnContainer.appendChild(rename);
            btnContainer.appendChild(delBtn);
            tab.appendChild(name);
            tab.appendChild(btnContainer);
            dom.sheetTabs.appendChild(tab);
        });
    }

    async function deleteSheet(id) {
        try {
            const resp = await window.AuthClient.fetch(`/api/adhoc-runs/${runId}/sheets/${id}`, {
                method: 'DELETE'
            });
            if (resp.ok) {
                // If we deleted the current sheet, set ID to null so loadRun picks a new one
                if (currentSheetId == id) {
                    currentSheetId = null;
                }
                await loadRun();
            } else {
                alert('Delete failed');
            }
        } catch (e) {
            console.error(e);
            alert('Delete error');
        }
    }

    async function renameSheet(id, name) {
        try {
            const resp = await window.AuthClient.fetch(`/api/adhoc-runs/${runId}/sheets/${id}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name })
            });
            if (resp.ok) {
                await loadRun();
                switchToSheet(id);
            } else {
                alert('Rename failed');
            }
        } catch (e) {
            console.error(e);
            alert('Rename error');
        }
    }

    function switchToSheet(sheetId) {
        currentSheetId = sheetId;
        renderTabs();
        loadSheetItems(sheetId);
    }

    async function loadSheetItems(sheetId) {
        const sheet = currentRun?.sheets?.find(s => s.id == sheetId);
        if (!sheet) return;
        const items = (sheet.items || []).slice().sort((a, b) => a.row_index - b.row_index);
        const rows = items.map(convertItemToRow);
        initHot(rows);
    }

    function convertItemToRow(item) {
        const isSection = (item?.test_case_number || '').trim().toUpperCase() === 'SECTION';
        return {
            id: item?.id || null,
            test_case_number: item?.test_case_number || '',
            title: item?.title || '',
            priority: isSection ? '' : (item?.priority || 'Medium'),
            precondition: isSection ? '' : (item?.precondition || ''),
            steps: isSection ? '' : (item?.steps || ''),
            expected_result: isSection ? '' : (item?.expected_result || ''),
            test_result: isSection ? '' : (item?.test_result || ''),
            assignee_name: isSection ? '' : (item?.assignee_name || ''),
            comments: item?.comments || '',
            bug_list: item?.bug_list || '',
            meta_json: item?.meta_json || '{}'
        };
    }

    function applyCommonStyles(instance, td, row, col, prop, value) {
        if (typeof row !== 'number' || row < 0) return;
        const physicalRow = instance.toPhysicalRow(row);
        if (physicalRow === null) return;
        
        const rowData = instance.getSourceDataAtRow(physicalRow);
        if (!rowData) return;

        const meta = rowData.meta || {};
        
        // Try to parse meta_json if meta object is empty
        let bgColor = null;
        if (meta.backgroundColor) {
            bgColor = meta.backgroundColor;
        } else if (rowData.meta_json) {
            try {
                const m = JSON.parse(rowData.meta_json);
                bgColor = m.backgroundColor;
            } catch (e) {}
        }

        const isSection = rowData.test_case_number === 'SECTION';

        // 1. Background Color
        if (bgColor) {
            td.style.backgroundColor = bgColor;
        } else if (isSection) {
            td.style.backgroundColor = '#f3f4f6';
        } else {
            // For standard cells, we don't clear background because:
            // - Default renderers might have set it (e.g. conditional formatting).
            // - If we want "No Color" to mean "Default", we leave it.
            // - If user explicitly set "No Color", bgColor would be null/undefined.
        }

        // 2. Section Row Logic
        if (isSection) {
            td.classList.add('adhoc-section-cell');
            td.style.textAlign = 'center';
            td.style.backgroundColor = '#f3f4f6';
            td.style.color = '#374151';
            if (prop === 'test_case_number') {
                td.style.color = '#6b7280';
            } else if (prop === 'title') {
                td.style.fontWeight = '700';
            } else {
                td.textContent = '';
            }
        }
    }

    // Merge disabled for Section rows (render-only styling)

    function initHot(data) {
        if (hot) {
            hot.destroy();
            dom.gridHost.innerHTML = '';
        }

        const columns = buildColumns();

        hot = new Handsontable(dom.gridHost, {
            data,
            columns,
            colHeaders: columns.map(c => c.title || ''),
            rowHeaders: true,
            width: '100%',
            height: '100%',
            rowHeights: 28,
            manualColumnResize: true,
            manualRowResize: true,
            stretchH: 'none',
            licenseKey: 'non-commercial-and-evaluation',
            contextMenu: ['copy','cut','paste','---------','row_above','row_below','remove_row','---------','undo','redo'],
            dropdownMenu: ['filter_by_condition','filter_by_value','filter_action_bar'],
            filters: true,
            fillHandle: true,
            search: true, // Enable Search Plugin
            outsideClickDeselects: false, // Keep selection when clicking toolbar buttons
            undoRedo: false, // Disable Undo/Redo
            beforeRemoveRow: (index, amount, physicalRows) => {
                if (!hot) return;
                physicalRows.forEach(row => {
                    const item = hot.getSourceDataAtRow(row);
                    if (item && item.id) {
                        deletedItemIds.add(item.id);
                    }
                });
            },
            afterRemoveRow: () => {
                handleChange();
            },
            cells: function(row, col) {
                const cellProps = {};
                if (typeof row !== 'number' || row < 0) return cellProps;
                
                const physicalRow = this.instance.toPhysicalRow(row);
                if (physicalRow === null) return cellProps;
                
                const rowData = this.instance.getSourceDataAtRow(physicalRow);
                
                if (rowData && rowData.test_case_number === 'SECTION') {
                    const prop = this.instance.colToProp(col);
                    cellProps.renderer = function(instance, td) {
                        td.textContent = '';
                        td.style.backgroundColor = '#f3f4f6';
                        td.style.color = '#374151';
                        td.style.textAlign = 'center';
                        if (prop === 'test_case_number') {
                            td.style.color = '#6b7280';
                            td.textContent = rowData.test_case_number || 'SECTION';
                        } else if (prop === 'title') {
                            td.style.fontWeight = '700';
                            td.textContent = rowData.title || '';
                        }
                    };
                    if (prop !== 'title') {
                        cellProps.readOnly = true;
                    }
                }
                return cellProps;
            },
            afterInit: function() {
                fixAriaHidden();
                
            },
            afterBeginEditing: fixAriaHidden,
            afterChange: (changes, source) => {
                if (source === 'loadData' || source === 'autosave') {
                    return;
                }
                handleChange();
            },
            afterPaste: () => { handleChange(); },
        });
    }

    // --- Search & Replace Feature ---

    // Inject Button: Add Section (align with system button style)
    if (dom.addRow && !document.getElementById('addSectionBtn')) {
        const btn = document.createElement('button');
        btn.id = 'addSectionBtn';
        btn.className = 'btn btn-sm btn-primary ms-2';
        btn.innerHTML = '<i class="fas fa-heading me-1"></i><span data-i18n="adhoc.addSection">Add Section</span>';
        btn.onclick = onAddSection;
        dom.addRow.parentNode.insertBefore(btn, dom.addRow.nextSibling);
    }

    // Color picker disabled (all)

    // Inject Button: Find & Replace (align with system secondary style)
    if (dom.addRow && !document.getElementById('searchReplaceBtn')) {
        const btn = document.createElement('button');
        btn.id = 'searchReplaceBtn';
        btn.className = 'btn btn-sm btn-secondary ms-2';
        btn.innerHTML = '<i class="fas fa-search me-1"></i><span data-i18n="adhoc.findReplace">Find & Replace</span>';
        btn.onclick = openSearchModal;
        btn.title = "Ctrl+F / ⌘+F";
        dom.addRow.parentNode.insertBefore(btn, dom.addRow.nextSibling);
    }

    // Keyboard shortcut: Ctrl+F or Cmd+F
    document.addEventListener('keydown', (e) => {
        if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'f') {
            e.preventDefault();
            openSearchModal();
        }
    });

    let searchModal = null;
    let searchResults = [];
    let currentSearchIdx = -1;

    function ensureSearchModal() {
        if (document.getElementById('adhocSearchModal')) return;
        
        const modalHtml = `
        <div class="modal fade" id="adhocSearchModal" tabindex="-1" data-bs-backdrop="false">
            <div class="modal-dialog modal-dialog-scrollable modal-sm" style="margin-right: 20px; margin-top: 60px; margin-left: auto;">
                <div class="modal-content shadow">
                    <div class="modal-header p-2">
                        <h6 class="modal-title small">Find & Replace</h6>
                        <button type="button" class="btn-close btn-sm" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body p-3">
                        <div class="mb-2">
                            <input type="text" id="findInput" class="form-control form-control-sm" placeholder="Find what...">
                        </div>
                        <div class="mb-3">
                            <input type="text" id="replaceInput" class="form-control form-control-sm" placeholder="Replace with...">
                        </div>
                        <div class="d-flex justify-content-between mb-2">
                            <button id="findNextBtn" class="btn btn-sm btn-primary flex-grow-1 me-1">Find Next</button>
                            <button id="findPrevBtn" class="btn btn-sm btn-primary flex-grow-1">Find Prev</button>
                        </div>
                        <div class="d-flex justify-content-between">
                            <button id="replaceBtn" class="btn btn-sm btn-secondary flex-grow-1 me-1">Replace</button>
                            <button id="replaceAllBtn" class="btn btn-sm btn-secondary flex-grow-1">Replace All</button>
                        </div>
                        <div id="searchMsg" class="text-muted small mt-2 text-center" style="min-height: 1.2em;"></div>
                    </div>
                </div>
            </div>
        </div>`;
        
        const div = document.createElement('div');
        div.innerHTML = modalHtml;
        document.body.appendChild(div.firstElementChild);

        const m = document.getElementById('adhocSearchModal');
        m.addEventListener('shown.bs.modal', () => document.getElementById('findInput').focus());
        
        document.getElementById('findNextBtn').addEventListener('click', () => doFind(1));
        document.getElementById('findPrevBtn').addEventListener('click', () => doFind(-1));
        document.getElementById('replaceBtn').addEventListener('click', doReplace);
        document.getElementById('replaceAllBtn').addEventListener('click', doReplaceAll);
        document.getElementById('findInput').addEventListener('keydown', e => {
            if(e.key === 'Enter') doFind(1);
        });
    }

    function openSearchModal() {
        ensureSearchModal();
        if (!searchModal) {
            searchModal = new bootstrap.Modal(document.getElementById('adhocSearchModal'));
        }
        searchModal.show();
    }

    function doFind(direction = 1) {
        if (!hot) return;
        const query = document.getElementById('findInput').value;
        if (!query) return;

        const plugin = hot.getPlugin('search');
        const result = plugin.query(query);
        searchResults = result || [];

        const msg = document.getElementById('searchMsg');
        if (searchResults.length === 0) {
            msg.textContent = 'No matches found.';
            currentSearchIdx = -1;
            hot.render();
            return;
        }

        // Cycle index
        currentSearchIdx += direction;
        if (currentSearchIdx >= searchResults.length) currentSearchIdx = 0;
        if (currentSearchIdx < 0) currentSearchIdx = searchResults.length - 1;

        msg.textContent = `${currentSearchIdx + 1} / ${searchResults.length}`;

        const match = searchResults[currentSearchIdx];
        hot.selectCell(match.row, match.col);
        hot.scrollViewportTo(match.row, match.col);
        hot.render();
    }

    function doReplace() {
        if (!hot || searchResults.length === 0 || currentSearchIdx < 0) {
            doFind(1); // Try to find first
            return;
        }

        const replaceVal = document.getElementById('replaceInput').value || '';
        const match = searchResults[currentSearchIdx];
        
        // Verify if cell still contains value (in case user edited)
        const cellData = hot.getDataAtCell(match.row, match.col);
        // Simple check, might need regex if partial match? 
        // Handsontable search is partial by default.
        // We will replace the WHOLE cell content or partial?
        // Usually "Replace" in spreadsheets replaces the whole content if it matches, 
        // OR replaces the substring. 
        // Let's do substring replacement for better UX.
        
        const query = document.getElementById('findInput').value;
        const newVal = String(cellData).replace(new RegExp(escapeRegExp(query), 'gi'), replaceVal); // Global case-insensitive

        hot.setDataAtCell(match.row, match.col, newVal);
        
        // Move to next
        doFind(1);
    }

    function doReplaceAll() {
        if (!hot) return;
        const query = document.getElementById('findInput').value;
        const replaceVal = document.getElementById('replaceInput').value || '';
        if (!query) return;

        const plugin = hot.getPlugin('search');
        const result = plugin.query(query);
        
        if (!result || result.length === 0) {
            document.getElementById('searchMsg').textContent = '0 matches replaced.';
            return;
        }

        const changes = [];
        const regex = new RegExp(escapeRegExp(query), 'gi');

        // Group by cell to avoid multiple replacements in same cell confusing indices (though query returns unique cells usually?)
        // plugin.query returns array of {row, col, data}.
        
        result.forEach(({row, col, data}) => {
            const newVal = String(data).replace(regex, replaceVal);
            changes.push([row, col, newVal]);
        });

        hot.setDataAtCell(changes);
        document.getElementById('searchMsg').textContent = `Replaced ${changes.length} instances.`;
        searchResults = [];
        currentSearchIdx = -1;
        hot.render();
    }

    function escapeRegExp(string) {
        return string.replace(/[.*+?^`{`}();|[\]\\]/g, '\\$&');
    }

    async function onAddSheet() {
        const name = prompt('Sheet name', `Sheet${(currentRun?.sheets?.length || 0) + 1}`);
        if (!name) return;
        try {
            const resp = await window.AuthClient.fetch(`/api/adhoc-runs/${runId}/sheets`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name, sort_order: currentRun?.sheets?.length || 0 })
            });
            if (!resp.ok) throw new Error(tt('adhoc.saveFailed','Failed to save'));
            const newSheet = await resp.json();
            await loadRun();
            switchToSheet(newSheet.id);
        } catch (e) {
            console.error(e);
            alert('Create sheet failed');
        }
    }

    function onAddRow() {
        if (!hot) return;
        const data = hot.getSourceData();
        data.push(convertItemToRow(null));
        hot.loadData(data);
        hot.selectCell(data.length - 1, 0);
        handleChange();
    }

    function onAddSection() {
        if (!hot) return;
        const data = hot.getSourceData();
        // Insert a section row
        data.push({
            id: null,
            test_case_number: 'SECTION',
            title: '--- Section Header ---',
            priority: 'Medium',
            precondition: '',
            steps: '',
            expected_result: '',
            test_result: 'Not Required',
            assignee_name: '',
            comments: '',
            bug_list: '',
            meta_json: JSON.stringify({ backgroundColor: '#f3f4f6' })
        });
        hot.loadData(data);
        hot.selectCell(data.length - 1, 1); // Select Title column
        handleChange();
    }

    // updateSectionRowsColor removed

    function handleChange() {
        if (!dom.saveStatus) return;
        dom.saveStatus.textContent = tt('adhoc.unsaved','Unsaved changes...');
        dom.saveStatus.className = 'text-warning small';
        clearTimeout(autoSaveTimer);
        autoSaveTimer = setTimeout(saveChanges, 800);
    }

    async function saveChanges() {
        if (!hot || !currentSheetId) return;
        
        if (isSaving) {
            isPendingSave = true;
            return;
        }
        
        isSaving = true;
        
        try {
            // Normalization maps
            const PRIORITY_MAP = {
                'high': 'High',
                'medium': 'Medium',
                'low': 'Low'
            };
            const RESULT_MAP = {
                'passed': 'Passed',
                'failed': 'Failed',
                'retest': 'Retest',
                'not available': 'Not Available',
                'pending': 'Pending',
                'not required': 'Not Required'
            };
            const RESULT_VALUES = Object.values(RESULT_MAP);
    
            const data = hot.getSourceData();
            
            // Prune deletedItemIds
            const currentIds = new Set(data.map(i => i.id).filter(id => id));
            for (const id of deletedItemIds) {
                if (currentIds.has(id)) {
                    deletedItemIds.delete(id);
                }
            }
    
            const payload = data
                .map((row, idx) => {
                    // Check if Section
                    const isSection = row.test_case_number === 'SECTION';
    
                    // Sanitize Priority
                    let prio = (row.priority || '').toString().trim();
                    const prioLower = prio.toLowerCase();
                    
                    if (isSection) {
                        prio = 'Medium'; 
                    } else {
                        if (PRIORITY_MAP[prioLower]) {
                            prio = PRIORITY_MAP[prioLower];
                        } else if (!['High', 'Medium', 'Low'].includes(prio)) {
                            prio = 'Medium'; 
                        }
                    }
    
                    // Sanitize Result
                    let res = (row.test_result || '').toString().trim();
                    const resLower = res.toLowerCase();
                    
                    if (isSection) {
                        res = 'Not Required';
                    } else {
                        if (RESULT_MAP[resLower]) {
                            res = RESULT_MAP[resLower];
                        } else if (!RESULT_VALUES.includes(res)) {
                            res = null; 
                        }
                    }
    
                    return {
                        id: row.id ? Number(row.id) : null,
                        row_index: idx,
                        test_case_number: isSection ? 'SECTION' : (row.test_case_number || '').trim(),
                        title: (row.title || '').trim(),
                        priority: prio,
                        precondition: (row.precondition || '').trim(),
                        steps: (row.steps || '').trim(),
                        expected_result: (row.expected_result || '').trim(),
                        test_result: res,
                        assignee_name: (row.assignee_name || '').trim(),
                        comments: (row.comments || '').trim(),
                        bug_list: (row.bug_list || '').trim(),
                        meta_json: row.meta_json
                    };
                })
                .filter(r => r.id || r.title || r.test_case_number || r.comments || r.bug_list || r.assignee_name);
    
            // Append Deletions
            deletedItemIds.forEach(id => {
                payload.push({ id: id, _delete: true });
            });
    
            if (payload.length === 0) {
                dom.saveStatus.textContent = tt('adhoc.saved','All changes saved');
                dom.saveStatus.className = 'text-muted small';
                return;
            }
    
            dom.saveStatus.textContent = tt('adhoc.saving','Saving...');
            dom.saveStatus.className = 'text-info small';
    
            const resp = await window.AuthClient.fetch(`/api/adhoc-runs/${runId}/sheets/${currentSheetId}/items/batch`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            if (!resp.ok) throw new Error(tt('adhoc.saveFailed','Failed to save'));
            const result = await resp.json().catch(() => ({}));
            
            // Success - Clear deletions
            deletedItemIds.clear();
    
            if (result?.items?.length) {
                // Update IDs using setSourceDataAtCell
                result.items.forEach(({ id, row_index }) => {
                    const idx = Number(row_index);
                    const newId = Number(id);
                    
                    if (Number.isInteger(idx) && idx >= 0 && Number.isInteger(newId) && newId > 0) {
                        // Use physical index from getSourceData mapping
                        hot.setSourceDataAtCell(idx, 'id', newId);
                    }
                });
                hot.render();
            }
            dom.saveStatus.textContent = tt('adhoc.saved','All changes saved');
            dom.saveStatus.className = 'text-muted small';
        } catch (e) {
            console.error(e);
            dom.saveStatus.textContent = tt('adhoc.saveFailed','Error saving!');
            dom.saveStatus.className = 'text-danger small';
        } finally {
            isSaving = false;
            if (isPendingSave) {
                isPendingSave = false;
                setTimeout(saveChanges, 100); // Small delay to debounce
            }
        }
    }

    async function loadAssignees() {
        let options = [];
        try {
            const resp = await window.AuthClient.fetch('/api/users?page=1&per_page=100');
            if (resp.ok) {
                const data = await resp.json();
                console.info('Assignee users raw', data);
                options = (data?.users || [])
                    .filter(u => {
                        const role = (u.role || '').toLowerCase();
                        const username = (u.username || '').toLowerCase();
                        // 排除預設 admin/super_admin
                        return role !== 'super_admin' && username !== 'admin';
                    })
                    .map(u => u.lark_name || u.full_name || u.username || '')
                    .filter(Boolean);
                console.info('Assignee options loaded', options.length);
            } else {
                console.warn('Assignee load users failed status', resp.status);
                console.warn('Assignee load users body', await resp.text().catch(() => ''));
            }
        } catch (e) {
            console.warn('Assignee load users error', e);
        }

        assigneeOptions = options
            .filter((v, idx, arr) => arr.indexOf(v) === idx)
            .sort((a, b) => a.localeCompare(b));

        if (hot) {
            const cols = buildColumns();
            hot.updateSettings({ columns: cols, colHeaders: cols.map(c => c.title || '') });
            hot.render();
        }
    }

    function fixAriaHidden() {
        try {
            document.querySelectorAll('.handsontableInput[aria-hidden="true"]').forEach(el => {
                el.setAttribute('aria-hidden', 'false');
            });
        } catch (_) {}
    }

    function priorityRenderer(instance, td, row, col, prop, value, cellProperties) {
        const rowData = instance.getSourceDataAtRow(instance.toPhysicalRow(row));
        const isSection = rowData?.test_case_number === 'SECTION';
        Handsontable.renderers.TextRenderer.apply(this, arguments);
        if (isSection) {
            td.textContent = '';
            td.style.backgroundColor = '#f3f4f6';
            td.style.color = '#6b7280';
            td.style.fontWeight = '600';
            td.style.textAlign = 'center';
            td.style.verticalAlign = 'middle';
            return;
        }
        const val = (value || '').toLowerCase();
        td.style.fontWeight = '600';
        td.style.textAlign = 'center';
        td.style.verticalAlign = 'middle';
        if (val === 'high') {
            td.style.backgroundColor = '#fdecea';
            td.style.color = '#b91c1c';
        } else if (val === 'medium') {
            td.style.backgroundColor = '#fff4e5';
            td.style.color = '#b45309';
        } else if (val === 'low') {
            td.style.backgroundColor = '#eef2ff';
            td.style.color = '#4338ca';
        } else {
            td.style.backgroundColor = '';
            td.style.color = '';
            td.style.fontWeight = '';
        }
    }

    function resultRenderer(instance, td, row, col, prop, value, cellProperties) {
        const rowData = instance.getSourceDataAtRow(instance.toPhysicalRow(row));
        const isSection = rowData?.test_case_number === 'SECTION';
        Handsontable.renderers.TextRenderer.apply(this, arguments);
        if (isSection) {
            td.textContent = '';
            td.style.backgroundColor = '#f3f4f6';
            td.style.color = '#6b7280';
            td.style.fontWeight = '600';
            td.style.textAlign = 'center';
            td.style.verticalAlign = 'middle';
            return;
        }
        const val = (value || '').toLowerCase();
        td.style.fontWeight = '600';
        td.style.textAlign = 'center';
        td.style.verticalAlign = 'middle';
        td.style.backgroundColor = '';
        td.style.color = '';
        if (val === 'passed') { td.style.color = '#15803d'; td.style.backgroundColor = '#e7f6ec'; }
        else if (val === 'failed') { td.style.color = '#b91c1c'; td.style.backgroundColor = '#fdecea'; }
        else if (val === 'retest') { td.style.color = '#b45309'; td.style.backgroundColor = '#fff4e5'; }
        else if (val === 'not available') { td.style.color = '#4b5563'; td.style.backgroundColor = '#f3f4f6'; }
        else if (val === 'pending') { td.style.color = '#92400e'; td.style.backgroundColor = '#fef3c7'; }
        else if (val === 'not required') { td.style.color = '#6b7280'; td.style.backgroundColor = '#f3f4f6'; }
        else { td.style.fontWeight = ''; }
    }

    // --- Charts & Reports (Ad-hoc) ---
    async function openReports() {
        try {
            ensureReportsModal();
            const modalEl = document.getElementById('adhocReportsModal');
            const contentEl = document.getElementById('adhocReportsContent');
            if (!modalEl || !contentEl) {
                console.warn('reports modal element missing');
                return;
            }
            if (!(window.bootstrap && window.bootstrap.Modal)) {
                console.error('bootstrap Modal not available');
                return;
            }

            // 取最新資料
            console.info('reports fetch run', runId);
            const resp = await window.AuthClient.fetch(`/api/adhoc-runs/${runId}`);
            if (!resp.ok) {
                console.error('reports fetch failed', resp.status);
                throw new Error('load run failed');
            }
            const run = await resp.json();
            console.info('reports run loaded with sheets', (run.sheets || []).length);

            const statuses = ['Passed','Failed','Retest','Not Available','Pending','Not Required'];
            const normalize = (v) => (v || '').toLowerCase();

            const sheetRows = [];
            const total = { name: 'Total', counts: {} };
            statuses.forEach(s => total.counts[s] = 0);

            (run.sheets || []).forEach(sheet => {
                const counts = {};
                statuses.forEach(s => counts[s] = 0);
                (sheet.items || []).forEach(item => {
                    const val = normalize(item.test_result || '');
                    const match = statuses.find(s => s.toLowerCase() === val);
                    if (match) counts[match] += 1;
                });
                statuses.forEach(s => total.counts[s] += counts[s]);
                sheetRows.push({ name: sheet.name, counts });
            });

            if (sheetRows.length === 0) {
                contentEl.innerHTML = '<div class=\"text-muted\">No sheets or data</div>';
            } else {
                renderReportsContent(contentEl, sheetRows, total, statuses);
            }

            const modal = bootstrap.Modal.getOrCreateInstance(modalEl);
            console.info('showing adhoc reports modal');
            modal.show();
        } catch (e) {
            console.error('adhoc reports error', e);
            alert(tt('adhoc.loadFailed','Failed to load reports'));
        }
    }

    function ensureReportsModal() {
        if (document.getElementById('adhocReportsModal')) return;
        const wrapper = document.createElement('div');
        wrapper.innerHTML = `
        <div class="modal fade" id="adhocReportsModal" tabindex="-1" aria-labelledby="adhocReportsModalLabel" aria-hidden="true">
          <div class="modal-dialog modal-lg modal-dialog-centered">
            <div class="modal-content">
              <div class="modal-header">
                <h5 class="modal-title" id="adhocReportsModalLabel"><i class="fas fa-chart-pie me-2"></i><span data-i18n="testRun.chartsReports">Charts & Reports</span></h5>
                <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
              </div>
              <div class="modal-body">
                <div id="adhocReportsContent" class="table-responsive"></div>
              </div>
              <div class="modal-footer">
                <button type="button" class="btn btn-primary" id="adhocOpenHtmlBtn">
                  <i class="fas fa-file-alt me-1"></i> Open HTML Report
                </button>
                <button type="button" class="btn btn-secondary" data-bs-dismiss="modal" data-i18n="common.close">Close</button>
              </div>
            </div>
          </div>
        </div>`;
        document.body.appendChild(wrapper.firstElementChild);

        const openBtn = document.getElementById('adhocOpenHtmlBtn');
        if (openBtn && !openBtn.dataset.bound) {
            openBtn.dataset.bound = 'true';
            openBtn.addEventListener('click', openHtmlReportView);
        }
    }

    function renderReportsContent(container, sheetRows, total, statuses) {
        const colors = {
            Passed: '#16a34a',
            Failed: '#dc2626',
            Retest: '#ea580c',
            'Not Available': '#6b7280',
            Pending: '#d97706',
            'Not Required': '#9ca3af'
        };

        const renderRow = (label, counts) => {
            const tds = statuses.map(s => `<td class=\"text-center\">${counts[s] || 0}</td>`).join('');
            return `<tr><th scope=\"row\">${label}</th>${tds}</tr>`;
        };

        const table = `
            <table class=\"table table-sm align-middle mb-3\">
                <thead>
                    <tr>
                        <th scope=\"col\">Sheet</th>
                        ${statuses.map(s => `<th scope=\"col\" class=\"text-center\">${s}</th>`).join('')}
                    </tr>
                </thead>
                <tbody>
                    ${renderRow('Total', total.counts)}
                    ${sheetRows.map(r => renderRow(r.name, r.counts)).join('')}
                </tbody>
            </table>
        `;

        const labels = statuses;
        const totalData = labels.map(l => total.counts[l] || 0);
        const datasets = [
            { label: 'Total', data: totalData, backgroundColor: labels.map(l => colors[l] || '#9ca3af') }
        ];

        // per-sheet stacked
        const perSheetDatasets = labels.map((label, idx) => ({
            label,
            data: sheetRows.map(r => r.counts[label] || 0),
            backgroundColor: colors[label] || '#9ca3af'
        }));

        container.innerHTML = `
            <div class=\"row g-3\">
                <div class=\"col-md-6\">
                    <div class=\"card h-100\">
                        <div class=\"card-body\">
                            <h6 class=\"card-title\">Summary (All Sheets)</h6>
                            <canvas id=\"adhocPie\"></canvas>
                        </div>
                    </div>
                </div>
                <div class=\"col-md-6\">
                    <div class=\"card h-100\">
                        <div class=\"card-body\">
                            <h6 class=\"card-title\">Per Sheet (Stacked)</h6>
                            <canvas id=\"adhocBar\"></canvas>
                        </div>
                    </div>
                </div>
            </div>
            <div class=\"mt-3\">${table}</div>
        `;

        const pieCtx = document.getElementById('adhocPie');
        const barCtx = document.getElementById('adhocBar');
        if (!pieCtx || !barCtx) return;

        new Chart(pieCtx, {
            type: 'pie',
            data: {
                labels,
                datasets: [{ data: totalData, backgroundColor: labels.map(l => colors[l] || '#9ca3af') }]
            },
            options: {
                plugins: { legend: { position: 'bottom' } }
            }
        });

        new Chart(barCtx, {
            type: 'bar',
            data: {
                labels: sheetRows.map(r => r.name),
                datasets: perSheetDatasets
            },
            options: {
                responsive: true,
                scales: { x: { stacked: true }, y: { stacked: true, beginAtZero: true } },
                plugins: { legend: { position: 'bottom' } }
            }
        });
    }

    // 簡單跳脫 HTML，避免報表輸出 XSS
    function escapeHtml(str) {
        return String(str || '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/\"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    async function exportHtmlReport() {
        try {
            const run = await fetchRunForReport();
            const html = buildReportHtml(run);

            const blob = new Blob([html], { type: 'text/html' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `adhoc-run-${runId}-report.html`;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(url);
        } catch (e) {
            console.error('export html error', e);
            alert('Failed to export HTML report');
        }
    }

    async function fetchRunForReport() {
        const resp = await window.AuthClient.fetch(`/api/adhoc-runs/${runId}`);
        if (!resp.ok) throw new Error('Failed to load data for report');
        return await resp.json();
    }

    function buildReportHtml(run) {
        const statuses = ['Passed','Failed','Retest','Not Available','Pending','Not Required'];
        const normalize = (v) => (v || '').toLowerCase();
        const total = {};
        statuses.forEach(s => total[s] = 0);

        const sheetBlocks = (run.sheets || []).map(sheet => {
            const counts = {};
            statuses.forEach(s => counts[s] = 0);
            (sheet.items || []).forEach(item => {
                const val = normalize(item.test_result || '');
                const match = statuses.find(s => s.toLowerCase() === val);
                if (match) counts[match] += 1;
            });
            statuses.forEach(s => total[s] += counts[s]);

            const rows = (sheet.items || []).map(it => `
                <tr>
                    <td>${escapeHtml(it.test_case_number || '')}</td>
                    <td>${escapeHtml(it.title || '')}</td>
                    <td>${escapeHtml(it.priority || '')}</td>
                    <td>${escapeHtml(it.test_result || '')}</td>
                    <td>${escapeHtml(it.assignee_name || '')}</td>
                    <td>${escapeHtml(it.comments || '')}</td>
                    <td>${escapeHtml(it.bug_list || '')}</td>
                </tr>
            `).join('') || '<tr><td colspan="7" class="text-muted">No items</td></tr>';

            const summaryTds = statuses.map(s => `<td>${counts[s] || 0}</td>`).join('');

            return `
                <h3>${escapeHtml(sheet.name || '')}</h3>
                <table class="summary"><thead><tr><th>Status</th>${statuses.map(s => `<th>${s}</th>`).join('')}</tr></thead><tbody><tr><td>Count</td>${summaryTds}</tr></tbody></table>
                <table class="items">
                    <thead><tr><th>Test Case #</th><th>Title</th><th>Priority</th><th>Result</th><th>Assignee</th><th>Comments</th><th>Bug List</th></tr></thead>
                    <tbody>${rows}</tbody>
                </table>
            `;
        }).join('<hr/>');

        const totalRow = statuses.map(s => `<td>${total[s] || 0}</td>`).join('');
        const now = new Date().toLocaleString();
        const runName = run.name || `Ad-hoc Run ${runId}`;

        return `<!doctype html>
<html><head><meta charset="UTF-8"><title>${escapeHtml(runName)} Report</title>
<style>
body { font-family: Arial, sans-serif; margin: 20px; color: #111827; }
table { border-collapse: collapse; width: 100%; margin: 12px 0; }
th, td { border: 1px solid #e5e7eb; padding: 6px 8px; font-size: 13px; text-align: left; }
th { background: #f3f4f6; }
.summary th, .summary td { text-align: center; }
h1 { margin-bottom: 0; }
.meta { color: #6b7280; margin-bottom: 16px; }
hr { border: none; border-top: 1px solid #e5e7eb; margin: 24px 0; }
</style>
</head><body>
<h1>${escapeHtml(runName)} - HTML Report</h1>
<div class="meta">Generated at ${escapeHtml(now)}</div>
<h3>Total Summary</h3>
<table class="summary"><thead><tr><th>Status</th>${statuses.map(s => `<th>${s}</th>`).join('')}</tr></thead><tbody><tr><td>Count</td>${totalRow}</tr></tbody></table>
${sheetBlocks}
</body></html>`;
    }

    async function openHtmlReportView() {
        try {
            const run = await fetchRunForReport();
            const html = buildReportHtml(run);
            const blob = new Blob([html], { type: 'text/html' });
            const url = URL.createObjectURL(blob);
            window.open(url, '_blank');
            setTimeout(() => URL.revokeObjectURL(url), 30000);
        } catch (e) {
            console.error('open html report error', e);
            alert('Failed to open HTML report');
        }
    }

});
