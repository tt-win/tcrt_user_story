function adhocT(key, fallback) { try { if (window.i18n && window.i18n.isReady && window.i18n.isReady()) { const v = window.i18n.t(key); if (v && v !== key) return v; } } catch(_) {} return fallback; }

function adhocT(key, fallback) {
    try {
        if (window.i18n && window.i18n.isReady && window.i18n.isReady()) {
            const v = window.i18n.t(key);
            if (v && v !== key) return v;
        }
    } catch (_) {}
    return fallback;
}

let currentAdHocTpTickets = [];

function renderAdHocTpTickets() {
    const container = document.getElementById('adHocTpTicketTags');
    const display = document.getElementById('adHocTpTicketsDisplay');
    if (!container || !display) return;

    container.innerHTML = '';
    if (currentAdHocTpTickets.length > 0) {
        display.style.display = 'block';
        currentAdHocTpTickets.forEach(ticket => {
            const tag = document.createElement('span');
            tag.className = 'tp-ticket-tag';
            tag.innerHTML = `${escapeHtml(ticket)} <button type="button" class="remove-btn" onclick="removeAdHocTpTicket('${escapeHtml(ticket)}')"><i class="fas fa-times"></i></button>`;
            container.appendChild(tag);
        });
    } else {
        display.style.display = 'none';
    }
}

window.removeAdHocTpTicket = function(ticket) {
    currentAdHocTpTickets = currentAdHocTpTickets.filter(t => t !== ticket);
    renderAdHocTpTickets();
};

function openAdHocRunModal(run) {
    const el = document.getElementById('adHocRunFormModal');
    const modal = bootstrap.Modal.getOrCreateInstance(el);
    const form = document.getElementById('adHocRunForm');
    form.reset();
    currentAdHocEditingId = run?.id || null;
    
    document.getElementById('adHocName').value = run?.name || '';
    document.getElementById('adHocDescription').value = run?.description || '';
    document.getElementById('adHocTestEnvironment').value = run?.test_environment || '';
    document.getElementById('adHocBuildNumber').value = run?.build_number || '';
    
    // Handle TP Tickets
    currentAdHocTpTickets = [];
    if (run?.related_tp_tickets_json) {
        try {
            const parsed = JSON.parse(run.related_tp_tickets_json);
            if (Array.isArray(parsed)) currentAdHocTpTickets = parsed;
        } catch (e) {
            console.error('Error parsing related_tp_tickets_json', e);
        }
    } else if (run?.jira_ticket) {
        // Legacy support
        currentAdHocTpTickets = [run.jira_ticket];
    }
    renderAdHocTpTickets();

    const tpInput = document.getElementById('adHocRelatedTpTicketsInput');
    if (tpInput) {
        // Remove old listener to avoid duplicates if any (cloning is a simple way)
        const newTpInput = tpInput.cloneNode(true);
        tpInput.parentNode.replaceChild(newTpInput, tpInput);
        
        newTpInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                const val = newTpInput.value.trim();
                if (val && !currentAdHocTpTickets.includes(val)) {
                    currentAdHocTpTickets.push(val);
                    renderAdHocTpTickets();
                    newTpInput.value = '';
                }
            }
        });
    }

    const titleEl = document.getElementById('adHocRunFormTitle');
    if (titleEl) titleEl.textContent = run ? adhocT('adhoc.edit','Edit Ad-hoc Run') : adhocT('adhoc.create','Create Ad-hoc Run');
    const saveBtn = document.getElementById('saveAdHocRunBtn');
    if (saveBtn) saveBtn.textContent = run ? (window.i18n ? window.i18n.t('common.save') : 'Save') : (window.i18n ? window.i18n.t('common.create') : 'Create');
    modal.show();
}

document.getElementById('saveAdHocRunBtn')?.addEventListener('click', async () => {
    const name = document.getElementById('adHocName').value;
    const desc = document.getElementById('adHocDescription').value;
    const env = document.getElementById('adHocTestEnvironment').value;
    const build = document.getElementById('adHocBuildNumber').value;
    
    if (!name) return alert(adhocT('common.nameRequired','Name is required'));
    
    const btn = document.getElementById('saveAdHocRunBtn');
    btn.disabled = true;
    
    try {
        const isEdit = !!currentAdHocEditingId;
        const payload = {
            name,
            description: desc,
            test_environment: env || null,
            build_number: build || null,
            related_tp_tickets_json: JSON.stringify(currentAdHocTpTickets),
            // Sync jira_ticket for backward compatibility if single
            jira_ticket: currentAdHocTpTickets.length > 0 ? currentAdHocTpTickets[0] : null
        };
        if (!isEdit) {
            payload.team_id = currentTeamId;
        }
        const url = isEdit ? `/api/adhoc-runs/${currentAdHocEditingId}` : '/api/adhoc-runs/';
        const method = isEdit ? "PUT" : "POST";

        const response = await window.AuthClient.fetch(url, {
            method,
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        
        if (response.ok) {
            const el = document.getElementById('adHocRunFormModal');
            const modal = bootstrap.Modal.getOrCreateInstance(el);
            modal.hide();
            loadTestRunConfigs(); // Reloads everything including adhoc
        } else {
            alert(adhocT('common.saveFailed','Failed to save'));
        }
    } catch (e) {
        console.error(e);
        alert(adhocT('adhoc.errorSave','Error saving Ad-hoc Run'));
    } finally {
        btn.disabled = false;
    }
});

function renderAdHocRuns(runs) {
    window.lastAdHocRuns = runs;
    const container = document.getElementById('adhoc-runs-container');
    const section = document.getElementById('adhoc-runs-section');
    
    // Always show section for the Add card
    section.style.display = 'block';
    
    let cardsHtml = '';
    
    if (runs && runs.length > 0) {
        cardsHtml += runs.map(run => {
            const runJson = escapeHtml(JSON.stringify({ 
                id: run.id, 
                name: run.name, 
                description: run.description, 
                jira_ticket: run.jira_ticket, 
                test_environment: run.test_environment,
                build_number: run.build_number,
                related_tp_tickets_json: run.related_tp_tickets_json,
                created_at: run.created_at, 
                updated_at: run.updated_at, 
                status: run.status 
            }));
            const sheetsHtml = (run.sheets && run.sheets.length > 0) ? 
                run.sheets.slice(0, 3).map(s => `
                    <div class="d-flex align-items-center py-1 border-bottom border-light small">
                        <i class="fas fa-file-alt text-muted me-2"></i>
                        <span class="text-truncate">${escapeHtml(s.name)}</span>
                    </div>
                `).join('') + (run.sheets.length > 3 ? `<div class="text-muted small pt-1">+${run.sheets.length - 3} more</div>` : '')
                : '<div class="text-muted small text-center py-2">No sheets</div>';

            const tpTickets = [];
            if (run.related_tp_tickets_json) {
                try {
                    const parsed = JSON.parse(run.related_tp_tickets_json);
                    if (Array.isArray(parsed)) tpTickets.push(...parsed);
                } catch (e) {}
            } else if (run.jira_ticket) {
                tpTickets.push(run.jira_ticket);
            }

            const tpTags = tpTickets.slice(0, 3).map(t => `<span class="tcg-tag" style="cursor: default; font-size: 0.75rem;">${escapeHtml(t)}</span>`).join('');
            const tpMore = tpTickets.length > 3 ? `<span class="text-muted small ms-1">+${tpTickets.length - 3}</span>` : '';
            const tpDisplay = tpTickets.length > 0 ? `${tpTags}${tpMore}` : '<span class="text-muted">N/A</span>';

            const created = run.created_at ? AppUtils.formatDate(run.created_at) : 'N/A';
            
            // Dynamic ${getStatusText ? getStatusText(status) : status}
            const status = run.status || 'draft';
            const statusClass = window.getStatusClass ? window.getStatusClass(status) : `status-${status}`;
            const statusText = window.getStatusText ? window.getStatusText(status) : status;
            
            // Locking Logic
            const locked = (status === 'completed' || status === 'archived');
            const canRerun = (status === 'completed');
            const canEnter = (status !== "archived");

            // Action Buttons Logic
            const enterBtn = canEnter ? `
                <button class="btn btn-primary btn-sm flex-grow-1" onclick="event.stopPropagation(); window.location.href='/adhoc-runs/${run.id}/execution'">
                    <i class="fas fa-arrow-right me-1"></i><span>${adhocT('adhoc.enter','Enter')}</span>
                </button>` : '';
                
            const editBtn = `
                <button class="btn btn-secondary btn-sm flex-grow-1 adhoc-edit-btn" data-adhoc-json="${runJson}" onclick="event.stopPropagation();" ${locked ? 'disabled' : ''}>
                    <i class="fas fa-edit me-1"></i><span>${adhocT('adhoc.basicSettings','Basic Settings')}</span>
                </button>`;
            
            const rerunBtn = canRerun ? `
                <button class="btn btn-info btn-sm flex-grow-1" onclick="event.stopPropagation(); rerunAdHocRun(${run.id})">
                    <i class="fas fa-redo me-1"></i><span>${adhocT('adhoc.rerun', 'Re-run')}</span>
                </button>` : '';

            // Stats Items
            const envLine = run.test_environment ? `
                <div class="stats-item justify-content-between gap-2">
                    <div class="d-flex align-items-center gap-2 flex-grow-1">
                        <i class="fas fa-server stats-icon"></i>
                        <small class="text-muted">Environment</small>
                    </div>
                    <small class="text-muted">${escapeHtml(run.test_environment)}</small>
                </div>` : '';

            const tpLine = `
                <div class="stats-item justify-content-between gap-2">
                    <div class="d-flex align-items-center gap-2 flex-grow-1">
                        <i class="fas fa-tags stats-icon"></i>
                        <small class="text-muted">${adhocT("adhoc.relatedTickets","Related Tickets")}</small>
                    </div>
                    <div class="d-flex flex-wrap gap-1 justify-content-end">
                        ${tpDisplay}
                    </div>
                </div>`;

            const buildLine = run.build_number ? `
                <div class="stats-item justify-content-between gap-2">
                    <div class="d-flex align-items-center gap-2 flex-grow-1">
                        <i class="fas fa-code-branch stats-icon"></i>
                        <small class="text-muted">Build</small>
                    </div>
                    <small class="text-muted">${escapeHtml(run.build_number)}</small>
                </div>` : '';

            const adhocCounts = { total: 0, executed: 0 };
            (run.sheets || []).forEach(s => {
                (s.items || []).forEach(it => {
                    const tcNum = String(it.test_case_number || '').toUpperCase();
                    if (tcNum === 'SECTION') return;
                    adhocCounts.total += 1;
                    const res = (it.test_result || '').toLowerCase();
                    if (res && res !== 'pending') adhocCounts.executed += 1;
                });
            });
            const totalText = adhocT('adhoc.totalLabel','Total: {total} | Executed: {executed}')
                .replace('{total}', String(adhocCounts.total))
                .replace('{executed}', String(adhocCounts.executed));
            const totalLine = `
                <div class="stats-item justify-content-between gap-2">
                    <div class="d-flex align-items-center gap-2 flex-grow-1">
                        <i class="fas fa-list-ul stats-icon"></i>
                        <small class="text-muted">${adhocT("adhoc.totalTitle","Total / Executed")}</small>
                    </div>
                    <small class="text-muted">${totalText}</small>
                </div>`;

            const createdLine = `
                <div class="stats-item justify-content-between gap-2">
                    <div class="d-flex align-items-center gap-2 flex-grow-1">
                        <i class="fas fa-calendar stats-icon"></i>
                        <small class="text-muted">Created</small>
                    </div>
                    <small class="text-muted">${created}</small>
                </div>`;

            return `
            <div class="col-xl-4 col-lg-6 mb-4">
                <div class="card h-100 test-run-card ${statusClass}" onclick="${canEnter ? `window.location.href='/adhoc-runs/${run.id}/execution'` : ''}">
                    <div class="card-body d-flex flex-column h-100">
                        <div class="d-none search-text">${escapeHtml(run.name || '')} ${escapeHtml(run.description || '')} ${escapeHtml(run.jira_ticket || '')}</div>
                        <div class="d-flex justify-content-between align-items-start mb-3 gap-2">
                            <div class="d-flex align-items-center overflow-hidden flex-grow-1">
                                <div class="flex-shrink-0 me-3">
                                    <div class="bg-info text-white rounded-circle d-flex align-items-center justify-content-center" 
                                         style="width: 48px; height: 48px; font-size: 20px;">
                                        <i class="fas fa-table"></i>
                                    </div>
                                </div>
                                <div class="min-width-0">
                                    <h5 class="card-title text-primary mb-1 text-truncate">${escapeHtml(run.name)}</h5>
                                </div>
                            </div>
                            <div class="flex-shrink-0">
                                <span class="status-badge ${statusClass}">${statusText}</span>
                            </div>
                        </div>
                        
                        <div class="small text-muted mb-2 line-clamp-2">${escapeHtml(run.description || '')}</div>
                        
                        <div class="mb-3">
                            ${envLine}
                            ${tpLine}
                            ${buildLine}
                            ${totalLine}
                            ${createdLine}
                        </div>

                        <div class="border rounded p-2 bg-light flex-grow-1 mb-3">
                            ${sheetsHtml}
                        </div>
                        <div class="d-flex justify-content-between align-items-center mt-auto pt-2 border-top">
                            <div class="d-flex w-100 gap-2 flex-wrap">
                                ${enterBtn}
                                ${editBtn}
                                ${rerunBtn}
                                <div class="position-relative flex-grow-1" style="min-width: 80px;" onclick="event.stopPropagation()">
                                    <button type="button" class="btn btn-warning btn-sm w-100" 
                                            onclick="event.stopPropagation(); toggleAdHocStatusDropdown(this, ${run.id}, '${status}')">
                                        <i class="fas fa-exchange-alt me-1"></i><span>${adhocT('common.status', 'Status')}</span>
                                        <i class="fas fa-chevron-down ms-1"></i>
                                    </button>
                                </div>
                                <button class="btn btn-danger btn-sm flex-grow-1" onclick="event.stopPropagation(); deleteAdHocRun(${run.id})">
                                    <i class="fas fa-trash me-1"></i><span>${adhocT('adhoc.deleteLabel','Delete')}</span>
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
            `;
        }).join('');
    }
    
    // Add "Create Ad-hoc Run" Card
    cardsHtml += `
        <div class="col-xl-4 col-lg-6 mb-4">
            <div class="card h-100 add-test-run-card" data-card-type="adhoc" onclick="openAdHocRunModal()">
                <div class="card-body py-5 d-flex flex-column align-items-center justify-content-center text-center">
                    <div class="text-primary rounded-circle d-flex align-items-center justify-content-center mb-3" 
                         style="width: 48px; height: 48px; font-size: 18px; border: 2px dashed var(--tr-primary);">
                        <i class="fas fa-plus"></i>
                    </div>
                    <h6 class="text-primary mb-1">${adhocT('adhoc.title','Ad-hoc Runs')}</h6>
                    <p class="text-muted small mb-0">${adhocT('adhoc.desc','Quick test runs without predefined test cases')}</p>
                </div>
            </div>
        </div>
    `;
    
    container.innerHTML = cardsHtml;
    container.querySelectorAll('.adhoc-edit-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const data = btn.getAttribute('data-adhoc-json') || '{}';
            try {
                const run = JSON.parse(data.replace(/&quot;/g, '"'));
                openAdHocRunModal(run);
            } catch (err) {
                console.error('Failed to parse adhoc json', err);
            }
        });
    });
}

function showAdHocConfirmModal({ title, message, confirmText, confirmClass, type = 'danger', onConfirm }) {
    let modalEl = document.getElementById('adhocConfirmModal');
    
    // Determine styles based on type
    let headerClass = 'bg-light';
    let closeBtnClass = '';
    let iconClass = 'text-secondary';
    let iconName = 'fa-question-circle';
    let alertClass = 'alert-secondary';

    if (type === 'danger') {
        headerClass = 'bg-danger text-white';
        closeBtnClass = 'btn-close-white';
        iconClass = ''; // Icon inherits text-white
        iconName = 'fa-exclamation-triangle';
        alertClass = 'alert-danger';
    } else if (type === 'info') {
        headerClass = 'bg-info text-white';
        closeBtnClass = 'btn-close-white';
        iconClass = '';
        iconName = 'fa-info-circle';
        alertClass = 'alert-info';
    } else if (type === 'primary') {
        headerClass = 'bg-primary text-white';
        closeBtnClass = 'btn-close-white';
        iconClass = '';
        iconName = 'fa-redo'; // Use redo icon for primary/rerun
        alertClass = 'alert-primary';
    }

    if (!modalEl) {
        const div = document.createElement('div');
        div.innerHTML = `
        <div class="modal fade" id="adhocConfirmModal" tabindex="-1" style="z-index: 1060;">
            <div class="modal-dialog modal-dialog-centered">
                <div class="modal-content border-${type === 'danger' ? 'danger' : (type === 'info' ? 'info' : 'secondary')}">
                    <div class="modal-header ${headerClass}">
                        <h5 class="modal-title d-flex align-items-center">
                            <i class="fas ${iconName} me-2 ${iconClass}"></i>
                            <span id="adhocConfirmTitle"></span>
                        </h5>
                        <button type="button" class="btn-close ${closeBtnClass}" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        <div class="alert ${alertClass} mb-0 d-flex align-items-center">
                            <i class="fas fa-exclamation-circle me-2"></i>
                            <span id="adhocConfirmMessage"></span>
                        </div>
                    </div>
                    <div class="modal-footer">
                        <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button>
                        <button type="button" class="btn" id="adhocConfirmBtn"></button>
                    </div>
                </div>
            </div>
        </div>`;
        document.body.appendChild(div.firstElementChild);
        modalEl = document.getElementById('adhocConfirmModal');
    } else {
        // Update existing modal structure/classes if reused
        const content = modalEl.querySelector('.modal-content');
        content.className = `modal-content border-${type === 'danger' ? 'danger' : (type === 'info' ? 'info' : 'secondary')}`;
        
        const header = modalEl.querySelector('.modal-header');
        header.className = `modal-header ${headerClass}`;
        
        const icon = header.querySelector('i');
        icon.className = `fas ${iconName} me-2 ${iconClass}`;
        
        const closeBtn = header.querySelector('.btn-close');
        closeBtn.className = `btn-close ${closeBtnClass}`;

        const alertBox = modalEl.querySelector('.alert');
        alertBox.className = `alert ${alertClass} mb-0 d-flex align-items-center`;
    }
    
    document.getElementById('adhocConfirmTitle').textContent = title;
    document.getElementById('adhocConfirmMessage').textContent = message;
    
    const btn = document.getElementById('adhocConfirmBtn');
    btn.textContent = confirmText;
    btn.className = `btn ${confirmClass}`;
    
    // Remove old listeners by cloning
    const newBtn = btn.cloneNode(true);
    btn.parentNode.replaceChild(newBtn, btn);
    
    newBtn.onclick = () => {
        onConfirm();
        const modalInstance = bootstrap.Modal.getInstance(modalEl);
        if (modalInstance) modalInstance.hide();
    };
    
    const modal = new bootstrap.Modal(modalEl);
    modal.show();
}

function deleteAdHocRun(id) {
    showAdHocConfirmModal({
        title: adhocT('common.confirm', 'Confirm'),
        message: adhocT('adhoc.deleteConfirm', 'Delete this Ad-hoc run?'),
        confirmText: adhocT('common.delete', 'Delete'),
        confirmClass: 'btn-danger',
        type: 'danger',
        onConfirm: async () => {
            try {
                await window.AuthClient.fetch(`/api/adhoc-runs/${id}`, { method: 'DELETE' });
                loadTestRunConfigs();
            } catch (e) {
                alert(adhocT('common.deleteFailed','Failed to delete'));
            }
        }
    });
}

// ... updateAdHocStatus ...

function rerunAdHocRun(id) {
    showAdHocConfirmModal({
        title: adhocT('common.confirm', 'Confirm'),
        message: adhocT('adhoc.rerunConfirm', 'Re-run this Ad-hoc run? This will create a new active copy.'),
        confirmText: adhocT('adhoc.rerun', 'Re-run'),
        confirmClass: 'btn-info',
        type: 'info',
        onConfirm: async () => {
            try {
                const resp = await window.AuthClient.fetch(`/api/adhoc-runs/${id}/rerun`, { method: 'POST' });
                if (resp.ok) {
                    loadTestRunConfigs();
                } else {
                    alert(adhocT('adhoc.rerunFailed','Failed to re-run'));
                }
            } catch (e) {
                console.error(e);
                alert(adhocT('adhoc.rerunFailed','Failed to re-run'));
            }
        }
    });
}

function toggleAdHocStatusDropdown(btn, id, currentStatus) {
    const dropdown = document.getElementById('customStatusDropdown');
    const overlay = document.getElementById('statusDropdownOverlay');
    if (!dropdown || !overlay) return;

    // Define options (Active is starting state, cannot return to it)
    const allOptions = [
        { value: 'completed', label: 'Completed', icon: 'fa-check', color: 'text-success' },
        { value: 'archived', label: 'Archived', icon: 'fa-archive', color: 'text-secondary' }
    ];

    // Status Transition Logic
    const status = (currentStatus || 'active').toLowerCase();
    let allowed = [];

    switch (status) {
        case 'active':
            allowed = ['completed', 'archived'];
            break;
        case 'completed':
            allowed = ['archived'];
            break;
        case 'archived':
            allowed = [];
            break;
        default:
            // Fallback for unknown states
            allowed = ['completed', 'archived'];
    }

    // Filter options
    const options = allOptions.filter(opt => allowed.includes(opt.value));

    if (options.length === 0) {
        // If no transitions allowed, maybe show a message or just don't show dropdown?
        // Better to give feedback.
        dropdown.innerHTML = '<div class="p-2 text-muted small text-center">No actions available</div>';
    } else {
        // Build HTML
        dropdown.innerHTML = options.map(opt => `
            <button class="custom-status-dropdown-item" onclick="updateAdHocStatus(${id}, '${opt.value}'); hideCustomStatusDropdown()">
                <i class="fas ${opt.icon} ${opt.color} me-2"></i>
                ${opt.label}
            </button>
        `).join('');
    }

    // Position logic (simple version, can be enhanced with Popper.js if available)
    const rect = btn.getBoundingClientRect();
    dropdown.style.top = `${rect.bottom + window.scrollY + 5}px`;
    dropdown.style.left = `${rect.left + window.scrollX}px`;
    // dropdown.style.display = 'block'; // Removed to rely on class
    dropdown.classList.add('show');
    overlay.classList.add('show');
}

// Global hide helper
window.hideCustomStatusDropdown = function() {
    const d = document.getElementById('customStatusDropdown');
    const o = document.getElementById('statusDropdownOverlay');
    if(d) {
        d.classList.remove('show');
        d.style.display = ''; // Clear inline style if any
    }
    if(o) o.classList.remove('show');
};

// Expose globals for inline handlers
window.renderAdHocRuns = renderAdHocRuns;
window.openAdHocRunModal = openAdHocRunModal;
window.deleteAdHocRun = deleteAdHocRun;
window.toggleAdHocStatusDropdown = toggleAdHocStatusDropdown;
window.updateAdHocStatus = updateAdHocStatus;
window.rerunAdHocRun = rerunAdHocRun;
