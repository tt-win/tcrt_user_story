/* ============================================================
   TEST CASE MANAGEMENT - AI ASSIST
   ============================================================ */

function getAIAssistFieldLabel(fieldId) {
    const meta = aiAssistFieldMap.get(fieldId);
    if (!meta) return '';
    if (window.i18n && window.i18n.isReady && window.i18n.isReady()) {
        return window.i18n.t(meta.labelKey, {}, meta.fallback) || meta.fallback;
    }
    return meta.fallback;
}

function getAIAssistModalElements(meta) {
    if (!meta) return {};
    const key = meta.modalKey;
    return {
        originalEl: document.getElementById(`aiAssistOriginal${key}`),
        revisedEl: document.getElementById(`aiAssistRevised${key}`),
        previewEl: document.getElementById(`aiAssistPreview${key}`),
        selectEl: document.getElementById(`aiAssistSelect${key}`)
    };
}

function getAIAssistUiLocale() {
    if (window.i18n && window.i18n.currentLanguage) {
        return window.i18n.currentLanguage;
    }
    return navigator.language || 'en-US';
}

function setAIAssistLoading(isLoading) {
    const loadingEl = document.getElementById('aiAssistLoading');
    const regenerateBtn = document.getElementById('aiAssistRegenerateBtn');
    const applySelectedBtn = document.getElementById('aiAssistApplySelectedBtn');
    const applyAllBtn = document.getElementById('aiAssistApplyAllBtn');
    if (loadingEl) {
        loadingEl.classList.toggle('d-none', !isLoading);
    }
    if (regenerateBtn) regenerateBtn.disabled = isLoading;
    if (applySelectedBtn) applySelectedBtn.disabled = isLoading;
    if (applyAllBtn) applyAllBtn.disabled = isLoading;
    document.querySelectorAll('.ai-assist-revised').forEach(textarea => {
        textarea.readOnly = isLoading;
    });
}

function setAIAssistError(message) {
    const errorEl = document.getElementById('aiAssistError');
    if (!errorEl) return;
    if (message) {
        errorEl.textContent = message;
        errorEl.classList.remove('d-none');
    } else {
        errorEl.textContent = '';
        errorEl.classList.add('d-none');
    }
}

function updateAIAssistActionLabel() {
    const actionBtn = document.getElementById('aiAssistRegenerateBtn');
    if (!actionBtn) return;
    const key = aiAssistHasResponse ? 'aiAssist.regenerate' : 'aiAssist.refine';
    const fallback = aiAssistHasResponse ? '重新建議' : '開始改寫';
    if (window.i18n && window.i18n.isReady && window.i18n.isReady()) {
        actionBtn.textContent = window.i18n.t(key, {}, fallback);
    } else {
        actionBtn.textContent = fallback;
    }
}

function renderAIAssistSuggestions(suggestions) {
    const listEl = document.getElementById('aiAssistSuggestions');
    const emptyEl = document.getElementById('aiAssistSuggestionsEmpty');
    if (!listEl) return;
    const items = Array.isArray(suggestions) ? suggestions : [];
    const cleaned = items.map(item => String(item || '').trim()).filter(Boolean);
    listEl.innerHTML = cleaned.map(item => `<li class="list-group-item">${escapeHtml(item)}</li>`).join('');
    if (emptyEl) {
        emptyEl.classList.toggle('d-none', cleaned.length > 0);
    }
}

async function requestAIAssist(payload) {
    setAIAssistLoading(true);
    setAIAssistError('');
    try {
        const currentTeam = AppUtils.getCurrentTeam ? AppUtils.getCurrentTeam() : null;
        const resolvedTeam = currentTeam && currentTeam.id ? currentTeam : await ensureTeamContext();
        if (!resolvedTeam || !resolvedTeam.id) {
            throw new Error(window.i18n ? window.i18n.t('errors.pleaseSelectTeam', {}, '請先選擇團隊') : '請先選擇團隊');
        }
        const response = await window.AuthClient.fetch(`/api/teams/${resolvedTeam.id}/testcases/ai-assist`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        if (!response.ok) {
            let detail = '';
            try {
                const errorData = await response.json();
                detail = errorData.detail || '';
            } catch (_) {}
            const fallback = window.i18n ? window.i18n.t('aiAssist.error', {}, 'AI 生成失敗') : 'AI 生成失敗';
            throw new Error(detail ? `${fallback}: ${detail}` : fallback);
        }
        const data = await response.json();
        const revisedPrecondition = data.revised_precondition;
        const revisedSteps = data.revised_steps;
        const revisedExpectedResult = data.revised_expected_result;
        if (
            typeof revisedPrecondition !== 'string'
            || typeof revisedSteps !== 'string'
            || typeof revisedExpectedResult !== 'string'
        ) {
            throw new Error(window.i18n ? window.i18n.t('aiAssist.error', {}, 'AI 生成失敗') : 'AI 生成失敗');
        }
        aiAssistFieldConfig.forEach(meta => {
            const elements = getAIAssistModalElements(meta);
            if (!elements.revisedEl) return;
            if (meta.apiField === 'precondition') {
                elements.revisedEl.value = revisedPrecondition;
            } else if (meta.apiField === 'steps') {
                elements.revisedEl.value = revisedSteps;
            } else if (meta.apiField === 'expected_result') {
                elements.revisedEl.value = revisedExpectedResult;
            }
            updateAIAssistPreview(meta);
        });
        renderAIAssistSuggestions(data.suggestions || []);
        aiAssistHasResponse = true;
        updateAIAssistActionLabel();
    } catch (error) {
        console.error('AI assist error:', error);
        const errorMessage = error?.message || (window.i18n ? window.i18n.t('aiAssist.error', {}, 'AI 生成失敗') : 'AI 生成失敗');
        setAIAssistError(errorMessage);
    } finally {
        setAIAssistLoading(false);
    }
}

function getAIAssistModalPayload() {
    const payload = {
        precondition: '',
        steps: '',
        expected_result: '',
        ui_locale: getAIAssistUiLocale()
    };
    aiAssistFieldConfig.forEach(meta => {
        const elements = getAIAssistModalElements(meta);
        const value = String(elements.revisedEl ? elements.revisedEl.value : '').trim();
        if (meta.apiField === 'precondition') {
            payload.precondition = value;
        } else if (meta.apiField === 'steps') {
            payload.steps = value;
        } else if (meta.apiField === 'expected_result') {
            payload.expected_result = value;
        }
    });
    return payload;
}

function hasAIAssistPayloadContent(payload) {
    return Boolean(
        (payload.precondition || '').trim()
        || (payload.steps || '').trim()
        || (payload.expected_result || '').trim()
    );
}

function updateAIAssistPreview(meta) {
    const elements = getAIAssistModalElements(meta);
    if (!elements.revisedEl || !elements.previewEl) return;
    renderMarkdownToElement(elements.revisedEl.value || '', elements.previewEl);
}

function openAIAssistModal() {
    const fieldValues = aiAssistFieldConfig.map(meta => {
        const textarea = document.getElementById(meta.fieldId);
        return { meta, value: String(textarea ? textarea.value : '') };
    });
    const hasContent = fieldValues.some(item => item.value.trim());
    if (!hasContent) {
        const message = window.i18n ? window.i18n.t('aiAssist.emptyInput', {}, '請先輸入內容') : '請先輸入內容';
        if (window.AppUtils && window.AppUtils.showWarning) {
            window.AppUtils.showWarning(message);
        } else {
            alert(message);
        }
        return;
    }

    initializeAIAssistModal();
    aiAssistHasResponse = false;

    fieldValues.forEach(({ meta, value }) => {
        const elements = getAIAssistModalElements(meta);
        if (elements.originalEl) {
            elements.originalEl.value = value;
        }
        if (elements.revisedEl) {
            elements.revisedEl.value = value;
        }
        if (elements.selectEl) {
            elements.selectEl.checked = true;
        }
        updateAIAssistPreview(meta);
    });

    renderAIAssistSuggestions([]);
    setAIAssistError('');
    updateAIAssistActionLabel();

    if (aiAssistModalInstance) {
        aiAssistModalInstance.show();
    }
}

function applyAIAssistResult(applyAll) {
    let applied = false;
    aiAssistFieldConfig.forEach(meta => {
        const elements = getAIAssistModalElements(meta);
        const shouldApply = applyAll || (elements.selectEl && elements.selectEl.checked);
        if (!shouldApply || !elements.revisedEl) return;
        const target = document.getElementById(meta.fieldId);
        if (!target) return;
        target.value = String(elements.revisedEl.value || '');
        target.dispatchEvent(new Event('input'));
        updateMarkdownPreview(meta.fieldId);
        applied = true;
    });

    if (!applyAll && !applied) {
        const message = window.i18n ? window.i18n.t('aiAssist.selectAtLeastOne', {}, '請先選擇要套用的欄位') : '請先選擇要套用的欄位';
        if (window.AppUtils && window.AppUtils.showWarning) {
            window.AppUtils.showWarning(message);
        } else {
            alert(message);
        }
        return;
    }

    if (applied && typeof checkFormChanges === 'function') {
        checkFormChanges();
    }
    if (aiAssistModalInstance) {
        aiAssistModalInstance.hide();
    }
}

function initializeAIAssistModal() {
    if (aiAssistInitialized) return;
    const modalEl = document.getElementById('aiAssistModal');
    if (!modalEl) return;
    aiAssistModalInstance = new bootstrap.Modal(modalEl);
    const regenerateBtn = document.getElementById('aiAssistRegenerateBtn');
    const applySelectedBtn = document.getElementById('aiAssistApplySelectedBtn');
    const applyAllBtn = document.getElementById('aiAssistApplyAllBtn');
    if (regenerateBtn) {
        regenerateBtn.addEventListener('click', () => {
            const payload = getAIAssistModalPayload();
            if (!hasAIAssistPayloadContent(payload)) {
                const message = window.i18n ? window.i18n.t('aiAssist.emptyInput', {}, '請先輸入內容') : '請先輸入內容';
                if (window.AppUtils && window.AppUtils.showWarning) {
                    window.AppUtils.showWarning(message);
                } else {
                    alert(message);
                }
                return;
            }
            requestAIAssist(payload);
        });
    }
    if (applySelectedBtn) {
        applySelectedBtn.addEventListener('click', () => applyAIAssistResult(false));
    }
    if (applyAllBtn) {
        applyAllBtn.addEventListener('click', () => applyAIAssistResult(true));
    }
    document.querySelectorAll('.ai-assist-revised').forEach(textarea => {
        textarea.addEventListener('input', () => {
            const fieldId = textarea.getAttribute('data-field');
            const meta = aiAssistFieldMap.get(fieldId);
            if (!meta) return;
            updateAIAssistPreview(meta);
        });
    });
    modalEl.addEventListener('hidden.bs.modal', () => {
        aiAssistHasResponse = false;
        setAIAssistError('');
        renderAIAssistSuggestions([]);
        setAIAssistLoading(false);
        aiAssistFieldConfig.forEach(meta => {
            const elements = getAIAssistModalElements(meta);
            if (elements.originalEl) {
                elements.originalEl.value = '';
            }
            if (elements.revisedEl) {
                elements.revisedEl.value = '';
            }
            if (elements.previewEl) {
                elements.previewEl.innerHTML = '';
            }
            if (elements.selectEl) {
                elements.selectEl.checked = true;
            }
        });
        updateAIAssistActionLabel();
    });
    aiAssistInitialized = true;
}

function bindAIAssistUnifiedButton() {
    const aiButton = document.getElementById('aiAssistUnifiedBtn');
    if (!aiButton || aiButton.dataset.bound) return;
    aiButton.addEventListener('click', openAIAssistModal);
    aiButton.dataset.bound = 'true';
}
