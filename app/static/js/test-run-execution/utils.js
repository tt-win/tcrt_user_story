/* Test Run Execution - Shared Helpers */

function treTranslate(key, params, fallback) {
    let resolvedParams = params;
    let resolvedFallback = fallback;
    if (typeof resolvedParams === 'string') {
        resolvedFallback = resolvedParams;
        resolvedParams = {};
    }
    if (!resolvedParams) resolvedParams = {};

    if (window.i18n && typeof window.i18n.t === 'function') {
        const text = window.i18n.t(key, resolvedParams, resolvedFallback);
        if (text && text !== key) return text;
    }
    return typeof resolvedFallback !== 'undefined' ? resolvedFallback : key;
}

function escapeHtml(text) {
    if (!text) return '';
    const map = {
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#039;'
    };
    return text.replace(/[&<>"']/g, function(m) { return map[m]; });
}

// Markdown 渲染輔助函數
function renderMarkdown(content) {
    return getMarkdownRenderResult(content).html;
}

function getMarkdownFallbackHtml(source) {
    return `<pre>${escapeHtml(source)}</pre>`;
}

function getMarkdownRenderResult(content) {
    const source = content === undefined || content === null ? '' : String(content);
    if (!source) {
        return { html: '', status: 'ok' };
    }

    const adapter = window.TCRTMarkdown;
    if (!adapter || typeof adapter.render !== 'function') {
        return { html: getMarkdownFallbackHtml(source), status: 'fallback', reason: 'adapter-unavailable' };
    }

    try {
        const result = adapter.render(source, { surface: 'test-run-execution' });
        if (!result || typeof result.html !== 'string') {
            return { html: getMarkdownFallbackHtml(source), status: 'fallback', reason: 'invalid-adapter-result' };
        }
        return {
            html: result.html,
            status: result.status === 'ok' ? 'ok' : 'fallback',
            ...(result.reason ? { reason: String(result.reason) } : {})
        };
    } catch (_) {
        return { html: getMarkdownFallbackHtml(source), status: 'fallback', reason: 'adapter-error' };
    }
}

function invalidateMarkdownRerender(element) {
    if (!element) return;
    element._markdownRenderRetryVersion = (element._markdownRenderRetryVersion || 0) + 1;
}

function getMarkdownRenderAttributes(source, result) {
    const normalizedSource = source === undefined || source === null ? '' : String(source);
    const status = result && result.status === 'ok' ? 'ok' : 'fallback';
    const encodedSource = encodeURIComponent(normalizedSource);
    const reason = result && result.reason ? ` data-markdown-reason="${escapeHtml(String(result.reason))}"` : '';
    return `data-markdown-source="${encodedSource}" data-markdown-status="${status}"${reason}`;
}

function applyMarkdownRenderState(element, result) {
    if (!element) return;
    const status = result && result.status === 'ok' ? 'ok' : 'fallback';
    element.setAttribute('data-markdown-status', status);
    if (result && result.reason) {
        element.setAttribute('data-markdown-reason', String(result.reason));
    } else {
        element.removeAttribute('data-markdown-reason');
    }
    element.classList.toggle('markdown-render-fallback', status === 'fallback');

    const existingIndicator = element.querySelector('[data-markdown-render-status]');
    if (status === 'fallback') {
        const indicator = existingIndicator || document.createElement('span');
        const fallback = treTranslate('errors.markdownRendererUnavailable', 'Markdown preview unavailable; showing source text.');
        indicator.setAttribute('data-markdown-render-status', 'fallback');
        indicator.setAttribute('data-i18n', 'errors.markdownRendererUnavailable');
        indicator.setAttribute('data-i18n-fallback', fallback);
        indicator.setAttribute('role', 'status');
        indicator.setAttribute('aria-live', 'polite');
        indicator.className = 'markdown-render-status text-muted small d-block mt-1';
        indicator.textContent = fallback;
        if (!existingIndicator) element.appendChild(indicator);
        if (window.i18n && typeof window.i18n.retranslate === 'function') {
            window.i18n.retranslate(indicator);
        }
    } else if (existingIndicator) {
        existingIndicator.remove();
    }
}

function applyMarkdownRenderStates(root) {
    if (!root) return;
    root.querySelectorAll('.markdown-preview[data-markdown-source][data-markdown-status]')
        .forEach((element) => {
            applyMarkdownRenderState(element, {
                status: element.getAttribute('data-markdown-status') === 'ok' ? 'ok' : 'fallback',
                reason: element.getAttribute('data-markdown-reason') || undefined
            });
        });
}

function rerenderMarkdownElement(element) {
    if (!element) return;
    const encodedSource = element.getAttribute('data-markdown-source') || '';
    let source = '';
    try {
        source = decodeURIComponent(encodedSource);
    } catch (_) {
        return;
    }
    const result = getMarkdownRenderResult(source);
    element.innerHTML = result.html;
    applyMarkdownRenderState(element, result);
}

function scheduleMarkdownRerender(root) {
    const adapter = window.TCRTMarkdown;
    if (!root || !adapter || !adapter.ready || typeof adapter.ready.then !== 'function') return;
    const pendingElements = Array.from(root.querySelectorAll('[data-markdown-status="fallback"][data-markdown-source]'))
        .map((element) => ({
            element,
            source: element.getAttribute('data-markdown-source') || '',
            version: element._markdownRenderRetryVersion || 0
        }));
    if (!pendingElements.length) return;

    Promise.resolve(adapter.ready).then((ready) => {
        if (!ready || ready.status !== 'ok') return;
        if (root.isConnected === false) return;
        pendingElements.forEach(({ element, source, version }) => {
            if (!element.isConnected || element._markdownRenderRetryVersion !== version) return;
            if (element.getAttribute('data-markdown-source') !== source
                || element.getAttribute('data-markdown-status') !== 'fallback') return;
            rerenderMarkdownElement(element);
        });
    }).catch(() => {});
}

function getResultClass(result) {
    const classMap = {
        'Passed': 'result-passed',
        'Failed': 'result-failed',
        'Retest': 'result-retest',
        'Not Available': 'result-na',
        'Pending': 'result-pending',
        'Not Required': 'result-not-required',
        'Skip': 'result-skip'
    };
    return classMap[result] || 'result-pending';
}

function getResultText(result) {
    const textMap = {
        'Passed': treTranslate('testRun.passed', 'Passed'),
        'Failed': treTranslate('testRun.failed', 'Failed'),
        'Retest': treTranslate('testRun.retest', 'Retest'),
        'Not Available': treTranslate('testRun.notAvailable', 'Not Available'),
        'Pending': treTranslate('testRun.pending', 'Pending'),
        'Not Required': treTranslate('testRun.notRequired', 'Not Required'),
        'Skip': treTranslate('testRun.skip', 'Skip')
    };
    return textMap[result] || treTranslate('testRun.notExecuted', 'Not Executed');
}

/**
 * 根據檔案名稱取得對應的檔案圖標
 */
function getFileIcon(fileName) {
    if (!fileName) return 'fas fa-file';

    const lowerName = fileName.toLowerCase();

    // PDF
    if (lowerName.endsWith('.pdf')) {
        return 'fas fa-file-pdf text-danger';
    }

    // Word
    if (lowerName.endsWith('.doc') || lowerName.endsWith('.docx')) {
        return 'fas fa-file-word text-primary';
    }

    // Excel
    if (lowerName.endsWith('.xls') || lowerName.endsWith('.xlsx')) {
        return 'fas fa-file-excel text-success';
    }

    // PowerPoint
    if (lowerName.endsWith('.ppt') || lowerName.endsWith('.pptx')) {
        return 'fas fa-file-powerpoint text-warning';
    }

    // Images
    if (lowerName.match(/\.(jpg|jpeg|png|gif|bmp|svg|webp)$/)) {
        return 'fas fa-file-image text-info';
    }

    // Archive
    if (lowerName.match(/\.(zip|rar|7z|tar|gz)$/)) {
        return 'fas fa-file-archive text-secondary';
    }

    // Video
    if (lowerName.match(/\.(mp4|avi|mov|mkv|flv|wmv)$/)) {
        return 'fas fa-file-video text-danger';
    }

    // Audio
    if (lowerName.match(/\.(mp3|wav|flac|aac|ogg)$/)) {
        return 'fas fa-file-audio text-primary';
    }

    // Text
    if (lowerName.match(/\.(txt|log|csv)$/)) {
        return 'fas fa-file-lines text-secondary';
    }

    // Default
    return 'fas fa-file text-muted';
}

async function resolveTeamFromUrl_TRE(teamParam) {
    const requestedTeamText = String(teamParam || '').trim();
    if (!/^[1-9]\d*$/.test(requestedTeamText) || typeof AppUtils === 'undefined') {
        return null;
    }

    const requestedTeamId = Number(requestedTeamText);
    const currentTeam = typeof AppUtils.getCurrentTeam === 'function'
        ? AppUtils.getCurrentTeam()
        : null;
    if (currentTeam && String(currentTeam.id) === requestedTeamText) {
        return currentTeam;
    }

    if (!window.AuthClient || typeof window.AuthClient.fetch !== 'function'
        || typeof AppUtils.setCurrentTeam !== 'function') {
        return null;
    }

    try {
        const response = await window.AuthClient.fetch('/api/teams/');
        if (!response.ok) return null;

        const teams = await response.json();
        if (!Array.isArray(teams)) return null;

        const targetTeam = teams.find((team) => Number(team?.id) === requestedTeamId);
        if (!targetTeam) return null;

        AppUtils.setCurrentTeam(targetTeam);
        if (typeof AppUtils.updateTeamNameBadge === 'function') {
            AppUtils.updateTeamNameBadge();
        }
        return targetTeam;
    } catch (_) {
        return null;
    }
}

function getCurrentTeamId() {
    try {
        const cur = AppUtils.getCurrentTeam && AppUtils.getCurrentTeam();
        if (cur && cur.id) return cur.id;
    } catch (_) {}
    const p = new URLSearchParams(window.location.search);
    const t = p.get('team_id') || p.get('teamId') || p.get('team');
    return t ? parseInt(t) : undefined;
}

function buildTreUrl(configId, teamId, tcNumber) {
    const origin = window.location.origin;
    const params = new URLSearchParams();
    if (configId) params.set('config_id', configId);
    if (teamId) params.set('team_id', teamId);
    if (tcNumber) params.set('tc', tcNumber);
    return `${origin}/test-run-execution?${params.toString()}`;
}

function safeCopyToClipboard(text, onSuccess, onError) {
    if (navigator && navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
        navigator.clipboard.writeText(text).then(() => { if (onSuccess) onSuccess(); }).catch(err => {
            try {
                const temp = document.createElement('input');
                temp.value = text;
                document.body.appendChild(temp);
                temp.select();
                document.execCommand('copy');
                document.body.removeChild(temp);
                if (onSuccess) onSuccess();
            } catch (e) { if (onError) onError(e); }
        });
    } else {
        try {
            const temp = document.createElement('input');
            temp.value = text;
            document.body.appendChild(temp);
            temp.select();
            document.execCommand('copy');
            document.body.removeChild(temp);
            if (onSuccess) onSuccess();
        } catch (e) { if (onError) onError(e); }
    }
}

function ensureTeamIdInUrl_TRE(teamId) {
    try {
        const url = new URL(window.location.href);
        const before = url.searchParams.get('team_id');
        if (String(before || '') !== String(teamId)) {
            url.searchParams.set('team_id', teamId);
            history.replaceState(null, '', `${url.pathname}?${url.searchParams.toString()}`);
        }
    } catch (_) {}
}
