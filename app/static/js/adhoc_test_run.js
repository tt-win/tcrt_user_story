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

    await loadRun();
    await loadAssignees();

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

            renderTabs();
            const firstSheetId = currentRun?.sheets?.[0]?.id;
            const targetSheet = currentSheetId && currentRun.sheets.find(s => s.id == currentSheetId) ? currentSheetId : firstSheetId;
            if (targetSheet) switchToSheet(targetSheet);
            else if (dom.runName && !dom.runName.textContent) {
                dom.runName.textContent = runName;
                dom.runName.removeAttribute('data-i18n');
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

            const rename = document.createElement('button');
            rename.className = 'btn btn-link btn-sm p-0 ms-1';
            rename.innerHTML = '<i class="fas fa-edit"></i>';
            rename.title = 'Rename sheet';

            const startRename = () => {
                if (tab.dataset.editing === 'true') return;
                tab.dataset.editing = 'true';
                const tabWidth = tab.getBoundingClientRect().width;
                tab.style.width = `${tabWidth}px`;
                tab.style.minWidth = `${tabWidth}px`;
                const input = document.createElement('input');
                input.type = 'text';
                input.className = 'form-control form-control-sm';
                input.value = sheet.name;
                input.style.position = 'absolute';
                input.style.top = '50%';
                input.style.left = '4px';
                input.style.transform = 'translateY(-50%)';
                input.style.height = '24px';
                input.style.padding = '2px 6px';
                input.style.lineHeight = '1.2';
                input.style.maxWidth = `${Math.max(80, tabWidth - 28)}px`;
                input.style.width = `${Math.max(80, tabWidth - 28)}px`;
                name.style.visibility = 'hidden';
                rename.style.visibility = 'hidden';
                tab.appendChild(input);
                input.focus();
                input.select();

                const commit = async () => {
                    tab.dataset.editing = 'false';
                    tab.removeChild(input);
                    tab.style.width = '';
                    tab.style.minWidth = '';
                    name.style.visibility = '';
                    rename.style.visibility = '';
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
                    tab.removeChild(input);
                    tab.style.width = '';
                    tab.style.minWidth = '';
                    name.style.visibility = '';
                    rename.style.visibility = '';
                };
                input.addEventListener('keydown', (e) => {
                    if (e.key === 'Enter') { e.preventDefault(); commit(); }
                    if (e.key === 'Escape') { e.preventDefault(); cancel(); }
                });
                // click outside to commit
                const outsideHandler = (e) => {
                    if (!input.contains(e.target)) {
                        commit();
                    }
                };
                input.addEventListener('blur', commit);
                setTimeout(() => document.addEventListener('mousedown', outsideHandler), 0);
                const cleanup = () => document.removeEventListener('mousedown', outsideHandler);
                const originalCommit = commit;
                commit = async () => {
                    cleanup();
                    await originalCommit();
                };
                const originalCancel = cancel;
                cancel = () => {
                    cleanup();
                    originalCancel();
                };
            };

            tab.addEventListener('click', () => {
                if (tab.dataset.editing === 'true') return;
                switchToSheet(sheet.id);
            });
            name.addEventListener('dblclick', (e) => { e.stopPropagation(); startRename(); });
            rename.addEventListener('click', (e) => { e.stopPropagation(); startRename(); });

            tab.appendChild(name);
            tab.appendChild(rename);
            dom.sheetTabs.appendChild(tab);
        });
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
        return {
            id: item?.id || null,
            test_case_number: item?.test_case_number || '',
            title: item?.title || '',
            priority: item?.priority || 'Medium',
            precondition: item?.precondition || '',
            steps: item?.steps || '',
            expected_result: item?.expected_result || '',
            test_result: item?.test_result || '',
            assignee_name: item?.assignee_name || '',
            comments: item?.comments || '',
            bug_list: item?.bug_list || ''
        };
    }

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
            afterInit: fixAriaHidden,
            afterBeginEditing: fixAriaHidden,
            afterChange: (changes, source) => {
                if (source === 'loadData' || source === 'autosave') return;
                handleChange();
            },
            afterPaste: handleChange,
        });
    }

    function onAddRow() {
        if (!hot) return;
        const data = hot.getSourceData();
        data.push(convertItemToRow(null));
        hot.loadData(data);
        hot.selectCell(data.length - 1, 0);
        handleChange();
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

    function handleChange() {
        if (!dom.saveStatus) return;
        dom.saveStatus.textContent = tt('adhoc.unsaved','Unsaved changes...');
        dom.saveStatus.className = 'text-warning small';
        clearTimeout(autoSaveTimer);
        autoSaveTimer = setTimeout(saveChanges, 800);
    }

    async function saveChanges() {
        if (!hot || !currentSheetId) return;
        const data = hot.getSourceData();
        const payload = data
            .map((row, idx) => ({
                id: row.id ? Number(row.id) : null,
                row_index: idx,
                test_case_number: (row.test_case_number || '').trim(),
                title: (row.title || '').trim(),
                priority: row.priority,
                precondition: (row.precondition || '').trim(),
                steps: (row.steps || '').trim(),
                expected_result: (row.expected_result || '').trim(),
                test_result: row.test_result || null,
                assignee_name: (row.assignee_name || '').trim(),
                comments: (row.comments || '').trim(),
                bug_list: (row.bug_list || '').trim(),
            }))
            .filter(r => r.id || r.title || r.test_case_number || r.comments || r.bug_list || r.assignee_name);

        if (payload.length === 0) {
            dom.saveStatus.textContent = tt('adhoc.saved','All changes saved');
            dom.saveStatus.className = 'text-muted small';
            return;
        }

        dom.saveStatus.textContent = tt('adhoc.saving','Saving...');
        dom.saveStatus.className = 'text-info small';

        try {
            const resp = await window.AuthClient.fetch(`/api/adhoc-runs/${runId}/sheets/${currentSheetId}/items/batch`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            if (!resp.ok) throw new Error(tt('adhoc.saveFailed','Failed to save'));
            const result = await resp.json().catch(() => ({}));
            if (result?.items?.length) {
                const source = hot.getSourceData();
                result.items.forEach(({ id, row_index }) => {
                    const idx = Number(row_index);
                    const newId = Number(id);
                    if (Number.isInteger(idx) && idx >= 0 && idx < source.length && Number.isInteger(newId) && newId > 0) {
                        source[idx].id = newId;
                    }
                });
                hot.loadData(source);
            }
            dom.saveStatus.textContent = tt('adhoc.saved','All changes saved');
            dom.saveStatus.className = 'text-muted small';
        } catch (e) {
            console.error(e);
            dom.saveStatus.textContent = tt('adhoc.saveFailed','Error saving!');
            dom.saveStatus.className = 'text-danger small';
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
        Handsontable.renderers.TextRenderer.apply(this, arguments);
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
        Handsontable.renderers.TextRenderer.apply(this, arguments);
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
