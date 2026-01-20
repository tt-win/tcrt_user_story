// 讓頁面更像彈窗：隱藏 Header/Footer
document.addEventListener('DOMContentLoaded', function() {
    document.body.classList.add('popup-minimal');

    // 從 URL 設定 team_id 到 AppUtils（若未設定）
    try {
        const urlParams = new URLSearchParams(window.location.search);
        const teamIdParam = urlParams.get('team_id');
        if (teamIdParam && (!AppUtils.getCurrentTeam() || !AppUtils.getCurrentTeam().id)) {
            const teamId = parseInt(teamIdParam);
            if (!isNaN(teamId)) {
                AppUtils.setCurrentTeam({ id: teamId, name: 'Popup Reference' });
            }
        }
    } catch (_) {}

    // i18n 應用
    if (window.i18n && window.i18n.isReady()) {
        window.i18n.retranslate(document);
    }

    // 綁定搜尋
    const searchInput = document.getElementById('referenceSearchInputPage');
    if (searchInput) {
        let debounce;
        searchInput.addEventListener('input', function() {
            const q = this.value.trim();
            if (debounce) clearTimeout(debounce);
            if (!q) { showInitial(); hideFrame(); return; }
            debounce = setTimeout(() => doSearch(q), 400);
        });
        setTimeout(() => searchInput.focus(), 200);
    }
});

function showInitial() {
    document.getElementById('referenceInitialMessagePage').style.display = 'block';
    document.getElementById('referenceLoadingMessagePage').style.display = 'none';
    document.getElementById('referenceNoResultsMessagePage').style.display = 'none';
    clearResults();
}

function showLoading() {
    document.getElementById('referenceInitialMessagePage').style.display = 'none';
    document.getElementById('referenceLoadingMessagePage').style.display = 'block';
    document.getElementById('referenceNoResultsMessagePage').style.display = 'none';
}

function showNoResults() {
    document.getElementById('referenceInitialMessagePage').style.display = 'none';
    document.getElementById('referenceLoadingMessagePage').style.display = 'none';
    document.getElementById('referenceNoResultsMessagePage').style.display = 'block';
}

function clearResults() {
    const container = document.getElementById('referenceSearchResultsPage');
    container.querySelectorAll('.reference-result-item').forEach(n => n.remove());
}

function hideFrame() {
    const frame = document.getElementById('referenceTestCaseFramePage');
    const holder = document.getElementById('referencePlaceholderPage');
    if (frame) {
        frame.style.display = 'none';
        frame.src = 'about:blank'; // 清空 iframe
    }
    if (holder) holder.style.display = 'flex';  // 顯示占位區
}

function showFrame() {
    const frame = document.getElementById('referenceTestCaseFramePage');
    const holder = document.getElementById('referencePlaceholderPage');
    if (holder) holder.style.display = 'none'; // 先隱藏占位區
    if (frame) frame.style.display = 'block';  // 再顯示 iframe
}

async function doSearch(query) {
    try {
        showLoading();
        hideFrame();
        const team = AppUtils.getCurrentTeam();
        if (!team || !team.id) throw new Error('請先選擇團隊');
        const resp = await window.AuthClient.fetch(`/api/teams/${team.id}/testcases/?search=${encodeURIComponent(query)}&limit=50`);
        if (!resp.ok) throw new Error('搜尋失敗');
        const arr = await resp.json();
        renderResults(arr || []);
    } catch (e) {
        console.error('搜尋參考測試案例失敗:', e);
        showNoResults();
        const msg = window.i18n ? window.i18n.t('testCase.referenceTestCaseError', {}, '載入參考測試案例失敗') : '載入參考測試案例失敗';
        AppUtils.showError(msg + ': ' + (e.message || e));
    }
}

function renderResults(testCases) {
    const container = document.getElementById('referenceSearchResultsPage');
    clearResults();
    document.getElementById('referenceInitialMessagePage').style.display = 'none';
    document.getElementById('referenceLoadingMessagePage').style.display = 'none';
    document.getElementById('referenceNoResultsMessagePage').style.display = testCases.length ? 'none' : 'block';

    testCases.forEach(tc => {
        const div = document.createElement('div');
        div.className = 'reference-result-item border-bottom p-2';
        div.style.cursor = 'pointer';
        div.innerHTML = `
        <div class="mb-1"><strong class="text-primary">${escapeHtml(tc.test_case_number || '無編號')}</strong></div>
        <div class="text-dark" style="font-size:0.9em;line-height:1.3;">${escapeHtml(tc.title || '無標題')}</div>`;
        div.addEventListener('click', () => selectTestCase(tc, div));
        div.addEventListener('mouseenter', ()=>{ div.style.backgroundColor = '#f8f9fa'; });
        div.addEventListener('mouseleave', ()=>{ if (!div.classList.contains('selected')) div.style.backgroundColor = ''; });
        container.appendChild(div);
    });
}

function selectTestCase(tc, el) {
    document.querySelectorAll('.reference-result-item.selected').forEach(n=>{ n.classList.remove('selected'); n.style.backgroundColor=''; });
    el.classList.add('selected');
    el.style.backgroundColor = '#e3f2fd';
    showTestCaseInFrame(tc);
}

function showTestCaseInFrame(tc) {
    try {
        const team = AppUtils.getCurrentTeam();
        if (!team || !team.id) throw new Error('請先選擇團隊');
        const frame = document.getElementById('referenceTestCaseFramePage');
        const tcNumber = (tc.test_case_number || '').trim();
        const setId = tc.test_case_set_id || tc.set_id || '';
        const params = new URLSearchParams();
        if (tcNumber) params.set('tc', tcNumber);
        if (setId !== '' && setId !== null && setId !== undefined) {
            params.set('set_id', String(setId));
        }
        params.set('team_id', String(team.id));
        params.set('minimal', '1');
        params.set('mode', 'browse');
        const url = `/test-case-management?${params.toString()}`;

        // 在 onload 隱藏底部固定按鈕區並禁用所有輸入欄位
        frame.onload = function() {
            try {
                const doc = frame.contentDocument || frame.contentWindow?.document;
                if (!doc) return;

                // 隱藏底部固定按鈕區
                const fixed = doc.querySelector('.fixed-buttons');
                if (fixed) fixed.style.display = 'none';

                // 隱藏個別按鈕（若有殘留）
                const refBtn = doc.getElementById('referenceTestCaseBtn');
                if (refBtn) refBtn.style.display = 'none';
                const copyBtn = doc.getElementById('copyTcmCaseLinkBtn');
                if (copyBtn) copyBtn.style.display = 'none';
                const modalCloseBtn = doc.querySelector('#testCaseModal .modal-header .btn-close');
                if (modalCloseBtn) modalCloseBtn.style.display = 'none';

                // 隱藏附件選擇控制（保留既有附件列表）
                const attachmentInput = doc.getElementById('attachmentUpload');
                if (attachmentInput) {
                    attachmentInput.style.display = 'none';
                    const attachmentLabel = doc.querySelector('label[for="attachmentUpload"]');
                    if (attachmentLabel) attachmentLabel.style.display = 'none';
                    const attachmentHint = attachmentInput.closest('.mb-3')?.querySelector('.form-text');
                    if (attachmentHint) attachmentHint.style.display = 'none';
                }

                // 移除/隱藏快速搜尋提示（在 iframe 內）
                try {
                    const hint = doc.getElementById('quickSearchHint');
                    if (hint) hint.remove();
                    const style = doc.createElement('style');
                    style.textContent = `#quickSearchHint{display:none!important}`;
                    doc.head.appendChild(style);
                } catch (_) {}

                // 禁用所有輸入欄位（input、textarea、select）
                doc.querySelectorAll('input, textarea, select').forEach(el => {
                    el.disabled = true;
                    el.readOnly = true;
                    el.style.pointerEvents = 'none';
                    el.style.backgroundColor = '#f8f9fa';
                });

                // 禁用所有按鈕
                doc.querySelectorAll('button').forEach(btn => {
                    btn.disabled = true;
                    btn.style.pointerEvents = 'none';
                });

                // 禁用所有可編輯區域
                doc.querySelectorAll('[contenteditable="true"]').forEach(el => {
                    el.contentEditable = 'false';
                    el.style.pointerEvents = 'none';
                });

                // 禁用檔案上傳
                doc.querySelectorAll('input[type="file"]').forEach(el => {
                    el.style.display = 'none';
                });

                // 移除所有點擊事件（TCG編輯等）
                doc.querySelectorAll('.tcg-edit-area').forEach(el => {
                    el.style.cursor = 'default';
                    el.onclick = null;
                });

                // 確保 modal 內的 body 也不能捲動
                const modalBody = doc.querySelector('.modal-body');
                if (modalBody) {
                    modalBody.style.userSelect = 'text'; // 允許文字選擇但不能編輯
                }

            } catch (err) {
                console.debug('iframe post-load adjustments failed:', err);
            }
        };

        frame.src = url;
        showFrame();
    } catch (e) {
        console.error('顯示參考測試案例失敗:', e);
        const msg = window.i18n ? window.i18n.t('testCase.referenceTestCaseError', {}, '載入參考測試案例失敗') : '載入參考測試案例失敗';
        AppUtils.showError(msg + ': ' + (e.message || e));
    }
}

function getPriorityColor(p) {
    switch (p) { case 'High': return 'danger'; case 'Medium': return 'warning'; case 'Low': return 'success'; default: return 'secondary'; }
}

function escapeHtml(text){
    return String(text||'')
      .replace(/&/g,'&amp;')
      .replace(/</g,'&lt;')
      .replace(/>/g,'&gt;')
      .replace(/"/g,'&quot;')
      .replace(/'/g,'&#039;');
}
