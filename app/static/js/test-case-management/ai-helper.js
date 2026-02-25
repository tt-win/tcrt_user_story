/* ============================================================
   TEST CASE MANAGEMENT - AI TEST CASE HELPER WIZARD
   ============================================================ */

(function () {
    const helperState = {
        initialized: false,
        autoOpenConsumed: false,
        teamId: null,
        modalInstance: null,
        sessionId: null,
        session: null,
        currentStep: 1,
        analyzeRuns: 0,
        generateRuns: 0,
        pretestcasePayload: null,
        pretestcaseOriginalPayload: null,
        selectedPreSection: '',
        selectedPreCid: '',
        finalTestcases: [],
        selectedFinalSection: '',
        selectedFinalCaseIndex: -1,
        targetSetId: null,
        lastErrorNotified: null,
        confirmModalInstance: null,
    };

    const STEP_COUNT = 3;
    const PHASE_BADGE_IDS = {
        analysis: 'helperPhaseAnalysis',
        pretestcase: 'helperPhasePretestcase',
        testcase: 'helperPhaseTestcase',
        commit: 'helperPhaseCommit',
    };

    function helperT(key, params, fallback) {
        if (window.i18n && window.i18n.isReady && window.i18n.isReady()) {
            return window.i18n.t(key, params || {}, fallback || key);
        }
        return fallback || key;
    }

    function el(id) {
        return document.getElementById(id);
    }

    function helperEscapeHtml(text) {
        return String(text || '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function helperDeepClone(value) {
        if (value === null || value === undefined) {
            return value;
        }
        return JSON.parse(JSON.stringify(value));
    }

    function helperNormalizeLocale(rawLocale) {
        const normalized = String(rawLocale || '').trim().toLowerCase();
        if (!normalized) return 'zh-TW';
        if (normalized.startsWith('zh-tw') || normalized.includes('hant') || normalized.startsWith('zh-hk')) {
            return 'zh-TW';
        }
        if (normalized.startsWith('zh-cn') || normalized.includes('hans') || normalized.startsWith('zh-sg')) {
            return 'zh-CN';
        }
        if (normalized.startsWith('en')) {
            return 'en';
        }
        if (normalized.startsWith('zh')) {
            return 'zh-TW';
        }
        return 'zh-TW';
    }

    function helperCurrentUiLocale() {
        if (window.i18n && window.i18n.currentLanguage) {
            return helperNormalizeLocale(window.i18n.currentLanguage);
        }
        return helperNormalizeLocale(navigator.language || 'zh-TW');
    }

    function helperGetCurrentSetId() {
        if (typeof currentSetId !== 'undefined' && currentSetId) {
            return currentSetId;
        }
        if (typeof window.currentSetId !== 'undefined' && window.currentSetId) {
            return window.currentSetId;
        }
        return null;
    }

    function helperNormalizeEscapedMarkdownForRender(content) {
        let normalized = String(content || '');
        normalized = normalized.replace(/\\\*\\\*([^\n]+?)\\\*\\\*/g, '**$1**');
        normalized = normalized.replace(/\\\*([^\n*]+?)\\\*/g, '*$1*');
        normalized = normalized.replace(/\\__([^\n]+?)\\__/g, '__$1__');
        normalized = normalized.replace(/\\_([^\n_]+?)\\_/g, '_$1_');
        return normalized;
    }

    function helperRenderMarkdown(content, targetElement) {
        if (!targetElement) return;
        const rawContent = helperNormalizeEscapedMarkdownForRender(content);

        if (typeof renderMarkdownToElement === 'function') {
            renderMarkdownToElement(rawContent, targetElement);
            return;
        }

        const markedParser = (() => {
            if (typeof marked === 'undefined') return null;
            if (typeof marked.parse === 'function') return marked.parse.bind(marked);
            if (typeof marked === 'function') return marked;
            return null;
        })();

        if (markedParser) {
            try {
                targetElement.innerHTML = markedParser(rawContent);
                return;
            } catch (_) {
                // Ignore parse error and fallback to plain text
            }
        }

        targetElement.innerHTML = helperFallbackMarkdown(rawContent);
    }

    function helperFallbackMarkdown(content) {
        const source = String(content || '').replace(/\r\n/g, '\n');
        if (!source.trim()) {
            const placeholder = helperT('messages.previewDisplayHere', {}, '預覽將在此顯示...');
            return `<p class="text-muted">${helperEscapeHtml(placeholder)}</p>`;
        }

        const escaped = helperEscapeHtml(source);
        let html = escaped
            .replace(/^### (.+)$/gim, '<h3>$1</h3>')
            .replace(/^## (.+)$/gim, '<h2>$1</h2>')
            .replace(/^# (.+)$/gim, '<h1>$1</h1>')
            .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
            .replace(/\*(.+?)\*/g, '<em>$1</em>')
            .replace(/`([^`\n]+)`/g, '<code>$1</code>')
            .replace(
                /\[([^\]]+)\]\(([^)\s]+)\)/g,
                '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>',
            )
            .replace(/\n/g, '<br>');
        return html;
    }

    function helperSessionStorageKey(teamId) {
        return `tc_helper_last_session_${teamId}`;
    }

    function helperSaveSessionId(teamId, sessionId) {
        if (!teamId || !sessionId) return;
        try {
            localStorage.setItem(helperSessionStorageKey(teamId), String(sessionId));
        } catch (_) {}
    }

    function helperLoadStoredSessionId(teamId) {
        if (!teamId) return null;
        try {
            const raw = localStorage.getItem(helperSessionStorageKey(teamId));
            if (!raw) return null;
            const parsed = parseInt(raw, 10);
            if (Number.isNaN(parsed) || parsed <= 0) return null;
            return parsed;
        } catch (_) {
            return null;
        }
    }

    function helperClearStoredSessionId(teamId) {
        if (!teamId) return;
        try {
            localStorage.removeItem(helperSessionStorageKey(teamId));
        } catch (_) {}
    }

    function helperGetFetchImpl() {
        if (window.AuthClient && typeof window.AuthClient.fetch === 'function') {
            return window.AuthClient.fetch.bind(window.AuthClient);
        }
        return window.fetch.bind(window);
    }

    async function helperApiFetch(url, options = {}) {
        const fetchImpl = helperGetFetchImpl();
        const requestOptions = { method: 'GET', ...options };

        if (requestOptions.body && !requestOptions.headers) {
            requestOptions.headers = { 'Content-Type': 'application/json' };
        }

        const response = await fetchImpl(url, requestOptions);
        let payload = null;
        try {
            payload = await response.json();
        } catch (_) {
            payload = null;
        }

        if (!response.ok) {
            const detail = payload && typeof payload === 'object'
                ? (payload.detail || payload.message || JSON.stringify(payload))
                : `HTTP ${response.status}`;
            throw new Error(detail || `HTTP ${response.status}`);
        }

        return payload;
    }

    function helperLoadTeamFromLocalStorage() {
        try {
            const raw = localStorage.getItem('currentTeam');
            if (!raw) return null;
            const parsed = JSON.parse(raw);
            if (!parsed || !parsed.id) return null;
            return parsed;
        } catch (_) {
            return null;
        }
    }

    async function helperResolveTeam(preferredTeamId) {
        const preferredId = Number(preferredTeamId || 0);
        if (!Number.isNaN(preferredId) && preferredId > 0) {
            const fromStorage = helperLoadTeamFromLocalStorage();
            if (fromStorage && Number(fromStorage.id) === preferredId) {
                return fromStorage;
            }
            return { id: preferredId };
        }

        let currentTeam = null;

        try {
            currentTeam = window.AppUtils && AppUtils.getCurrentTeam
                ? AppUtils.getCurrentTeam()
                : null;
        } catch (_) {
            currentTeam = null;
        }

        if (!currentTeam || !currentTeam.id) {
            currentTeam = helperLoadTeamFromLocalStorage();
        }

        if (!currentTeam || !currentTeam.id) {
            if (typeof ensureTeamContext === 'function') {
                currentTeam = await ensureTeamContext();
            }
        }

        if (!currentTeam || !currentTeam.id) {
            throw new Error(helperT('errors.pleaseSelectTeam', {}, '請先選擇團隊'));
        }

        return currentTeam;
    }

    function helperSetBusy(isBusy, loadingText) {
        const loadingRow = el('helperLoadingRow');
        const loadingLabel = el('helperLoadingText');

        if (loadingRow) {
            loadingRow.classList.toggle('d-none', !isBusy);
        }
        if (loadingLabel && loadingText) {
            loadingLabel.textContent = loadingText;
        }

        const actionIds = [
            'helperNormalizeBtn',
            'helperGenerateBtn',
            'helperCommitBtn',
            'helperPrevBtn',
            'helperNextBtn',
            'helperAddPretestcaseRowBtn',
            'helperRestoreSessionBtn',
            'helperStartOverBtn',
        ];
        actionIds.forEach((id) => {
            const node = el(id);
            if (node) node.disabled = !!isBusy;
        });
    }

    function helperShowToastFallback(message, level) {
        const content = String(message || '').trim();
        if (!content) return;

        if (!(window.bootstrap && bootstrap.Toast)) {
            console.warn('[AI Helper Notice]', content);
            return;
        }

        let container = document.getElementById('helperToastContainer');
        if (!container) {
            container = document.createElement('div');
            container.id = 'helperToastContainer';
            container.className = 'toast-container position-fixed top-0 end-0 p-3';
            container.style.zIndex = '1090';
            document.body.appendChild(container);
        }

        const variantMap = {
            success: 'success',
            error: 'danger',
            warning: 'warning',
            info: 'info',
        };
        const variant = variantMap[String(level || 'info')] || 'info';
        const iconMap = {
            success: 'check-circle',
            error: 'triangle-exclamation',
            warning: 'triangle-exclamation',
            info: 'circle-info',
        };
        const icon = iconMap[String(level || 'info')] || 'circle-info';

        const wrapper = document.createElement('div');
        wrapper.className = `toast align-items-center text-bg-${variant} border-0`;
        wrapper.setAttribute('role', 'alert');
        wrapper.setAttribute('aria-live', 'assertive');
        wrapper.setAttribute('aria-atomic', 'true');
        wrapper.innerHTML = `
            <div class="d-flex">
                <div class="toast-body">
                    <i class="fas fa-${icon} me-2"></i>${helperEscapeHtml(content)}
                </div>
                <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button>
            </div>
        `;

        container.appendChild(wrapper);
        const toast = new bootstrap.Toast(wrapper, {
            autohide: true,
            delay: 5000,
        });
        wrapper.addEventListener('hidden.bs.toast', () => {
            wrapper.remove();
        });
        toast.show();
    }

    function helperNotify(message, level) {
        const content = String(message || '').trim();
        if (!content) return;

        const type = String(level || 'info');
        const methodMap = {
            success: 'showSuccess',
            error: 'showError',
            warning: 'showWarning',
            info: 'showInfo',
        };
        const methodName = methodMap[type] || methodMap.info;

        if (window.AppUtils && typeof AppUtils[methodName] === 'function') {
            AppUtils[methodName](content);
            return;
        }

        helperShowToastFallback(content, type);
    }

    async function helperConfirm(message, options = {}) {
        const modalEl = el('helperConfirmModal');
        const titleEl = el('helperConfirmModalTitle');
        const bodyEl = el('helperConfirmModalMessage');
        const okBtn = el('helperConfirmOkBtn');
        const cancelBtn = el('helperConfirmCancelBtn');

        if (!modalEl || !titleEl || !bodyEl || !okBtn || !cancelBtn || !(window.bootstrap && bootstrap.Modal)) {
            helperNotify(message, 'warning');
            return false;
        }

        titleEl.textContent = options.title || helperT('common.confirm', {}, '確認');
        bodyEl.textContent = String(message || '');
        okBtn.textContent = options.confirmText || helperT('common.confirm', {}, '確認');
        cancelBtn.textContent = options.cancelText || helperT('common.cancel', {}, '取消');
        okBtn.className = options.confirmClass || 'btn btn-primary';

        if (!helperState.confirmModalInstance) {
            helperState.confirmModalInstance = new bootstrap.Modal(modalEl);
        }

        return await new Promise((resolve) => {
            let settled = false;

            const cleanup = () => {
                okBtn.removeEventListener('click', onConfirm);
                cancelBtn.removeEventListener('click', onCancel);
                modalEl.removeEventListener('hidden.bs.modal', onHidden);
            };

            const finish = (value) => {
                if (settled) return;
                settled = true;
                cleanup();
                resolve(value);
            };

            const onConfirm = () => {
                finish(true);
                helperState.confirmModalInstance.hide();
            };

            const onCancel = () => {
                finish(false);
                helperState.confirmModalInstance.hide();
            };

            const onHidden = () => {
                finish(false);
            };

            okBtn.addEventListener('click', onConfirm);
            cancelBtn.addEventListener('click', onCancel);
            modalEl.addEventListener('hidden.bs.modal', onHidden);

            helperState.confirmModalInstance.show();
        });
    }

    function helperSetError(message, options = {}) {
        void options;
        helperNotify(message, 'error');
    }

    function helperSetSuccess(message, options = {}) {
        void options;
        helperNotify(message, 'success');
    }

    function helperClearMessages() {
        // Keep as no-op for compatibility with existing flow calls.
        // Notifications now use global AppUtils and auto-dismiss by system style.
    }

    function helperNotifyWarning(message) {
        helperNotify(message, 'warning');
    }

    function helperToggleSetMode() {
        const createFields = el('helperCreateSetFields');
        const existingSelect = el('helperExistingSetSelect');
        const isCreate = !!(el('helperSetModeCreate') && el('helperSetModeCreate').checked);

        if (createFields) {
            createFields.style.display = isCreate ? '' : 'none';
        }
        if (existingSelect) {
            existingSelect.disabled = isCreate;
        }
    }

    function helperLockSetupFields(locked) {
        const ids = [
            'helperSetModeExisting',
            'helperSetModeCreate',
            'helperExistingSetSelect',
            'helperNewSetName',
            'helperNewSetDescription',
            'helperOutputLocale',
            'helperInitialMiddle',
        ];
        ids.forEach((id) => {
            const node = el(id);
            if (node) node.disabled = !!locked;
        });
    }

    function helperRenderTicketSummary(payload) {
        const container = el('helperTicketSummary');
        if (!container) return;

        if (!payload || !payload.ticket_key) {
            container.innerHTML = `<span class="text-muted">${helperEscapeHtml(helperT('aiHelper.noTicketSummary', {}, '尚未讀取 Ticket'))}</span>`;
            return;
        }

        const components = Array.isArray(payload.components) && payload.components.length > 0
            ? payload.components.join(', ')
            : 'N/A';

        const summary = String(payload.summary || '').trim();
        const description = String(payload.description || '').trim();
        const shortDescription = description.length > 240
            ? `${description.slice(0, 240)}...`
            : description;

        const urlHtml = payload.url
            ? `<a href="${helperEscapeHtml(payload.url)}" target="_blank" rel="noopener">${helperEscapeHtml(payload.ticket_key)}</a>`
            : helperEscapeHtml(payload.ticket_key);

        container.innerHTML = `
            <div><strong>${helperEscapeHtml(helperT('aiHelper.ticketKey', {}, 'TCG 單號'))}:</strong> ${urlHtml}</div>
            <div class="mt-1"><strong>${helperEscapeHtml(helperT('common.title', {}, '標題'))}:</strong> ${helperEscapeHtml(summary || 'N/A')}</div>
            <div class="mt-1"><strong>Components:</strong> ${helperEscapeHtml(components)}</div>
            <div class="mt-1"><strong>${helperEscapeHtml(helperT('common.description', {}, '描述'))}:</strong><br>${helperEscapeHtml(shortDescription || 'N/A')}</div>
        `;
    }

    function helperSyncStepperLayout() {
        const stepper = document.querySelector('#aiTestCaseHelperModal .tc-helper-stepper');
        if (!stepper) return;
        const stepCount = stepper.querySelectorAll('.tc-helper-step').length || STEP_COUNT;
        stepper.style.setProperty('--tc-helper-step-count', String(Math.max(1, stepCount)));
    }

    function helperSetStep(step) {
        helperSyncStepperLayout();
        const normalizedStep = Math.max(1, Math.min(STEP_COUNT, Number(step) || 1));
        helperState.currentStep = normalizedStep;

        document.querySelectorAll('.tc-helper-step').forEach((item) => {
            const itemStep = parseInt(item.getAttribute('data-helper-step') || '0', 10);
            item.classList.toggle('is-active', itemStep === normalizedStep);
            item.classList.toggle('is-complete', itemStep < normalizedStep);
        });

        document.querySelectorAll('.tc-helper-panel').forEach((panel) => {
            const panelStep = parseInt(panel.getAttribute('data-helper-panel') || '0', 10);
            panel.classList.toggle('is-active', panelStep === normalizedStep);
        });

        const prevBtn = el('helperPrevBtn');
        const nextBtn = el('helperNextBtn');
        if (prevBtn) prevBtn.disabled = normalizedStep <= 1;
        if (nextBtn) nextBtn.disabled = normalizedStep >= STEP_COUNT;
    }

    function helperGetDraft(session, phase) {
        if (!session || !Array.isArray(session.drafts)) return null;
        return session.drafts.find((draft) => draft && draft.phase === phase) || null;
    }

    function helperSetPhaseBadgeStatus(targetId, status) {
        const node = el(targetId);
        if (!node) return;

        node.classList.remove('text-bg-secondary', 'text-bg-success', 'text-bg-warning', 'text-bg-danger', 'text-bg-info');
        switch (status) {
            case 'success':
                node.classList.add('text-bg-success');
                break;
            case 'warning':
                node.classList.add('text-bg-warning');
                break;
            case 'danger':
                node.classList.add('text-bg-danger');
                break;
            case 'info':
                node.classList.add('text-bg-info');
                break;
            default:
                node.classList.add('text-bg-secondary');
                break;
        }
    }

    function helperUpdatePhaseBadges(session) {
        Object.values(PHASE_BADGE_IDS).forEach((id) => helperSetPhaseBadgeStatus(id, 'default'));

        if (!session) return;

        const analysisDraft = helperGetDraft(session, 'analysis');
        const coverageDraft = helperGetDraft(session, 'coverage');
        const pretestcaseDraft = helperGetDraft(session, 'pretestcase');
        const finalDraft = helperGetDraft(session, 'final_testcases');

        if ((analysisDraft && analysisDraft.payload) || (coverageDraft && coverageDraft.payload)) {
            helperSetPhaseBadgeStatus(PHASE_BADGE_IDS.analysis, 'success');
        }
        if (pretestcaseDraft && pretestcaseDraft.payload && Array.isArray(pretestcaseDraft.payload.en) && pretestcaseDraft.payload.en.length > 0) {
            helperSetPhaseBadgeStatus(PHASE_BADGE_IDS.pretestcase, 'success');
        }
        if (finalDraft && finalDraft.payload && Array.isArray(finalDraft.payload.tc) && finalDraft.payload.tc.length > 0) {
            helperSetPhaseBadgeStatus(PHASE_BADGE_IDS.testcase, 'success');
        }
        if (session.status === 'completed') {
            helperSetPhaseBadgeStatus(PHASE_BADGE_IDS.commit, 'success');
        }

        const runningPhase = String(session.current_phase || '').trim();
        const runningStatus = String(session.phase_status || '').trim();

        const phaseToBadge = {
            analysis: PHASE_BADGE_IDS.analysis,
            pretestcase: PHASE_BADGE_IDS.pretestcase,
            testcase: PHASE_BADGE_IDS.testcase,
            commit: PHASE_BADGE_IDS.commit,
        };
        const targetBadgeId = phaseToBadge[runningPhase];
        if (targetBadgeId) {
            if (runningStatus === 'running') {
                helperSetPhaseBadgeStatus(targetBadgeId, 'warning');
            } else if (runningStatus === 'failed') {
                helperSetPhaseBadgeStatus(targetBadgeId, 'danger');
            } else if (runningStatus === 'waiting_confirm') {
                helperSetPhaseBadgeStatus(targetBadgeId, 'info');
            }
        }
    }

    function helperUpdateSessionBadge(session) {
        const badge = el('helperSessionBadge');
        if (!badge) return;

        if (!session || !session.id) {
            badge.textContent = helperT('aiHelper.noSession', {}, '尚未建立 Session');
            return;
        }

        const isCompleted = String(session.status || '') === 'completed';
        const suffix = isCompleted
            ? helperT('aiHelper.sessionCompleted', {}, '已完成')
            : helperT('aiHelper.sessionActive', {}, '進行中');
        badge.textContent = `${helperT('aiHelper.sessionLabel', {}, 'Session')} #${session.id} (${suffix})`;
    }

    function helperInsertMarkdown(targetId, syntax) {
        const textarea = el(targetId);
        if (!textarea) return;

        const start = textarea.selectionStart;
        const end = textarea.selectionEnd;
        const selected = textarea.value.substring(start, end);

        let insertion = '';
        let cursorOffset = 0;

        if (syntax === '**' || syntax === '*') {
            insertion = `${syntax}${selected}${syntax}`;
            cursorOffset = syntax.length;
        } else if (syntax === '- ' || syntax === '1. ' || syntax.startsWith('#')) {
            insertion = `${syntax}${selected}`;
            cursorOffset = syntax.length;
        } else {
            insertion = `${syntax}${selected}`;
            cursorOffset = syntax.length;
        }

        textarea.value = `${textarea.value.slice(0, start)}${insertion}${textarea.value.slice(end)}`;
        const cursor = start + (selected ? insertion.length : cursorOffset);
        textarea.setSelectionRange(cursor, cursor);
        textarea.dispatchEvent(new Event('input', { bubbles: true }));
        textarea.focus();
    }

    function helperResolveAvailableStep() {
        if (helperState.finalTestcases && helperState.finalTestcases.length > 0) return 3;
        if (
            helperState.pretestcasePayload
            && Array.isArray(helperState.pretestcasePayload.en)
            && helperState.pretestcasePayload.en.length > 0
        ) {
            return 2;
        }
        return 1;
    }

    function helperSyncStepFromState() {
        const availableStep = helperResolveAvailableStep();
        if (helperState.currentStep > availableStep) {
            helperSetStep(availableStep);
            return;
        }
        helperSetStep(helperState.currentStep);
    }

    function helperGetOutputLocale() {
        const selector = el('helperOutputLocale');
        return selector ? String(selector.value || 'zh-TW') : 'zh-TW';
    }

    function helperParseInitialMiddle(value) {
        const normalized = String(value || '').trim();
        if (!/^\d{3}$/.test(normalized)) {
            throw new Error(helperT('aiHelper.errorInitialMiddle', {}, '起始 middle 編號必須是三位數（如 010）'));
        }
        const number = parseInt(normalized, 10);
        if (number < 10 || number > 990 || number % 10 !== 0) {
            throw new Error(helperT('aiHelper.errorInitialMiddleRule', {}, '起始 middle 編號必須介於 010~990 且每 10 遞增'));
        }
        return normalized;
    }

    async function helperLoadSetOptions(teamId) {
        const sets = await helperApiFetch(`/api/teams/${teamId}/test-case-sets`);
        const list = Array.isArray(sets) ? sets.slice() : [];

        list.sort((a, b) => {
            if (!!a.is_default !== !!b.is_default) {
                return a.is_default ? -1 : 1;
            }
            return String(a.name || '').localeCompare(String(b.name || ''));
        });

        const selector = el('helperExistingSetSelect');
        if (!selector) return;

        selector.innerHTML = '';
        if (!list.length) {
            selector.innerHTML = `<option value="">${helperEscapeHtml(helperT('aiHelper.noSetAvailable', {}, '無可用 Test Case Set'))}</option>`;
            return;
        }

        const preferredSetId = helperState.targetSetId || helperGetCurrentSetId();

        list.forEach((item) => {
            const option = document.createElement('option');
            option.value = String(item.id);
            const defaultText = item.is_default ? ` (${helperT('aiHelper.defaultSetLabel', {}, '預設')})` : '';
            option.textContent = `${item.name}${defaultText}`;
            selector.appendChild(option);
        });

        if (preferredSetId) {
            selector.value = String(preferredSetId);
        }

        if (!selector.value && list.length > 0) {
            selector.value = String(list[0].id);
        }
    }

    function helperResetPanels() {
        const ticketKeyInput = el('helperTicketKey');
        const middleInput = el('helperInitialMiddle');
        const outputLocale = el('helperOutputLocale');

        helperState.sessionId = null;
        helperState.session = null;
        helperState.analyzeRuns = 0;
        helperState.generateRuns = 0;
        helperState.pretestcasePayload = null;
        helperState.pretestcaseOriginalPayload = null;
        helperState.selectedPreSection = '';
        helperState.selectedPreCid = '';
        helperState.finalTestcases = [];
        helperState.selectedFinalSection = '';
        helperState.selectedFinalCaseIndex = -1;
        helperState.targetSetId = null;
        helperState.lastErrorNotified = null;

        if (ticketKeyInput) ticketKeyInput.value = '';
        if (middleInput) middleInput.value = '010';
        if (outputLocale) outputLocale.value = helperCurrentUiLocale();

        helperRenderTicketSummary(null);
        helperRenderPretestcaseTable(null);
        helperRenderPretestcaseDiff();
        helperRenderFinalCases([]);
        helperUpdateSessionBadge(null);
        helperUpdatePhaseBadges(null);
        helperLockSetupFields(false);
        helperSetStep(1);
        helperClearMessages();
    }

    async function helperStartOver() {
        const confirmed = await helperConfirm(
            helperT(
                'aiHelper.startOverConfirm',
                {},
                '確定要重新開始嗎？目前 AI Helper 流程進度將不會保留。',
            ),
            {
                confirmClass: 'btn btn-danger',
            },
        );
        if (!confirmed) return;

        const teamId = helperState.teamId;
        helperClearMessages();
        helperSetBusy(true, helperT('aiHelper.loadingReset', {}, '重置流程中...'));

        try {
            if (teamId) {
                helperClearStoredSessionId(teamId);
            }
            helperResetPanels();
            if (teamId) {
                helperState.teamId = teamId;
                await helperLoadSetOptions(teamId);
                helperToggleSetMode();
            }
            helperSetSuccess(
                helperT('aiHelper.startOverDone', {}, '已重新開始，請重新設定目標 Set 與 TCG 單號。'),
                { autoHideMs: 5000 },
            );
        } catch (error) {
            helperSetError(
                error.message || helperT('aiHelper.startOverFailed', {}, '重新開始失敗'),
                { autoHideMs: 8000 },
            );
        } finally {
            helperSetBusy(false);
        }
    }

    function helperApplySession(session) {
        if (!session || !session.id) return;

        helperState.session = session;
        helperState.sessionId = session.id;
        helperState.targetSetId = session.target_test_case_set_id;

        helperSaveSessionId(helperState.teamId, session.id);

        const ticketKeyInput = el('helperTicketKey');
        const outputLocale = el('helperOutputLocale');
        const middleInput = el('helperInitialMiddle');
        const existingSetSelect = el('helperExistingSetSelect');

        if (ticketKeyInput && session.ticket_key) {
            ticketKeyInput.value = session.ticket_key;
        }
        if (outputLocale && session.output_locale) {
            outputLocale.value = String(session.output_locale);
        }
        if (middleInput && session.initial_middle) {
            middleInput.value = String(session.initial_middle);
        }
        if (existingSetSelect && session.target_test_case_set_id) {
            existingSetSelect.value = String(session.target_test_case_set_id);
        }

        helperUpdateSessionBadge(session);
        helperUpdatePhaseBadges(session);
        helperLockSetupFields(true);

        const jiraDraft = helperGetDraft(session, 'jira_ticket');
        if (jiraDraft && jiraDraft.payload) {
            helperRenderTicketSummary(jiraDraft.payload);
        }

        const pretestcaseDraft = helperGetDraft(session, 'pretestcase');
        if (pretestcaseDraft && pretestcaseDraft.payload && Array.isArray(pretestcaseDraft.payload.en)) {
            helperState.pretestcasePayload = helperDeepClone(pretestcaseDraft.payload);
            if (!helperState.pretestcaseOriginalPayload) {
                helperState.pretestcaseOriginalPayload = helperDeepClone(pretestcaseDraft.payload);
            }
            helperRenderPretestcaseTable(helperState.pretestcasePayload);
            helperRenderPretestcaseDiff();
        } else {
            helperRenderPretestcaseTable(null);
            helperRenderPretestcaseDiff();
        }

        const finalDraft = helperGetDraft(session, 'final_testcases');
        const auditDraft = helperGetDraft(session, 'audit');
        let finalCases = [];
        if (finalDraft && finalDraft.payload && Array.isArray(finalDraft.payload.tc)) {
            finalCases = finalDraft.payload.tc;
        } else if (auditDraft && auditDraft.payload && Array.isArray(auditDraft.payload.tc)) {
            finalCases = auditDraft.payload.tc;
        }

        if (finalCases.length > 0) {
            helperState.finalTestcases = helperDeepClone(finalCases);
            helperRenderFinalCases(helperState.finalTestcases);
        } else {
            helperState.finalTestcases = [];
            helperRenderFinalCases([]);
        }

        const lastError = String(session.last_error || '').trim();
        if (lastError) {
            if (lastError !== helperState.lastErrorNotified) {
                helperSetError(lastError);
                helperState.lastErrorNotified = lastError;
            }
        } else {
            helperState.lastErrorNotified = null;
        }

        const availableStep = helperResolveAvailableStep();
        helperSetStep(availableStep);
    }

    async function helperStartSessionIfNeeded() {
        if (helperState.sessionId) {
            return helperState.session;
        }

        const existingMode = !!(el('helperSetModeExisting') && el('helperSetModeExisting').checked);
        const setId = existingMode ? parseInt((el('helperExistingSetSelect') || {}).value || '0', 10) : null;
        const createName = !existingMode ? String((el('helperNewSetName') || {}).value || '').trim() : '';
        const createDescription = !existingMode ? String((el('helperNewSetDescription') || {}).value || '').trim() : '';
        const outputLocale = helperGetOutputLocale();
        const reviewLocale = helperCurrentUiLocale();
        const initialMiddle = helperParseInitialMiddle((el('helperInitialMiddle') || {}).value || '010');

        if (existingMode && (!setId || Number.isNaN(setId))) {
            throw new Error(helperT('aiHelper.errorSetRequired', {}, '請先選擇目標 Test Case Set'));
        }
        if (!existingMode && !createName) {
            throw new Error(helperT('aiHelper.errorSetNameRequired', {}, '建立新 Set 時，名稱不可為空'));
        }

        const body = {
            output_locale: outputLocale,
            review_locale: reviewLocale,
            initial_middle: initialMiddle,
            enable_qdrant_context: true,
        };

        if (existingMode) {
            body.test_case_set_id = setId;
        } else {
            body.create_set_name = createName;
            if (createDescription) {
                body.create_set_description = createDescription;
            }
        }

        const session = await helperApiFetch(
            `/api/teams/${helperState.teamId}/test-case-helper/sessions`,
            {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            }
        );

        helperApplySession(session);
        if (!existingMode) {
            await helperLoadSetOptions(helperState.teamId);
        }
        return session;
    }

    async function helperRestoreSession(sessionId, showToastIfMissing) {
        const targetSessionId = sessionId || helperLoadStoredSessionId(helperState.teamId);
        if (!targetSessionId) {
            if (showToastIfMissing) {
                helperNotifyWarning(helperT('aiHelper.noStoredSession', {}, '找不到可恢復的 Session'));
            }
            return false;
        }

        try {
            helperSetBusy(true, helperT('aiHelper.loadingSession', {}, '讀取 Session 中...'));
            const session = await helperApiFetch(
                `/api/teams/${helperState.teamId}/test-case-helper/sessions/${targetSessionId}`
            );
            helperApplySession(session);
            helperSetSuccess(
                helperT('aiHelper.sessionRestored', {}, '已恢復先前 Session'),
                { autoHideMs: 3500 },
            );
            return true;
        } catch (error) {
            helperClearStoredSessionId(helperState.teamId);
            if (showToastIfMissing) {
                helperNotifyWarning(`${helperT('aiHelper.restoreFailed', {}, 'Session 恢復失敗')}: ${error.message}`);
            }
            return false;
        } finally {
            helperSetBusy(false);
        }
    }

    async function helperRunAnalysis(requirementMarkdown, options = {}) {
        const overrideIncompleteRequirement = !!options.overrideIncompleteRequirement;
        const requestBody = {
            retry: helperState.analyzeRuns > 0,
            override_incomplete_requirement: overrideIncompleteRequirement,
        };
        const normalizedRequirementMarkdown = String(requirementMarkdown || '').trim();
        if (normalizedRequirementMarkdown) {
            requestBody.requirement_markdown = normalizedRequirementMarkdown;
        }

        const result = await helperApiFetch(
            `/api/teams/${helperState.teamId}/test-case-helper/sessions/${helperState.sessionId}/analyze`,
            {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(requestBody),
            }
        );

        helperApplySession(result.session);

        const warningPayload = result && result.payload ? result.payload : null;
        if (warningPayload && warningPayload.requires_override) {
            if (overrideIncompleteRequirement) {
                throw new Error(helperT('aiHelper.requirementWarningRetryFailed', {}, '已確認繼續但仍無法通過 requirement 驗證，請修正需求內容後再試'));
            }

            const warning = warningPayload.warning || {};
            const missingSections = Array.isArray(warning.missing_sections) ? warning.missing_sections : [];
            const missingFields = Array.isArray(warning.missing_fields) ? warning.missing_fields : [];
            const qualityLevel = String(warning.quality_level || '').trim() || 'low';

            const detailLines = [
                helperT('aiHelper.requirementIncompleteWarningTitle', {}, 'Requirement 格式不完整'),
                helperT('aiHelper.requirementIncompleteWarningLevel', { level: qualityLevel }, `品質等級：${qualityLevel}`),
            ];
            if (missingSections.length > 0) {
                detailLines.push(
                    helperT(
                        'aiHelper.requirementIncompleteWarningSections',
                        { sections: missingSections.join(', ') },
                        `缺漏段落：${missingSections.join(', ')}`
                    )
                );
            }
            if (missingFields.length > 0) {
                detailLines.push(
                    helperT(
                        'aiHelper.requirementIncompleteWarningFields',
                        { fields: missingFields.join(', ') },
                        `缺漏欄位：${missingFields.join(', ')}`
                    )
                );
            }

            const confirmed = await helperConfirm(detailLines.join('\n'), {
                title: helperT('aiHelper.requirementIncompleteWarningDialogTitle', {}, 'Requirement 不完整'),
                confirmText: helperT('aiHelper.proceedAnyway', {}, '仍要繼續'),
                cancelText: helperT('aiHelper.goBackAndFix', {}, '返回修正'),
                confirmClass: 'btn btn-warning',
            });
            if (!confirmed) {
                helperNotifyWarning(helperT('aiHelper.requirementIncompleteCancelled', {}, '已取消前進，請先補齊 requirement 格式'));
                return;
            }
            await helperRunAnalysis(requirementMarkdown, { overrideIncompleteRequirement: true });
            return;
        }

        helperState.analyzeRuns += 1;

        const payloadFromResponse = result && result.payload ? result.payload.pretestcase : null;
        const preDraft = helperGetDraft(result.session, 'pretestcase');
        const prePayload = payloadFromResponse || (preDraft ? preDraft.payload : null);

        if (!prePayload || !Array.isArray(prePayload.en) || prePayload.en.length === 0) {
            throw new Error(helperT('aiHelper.errorPretestcaseEmpty', {}, 'Analysis/Coverage 未產生有效條目'));
        }

        helperState.pretestcasePayload = helperDeepClone(prePayload);
        helperState.pretestcaseOriginalPayload = helperDeepClone(prePayload);
        helperRenderPretestcaseTable(helperState.pretestcasePayload);
        helperRenderPretestcaseDiff();

        helperSetSuccess(
            helperT('aiHelper.analyzeDone', {}, 'Analysis/Coverage 完成，請確認條目後產生 Test Case'),
            { autoHideMs: 5000 },
        );
        helperSetStep(2);
    }

    async function helperNormalizeRequirement() {
        helperClearMessages();
        helperSetBusy(true, helperT('aiHelper.loadingNormalize', {}, '讀取 Ticket 並執行 Analysis/Coverage 中...'));

        try {
            await helperStartSessionIfNeeded();

            const ticketKey = String((el('helperTicketKey') || {}).value || '').trim();
            if (!ticketKey) {
                throw new Error(helperT('aiHelper.errorTicketRequired', {}, '請輸入 TCG 單號'));
            }

            const ticketPayload = await helperApiFetch(
                `/api/teams/${helperState.teamId}/test-case-helper/sessions/${helperState.sessionId}/ticket`,
                {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ ticket_key: ticketKey }),
                }
            );
            helperRenderTicketSummary(ticketPayload);

            const ticketDescription = String((ticketPayload || {}).description || '');
            await helperRunAnalysis(ticketDescription);
        } catch (error) {
            helperSetError(error.message || helperT('aiHelper.normalizeFailed', {}, '讀取 Ticket 或 Analysis/Coverage 失敗'));
        } finally {
            helperSetBusy(false);
        }
    }

    function helperBuildPreSections(entries) {
        const grouped = new Map();
        entries.forEach((entry) => {
            const sectionName = String(entry.g || '未分類').trim() || '未分類';
            const sectionNoFromCid = String(entry.cid || '').split('.')[0] || '';
            const sectionNo = String(entry.sn || sectionNoFromCid).trim();
            if (!grouped.has(sectionName)) {
                grouped.set(sectionName, { sn: sectionNo, en: [] });
            }
            const group = grouped.get(sectionName);
            if (!group.sn && sectionNo) {
                group.sn = sectionNo;
            }
            group.en.push(entry);
        });
        return Array.from(grouped.entries()).map(([group, groupedData]) => ({
            g: group,
            sn: String(groupedData.sn || '').trim(),
            en: groupedData.en,
        }));
    }

    function helperFormatSectionLabel(sn, sectionName) {
        const sectionNo = String(sn || '').trim();
        const name = String(sectionName || '未分類').trim() || '未分類';
        return sectionNo ? `${sectionNo} ${name}` : name;
    }

    function helperGetPreSeqBase() {
        const rawFromInput = String((el('helperInitialMiddle') || {}).value || '').trim();
        const raw = rawFromInput || String((helperState.session || {}).initial_middle || '').trim() || '010';
        const value = parseInt(raw, 10);
        if (Number.isNaN(value) || value < 10 || value > 990 || value % 10 !== 0) {
            return 10;
        }
        return value;
    }

    function helperReindexPreEntries(entries) {
        const source = Array.isArray(entries) ? entries : [];
        const grouped = new Map();
        source.forEach((entry) => {
            const sectionName = String((entry || {}).g || '未分類').trim() || '未分類';
            if (!grouped.has(sectionName)) {
                grouped.set(sectionName, []);
            }
            grouped.get(sectionName).push(entry);
        });

        const base = helperGetPreSeqBase();
        const normalized = [];
        let globalIndex = 1;
        Array.from(grouped.entries()).forEach(([sectionName, sectionEntries], sectionIndex) => {
            const sectionNo = String(base + sectionIndex * 10).padStart(3, '0');
            sectionEntries.forEach((entry, entryIndex) => {
                const testNo = String(base + entryIndex * 10).padStart(3, '0');
                entry.idx = globalIndex;
                entry.g = sectionName;
                entry.sn = sectionNo;
                entry.tn = testNo;
                entry.cid = `${sectionNo}.${testNo}`;
                normalized.push(entry);
                globalIndex += 1;
            });
        });
        return normalized;
    }

    function helperNormalizeCategory(value) {
        const normalized = String(value || '').trim().toLowerCase();
        if (['happy', 'negative', 'boundary'].includes(normalized)) return normalized;
        if (['positive', 'normal', 'success'].includes(normalized)) return 'happy';
        if (['error', 'fail', 'failed', 'invalid', 'permission', 'forbidden'].includes(normalized)) return 'negative';
        if (['edge', 'limit'].includes(normalized)) return 'boundary';
        return 'happy';
    }

    function helperNormalizeTextArray(rawValue) {
        if (Array.isArray(rawValue)) {
            return rawValue
                .map((item) => String(item || '').trim())
                .filter(Boolean);
        }
        const normalized = String(rawValue || '').trim();
        return normalized ? [normalized] : [];
    }

    function helperNormalizeRequirementContext(rawContext, entry) {
        const context = rawContext && typeof rawContext === 'object' ? helperDeepClone(rawContext) : {};
        const summary = String(context.summary || entry.t || '').trim();
        const requirementKey = String(context.requirement_key || entry.requirement_key || '').trim();

        context.requirement_key = requirementKey;
        context.source_requirement_keys = helperNormalizeTextArray(context.source_requirement_keys);
        context.summary = summary;
        context.content = helperNormalizeTextArray(context.content);
        if (!context.content.length && summary) {
            context.content = [summary];
        }
        context.spec_requirements = helperNormalizeTextArray(context.spec_requirements);
        context.verification_points = helperNormalizeTextArray(context.verification_points);
        context.validation_requirements = helperNormalizeTextArray(
            context.validation_requirements && context.validation_requirements.length > 0
                ? context.validation_requirements
                : context.verification_points
        );
        context.expected_outcomes = helperNormalizeTextArray(context.expected_outcomes);
        return context;
    }

    function helperNormalizePreEntry(entry, index) {
        const next = helperDeepClone(entry || {});
        const fallbackNumber = String((index + 1) * 10).padStart(3, '0');
        const cid = String(next.cid || '').trim();
        const parts = cid.split('.');
        const snFromCid = parts.length === 2 ? String(parts[0] || '').trim() : '';
        const tnFromCid = parts.length === 2 ? String(parts[1] || '').trim() : '';

        next.sn = String(next.sn || snFromCid || '010').trim().padStart(3, '0').slice(-3);
        next.tn = String(next.tn || tnFromCid || fallbackNumber).trim().padStart(3, '0').slice(-3);
        next.cid = `${next.sn}.${next.tn}`;
        next.idx = index + 1;
        next.g = String(next.g || '未分類').trim() || '未分類';
        next.t = String(next.t || '').trim();
        next.cat = helperNormalizeCategory(next.cat);
        next.st = String(next.st || 'ok').trim() || 'ok';
        next.ref = Array.isArray(next.ref)
            ? next.ref.map((item) => String(item || '').trim()).filter(Boolean)
            : [];
        next.rid = Array.isArray(next.rid)
            ? next.rid.map((item) => String(item || '').trim()).filter(Boolean)
            : [];
        next.req = Array.isArray(next.req)
            ? next.req.map((item) => {
                if (item && typeof item === 'object') {
                    const rid = String(item.id || '').trim();
                    const title = String(item.t || '').trim();
                    if (rid && title) return `${rid} ${title}`;
                    return rid || title;
                }
                return String(item || '').trim();
            }).filter(Boolean)
            : [];
        next.requirement_key = String(next.requirement_key || '').trim();
        next.requirement_context = helperNormalizeRequirementContext(next.requirement_context, next);
        if (!next.requirement_key && next.requirement_context.requirement_key) {
            next.requirement_key = String(next.requirement_context.requirement_key || '').trim();
        }

        if (!next.trace || typeof next.trace !== 'object') {
            next.trace = {};
        }
        next.trace.ref_tokens = helperNormalizeTextArray(next.ref);
        next.trace.rid_tokens = helperNormalizeTextArray(next.rid);

        if (next.st === 'assume') {
            next.a = String(next.a || '').trim();
            delete next.q;
        } else if (next.st === 'ask') {
            next.q = String(next.q || '').trim();
            delete next.a;
        } else {
            delete next.a;
            delete next.q;
        }

        return next;
    }

    function helperNormalizePrePayload(payload) {
        const nextPayload = helperDeepClone(payload || {});
        const sourceEntries = Array.isArray(nextPayload.en) ? nextPayload.en : [];
        const normalizedEntries = sourceEntries.map((entry, index) => helperNormalizePreEntry(entry, index));
        const reindexedEntries = helperReindexPreEntries(normalizedEntries);

        nextPayload.en = reindexedEntries;
        nextPayload.sec = helperBuildPreSections(reindexedEntries);
        if (!nextPayload.lang && helperState.session && helperState.session.review_locale) {
            nextPayload.lang = helperState.session.review_locale;
        }
        return nextPayload;
    }

    function helperGetPreEntries() {
        return Array.isArray((helperState.pretestcasePayload || {}).en)
            ? helperState.pretestcasePayload.en
            : [];
    }

    function helperGetSelectedPreEntry() {
        const entries = helperGetPreEntries();
        return entries.find((entry) => String(entry.cid || '') === helperState.selectedPreCid) || null;
    }

    function helperEnsurePreSelection() {
        const entries = helperGetPreEntries();
        if (!entries.length) {
            helperState.selectedPreSection = '';
            helperState.selectedPreCid = '';
            return;
        }

        const sections = Array.from(new Set(entries.map((entry) => String(entry.g || '未分類').trim() || '未分類')));
        if (!sections.includes(helperState.selectedPreSection)) {
            helperState.selectedPreSection = sections[0];
        }

        const filtered = entries.filter(
            (entry) => (String(entry.g || '未分類').trim() || '未分類') === helperState.selectedPreSection
        );
        if (!filtered.length) {
            helperState.selectedPreSection = sections[0];
            helperState.selectedPreCid = String(entries[0].cid || '');
            return;
        }

        const selectedExists = filtered.some((entry) => String(entry.cid || '') === helperState.selectedPreCid);
        if (!selectedExists) {
            helperState.selectedPreCid = String(filtered[0].cid || '');
        }
    }

    function helperRenderPreSectionList() {
        const container = el('helperPreSectionList');
        if (!container) return;

        const entries = helperGetPreEntries();
        const grouped = helperBuildPreSections(entries);
        if (!grouped.length) {
            container.innerHTML = `<div class="text-muted small px-2 py-1">${helperEscapeHtml(helperT('aiHelper.noPretestcase', {}, '尚無 pre-testcase 條目'))}</div>`;
            return;
        }

        container.innerHTML = grouped.map((section) => {
            const name = String(section.g || '未分類').trim() || '未分類';
            const count = Array.isArray(section.en) ? section.en.length : 0;
            const displayLabel = helperFormatSectionLabel(section.sn, name);
            const activeClass = helperState.selectedPreSection === name ? ' active' : '';
            return `
                <button type="button" class="list-group-item list-group-item-action d-flex justify-content-between align-items-center${activeClass}" data-helper-pre-section="${helperEscapeHtml(name)}">
                    <span class="text-truncate">${helperEscapeHtml(displayLabel)}</span>
                    <span class="badge text-bg-light">${count}</span>
                </button>
            `;
        }).join('');
    }

    function helperRenderPreEntryList() {
        const container = el('helperPreEntryList');
        if (!container) return;

        const entries = helperGetPreEntries().filter(
            (entry) => (String(entry.g || '未分類').trim() || '未分類') === helperState.selectedPreSection
        );

        if (!entries.length) {
            container.innerHTML = `<div class="text-muted small px-2 py-1">${helperEscapeHtml(helperT('aiHelper.preDetailEmpty', {}, '請先選擇左側條目'))}</div>`;
            return;
        }

        container.innerHTML = entries.map((entry) => {
            const cid = String(entry.cid || '');
            const title = String(entry.t || '').trim() || helperT('common.untitled', {}, '(未命名)');
            const category = String(entry.cat || 'happy');
            const state = String(entry.st || 'ok');
            const activeClass = helperState.selectedPreCid === cid ? ' active' : '';
            return `
                <button type="button" class="list-group-item list-group-item-action${activeClass}" data-helper-pre-cid="${helperEscapeHtml(cid)}">
                    <div class="d-flex align-items-start justify-content-between gap-2">
                        <div class="min-w-0">
                            <div class="small text-muted"><code>${helperEscapeHtml(cid)}</code></div>
                            <div class="fw-semibold text-break">${helperEscapeHtml(title)}</div>
                        </div>
                        <div class="d-flex flex-column align-items-end gap-1">
                            <span class="badge text-bg-info">${helperEscapeHtml(category)}</span>
                            <span class="badge text-bg-secondary">${helperEscapeHtml(state)}</span>
                        </div>
                    </div>
                </button>
            `;
        }).join('');
    }

    function helperRenderPreReqPreview(entry) {
        const container = el('helperPreReqPreview');
        if (!container) return;

        const sourceKeys = entry
            && entry.requirement_context
            && Array.isArray(entry.requirement_context.source_requirement_keys)
            ? entry.requirement_context.source_requirement_keys
            : [];
        const reqItems = sourceKeys.length > 0
            ? sourceKeys
            : (entry && Array.isArray(entry.req) ? entry.req : []);
        if (!reqItems.length && !String((entry || {}).requirement_key || '').trim()) {
            container.innerHTML = `<span class="text-muted">${helperEscapeHtml(helperT('aiHelper.reqMappingEmpty', {}, '無需求映射'))}</span>`;
            return;
        }

        const displayItems = [];
        const requirementKey = String((entry || {}).requirement_key || '').trim();
        if (requirementKey) {
            displayItems.push(requirementKey);
        }
        reqItems.forEach((item) => displayItems.push(String(item || '').trim()));

        container.innerHTML = Array.from(new Set(displayItems.filter(Boolean)))
            .map((item) => `<span class="badge text-bg-light me-1 mb-1">${helperEscapeHtml(String(item || ''))}</span>`)
            .join('');
    }

    function helperRenderPreContextList(containerId, items, emptyI18nKey, emptyFallback) {
        const container = el(containerId);
        if (!container) return;
        const values = helperNormalizeTextArray(items);
        if (!values.length) {
            container.innerHTML = `<span class="text-muted">${helperEscapeHtml(helperT(emptyI18nKey, {}, emptyFallback))}</span>`;
            return;
        }
        container.innerHTML = values
            .map((item) => `<div class="tc-helper-context-item">• ${helperEscapeHtml(item)}</div>`)
            .join('');
    }

    function helperRenderRequirementContext(entry) {
        const context = entry && entry.requirement_context && typeof entry.requirement_context === 'object'
            ? entry.requirement_context
            : {};
        const summaryContainer = el('helperPreRequirementSummary');
        if (summaryContainer) {
            const summary = String(context.summary || entry.t || '').trim();
            if (!summary) {
                summaryContainer.innerHTML = `<span class="text-muted">${helperEscapeHtml(helperT('aiHelper.requirementSummaryEmpty', {}, '無需求摘要'))}</span>`;
            } else {
                summaryContainer.textContent = summary;
            }
        }

        helperRenderPreContextList(
            'helperPreRequirementContent',
            context.content,
            'aiHelper.requirementContentEmpty',
            '無需求內容條目',
        );
        helperRenderPreContextList(
            'helperPreSpecRequirements',
            context.spec_requirements,
            'aiHelper.specRequirementsEmpty',
            '無規格需求條目',
        );
        helperRenderPreContextList(
            'helperPreVerificationPoints',
            context.verification_points,
            'aiHelper.verificationPointsEmpty',
            '無驗證檢核點',
        );
        helperRenderPreContextList(
            'helperPreExpectedOutcomes',
            context.expected_outcomes,
            'aiHelper.expectedOutcomesEmpty',
            '無預期結果條目',
        );
        helperRenderPreContextList(
            'helperPreTraceMeta',
            [
                ...helperNormalizeTextArray(((entry || {}).trace || {}).ref_tokens),
                ...helperNormalizeTextArray(((entry || {}).trace || {}).rid_tokens),
            ],
            'aiHelper.traceMetaEmpty',
            '無 trace 參考',
        );
    }

    function helperRenderPreDetail() {
        const emptyNode = el('helperPreDetailEmpty');
        const detailForm = el('helperPreDetailForm');
        const selected = helperGetSelectedPreEntry();

        if (!selected) {
            if (emptyNode) emptyNode.classList.remove('d-none');
            if (detailForm) detailForm.classList.add('d-none');
            return;
        }

        if (emptyNode) emptyNode.classList.add('d-none');
        if (detailForm) detailForm.classList.remove('d-none');

        const noteValue = selected.st === 'assume'
            ? String(selected.a || '')
            : (selected.st === 'ask' ? String(selected.q || '') : '');

        const cidInput = el('helperPreCidInput');
        const sectionInput = el('helperPreSectionInput');
        const titleInput = el('helperPreTitleInput');
        const categoryInput = el('helperPreCategoryInput');
        const stateInput = el('helperPreStateInput');
        const refInput = el('helperPreRefInput');
        const noteInput = el('helperPreNoteInput');

        if (cidInput) cidInput.value = String(selected.cid || '');
        if (sectionInput) sectionInput.value = String(selected.g || '未分類');
        if (titleInput) titleInput.value = String(selected.t || '');
        if (categoryInput) categoryInput.value = String(selected.cat || 'happy');
        if (stateInput) stateInput.value = String(selected.st || 'ok');
        if (refInput) refInput.value = Array.isArray(selected.ref) ? selected.ref.join(', ') : '';
        if (noteInput) {
            noteInput.value = noteValue;
            if (String(selected.st || '') === 'assume') {
                noteInput.placeholder = helperT('aiHelper.noteAssume', {}, '輸入 assume 說明');
            } else if (String(selected.st || '') === 'ask') {
                noteInput.placeholder = helperT('aiHelper.noteAsk', {}, '輸入待確認問題');
            } else {
                noteInput.placeholder = '';
            }
        }

        helperRenderPreReqPreview(selected);
        helperRenderRequirementContext(selected);
    }

    function helperSyncSelectedPreEntryFromDetail() {
        const selected = helperGetSelectedPreEntry();
        if (!selected) return false;

        const sectionInput = el('helperPreSectionInput');
        const titleInput = el('helperPreTitleInput');
        const categoryInput = el('helperPreCategoryInput');
        const stateInput = el('helperPreStateInput');
        const refInput = el('helperPreRefInput');
        const noteInput = el('helperPreNoteInput');

        selected.g = String((sectionInput || {}).value || '未分類').trim() || '未分類';
        selected.t = String((titleInput || {}).value || '').trim();
        selected.cat = helperNormalizeCategory((categoryInput || {}).value || selected.cat || 'happy');
        selected.st = String((stateInput || {}).value || 'ok').trim() || 'ok';
        if (refInput) {
            selected.ref = String(refInput.value || '')
                .split(',')
                .map((item) => item.trim())
                .filter(Boolean);
        } else if (!Array.isArray(selected.ref)) {
            selected.ref = [];
        }

        const note = String((noteInput || {}).value || '').trim();
        if (selected.st === 'assume') {
            selected.a = note;
            delete selected.q;
        } else if (selected.st === 'ask') {
            selected.q = note;
            delete selected.a;
        } else {
            delete selected.a;
            delete selected.q;
        }
        selected.requirement_context = helperNormalizeRequirementContext(selected.requirement_context, selected);
        selected.requirement_context.summary = String(selected.t || selected.requirement_context.summary || '').trim();
        selected.trace = selected.trace && typeof selected.trace === 'object' ? selected.trace : {};
        selected.trace.ref_tokens = helperNormalizeTextArray(selected.ref);
        selected.trace.rid_tokens = helperNormalizeTextArray(selected.rid);
        return true;
    }

    function helperRenderPretestcaseTable(payload) {
        if (payload && typeof payload === 'object') {
            helperState.pretestcasePayload = helperNormalizePrePayload(payload);
        } else if (payload === null) {
            helperState.pretestcasePayload = helperNormalizePrePayload({ en: [] });
        } else if (helperState.pretestcasePayload) {
            helperState.pretestcasePayload = helperNormalizePrePayload(helperState.pretestcasePayload);
        } else {
            helperState.pretestcasePayload = helperNormalizePrePayload({ en: [] });
        }

        helperEnsurePreSelection();
        helperRenderPreSectionList();
        helperRenderPreEntryList();
        helperRenderPreDetail();
    }

    function helperGenerateNextCid() {
        const entries = helperGetPreEntries();
        let maxSn = 10;
        let maxTn = 0;

        entries.forEach((entry) => {
            const cid = String(entry.cid || '');
            const parts = cid.split('.').map((item) => parseInt(item, 10));
            if (parts.length === 2 && !Number.isNaN(parts[0]) && !Number.isNaN(parts[1])) {
                if (parts[0] > maxSn) {
                    maxSn = parts[0];
                    maxTn = parts[1];
                } else if (parts[0] === maxSn && parts[1] > maxTn) {
                    maxTn = parts[1];
                }
            }
        });

        let nextSn = maxSn;
        let nextTn = maxTn + 10;
        if (nextTn > 990) {
            nextSn += 10;
            nextTn = 10;
        }

        return {
            sn: String(nextSn).padStart(3, '0'),
            tn: String(nextTn).padStart(3, '0'),
        };
    }

    function helperGetPretestcasePayloadFromTable() {
        helperSyncSelectedPreEntryFromDetail();
        helperState.pretestcasePayload = helperNormalizePrePayload(helperState.pretestcasePayload || { en: [] });
        helperEnsurePreSelection();
        return helperDeepClone(helperState.pretestcasePayload);
    }

    function helperSetPretestcaseDiff(container, html, visible) {
        if (!container) return;
        if (!visible) {
            container.innerHTML = '';
            container.classList.add('d-none');
            return;
        }
        container.classList.remove('d-none');
        container.innerHTML = html;
    }

    function helperRenderPretestcaseDiff() {
        const container = el('helperPretestcaseDiff');
        if (!container) return;

        if (!helperState.pretestcaseOriginalPayload || !Array.isArray(helperState.pretestcaseOriginalPayload.en)) {
            helperSetPretestcaseDiff(
                container,
                `<span class="text-muted">${helperEscapeHtml(helperT('aiHelper.diffUnavailable', {}, '尚無差異基準'))}</span>`,
                true,
            );
            return;
        }

        const current = helperGetPretestcasePayloadFromTable();
        const currentEntries = Array.isArray(current.en) ? current.en : [];
        const baselineMap = new Map();
        const fieldLabelMap = {
            g: helperT('testCase.section', {}, '區段'),
            t: helperT('common.title', {}, '標題'),
            cat: helperT('aiHelper.category', {}, '類別'),
            st: helperT('aiHelper.state', {}, '狀態'),
            ref: helperT('aiHelper.ref', {}, '需求對應'),
            note: helperT('aiHelper.note', {}, '備註'),
        };

        helperState.pretestcaseOriginalPayload.en.forEach((entry) => {
            const key = String(entry.cid || '');
            if (key) baselineMap.set(key, entry);
        });

        const changed = [];
        currentEntries.forEach((entry) => {
            const key = String(entry.cid || '');
            const baseline = baselineMap.get(key);
            if (!baseline) {
                changed.push(`${key}: ${helperT('aiHelper.diffAdded', {}, '新增條目')}`);
                return;
            }

            const fields = [];
            if (String(entry.g || '') !== String(baseline.g || '')) fields.push('g');
            if (String(entry.t || '') !== String(baseline.t || '')) fields.push('t');
            if (String(entry.cat || '') !== String(baseline.cat || '')) fields.push('cat');
            if (String(entry.st || '') !== String(baseline.st || '')) fields.push('st');

            const refCurrent = Array.isArray(entry.ref) ? entry.ref.join(',') : '';
            const refBaseline = Array.isArray(baseline.ref) ? baseline.ref.join(',') : '';
            if (refCurrent !== refBaseline) fields.push('ref');

            const noteCurrent = String(entry.a || entry.q || '');
            const noteBaseline = String(baseline.a || baseline.q || '');
            if (noteCurrent !== noteBaseline) fields.push('note');

            if (fields.length > 0) {
                changed.push(`${key}: ${fields.map((field) => fieldLabelMap[field] || field).join('、')}`);
            }
        });

        if (!changed.length) {
            helperSetPretestcaseDiff(container, '', false);
            return;
        }

        const limit = 8;
        const displayItems = changed.slice(0, limit).map((line) => `<li>${helperEscapeHtml(line)}</li>`).join('');
        const remain = changed.length > limit
            ? `<li>... ${helperEscapeHtml(helperT('aiHelper.diffMore', { count: changed.length - limit }, '另有 {count} 筆'))}</li>`
            : '';

        helperSetPretestcaseDiff(
            container,
            `
                <div class="mb-1"><strong>${helperEscapeHtml(helperT('aiHelper.diffChanged', { count: changed.length }, '已調整 {count} 筆條目'))}</strong></div>
                <ul class="mb-0">${displayItems}${remain}</ul>
            `,
            true,
        );
    }

    function helperListToText(lines, withNumbering) {
        if (!Array.isArray(lines) || !lines.length) return '';
        return lines
            .map((line, index) => {
                const text = String(line || '').trim();
                if (!text) return '';
                if (withNumbering) return `${index + 1}. ${text}`;
                return text;
            })
            .filter(Boolean)
            .join('\n');
    }

    function helperTextToList(rawText, removeNumberPrefix) {
        return String(rawText || '')
            .split('\n')
            .map((line) => String(line || '').trim())
            .filter(Boolean)
            .map((line) => line.replace(/^[-*]\s+/, ''))
            .map((line) => {
                if (!removeNumberPrefix) return line;
                return line.replace(/^\d+[\.)]\s+/, '');
            })
            .map((line) => String(line || '').trim())
            .filter(Boolean);
    }

    function helperBuildFinalSections(testcases) {
        const grouped = new Map();
        testcases.forEach((testcase, index) => {
            const sectionPath = String(testcase.section_path || 'Unassigned').trim() || 'Unassigned';
            if (!grouped.has(sectionPath)) {
                grouped.set(sectionPath, []);
            }
            grouped.get(sectionPath).push({ index, testcase });
        });
        return Array.from(grouped.entries()).map(([sectionPath, items]) => {
            const firstCaseId = String(((items[0] || {}).testcase || {}).id || '').trim();
            const parts = firstCaseId.split('.');
            const middleNo = parts.length >= 3 && /^\d{3}$/.test(String(parts[parts.length - 2] || ''))
                ? String(parts[parts.length - 2] || '')
                : '';
            const hasPrefix = /^\d{3}\s+/.test(sectionPath);
            const displayLabel = (middleNo && !hasPrefix && sectionPath.toLowerCase() !== 'unassigned')
                ? `${middleNo} ${sectionPath}`
                : sectionPath;
            return { sectionPath, displayLabel, items };
        });
    }

    function helperEnsureFinalSelection() {
        const list = Array.isArray(helperState.finalTestcases) ? helperState.finalTestcases : [];
        if (!list.length) {
            helperState.selectedFinalSection = '';
            helperState.selectedFinalCaseIndex = -1;
            return;
        }

        const sections = helperBuildFinalSections(list).map((item) => item.sectionPath);
        if (!sections.includes(helperState.selectedFinalSection)) {
            helperState.selectedFinalSection = sections[0];
        }

        const filtered = list
            .map((testcase, index) => ({ testcase, index }))
            .filter((item) => (String(item.testcase.section_path || 'Unassigned').trim() || 'Unassigned') === helperState.selectedFinalSection);

        const validSelected = filtered.some((item) => item.index === helperState.selectedFinalCaseIndex);
        if (!validSelected) {
            helperState.selectedFinalCaseIndex = filtered.length ? filtered[0].index : 0;
        }
    }

    function helperGetSelectedFinalCase() {
        const list = Array.isArray(helperState.finalTestcases) ? helperState.finalTestcases : [];
        if (!list.length) return null;
        if (helperState.selectedFinalCaseIndex < 0 || helperState.selectedFinalCaseIndex >= list.length) {
            return null;
        }
        return list[helperState.selectedFinalCaseIndex] || null;
    }

    function helperRenderFinalSectionList() {
        const container = el('helperFinalSectionList');
        if (!container) return;

        const list = Array.isArray(helperState.finalTestcases) ? helperState.finalTestcases : [];
        const sections = helperBuildFinalSections(list);
        if (!sections.length) {
            container.innerHTML = `<div class="text-muted small px-2 py-1">${helperEscapeHtml(helperT('aiHelper.noGeneratedCases', {}, '尚未產生 Test Cases'))}</div>`;
            return;
        }

        container.innerHTML = sections.map((sectionItem) => {
            const activeClass = helperState.selectedFinalSection === sectionItem.sectionPath ? ' active' : '';
            return `
                <button type="button" class="list-group-item list-group-item-action d-flex justify-content-between align-items-center${activeClass}" data-helper-final-section="${helperEscapeHtml(sectionItem.sectionPath)}">
                    <span class="text-truncate">${helperEscapeHtml(sectionItem.displayLabel || sectionItem.sectionPath)}</span>
                    <span class="badge text-bg-light">${sectionItem.items.length}</span>
                </button>
            `;
        }).join('');
    }

    function helperRenderFinalCaseList() {
        const container = el('helperFinalCaseList');
        if (!container) return;

        const list = Array.isArray(helperState.finalTestcases) ? helperState.finalTestcases : [];
        const filtered = list
            .map((testcase, index) => ({ testcase, index }))
            .filter((item) => (String(item.testcase.section_path || 'Unassigned').trim() || 'Unassigned') === helperState.selectedFinalSection);

        if (!filtered.length) {
            container.innerHTML = `<div class="text-muted small px-2 py-1">${helperEscapeHtml(helperT('aiHelper.finalDetailEmpty', {}, '請先選擇左側 Test Case'))}</div>`;
            return;
        }

        container.innerHTML = filtered.map((item) => {
            const testcase = item.testcase;
            const caseId = String(testcase.id || '').trim() || 'N/A';
            const title = String(testcase.t || '').trim() || helperT('common.untitled', {}, '(未命名)');
            const activeClass = helperState.selectedFinalCaseIndex === item.index ? ' active' : '';
            return `
                <button type="button" class="list-group-item list-group-item-action${activeClass}" data-helper-final-index="${item.index}">
                    <div class="small text-muted"><code>${helperEscapeHtml(caseId)}</code></div>
                    <div class="fw-semibold text-break">${helperEscapeHtml(title)}</div>
                </button>
            `;
        }).join('');
    }

    function helperRenderFinalCasePreviews() {
        helperRenderMarkdown(String((el('helperCasePreInput') || {}).value || ''), el('helperCasePrePreview'));
        helperRenderMarkdown(String((el('helperCaseStepsInput') || {}).value || ''), el('helperCaseStepsPreview'));
        helperRenderMarkdown(String((el('helperCaseExpInput') || {}).value || ''), el('helperCaseExpPreview'));
    }

    function helperRenderFinalDetail() {
        const emptyNode = el('helperFinalDetailEmpty');
        const detailForm = el('helperFinalDetailForm');
        const selected = helperGetSelectedFinalCase();

        if (!selected) {
            if (emptyNode) emptyNode.classList.remove('d-none');
            if (detailForm) detailForm.classList.add('d-none');
            return;
        }

        if (emptyNode) emptyNode.classList.add('d-none');
        if (detailForm) detailForm.classList.remove('d-none');

        const idInput = el('helperCaseIdInput');
        const titleInput = el('helperCaseTitleInput');
        const priorityInput = el('helperCasePriorityInput');
        const sectionInput = el('helperCaseSectionInput');
        const preInput = el('helperCasePreInput');
        const stepsInput = el('helperCaseStepsInput');
        const expInput = el('helperCaseExpInput');

        if (idInput) idInput.value = String(selected.id || '');
        if (titleInput) titleInput.value = String(selected.t || '');
        if (priorityInput) priorityInput.value = String(selected.priority || 'Medium');
        if (sectionInput) sectionInput.value = String(selected.section_path || 'Unassigned');
        if (preInput) preInput.value = helperListToText(selected.pre, false);
        if (stepsInput) stepsInput.value = helperListToText(selected.s, true);
        if (expInput) expInput.value = helperListToText(selected.exp, false);

        helperRenderFinalCasePreviews();
    }

    function helperSyncSelectedFinalCaseFromDetail() {
        const selected = helperGetSelectedFinalCase();
        if (!selected) return false;

        selected.id = String((el('helperCaseIdInput') || {}).value || '').trim();
        selected.t = String((el('helperCaseTitleInput') || {}).value || '').trim();
        selected.priority = String((el('helperCasePriorityInput') || {}).value || 'Medium').trim() || 'Medium';
        const middleParts = selected.id.split('.');
        const middleNo = middleParts.length >= 3 && /^\d{3}$/.test(String(middleParts[middleParts.length - 2] || ''))
            ? String(middleParts[middleParts.length - 2] || '')
            : '';
        let sectionPath = String((el('helperCaseSectionInput') || {}).value || 'Unassigned').trim() || 'Unassigned';
        if (middleNo && sectionPath.toLowerCase() !== 'unassigned') {
            const parts = sectionPath.split('/');
            const first = String(parts[0] || '').trim();
            const rest = parts.slice(1);
            const firstWithoutPrefix = first.replace(/^\d{3}\s+/, '').trim() || '未分類';
            sectionPath = [`${middleNo} ${firstWithoutPrefix}`, ...rest.map((part) => String(part || '').trim()).filter(Boolean)].join('/');
        }
        selected.section_path = sectionPath;
        selected.pre = helperTextToList(String((el('helperCasePreInput') || {}).value || ''), false);
        selected.s = helperTextToList(String((el('helperCaseStepsInput') || {}).value || ''), true);
        selected.exp = helperTextToList(String((el('helperCaseExpInput') || {}).value || ''), false);
        const sectionInput = el('helperCaseSectionInput');
        if (sectionInput && sectionInput.value !== sectionPath) {
            sectionInput.value = sectionPath;
        }
        return true;
    }

    function helperRenderFinalCases(testcases) {
        helperState.finalTestcases = Array.isArray(testcases)
            ? helperDeepClone(testcases)
            : [];
        helperEnsureFinalSelection();
        helperRenderFinalSectionList();
        helperRenderFinalCaseList();
        helperRenderFinalDetail();
    }

    function helperCollectFinalCases() {
        helperSyncSelectedFinalCaseFromDetail();
        const list = Array.isArray(helperState.finalTestcases) ? helperState.finalTestcases : [];
        return helperDeepClone(list);
    }

    function helperValidateFinalCases(testcases) {
        const errors = [];

        if (!Array.isArray(testcases) || !testcases.length) {
            errors.push(helperT('aiHelper.errorNoTestcase', {}, '沒有可提交的 Test Case'));
            return errors;
        }

        testcases.forEach((item, index) => {
            const rowNo = index + 1;
            if (!item.id) {
                errors.push(helperT('aiHelper.errorCaseIdMissing', { index: rowNo }, `第 ${rowNo} 筆缺少 ID`));
            }
            if (!item.t) {
                errors.push(helperT('aiHelper.errorCaseTitleMissing', { index: rowNo }, `第 ${rowNo} 筆缺少標題`));
            }
            if (!Array.isArray(item.s) || item.s.length === 0) {
                errors.push(helperT('aiHelper.errorCaseStepsMissing', { index: rowNo }, `第 ${rowNo} 筆缺少 steps`));
            }
            if (!Array.isArray(item.exp) || item.exp.length !== 1) {
                errors.push(helperT('aiHelper.errorCaseExpRule', { index: rowNo }, `第 ${rowNo} 筆 expected result 必須且只能一筆`));
            }
        });

        return errors;
    }

    async function helperGenerateTestcases() {
        helperClearMessages();
        helperSetBusy(true, helperT('aiHelper.loadingGenerate', {}, '產生 Test Cases 與 Audit 中...'));

        try {
            await helperStartSessionIfNeeded();
            const prePayload = helperGetPretestcasePayloadFromTable();

            if (!prePayload || !Array.isArray(prePayload.en) || prePayload.en.length === 0) {
                throw new Error(helperT('aiHelper.errorPretestcaseEmpty', {}, 'Pre-testcase 條目不可為空'));
            }

            const result = await helperApiFetch(
                `/api/teams/${helperState.teamId}/test-case-helper/sessions/${helperState.sessionId}/generate`,
                {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        pretestcase_payload: prePayload,
                        retry: helperState.generateRuns > 0,
                    }),
                }
            );
            helperState.generateRuns += 1;

            helperApplySession(result.session);

            const casesFromResponse = result && result.payload && Array.isArray(result.payload.tc)
                ? result.payload.tc
                : [];
            const finalDraft = helperGetDraft(result.session, 'final_testcases');
            const finalCases = casesFromResponse.length > 0
                ? casesFromResponse
                : (finalDraft && finalDraft.payload && Array.isArray(finalDraft.payload.tc) ? finalDraft.payload.tc : []);

            if (!finalCases.length) {
                throw new Error(helperT('aiHelper.errorNoGeneratedCases', {}, '未產生可審核的 Test Cases'));
            }

            helperState.finalTestcases = helperDeepClone(finalCases);
            helperRenderFinalCases(helperState.finalTestcases);
            helperSetSuccess(
                helperT('aiHelper.generateDone', {}, 'Test Case 產生完成，請最後確認後提交'),
                { autoHideMs: 5000 },
            );
            helperSetStep(3);
        } catch (error) {
            helperSetError(error.message || helperT('aiHelper.generateFailed', {}, 'Test Case 產生失敗'));
        } finally {
            helperSetBusy(false);
        }
    }

    function helperBuildRedirectUrl(teamId, setId, createdNumbers) {
        const params = new URLSearchParams(window.location.search);
        params.set('team_id', String(teamId));
        params.set('set_id', String(setId));

        if (Array.isArray(createdNumbers) && createdNumbers.length > 0) {
            params.set('helper_created', createdNumbers.join(','));
        }

        return `/test-case-management?${params.toString()}`;
    }

    async function helperCommitTestcases() {
        helperClearMessages();

        const collectedCases = helperCollectFinalCases();
        const validationErrors = helperValidateFinalCases(collectedCases);
        if (validationErrors.length > 0) {
            helperSetError(validationErrors.join('\n'));
            return;
        }

        const confirmText = helperT('aiHelper.commitConfirm', {}, '確認要建立這些 Test Cases 嗎？');
        const confirmed = await helperConfirm(confirmText, {
            confirmClass: 'btn btn-success',
        });
        if (!confirmed) {
            return;
        }

        helperSetBusy(true, helperT('aiHelper.loadingCommit', {}, '提交 Test Cases 中...'));

        try {
            const payload = {
                testcases: collectedCases,
            };

            const result = await helperApiFetch(
                `/api/teams/${helperState.teamId}/test-case-helper/sessions/${helperState.sessionId}/commit`,
                {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload),
                }
            );

            const createdCount = Number(result.created_count || 0);
            const createdNumbers = Array.isArray(result.created_test_case_numbers)
                ? result.created_test_case_numbers
                : [];
            const targetSetId = result.target_test_case_set_id || helperState.targetSetId || helperGetCurrentSetId();

            helperSetSuccess(helperT('aiHelper.commitDone', { count: createdCount }, `已建立 ${createdCount} 筆 Test Case`));
            helperClearStoredSessionId(helperState.teamId);

            if (targetSetId) {
                const redirectUrl = helperBuildRedirectUrl(helperState.teamId, targetSetId, createdNumbers);
                setTimeout(() => {
                    window.location.href = redirectUrl;
                }, 350);
            }
        } catch (error) {
            helperSetError(error.message || helperT('aiHelper.commitFailed', {}, '提交失敗'));
        } finally {
            helperSetBusy(false);
        }
    }

    async function helperOpenModal(options = {}) {
        helperClearMessages();
        const requestedTeamId = Number(options && options.teamId ? options.teamId : 0);

        try {
            helperSetBusy(true, helperT('aiHelper.loadingSets', {}, '載入 Test Case Sets 中...'));
            helperResetPanels();

            const team = await helperResolveTeam(requestedTeamId);
            helperState.teamId = team.id;

            await helperLoadSetOptions(team.id);
            helperToggleSetMode();

            if (!helperState.modalInstance) {
                const modalEl = el('aiTestCaseHelperModal');
                if (modalEl && window.bootstrap && bootstrap.Modal) {
                    helperState.modalInstance = new bootstrap.Modal(modalEl);
                }
            }

            if (!helperState.modalInstance) {
                throw new Error(helperT('aiHelper.modalInitFailed', {}, '無法開啟 Helper 視窗'));
            }

            helperState.modalInstance.show();
            await helperRestoreSession(null, false);
        } catch (error) {
            const message = error.message || helperT('aiHelper.openFailed', {}, '開啟 Helper 失敗');
            helperSetError(message);
        } finally {
            helperSetBusy(false);
        }
    }

    function helperBindToolbar() {
        document.querySelectorAll('#aiTestCaseHelperModal .tc-helper-md-toolbar button[data-md]').forEach((button) => {
            if (button.dataset.bound === '1') return;
            button.dataset.bound = '1';
            button.addEventListener('click', () => {
                const toolbar = button.closest('.tc-helper-md-toolbar');
                if (!toolbar) return;
                const targetId = toolbar.getAttribute('data-target');
                const syntax = button.getAttribute('data-md');
                helperInsertMarkdown(targetId, syntax);
            });
        });
    }

    function helperBindPretestcaseEvents() {
        const sectionList = el('helperPreSectionList');
        if (sectionList && sectionList.dataset.bound !== '1') {
            sectionList.dataset.bound = '1';
            sectionList.addEventListener('click', (event) => {
                const trigger = event.target.closest('[data-helper-pre-section]');
                if (!trigger) return;
                helperSyncSelectedPreEntryFromDetail();
                helperState.selectedPreSection = String(trigger.getAttribute('data-helper-pre-section') || '').trim();
                helperState.selectedPreCid = '';
                helperEnsurePreSelection();
                helperRenderPreSectionList();
                helperRenderPreEntryList();
                helperRenderPreDetail();
            });
        }

        const entryList = el('helperPreEntryList');
        if (entryList && entryList.dataset.bound !== '1') {
            entryList.dataset.bound = '1';
            entryList.addEventListener('click', (event) => {
                const trigger = event.target.closest('[data-helper-pre-cid]');
                if (!trigger) return;
                helperSyncSelectedPreEntryFromDetail();
                helperState.selectedPreCid = String(trigger.getAttribute('data-helper-pre-cid') || '').trim();
                helperEnsurePreSelection();
                helperRenderPreEntryList();
                helperRenderPreDetail();
            });
        }

        const detailFieldIds = [
            'helperPreSectionInput',
            'helperPreTitleInput',
            'helperPreCategoryInput',
            'helperPreStateInput',
            'helperPreRefInput',
            'helperPreNoteInput',
        ];
        detailFieldIds.forEach((id) => {
            const node = el(id);
            if (!node || node.dataset.bound === '1') return;
            node.dataset.bound = '1';
            node.addEventListener('input', () => {
                if (id === 'helperPreSectionInput' || id === 'helperPreStateInput' || id === 'helperPreCategoryInput') {
                    return;
                }
                if (!helperSyncSelectedPreEntryFromDetail()) return;
                helperState.pretestcasePayload = helperNormalizePrePayload(helperState.pretestcasePayload || { en: [] });
                helperEnsurePreSelection();
                helperRenderPreEntryList();
                helperRenderPretestcaseDiff();
            });
            node.addEventListener('change', () => {
                if (!helperSyncSelectedPreEntryFromDetail()) return;
                helperState.pretestcasePayload = helperNormalizePrePayload(helperState.pretestcasePayload || { en: [] });
                helperEnsurePreSelection();
                helperRenderPreSectionList();
                helperRenderPreEntryList();
                helperRenderPreDetail();
                helperRenderPretestcaseDiff();
            });
        });

        const deleteBtn = el('helperDeletePreEntryBtn');
        if (deleteBtn && deleteBtn.dataset.bound !== '1') {
            deleteBtn.dataset.bound = '1';
            deleteBtn.addEventListener('click', () => {
                const entries = helperGetPreEntries();
                const targetIndex = entries.findIndex((entry) => String(entry.cid || '') === helperState.selectedPreCid);
                if (targetIndex < 0) return;

                entries.splice(targetIndex, 1);
                helperState.pretestcasePayload = helperNormalizePrePayload(helperState.pretestcasePayload || { en: [] });
                helperEnsurePreSelection();
                helperRenderPretestcaseTable(helperState.pretestcasePayload);
                helperRenderPretestcaseDiff();
            });
        }
    }

    function helperBindFinalCaseEvents() {
        const sectionList = el('helperFinalSectionList');
        if (sectionList && sectionList.dataset.bound !== '1') {
            sectionList.dataset.bound = '1';
            sectionList.addEventListener('click', (event) => {
                const trigger = event.target.closest('[data-helper-final-section]');
                if (!trigger) return;
                helperSyncSelectedFinalCaseFromDetail();
                helperState.selectedFinalSection = String(trigger.getAttribute('data-helper-final-section') || '').trim();
                helperState.selectedFinalCaseIndex = -1;
                helperEnsureFinalSelection();
                helperRenderFinalSectionList();
                helperRenderFinalCaseList();
                helperRenderFinalDetail();
            });
        }

        const caseList = el('helperFinalCaseList');
        if (caseList && caseList.dataset.bound !== '1') {
            caseList.dataset.bound = '1';
            caseList.addEventListener('click', (event) => {
                const trigger = event.target.closest('[data-helper-final-index]');
                if (!trigger) return;
                helperSyncSelectedFinalCaseFromDetail();
                helperState.selectedFinalCaseIndex = parseInt(
                    String(trigger.getAttribute('data-helper-final-index') || '-1'),
                    10,
                );
                helperEnsureFinalSelection();
                helperRenderFinalCaseList();
                helperRenderFinalDetail();
            });
        }

        const instantPreviewIds = ['helperCasePreInput', 'helperCaseStepsInput', 'helperCaseExpInput'];
        instantPreviewIds.forEach((id) => {
            const node = el(id);
            if (!node || node.dataset.bound === '1') return;
            node.dataset.bound = '1';
            node.addEventListener('input', () => {
                if (!helperSyncSelectedFinalCaseFromDetail()) return;
                helperRenderFinalCasePreviews();
            });
            node.addEventListener('change', () => {
                if (!helperSyncSelectedFinalCaseFromDetail()) return;
                helperRenderFinalCasePreviews();
            });
        });

        const summaryFieldIds = ['helperCaseIdInput', 'helperCaseTitleInput', 'helperCasePriorityInput', 'helperCaseSectionInput'];
        summaryFieldIds.forEach((id) => {
            const node = el(id);
            if (!node || node.dataset.bound === '1') return;
            node.dataset.bound = '1';
            node.addEventListener('input', () => {
                if (!helperSyncSelectedFinalCaseFromDetail()) return;
                if (id === 'helperCaseSectionInput') {
                    helperState.selectedFinalSection = String((el('helperCaseSectionInput') || {}).value || 'Unassigned').trim() || 'Unassigned';
                    helperEnsureFinalSelection();
                }
                helperRenderFinalSectionList();
                helperRenderFinalCaseList();
            });
            node.addEventListener('change', () => {
                if (!helperSyncSelectedFinalCaseFromDetail()) return;
                if (id === 'helperCaseSectionInput') {
                    helperState.selectedFinalSection = String((el('helperCaseSectionInput') || {}).value || 'Unassigned').trim() || 'Unassigned';
                    helperEnsureFinalSelection();
                }
                helperRenderFinalSectionList();
                helperRenderFinalCaseList();
                if (id === 'helperCasePriorityInput') {
                    helperRenderFinalDetail();
                }
            });
        });
    }

    function helperBindStepperClicks() {
        document.querySelectorAll('#aiTestCaseHelperModal .tc-helper-step').forEach((node) => {
            if (node.dataset.bound === '1') return;
            node.dataset.bound = '1';
            node.addEventListener('click', () => {
                const targetStep = parseInt(node.getAttribute('data-helper-step') || '1', 10);
                const availableStep = helperResolveAvailableStep();
                if (targetStep > availableStep) {
                    helperNotifyWarning(helperT('aiHelper.stepLocked', {}, '請先完成前一階段')); 
                    return;
                }
                helperSetStep(targetStep);
            });
        });
    }

    function helperBindButtons() {
        const helperBtn = el('aiTestCaseHelperBtn');
        if (helperBtn && helperBtn.dataset.bound !== '1') {
            helperBtn.dataset.bound = '1';
            helperBtn.addEventListener('click', helperOpenModal);
        }

        const restoreBtn = el('helperRestoreSessionBtn');
        if (restoreBtn && restoreBtn.dataset.bound !== '1') {
            restoreBtn.dataset.bound = '1';
            restoreBtn.addEventListener('click', async () => {
                helperClearMessages();
                await helperRestoreSession(null, true);
            });
        }

        const startOverBtn = el('helperStartOverBtn');
        if (startOverBtn && startOverBtn.dataset.bound !== '1') {
            startOverBtn.dataset.bound = '1';
            startOverBtn.addEventListener('click', helperStartOver);
        }

        const normalizeBtn = el('helperNormalizeBtn');
        if (normalizeBtn && normalizeBtn.dataset.bound !== '1') {
            normalizeBtn.dataset.bound = '1';
            normalizeBtn.addEventListener('click', helperNormalizeRequirement);
        }

        const generateBtn = el('helperGenerateBtn');
        if (generateBtn && generateBtn.dataset.bound !== '1') {
            generateBtn.dataset.bound = '1';
            generateBtn.addEventListener('click', helperGenerateTestcases);
        }

        const commitBtn = el('helperCommitBtn');
        if (commitBtn && commitBtn.dataset.bound !== '1') {
            commitBtn.dataset.bound = '1';
            commitBtn.addEventListener('click', helperCommitTestcases);
        }

        const addPreRowBtn = el('helperAddPretestcaseRowBtn');
        if (addPreRowBtn && addPreRowBtn.dataset.bound !== '1') {
            addPreRowBtn.dataset.bound = '1';
            addPreRowBtn.addEventListener('click', () => {
                helperGetPretestcasePayloadFromTable();
                const next = helperGenerateNextCid();
                const entries = helperGetPreEntries();
                const idx = entries.length + 1;
                const defaultSection = helperState.selectedPreSection || helperT('aiHelper.defaultPreSection', {}, '未分類');
                const newEntry = {
                    idx,
                    g: defaultSection,
                    t: '',
                    cat: 'happy',
                    st: 'ok',
                    ref: [],
                    cid: `${next.sn}.${next.tn}`,
                    sn: next.sn,
                    tn: next.tn,
                    req: [],
                };

                entries.push(newEntry);
                helperState.selectedPreSection = defaultSection;
                helperState.selectedPreCid = newEntry.cid;
                helperState.pretestcasePayload = helperNormalizePrePayload(helperState.pretestcasePayload || { en: [] });
                helperRenderPretestcaseTable(helperState.pretestcasePayload);
                helperRenderPretestcaseDiff();
            });
        }

        const prevBtn = el('helperPrevBtn');
        if (prevBtn && prevBtn.dataset.bound !== '1') {
            prevBtn.dataset.bound = '1';
            prevBtn.addEventListener('click', () => {
                helperSetStep(helperState.currentStep - 1);
            });
        }

        const nextBtn = el('helperNextBtn');
        if (nextBtn && nextBtn.dataset.bound !== '1') {
            nextBtn.dataset.bound = '1';
            nextBtn.addEventListener('click', () => {
                const targetStep = helperState.currentStep + 1;
                const availableStep = helperResolveAvailableStep();
                if (targetStep > availableStep) {
                    helperNotifyWarning(helperT('aiHelper.stepLocked', {}, '請先完成前一階段'));
                    return;
                }
                helperSetStep(targetStep);
            });
        }

        const setModeExisting = el('helperSetModeExisting');
        const setModeCreate = el('helperSetModeCreate');
        if (setModeExisting && setModeExisting.dataset.bound !== '1') {
            setModeExisting.dataset.bound = '1';
            setModeExisting.addEventListener('change', helperToggleSetMode);
        }
        if (setModeCreate && setModeCreate.dataset.bound !== '1') {
            setModeCreate.dataset.bound = '1';
            setModeCreate.addEventListener('change', helperToggleSetMode);
        }
    }

    function helperInitializeModalLifecycle() {
        const modalEl = el('aiTestCaseHelperModal');
        if (!modalEl || modalEl.dataset.bound === '1') return;

        modalEl.dataset.bound = '1';

        modalEl.addEventListener('shown.bs.modal', () => {
            helperSyncStepperLayout();
            helperBindToolbar();
            helperBindPretestcaseEvents();
            helperBindFinalCaseEvents();
            helperBindStepperClicks();
            if (window.i18n && window.i18n.isReady && window.i18n.isReady()) {
                window.i18n.retranslate(modalEl);
            }
        });

        modalEl.addEventListener('hidden.bs.modal', () => {
            helperSetBusy(false);
            helperClearMessages();
        });
    }

    function helperInitCreatedCaseHighlightFromUrl() {
        const params = new URLSearchParams(window.location.search);
        const raw = params.get('helper_created');
        if (!raw) return;

        const numbers = raw
            .split(',')
            .map((item) => String(item || '').trim())
            .filter(Boolean);

        if (!numbers.length) {
            params.delete('helper_created');
            const query = params.toString();
            history.replaceState({}, '', query ? `${window.location.pathname}?${query}` : window.location.pathname);
            return;
        }

        window.__tcHelperCreatedNumbers = new Set(numbers);

        if (window.AppUtils && AppUtils.showSuccess) {
            AppUtils.showSuccess(helperT('aiHelper.createdHighlightNotice', { count: numbers.length }, `已建立 ${numbers.length} 筆 Test Case`));
        }

        params.delete('helper_created');
        const query = params.toString();
        history.replaceState({}, '', query ? `${window.location.pathname}?${query}` : window.location.pathname);
    }

    function helperShouldAutoOpenFromUrl() {
        const params = new URLSearchParams(window.location.search);
        const raw = String(params.get('helper') || '').trim().toLowerCase();
        return raw === '1' || raw === 'true';
    }

    function helperRemoveQueryParam(paramName) {
        const params = new URLSearchParams(window.location.search);
        if (!params.has(paramName)) return;
        params.delete(paramName);
        const query = params.toString();
        history.replaceState({}, '', query ? `${window.location.pathname}?${query}` : window.location.pathname);
    }

    async function helperAutoOpenFromUrlIfNeeded() {
        if (helperState.autoOpenConsumed) return;
        if (!helperShouldAutoOpenFromUrl()) return;

        helperState.autoOpenConsumed = true;
        await helperOpenModal();
    }

    function initAiHelperWizard() {
        if (helperState.initialized) return;
        helperState.initialized = true;

        helperBindButtons();
        helperInitializeModalLifecycle();
        helperToggleSetMode();
        helperInitCreatedCaseHighlightFromUrl();
        setTimeout(() => {
            helperAutoOpenFromUrlIfNeeded();
        }, 0);
    }

    window.AiTestCaseHelper = window.AiTestCaseHelper || {};
    window.AiTestCaseHelper.openModal = helperOpenModal;

    document.addEventListener('DOMContentLoaded', initAiHelperWizard);
})();
