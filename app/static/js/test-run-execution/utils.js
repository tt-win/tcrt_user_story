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
    if (!content) return '';

    if (typeof marked !== 'undefined') {
        try {
            return marked.parse(content);
        } catch (error) {
            console.error('Markdown parse error:', error);
            // 如果 Markdown 渲染失敗，回退到純文字顯示
            return `<pre style="white-space: pre-wrap; font-size: 0.9rem;">${escapeHtml(content)}</pre>`;
        }
    } else {
        // 如果 marked 庫未載入，回退到純文字顯示
        return `<pre style="white-space: pre-wrap; font-size: 0.9rem;">${escapeHtml(content)}</pre>`;
    }
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
