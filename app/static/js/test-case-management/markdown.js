/* ============================================================
   TEST CASE MANAGEMENT - MARKDOWN EDITOR
   ============================================================ */

/* ============================================================
   18. Markdown 編輯器 (Markdown Editor)
   ============================================================ */

// NOTE: currentEditorMode, markdownPreviewTimeout, activeTextarea 已統一定義於 Section 2

// 支援 Markdown 的欄位
const markdownFields = ['precondition', 'test_steps', 'expected_result'];
const aiAssistFieldConfig = [
    {
        fieldId: 'precondition',
        apiField: 'precondition',
        labelKey: 'testCase.preconditions',
        fallback: '前置條件',
        modalKey: 'Precondition'
    },
    {
        fieldId: 'test_steps',
        apiField: 'steps',
        labelKey: 'form.testSteps',
        fallback: '測試步驟',
        modalKey: 'Steps'
    },
    {
        fieldId: 'expected_result',
        apiField: 'expected_result',
        labelKey: 'form.expectedResults',
        fallback: '預期結果',
        modalKey: 'ExpectedResult'
    }
];
const aiAssistFieldMap = new Map(aiAssistFieldConfig.map(meta => [meta.fieldId, meta]));

/**
 * 綁定 Markdown 事件
 */
function bindMarkdownEvents() {
    // Markdown 工具列按鈕 (個別工具列)
    document.querySelectorAll('.markdown-toolbar button[data-md]').forEach(btn => {
        btn.addEventListener('click', (e) => {
            const toolbar = e.currentTarget.closest('.markdown-toolbar');
            const targetFieldId = toolbar.getAttribute('data-target');
            const mdSyntax = e.currentTarget.getAttribute('data-md');
            insertMarkdownToField(targetFieldId, mdSyntax);
        });
    });

    // 為所有 Markdown 欄位添加事件監聽
    markdownFields.forEach(fieldId => {
        const textarea = document.getElementById(fieldId);
        if (textarea) {
            // 焦點事件：記住當前活動的 textarea
            textarea.addEventListener('focus', () => {
                activeTextarea = textarea;
            });

            // 輸入事件：更新預覽
            textarea.addEventListener('input', () => {
                if (currentEditorMode !== 'edit') {
                    clearTimeout(markdownPreviewTimeout);
                    markdownPreviewTimeout = setTimeout(() => {
                        updateMarkdownPreview(fieldId);
                    }, 300);
                }
            });

            // 追蹤輸入法組字狀態（IME），避免 Enter 造成內容重複
            textarea._isIMEComposing = false;
            textarea.addEventListener('compositionstart', () => { textarea._isIMEComposing = true; });
            textarea.addEventListener('compositionend', () => { textarea._isIMEComposing = false; });

            // 按下 Enter 時自動新增下一項（列表狀態）
            textarea.addEventListener('keydown', (e) => {
                // Shift+Enter 保持預設換行
                if (e.key !== 'Enter' || e.shiftKey) return;
                // 若正在使用輸入法組字（中文/日文等），讓瀏覽器處理（避免複製上一項內容）
                if (e.isComposing || e.keyCode === 229 || textarea._isIMEComposing) return;
                const handled = handleMarkdownListEnter(e, textarea);
                if (handled) {
                    // 由我們處理插入，阻止預設行為
                    e.preventDefault();
                }
            });
        }
    });

}

// 在列表行中按下 Enter 自動建立下一個項目
function handleMarkdownListEnter(event, textarea) {
    if (!textarea) return false;
    // 僅處理插入點（無選取範圍）情況
    if (textarea.selectionStart !== textarea.selectionEnd) return false;

    const value = textarea.value;
    const pos = textarea.selectionStart;

    // 取得當前行的起訖與文本
    const lineStart = value.lastIndexOf('\n', pos - 1) + 1; // 若找不到回傳 -1，加 1 後變 0
    const nextNewline = value.indexOf('\n', pos);
    const lineEnd = nextNewline === -1 ? value.length : nextNewline;
    const lineText = value.slice(lineStart, lineEnd);

    // 偵測無序與有序清單項目前綴
    const unorderedMatch = lineText.match(/^(\s*)([-*+])\s+/);
    const orderedMatch = lineText.match(/^(\s*)(\d+)\.\s+/);

    if (!unorderedMatch && !orderedMatch) {
        return false; // 非清單行，交給瀏覽器預設行為
    }

    let nextMarker = '';
    if (unorderedMatch) {
        const indent = unorderedMatch[1] || '';
        const bullet = unorderedMatch[2]; // -, *, +
        nextMarker = `${indent}${bullet} `;
    } else if (orderedMatch) {
        const indent = orderedMatch[1] || '';
        const num = parseInt(orderedMatch[2], 10) || 1;
        nextMarker = `${indent}${num + 1}. `;
    }

    // 插入換行與下一個標記，並將游標置於新項目之後
    const before = value.slice(0, pos);
    const after = value.slice(pos);
    const insertion = `\n${nextMarker}`;
    textarea.value = before + insertion + after;

    const newCaret = pos + insertion.length;
    textarea.setSelectionRange(newCaret, newCaret);
    textarea.focus();

    // 觸發 input 事件以更新預覽
    textarea.dispatchEvent(new Event('input'));
    return true;
}

// 安全地添加幫助按鈕到現有工具列
function addHelpButtonsToToolbars() {
    markdownFields.forEach(fieldId => {
        const toolbar = document.querySelector(`.markdown-toolbar[data-target="${fieldId}"]`);
        if (toolbar && !toolbar.querySelector('.markdown-help-btn')) {
            const helpButton = document.createElement('button');
            helpButton.type = 'button';
            helpButton.className = 'btn btn-info btn-sm markdown-help-btn ms-2';
            helpButton.setAttribute('data-i18n-title', 'markdown.help');
            helpButton.title = window.i18n
                ? window.i18n.t('markdown.help', {}, 'Markdown 語法說明')
                : 'Markdown 語法說明';
            helpButton.addEventListener('click', () => {
                window.open('https://www.markdownguide.org/cheat-sheet/', '_blank');
            });
            helpButton.innerHTML = '<i class="fas fa-question-circle"></i>';
            toolbar.appendChild(helpButton);

            // 手動觸發翻譯
            if (window.i18n && window.i18n.isReady()) {
                const translatedTitle = window.i18n.t('markdown.help');
                if (translatedTitle && translatedTitle !== 'markdown.help') {
                    helpButton.title = translatedTitle;
                }
            }
        }
    });
}

// 初始化 Markdown 編輯器
function initializeMarkdownEditor() {
    // 模式切換按鈕
    document.getElementById('previewModeBtn').addEventListener('click', () => setEditorMode('preview'));
    document.getElementById('splitModeBtn').addEventListener('click', () => {
        // 檢查編輯權限
        if (hasTestCasePermission('splitModeBtn')) {
            setEditorMode('split');
        } else {
            // Viewer 沒有編輯權限
            const message = window.i18n ? window.i18n.t('errors.noEditPermission', {}, '您沒有編輯權限') : '您沒有編輯權限';
            if (window.AppUtils && window.AppUtils.showWarning) {
                window.AppUtils.showWarning(message);
            } else {
                AppUtils.notify(message, 'warning');
            }
        }
    });

    // 綁定 Markdown 事件
    bindMarkdownEvents();

    // 安全地添加幫助按鈕
    addHelpButtonsToToolbars();
    if (typeof bindAIAssistUnifiedButton === 'function') {
        bindAIAssistUnifiedButton();
    }

    // 附件上傳功能
    const attachmentUpload = document.getElementById('attachmentUpload');
    if (attachmentUpload) {
        attachmentUpload.addEventListener('change', handleAttachmentUpload);
    }
    // 工具列顯示狀態可能改變整體高度，需重新計算列表高度
    adjustTestCasesScrollHeight();
}

// 設置編輯器模式
function setEditorMode(mode) {
    currentEditorMode = mode;
    const shouldUpdatePreview = mode === 'preview' || mode === 'split';

    // 更新按鈕狀態
    document.querySelectorAll('#previewModeBtn, #splitModeBtn').forEach(btn => {
        btn.classList.remove('active', 'btn-secondary');
        btn.classList.add('btn-secondary');
    });
    const activeBtn = document.getElementById(mode + 'ModeBtn');
    if (activeBtn) {
        activeBtn.classList.remove('btn-secondary');
        activeBtn.classList.add('btn-secondary', 'active');
    }

    // 為所有 Markdown 欄位設置模式
    markdownFields.forEach(fieldId => {
        const container = document.querySelector(`#${fieldId}`).closest('.markdown-field-container');
        if (!container) return;

        const editColumn = container.querySelector('.edit-column');
        const previewColumn = container.querySelector('.preview-column');

        // 重置類別
        editColumn.className = 'edit-column';
        previewColumn.className = 'preview-column';

        switch (mode) {
            case 'edit':
                editColumn.className = 'col-12 edit-column';
                previewColumn.className = 'col-12 d-none preview-column';
                break;
            case 'preview':
                editColumn.className = 'col-12 d-none edit-column';
                previewColumn.className = 'col-12 preview-column';
                break;
            case 'split':
                editColumn.className = 'col-6 edit-column';
                previewColumn.className = 'col-6 preview-column';
                break;
        }
    });

    // 控制個別工具列顯示
    markdownFields.forEach(fieldId => {
        const toolbar = document.querySelector(`.markdown-toolbar[data-target="${fieldId}"]`);
        if (toolbar) {
            toolbar.classList.toggle('d-none', mode === 'preview');
        }
    });

    if (shouldUpdatePreview) {
        updateMarkdownPreview();
    }
}

// 插入 Markdown 語法到指定欄位
function insertMarkdownToField(fieldId, syntax) {
    const textarea = document.getElementById(fieldId);
    if (!textarea) return;

    const start = textarea.selectionStart;
    const end = textarea.selectionEnd;
    const selectedText = textarea.value.substring(start, end);

    let insertText = '';
    let cursorOffset = 0;

    if (syntax === '**' || syntax === '*' || syntax === '`') {
        insertText = syntax + selectedText + syntax;
        cursorOffset = syntax.length;
    } else if (syntax.startsWith('#')) {
        insertText = syntax + selectedText;
        cursorOffset = syntax.length;
    } else if (syntax === '- ' || syntax === '1. ') {
        const lines = selectedText.split('\n');
        if (lines.length === 1 && lines[0] === '') {
            insertText = syntax;
            cursorOffset = syntax.length;
        } else {
            insertText = lines.map((line, index) => {
                if (syntax === '1. ') {
                    return `${index + 1}. ${line}`;
                } else {
                    return `- ${line}`;
                }
            }).join('\n');
            cursorOffset = 0;
        }
    } else if (syntax === '[text](url)') {
        insertText = selectedText ? `[${selectedText}](url)` : '[text](url)';
        cursorOffset = selectedText ? insertText.length - 4 : 1;
    } else if (syntax === '![alt](url)') {
        insertText = selectedText ? `![${selectedText}](url)` : '![alt](url)';
        cursorOffset = selectedText ? insertText.length - 4 : 2;
    }

    // 替換選中的文字
    textarea.value = textarea.value.substring(0, start) + insertText + textarea.value.substring(end);

    // 設置光標位置
    if (selectedText) {
        textarea.setSelectionRange(start + cursorOffset, start + insertText.length - (syntax === '**' || syntax === '*' || syntax === '`' ? syntax.length : 0));
    } else {
        textarea.setSelectionRange(start + cursorOffset, start + cursorOffset);
    }

    textarea.focus();

    // 觸發變更事件
    textarea.dispatchEvent(new Event('input'));
}

// 插入 Markdown 語法到活動欄位 (保留向後兼容)

// 更新特定欄位的 Markdown 預覽
function updateMarkdownPreview(fieldId) {
    if (fieldId) {
        // 更新特定欄位
        updateSingleFieldPreview(fieldId);
    } else {
        // 更新所有欄位
        markdownFields.forEach(id => updateSingleFieldPreview(id));
    }
}

function escapeTcmMarkdownFallback(value) {
    return String(value === undefined || value === null ? '' : value).replace(/[&<>"']/g, (character) => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '\"': '&quot;', "'": '&#39;'
    })[character]);
}

function getTcmMarkdownFallbackHtml(source) {
    return `<pre>${escapeTcmMarkdownFallback(source)}</pre>`;
}

function getTcmMarkdownRenderResult(content) {
    const source = content === undefined || content === null ? '' : String(content);
    if (!source) {
        return { html: '', status: 'ok' };
    }

    const adapter = window.TCRTMarkdown;
    if (!adapter || typeof adapter.render !== 'function') {
        return { html: getTcmMarkdownFallbackHtml(source), status: 'fallback', reason: 'adapter-unavailable' };
    }

    try {
        const result = adapter.render(source, { surface: 'test-case-management' });
        if (!result || typeof result.html !== 'string') {
            return { html: getTcmMarkdownFallbackHtml(source), status: 'fallback', reason: 'invalid-adapter-result' };
        }
        return {
            html: result.html,
            status: result.status === 'ok' ? 'ok' : 'fallback',
            ...(result.reason ? { reason: String(result.reason) } : {})
        };
    } catch (_) {
        return { html: getTcmMarkdownFallbackHtml(source), status: 'fallback', reason: 'adapter-error' };
    }
}

function getTcmMarkdownUnavailableLabel() {
    const fallback = 'Markdown 預覽暫時無法使用，目前顯示原始文字。';
    if (window.i18n && typeof window.i18n.t === 'function') {
        return window.i18n.t('errors.markdownRendererUnavailable', {}, fallback);
    }
    return fallback;
}

function updateTcmMarkdownRenderState(previewDiv, result) {
    if (!previewDiv) return;
    const status = result && result.status === 'ok' ? 'ok' : 'fallback';
    previewDiv.setAttribute('data-markdown-status', status);
    if (result && result.reason) {
        previewDiv.setAttribute('data-markdown-reason', String(result.reason));
    } else {
        previewDiv.removeAttribute('data-markdown-reason');
    }
    previewDiv.classList.toggle('markdown-render-fallback', status === 'fallback');

    const existingIndicator = previewDiv.querySelector('[data-markdown-render-status]');
    if (status === 'fallback') {
        const indicator = existingIndicator || document.createElement('span');
        const fallback = getTcmMarkdownUnavailableLabel();
        indicator.setAttribute('data-markdown-render-status', 'fallback');
        indicator.setAttribute('data-i18n', 'errors.markdownRendererUnavailable');
        indicator.setAttribute('data-i18n-fallback', fallback);
        indicator.setAttribute('role', 'status');
        indicator.setAttribute('aria-live', 'polite');
        indicator.className = 'markdown-render-status text-muted small d-block mt-1';
        indicator.textContent = fallback;
        if (!existingIndicator) previewDiv.appendChild(indicator);
        if (window.i18n && typeof window.i18n.retranslate === 'function') {
            window.i18n.retranslate(indicator);
        }
    } else if (existingIndicator) {
        existingIndicator.remove();
    }
}

function scheduleTcmMarkdownRerender(previewDiv) {
    const adapter = window.TCRTMarkdown;
    if (!previewDiv || !adapter || !adapter.ready || typeof adapter.ready.then !== 'function') return;
    if (previewDiv.getAttribute('data-markdown-status') !== 'fallback') return;

    const source = previewDiv.getAttribute('data-markdown-source') || '';
    Promise.resolve(adapter.ready).then((ready) => {
        if (!ready || ready.status !== 'ok') return;
        if (!previewDiv.isConnected || previewDiv.getAttribute('data-markdown-source') !== source) return;
        const result = getTcmMarkdownRenderResult(source);
        previewDiv.innerHTML = result.html;
        updateTcmMarkdownRenderState(previewDiv, result);
    }).catch(() => {});
}

function renderMarkdownToElement(content, previewDiv) {
    if (!previewDiv) return;
    const source = content === undefined || content === null ? '' : String(content);
    if (!source) {
        const previewPlaceholder = window.i18n ? window.i18n.t('messages.previewDisplayHere') : '預覽將在此顯示...';
        previewDiv.innerHTML = `<p class="text-muted">${previewPlaceholder}</p>`;
        previewDiv.removeAttribute('data-markdown-source');
        previewDiv.removeAttribute('data-markdown-status');
        previewDiv.removeAttribute('data-markdown-reason');
        previewDiv.classList.remove('markdown-render-fallback');
        return;
    }

    const result = getTcmMarkdownRenderResult(source);
    previewDiv.setAttribute('data-markdown-source', source);
    previewDiv.innerHTML = result.html;
    updateTcmMarkdownRenderState(previewDiv, result);
    scheduleTcmMarkdownRerender(previewDiv);
}

// 更新單一欄位的預覽
function updateSingleFieldPreview(fieldId) {
    const textarea = document.getElementById(fieldId);
    const previewDiv = document.querySelector(`.markdown-preview[data-target="${fieldId}"]`);

    if (!textarea || !previewDiv) return;

    const content = textarea.value;
    renderMarkdownToElement(content, previewDiv);
}
