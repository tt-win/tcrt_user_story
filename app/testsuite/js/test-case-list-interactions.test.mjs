// Test Case 列表開啟／快速編輯互動的 DOM-free 回歸測試：
//   node --test app/testsuite/js/test-case-list-interactions.test.mjs
// cache.js 與 init.js 是瀏覽器全域 script（無 module.exports），以 vm 載入並用最小
// browser-global stub 驗證 renderer、事件委派與權限欄位契約。
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { test } from 'node:test';
import vm from 'node:vm';

const here = path.dirname(fileURLToPath(import.meta.url));
const cacheSource = readFileSync(
    path.join(here, '../../static/js/test-case-management/cache.js'),
    'utf-8',
);
const initSource = readFileSync(
    path.join(here, '../../static/js/test-case-management/init.js'),
    'utf-8',
);
const quickSearchSource = readFileSync(
    path.join(here, '../../static/js/test-case-management/quick-search.js'),
    'utf-8',
);
const appSource = readFileSync(
    path.join(here, '../../static/js/app.js'),
    'utf-8',
);
const coreSource = readFileSync(
    path.join(here, '../../static/js/test-case-management/core.js'),
    'utf-8',
);
const modalSource = readFileSync(
    path.join(here, '../../static/js/test-case-management/modal.js'),
    'utf-8',
);
const markdownSource = readFileSync(
    path.join(here, '../../static/js/test-case-management/markdown.js'),
    'utf-8',
);
const testRunExecutionRenderSource = readFileSync(
    path.join(here, '../../static/js/test-run-execution/render.js'),
    'utf-8',
);
const stylesheetSource = readFileSync(
    path.join(here, '../../static/css/test-case-management.css'),
    'utf-8',
);
const globalStylesheetSource = readFileSync(
    path.join(here, '../../static/css/style.css'),
    'utf-8',
);
const testCaseManagementTemplateSource = readFileSync(
    path.join(here, '../../templates/test_case_management.html'),
    'utf-8',
);
const testRunExecutionTemplateSource = readFileSync(
    path.join(here, '../../templates/test_run_execution.html'),
    'utf-8',
);

function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>"']/g, (character) => ({
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#039;',
    })[character]);
}

function createCacheContext() {
    const retranslated = [];
    const context = vm.createContext({
        console,
        document: {
            addEventListener() {},
        },
        escapeHtml,
        formatDate: () => '2026-07-29',
        getDisplaySectionName: (sectionGroup) => sectionGroup.name || 'Root',
        getPriorityBadgeClass: () => 'bg-secondary',
        getPriorityText: () => 'Medium',
        getTCGTags: () => '',
        sectionCollapsedState: new Set(),
        selectedTestCases: new Set(),
        window: {
            __tcHelperCreatedNumbers: null,
            _testCasePermissions: {
                testCaseActionCopy: false,
                testCaseActionDelete: false,
            },
            i18n: {
                isReady: () => true,
                retranslate: (target) => retranslated.push(target),
                t: (key) => key,
            },
        },
    });
    vm.runInContext(cacheSource, context);
    return { context, retranslated };
}

function createInitContext() {
    const calls = [];
    const listeners = [];
    const stack = {
        dataset: {},
        addEventListener: (eventName, handler) => listeners.push({ eventName, handler }),
    };
    const context = vm.createContext({
        console,
        document: {
            getElementById: (id) => (id === 'testCasesStack' ? stack : null),
        },
        quickEdit: (...args) => calls.push(['quick-edit', ...args]),
        viewTestCase: (...args) => calls.push(['open-test-case', ...args]),
        window: {},
    });
    vm.runInContext(initSource, context);
    return { calls, context, listeners };
}

function createQuickEditContext(fetchTestCase) {
    const restoreCalls = [];
    const inputListeners = {};
    const input = {
        addEventListener: (eventName, handler) => { inputListeners[eventName] = handler; },
        focus() {},
        select() {},
        value: '',
    };
    const cell = {
        dataset: { field: 'title', recordId: 'rec-1' },
        replaceChildren: (child) => { cell.child = child; },
    };
    const testCase = {
        record_id: 'rec-1',
        title: 'Original title',
    };
    const messages = [];
    const context = vm.createContext({
        AppUtils: {
            getCurrentTeam: () => ({ id: 'team-1' }),
        },
        console: { error() {} },
        document: {
            addEventListener() {},
            createElement: () => input,
            querySelectorAll: () => [cell],
        },
        escapeHtml,
        restoreTestCaseListFieldCell: (...args) => restoreCalls.push(args),
        showError: (message) => messages.push(['error', message]),
        showSuccess: (message) => messages.push(['success', message]),
        testCases: [testCase],
        window: {
            AuthClient: { fetch: fetchTestCase },
            i18n: { t: (key) => key },
        },
    });
    vm.runInContext(quickSearchSource, context);
    return {
        cell,
        context,
        input,
        inputListeners,
        messages,
        restoreCalls,
        testCase,
    };
}

function createAppUtilsContext() {
    const animationFrames = [];
    const documentStub = {
        activeElement: null,
        addEventListener() {},
        body: null,
        createElement: () => ({
            innerHTML: '',
            textContent: '',
        }),
    };
    const context = vm.createContext({
        bootstrap: {},
        clearTimeout() {},
        console,
        CustomEvent: class {},
        document: documentStub,
        localStorage: {
            getItem: () => null,
            removeItem() {},
            setItem() {},
        },
        MutationObserver: class {
            disconnect() {}
            observe() {}
        },
        requestAnimationFrame: (callback) => animationFrames.push(callback),
        setInterval: () => 1,
        setTimeout: () => 1,
        window: {
            dispatchEvent() {},
        },
    });
    vm.runInContext(`${appSource}\nglobalThis.__appUtils = AppUtils;`, context);
    return {
        animationFrames,
        appUtils: context.__appUtils,
        documentStub,
    };
}

function createModalBindingContext() {
    const listeners = [];
    const form = {
        dataset: {},
        addEventListener: (eventName, handler) => listeners.push({ eventName, handler }),
    };
    const context = vm.createContext({
        console,
        document: {
            addEventListener() {},
            getElementById: (id) => (id === 'testCaseForm' ? form : null),
        },
        window: {
            addEventListener() {},
        },
    });
    vm.runInContext(
        `${modalSource}\nglobalThis.__bindFormChangeListeners = bindFormChangeListeners;`,
        context,
    );
    return {
        bindFormChangeListeners: context.__bindFormChangeListeners,
        form,
        listeners,
    };
}

function createMarkdownHotkeyContext() {
    const context = vm.createContext({
        console,
        document: {},
        navigator: { platform: 'MacIntel' },
        setTimeout,
        window: {
            addEventListener() {},
            marked: null,
        },
    });
    vm.runInContext(
        `${coreSource}\nglobalThis.__setupMarkdownHotkeys = setupMarkdownHotkeys;`,
        context,
    );
    return context.__setupMarkdownHotkeys;
}

async function flushPromises() {
    await new Promise((resolve) => setImmediate(resolve));
    await new Promise((resolve) => setImmediate(resolve));
}

function makeActionEvent(action, recordId, field) {
    const target = {
        dataset: {
            tcmAction: action,
            recordId,
            ...(field ? { field } : {}),
        },
        closest: (selector) => (selector === '[data-tcm-action]' ? target : null),
    };
    let prevented = false;
    let stopped = false;
    return {
        event: {
            preventDefault: () => { prevented = true; },
            stopPropagation: () => { stopped = true; },
            target,
        },
        wasPrevented: () => prevented,
        wasStopped: () => stopped,
    };
}

test('編號與標題 renderer 提供 sibling 開啟／快速編輯控制項，且保留 escaping 與 tooltip keys', () => {
    const { context } = createCacheContext();
    const testCase = {
        record_id: 'rec-1',
        test_case_number: 'TC-<1>',
        title: 'Title <script>',
        description: 'Description <unsafe>',
    };

    const numberHtml = context.renderTestCaseListFieldContent(testCase, 'test_case_number');
    const titleHtml = context.renderTestCaseListFieldContent(testCase, 'title');

    for (const html of [numberHtml, titleHtml]) {
        assert.match(html, /<button[^>]+type="button"[^>]+data-tcm-action="open-test-case"/);
        assert.match(html, /data-tcm-action="quick-edit"/);
        assert.match(html, /data-i18n-title="tooltips\.viewEdit"/);
        assert.match(html, /data-i18n-title="tooltips\.quickEdit"/);
        assert.ok(
            html.indexOf('data-tcm-action="open-test-case"')
                < html.indexOf('data-tcm-action="quick-edit"'),
            '開啟與快速編輯必須是同層 sibling controls',
        );
        assert.doesNotMatch(html, /fa-eye/);
    }

    assert.match(numberHtml, /TC-&lt;1&gt;/);
    assert.match(titleHtml, /Title &lt;script&gt;/);
    assert.match(titleHtml, /Description &lt;unsafe&gt;\.\.\./);
});

test('快速編輯還原共用 field renderer 並局部重新翻譯', () => {
    const { context, retranslated } = createCacheContext();
    const cell = { innerHTML: '' };
    const testCase = {
        record_id: 'rec-1',
        test_case_number: 'TC-1',
        title: 'Editable title',
        description: 'Description',
    };

    context.restoreTestCaseListFieldCell(cell, testCase, 'title');

    assert.match(cell.innerHTML, /data-tcm-action="open-test-case"/);
    assert.match(cell.innerHTML, /data-tcm-action="quick-edit"/);
    assert.equal(retranslated.length, 1);
    assert.equal(retranslated[0], cell);
});

test('操作欄依複製／刪除權限渲染，且不再產生列尾檢視按鈕', () => {
    const { context } = createCacheContext();
    const testCase = {
        record_id: 'rec-1',
        test_case_number: 'TC-1',
        title: 'Title',
        description: '',
        priority: 'Medium',
        created_at: '2026-07-29',
        updated_at: '2026-07-29',
    };
    const section = {
        sectionId: 'section-1',
        sectionLevel: 1,
        name: 'Root',
        testCases: [testCase],
    };

    const readOnlyRow = context.renderTestCaseRow(testCase);
    const readOnlySection = context.renderSectionBlockHTML(section, readOnlyRow);
    assert.match(readOnlyRow, /test-case-checkbox/);
    assert.match(readOnlyRow, /data-field="tcg"/);
    assert.match(readOnlySection, /data-sort-field="test_case_number"/);
    assert.match(readOnlySection, /data-sort-field="title"/);
    assert.doesNotMatch(readOnlyRow, /test-case-actions/);
    assert.doesNotMatch(readOnlySection, /data-i18n="common\.actions"/);
    assert.doesNotMatch(readOnlyRow, /fa-eye/);

    context.window._testCasePermissions.testCaseActionCopy = true;
    const copyRow = context.renderTestCaseRow(testCase);
    const copySection = context.renderSectionBlockHTML(section, copyRow);
    assert.match(copyRow, /fa-copy/);
    assert.match(copyRow, /onclick="copyTestCase\(/);
    assert.match(copySection, /data-i18n="common\.actions"/);
    assert.doesNotMatch(copyRow, /fa-eye/);
});

test('穩定父層事件委派只綁定一次，並支援後續 lazy row 的開啟與快速編輯', () => {
    const { calls, context, listeners } = createInitContext();

    context.bindTestCaseListRowActions();
    context.bindTestCaseListRowActions();
    assert.equal(listeners.length, 1);
    assert.equal(listeners[0].eventName, 'click');

    const lazyOpen = makeActionEvent('open-test-case', 'lazy-rec-1');
    listeners[0].handler(lazyOpen.event);
    assert.deepEqual(calls, [['open-test-case', 'lazy-rec-1']]);
    assert.equal(lazyOpen.wasPrevented(), true);

    const quickEdit = makeActionEvent('quick-edit', 'lazy-rec-1', 'title');
    listeners[0].handler(quickEdit.event);
    assert.deepEqual(calls, [
        ['open-test-case', 'lazy-rec-1'],
        ['quick-edit', 'lazy-rec-1', 'title'],
    ]);
    assert.equal(quickEdit.wasPrevented(), true);
    assert.equal(quickEdit.wasStopped(), true);

    let prevented = false;
    context.handleTestCaseListRowAction({
        preventDefault: () => { prevented = true; },
        target: { closest: () => null },
    });
    assert.equal(prevented, false, '非列表 action 不得攔截排序、checkbox、TCG 或列尾操作');
});

test('快速編輯取消、儲存成功與失敗都透過共用 renderer 還原 cell', async () => {
    const cancel = createQuickEditContext(() => Promise.resolve({ ok: true }));
    cancel.context.quickEdit('rec-1', 'title');
    cancel.inputListeners.keydown({ key: 'Escape', preventDefault() {} });
    assert.equal(cancel.restoreCalls.length, 1);
    assert.equal(cancel.restoreCalls[0][0], cancel.cell);
    assert.equal(cancel.restoreCalls[0][1], cancel.testCase);
    assert.equal(cancel.restoreCalls[0][2], 'title');

    const success = createQuickEditContext(() => Promise.resolve({ ok: true }));
    success.context.quickEdit('rec-1', 'title');
    success.input.value = 'Updated title';
    success.inputListeners.keydown({ key: 'Enter', preventDefault() {} });
    await flushPromises();
    assert.equal(success.testCase.title, 'Updated title');
    assert.equal(success.restoreCalls.length, 2);
    assert.equal(success.messages[0][0], 'success');

    const failure = createQuickEditContext(() => Promise.resolve({
        ok: false,
        json: async () => ({ detail: 'update failed' }),
    }));
    failure.context.quickEdit('rec-1', 'title');
    failure.input.value = 'Rejected title';
    failure.inputListeners.keydown({ key: 'Enter', preventDefault() {} });
    await flushPromises();
    assert.equal(failure.testCase.title, 'Original title');
    assert.equal(failure.restoreCalls.length, 2);
    assert.equal(failure.messages[0][0], 'error');
});

test('樣式保留原欄位配色與等寬編號，並提供 focus、無 hover 與窄螢幕 fallback', () => {
    assert.match(stylesheetSource, /\.hover-editable:focus-within/);
    assert.match(stylesheetSource, /@media \(hover: none\)[\s\S]*?\.hover-edit-btn/);
    assert.match(stylesheetSource, /@media \(max-width: 767\.98px\)[\s\S]*?\.test-case-actions-cell/);
    assert.match(stylesheetSource, /rgba\(var\(--tr-primary-rgb\), 0\.1\)/);
    assert.doesNotMatch(stylesheetSource, /rgba\(0, 123, 255, 0\.1\)/);
    assert.match(
        stylesheetSource,
        /\.test-case-number-value\s*\{[\s\S]*?font-family:\s*var\(--bs-font-monospace, ui-monospace, SFMono-Regular, Menlo, Consolas, monospace\)\s*!important;/,
    );
    assert.match(
        stylesheetSource,
        /\.test-case-open-trigger\s*\{[\s\S]*?width:\s*calc\(100% - 45px\);/,
    );
    assert.match(
        stylesheetSource,
        /\.test-case-open-trigger:hover,[\s\S]*?\.test-case-open-trigger:active\s*\{[\s\S]*?background:\s*transparent;[\s\S]*?box-shadow:\s*none;[\s\S]*?color:\s*inherit;[\s\S]*?transform:\s*none;/,
    );
    assert.doesNotMatch(stylesheetSource, /\.test-case-open-trigger:hover\s*\{\s*color:\s*var\(--tr-primary\)/);
    assert.match(
        stylesheetSource,
        /\.hover-edit-btn\s*\{[\s\S]*?right:\s*5px;[\s\S]*?z-index:\s*10;/,
    );
    assert.match(
        stylesheetSource,
        /\.hover-edit-btn:hover,[\s\S]*?\.hover-edit-btn:active\s*\{\s*transform:\s*translateY\(-50%\);\s*\}/,
    );
});

test('Detail 前後筆按鈕只在鍵盤焦點顯示共用焦點外框，並保留右上角位置', () => {
    assert.match(
        globalStylesheetSource,
        /\.btn:focus:not\(:focus-visible\)\s*\{\s*outline:\s*none;\s*box-shadow:\s*none;/,
    );
    assert.match(
        globalStylesheetSource,
        /\.btn:focus-visible\s*\{\s*outline:\s*none;\s*box-shadow:\s*0 0 0 0\.2rem rgba\(var\(--tr-primary-rgb\), 0\.25\);/,
    );
    assert.doesNotMatch(globalStylesheetSource, /\.btn:focus,\s*\.btn:focus-visible\s*\{/);

    for (const [templateSource, buttonId] of [
        [testCaseManagementTemplateSource, 'prevTestCaseBtn'],
        [testCaseManagementTemplateSource, 'nextTestCaseBtn'],
        [testRunExecutionTemplateSource, 'prevExecCaseBtn'],
        [testRunExecutionTemplateSource, 'nextExecCaseBtn'],
    ]) {
        assert.match(
            templateSource,
            new RegExp(`<button[^>]*class="btn btn-secondary btn-sm"[^>]*id="${buttonId}"`),
        );
    }

    const testCaseModalHeader = testCaseManagementTemplateSource.match(
        /<div class="modal fade" id="testCaseModal"[\s\S]*?<div class="modal-header">([\s\S]*?)<\/div>\s*<div class="modal-body"/,
    );
    assert.ok(testCaseModalHeader, 'Test Case Detail Modal 必須具有標頭');
    const headerSource = testCaseModalHeader[1];
    assert.match(headerSource, /class="d-flex align-items-center gap-2"/);
    assert.match(
        headerSource,
        /id="copyTcmCaseLinkBtn"[\s\S]*?id="prevTestCaseBtn"[\s\S]*?id="nextTestCaseBtn"[\s\S]*?class="btn-close"/,
    );
    assert.doesNotMatch(testCaseManagementTemplateSource, /記錄導覽子工具列/);

    for (const buttonId of ['copyTcmCaseLinkBtn', 'prevTestCaseBtn', 'nextTestCaseBtn']) {
        assert.equal(
            [...testCaseManagementTemplateSource.matchAll(new RegExp(`id="${buttonId}"`, 'g'))].length,
            1,
            `${buttonId} 不得同時存在於標頭與 body`,
        );
    }
});

test('Detail 導覽只釋放 pointer activation 焦點，鍵盤 activation 保留焦點', () => {
    const { animationFrames, appUtils, documentStub } = createAppUtilsContext();
    const pointerControl = {
        blurCount: 0,
        blur() {
            this.blurCount += 1;
            documentStub.activeElement = null;
        },
    };
    documentStub.activeElement = pointerControl;

    appUtils.releasePointerFocus({ currentTarget: pointerControl, detail: 1 });
    assert.equal(pointerControl.blurCount, 0, '焦點應在下一個 frame 才釋放');
    assert.equal(animationFrames.length, 1);
    animationFrames.shift()();
    assert.equal(pointerControl.blurCount, 1);

    const keyboardControl = {
        blurCount: 0,
        blur() { this.blurCount += 1; },
    };
    documentStub.activeElement = keyboardControl;
    appUtils.releasePointerFocus({ currentTarget: keyboardControl, detail: 0 });
    assert.equal(animationFrames.length, 0);
    assert.equal(keyboardControl.blurCount, 0);
    assert.equal(documentStub.activeElement, keyboardControl);

    assert.match(
        initSource,
        /prevTestCaseBtn'[\s\S]*?AppUtils\.releasePointerFocus\(event\)[\s\S]*?showPrevTestCase\(\)/,
    );
    assert.match(
        initSource,
        /nextTestCaseBtn'[\s\S]*?AppUtils\.releasePointerFocus\(event\)[\s\S]*?showNextTestCase\(\)/,
    );
    assert.match(
        testRunExecutionRenderSource,
        /prevBtn\.onclick = \(event\)[\s\S]*?AppUtils\.releasePointerFocus\(event\)[\s\S]*?navigateExecCase\(testCase, -1\)/,
    );
    assert.match(
        testRunExecutionRenderSource,
        /nextBtn\.onclick = \(event\)[\s\S]*?AppUtils\.releasePointerFocus\(event\)[\s\S]*?navigateExecCase\(testCase, 1\)/,
    );
});

test('重複開啟 Detail 不累積表單與 Markdown hotkey listeners', () => {
    const { bindFormChangeListeners, form, listeners } = createModalBindingContext();
    bindFormChangeListeners();
    bindFormChangeListeners();

    assert.equal(form.dataset.changeListenersBound, 'true');
    assert.deepEqual(listeners.map(({ eventName }) => eventName), ['input', 'change']);

    const setupMarkdownHotkeys = createMarkdownHotkeyContext();
    const hotkeyListeners = [];
    const textarea = {
        addEventListener: (eventName, handler) => hotkeyListeners.push({ eventName, handler }),
    };
    setupMarkdownHotkeys(textarea);
    setupMarkdownHotkeys(textarea);
    assert.equal(textarea._markdownHotkeysBound, true);
    assert.deepEqual(hotkeyListeners.map(({ eventName }) => eventName), ['keydown']);
});

test('Detail Markdown 編輯器不重複 render、量測或重疊內容', () => {
    const updateMarkdownPreviewSource = markdownSource.match(
        /function updateMarkdownPreview\(fieldId\) \{[\s\S]*?\n\}/,
    )?.[0] || '';
    const updateSingleFieldPreviewSource = markdownSource.match(
        /function updateSingleFieldPreview\(fieldId\) \{[\s\S]*?\n\}/,
    )?.[0] || '';
    const showTestCaseModalSource = modalSource.match(
        /function showTestCaseModal\(testCase = null\) \{[\s\S]*?\n\}/,
    )?.[0] || '';

    assert.doesNotMatch(updateMarkdownPreviewSource, /adjustTestCasesScrollHeight/);
    assert.doesNotMatch(updateSingleFieldPreviewSource, /adjustTestCasesScrollHeight/);
    assert.doesNotMatch(
        showTestCaseModalSource,
        /markdownFields\.forEach\([\s\S]*?updateMarkdownPreview/,
    );
    assert.doesNotMatch(
        attachmentsSourceForNavigation(),
        /adjustTestCasesScrollHeight/,
    );
    assert.doesNotMatch(
        testCaseManagementTemplateSource,
        /class="markdown-toolbar[^"]*"[^>]*\sstyle=/,
    );
    assert.doesNotMatch(
        testCaseManagementTemplateSource,
        /class="markdown-textarea"[^>]*\sstyle=/,
    );
    assert.match(
        stylesheetSource,
        /\.markdown-edit-container\s*\{[^}]*display:\s*flex;[^}]*flex-direction:\s*column;/,
    );
    assert.match(
        stylesheetSource,
        /\.markdown-toolbar\s*\{[^}]*flex:\s*0 0 auto;[^}]*flex-wrap:\s*wrap;[^}]*min-height:\s*2\.25rem;/,
    );
    assert.match(
        stylesheetSource,
        /\.markdown-textarea\s*\{[^}]*flex:\s*1 1 0;[^}]*min-height:\s*0;/,
    );
    assert.doesNotMatch(
        markdownSource,
        /btn-xs|helpButton\.style\.marginLeft|toolbar\.style\.display/,
    );
    assert.match(
        markdownSource,
        /toolbar\.classList\.toggle\('d-none', mode === 'preview'\)/,
    );
});

function attachmentsSourceForNavigation() {
    const attachmentsSource = readFileSync(
        path.join(here, '../../static/js/test-case-management/attachments.js'),
        'utf-8',
    );
    const previous = attachmentsSource.match(
        /function showPrevTestCase\(\) \{[\s\S]*?\n\}/,
    )?.[0] || '';
    const next = attachmentsSource.match(
        /function showNextTestCase\(\) \{[\s\S]*?\n\}/,
    )?.[0] || '';
    return `${previous}\n${next}`;
}
