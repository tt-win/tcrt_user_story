/* ============================================================
   TEST CASE MANAGEMENT - BULK OPERATIONS
   ============================================================ */

/* ============================================================
   14. 批次操作 (Batch Operations)
   ============================================================ */

/* ------------------------------------------------------------
   14.1 批次複製 (Batch Copy)
   ------------------------------------------------------------ */

// NOTE: batchCopyModalInstance, batchCopyPreviewModalInstance, batchCopyItems, lastBatchCopyCheckboxIndex 已統一定義於 Section 2

/**
 * 開啟批次複製 Modal
 */
function openTestCaseBatchCopyModal() {
    try {
        const selectedIds = Array.from(selectedTestCases || []);
        if (!selectedIds.length) {
            const msg = window.i18n ? window.i18n.t('errors.pleaseSelectTestCases') : '請至少選擇一個測試案例';
            AppUtils.showError(msg);
            return;
        }
        // 準備資料來源
        const map = new Map((testCases || []).map(tc => [tc.record_id, tc]));
        batchCopyItems = selectedIds
            .map(id => map.get(id))
            .filter(Boolean)
            .map(tc => ({
                source_record_id: tc.record_id,
                original_number: tc.test_case_number || '',
                original_title: tc.title || '',
                new_number: tc.test_case_number || '',
                new_title: tc.title || '',
                precondition: tc.precondition || '',
                steps: tc.steps || '',
                expected_result: tc.expected_result || '',
                priority: tc.priority || '',
                selected: false,
                conflict: false,
                errors: {}
            }));

        // 開啟 Modal
        const el = document.getElementById('testCaseBatchCopyModal');
        if (!batchCopyModalInstance) batchCopyModalInstance = new bootstrap.Modal(el);
        renderBatchCopyTable();
        if (window.i18n && window.i18n.isReady()) window.i18n.retranslate(el);
        batchCopyModalInstance.show();
    } catch (e) {
        console.error('openTestCaseBatchCopyModal error:', e);
        AppUtils.showError(window.i18n ? window.i18n.t('testCase.batchCopy.openFailed', {}, '開啟批次複製失敗') : '開啟批次複製失敗');
    }
}

function bindBatchCopyModalEvents() {
    const selectAllTop = document.getElementById('batchCopySelectAllTop');
    if (selectAllTop) selectAllTop.addEventListener('change', () => {
        const checked = !!selectAllTop.checked;
        batchCopyItems.forEach(item => item.selected = checked);
        renderBatchCopyTable();
    });

    // 表頭 checkbox 控制全選

    // 套用 Prefix
    const applyPrefixBtn = document.getElementById('applyCopyPrefixBtn');
    if (applyPrefixBtn) applyPrefixBtn.addEventListener('click', () => {
        const input = document.getElementById('copyPrefixInput');
        const prefix = (input.value || '').trim();
        const reg = /^[A-Za-z0-9]+-[0-9]+$/;
        if (!reg.test(prefix)) { AppUtils.showError(window.i18n ? window.i18n.t('errors.prefixFormatInvalid') : 'Prefix 格式不正確'); return; }
        const targets = getBatchCopySelectedIndexes();
        if (!targets.length) { AppUtils.showError(window.i18n ? window.i18n.t('errors.batchCopyNoSelection') : '請先選擇要套用的項目'); return; }
        targets.forEach(idx => {
            const parts = (batchCopyItems[idx].new_number || '').split('.');
            if (parts.length === 3) {
                parts[0] = prefix;
                batchCopyItems[idx].new_number = parts.join('.');
                batchCopyItems[idx].conflict = false;
                batchCopyItems[idx].errors = {};
            }
        });
        renderBatchCopyTable();
    });

    // 套用 Middle
    const applyMiddleBtn = document.getElementById('applyCopyMiddleBtn');
    if (applyMiddleBtn) applyMiddleBtn.addEventListener('click', () => {
        const val = (document.getElementById('copyMiddleInput').value || '').trim();
        if (!/^\d{3}$/.test(val) || parseInt(val,10) < 1 || parseInt(val,10) > 999) {
            AppUtils.showError(window.i18n ? window.i18n.t('errors.middleInvalid') : 'Middle 必須為 001～999 的三位數'); return;
        }
        const targets = getBatchCopySelectedIndexes();
        if (!targets.length) { AppUtils.showError(window.i18n ? window.i18n.t('errors.batchCopyNoSelection') : '請先選擇要套用的項目'); return; }
        targets.forEach(idx => {
            const parts = (batchCopyItems[idx].new_number || '').split('.');
            if (parts.length === 3) {
                parts[1] = val;
                batchCopyItems[idx].new_number = parts.join('.');
                batchCopyItems[idx].conflict = false;
                batchCopyItems[idx].errors = {};
            }
        });
        renderBatchCopyTable();
    });

    // 套用 Suffix 起始（依 10 遞增）
    const applySuffixBtn = document.getElementById('applyCopySuffixBtn');
    if (applySuffixBtn) applySuffixBtn.addEventListener('click', () => {
        const startStr = (document.getElementById('copySuffixStartInput').value || '').trim();
        if (!/^\d{3}$/.test(startStr)) { AppUtils.showError(window.i18n ? window.i18n.t('errors.suffixInvalid') : 'Suffix 起始需為 000～990 的三位數'); return; }
        const start = parseInt(startStr,10);
        if (start < 0 || start > 990) { AppUtils.showError(window.i18n ? window.i18n.t('errors.suffixInvalid') : 'Suffix 起始需為 000～990 的三位數'); return; }
        const targets = getBatchCopySelectedIndexes();
        if (!targets.length) { AppUtils.showError(window.i18n ? window.i18n.t('errors.batchCopyNoSelection') : '請先選擇要套用的項目'); return; }
        const need = targets.length;
        const last = start + (need - 1) * 10;
        if (last > 990) { AppUtils.showError(window.i18n ? window.i18n.t('errors.suffixOutOfRange') : '末尾單號超出 990，無法套用'); return; }
        targets.forEach((idx, i) => {
            const suf = String(start + i*10).padStart(3,'0');
            const parts = (batchCopyItems[idx].new_number || '').split('.');
            if (parts.length === 3) {
                parts[2] = suf;
                batchCopyItems[idx].new_number = parts.join('.');
                batchCopyItems[idx].conflict = false;
                batchCopyItems[idx].errors = {};
            }
        });
        renderBatchCopyTable();
    });

    // Save：先檢查重複，通過則開預覽
    const saveBtn = document.getElementById('saveBatchCopyBtn');
    if (saveBtn) saveBtn.addEventListener('click', onSaveBatchCopy);
}

function getBatchCopySelectedIndexes() {
    const res = [];
    batchCopyItems.forEach((it, idx) => { if (it.selected) res.push(idx); });
    return res;
}

function renderBatchCopyTable() {
    const tbody = document.getElementById('batchCopyTableBody');
    if (!tbody) return;

    let html = '';
    batchCopyItems.forEach((it, idx) => {
        const priorityBadgeClass = it.priority === 'HIGH' ? 'bg-danger' : (it.priority === 'LOW' ? 'bg-info' : 'bg-warning text-dark');
        html += `
            <tr class="${it.conflict ? 'table-danger' : ''}">
                <td class="text-center">
                    <input type="checkbox" class="form-check-input batch-copy-checkbox" data-idx="${idx}" ${it.selected ? 'checked' : ''}>
                </td>
                <td>
                    <span class="badge bg-secondary font-monospace px-2 py-1">${escapeHtml(it.original_number)}</span>
                </td>
                <td>
                    <input type="text" class="form-control form-control-sm font-monospace" value="${escapeHtml(it.new_number)}" data-idx="${idx}" data-field="number" />
                    ${it.errors.number ? `<div class="text-danger small mt-1">${escapeHtml(it.errors.number)}</div>` : ''}
                </td>
                <td>
                    <input type="text" class="form-control form-control-sm" value="${escapeHtml(it.new_title)}" data-idx="${idx}" data-field="title" />
                </td>
                <td class="text-center">
                    <button type="button" class="btn btn-sm btn-outline-secondary toggle-details-btn py-0 px-2" data-idx="${idx}">
                        <i class="fas fa-chevron-down me-1" id="toggleIcon_${idx}"></i><span class="small" data-i18n="common.view">查看</span>
                    </button>
                </td>
            </tr>
            <tr class="d-none bg-light" id="batchCopyDetailsRow_${idx}">
                <td colspan="5" class="p-3 border-bottom">
                    <div class="card border border-light-subtle shadow-sm rounded-3 overflow-hidden">
                        <!-- 卡片頂部資訊列 -->
                        <div class="card-header bg-white py-2 px-3 d-flex align-items-center justify-content-between border-bottom">
                            <div class="d-flex align-items-center gap-2 me-3 text-truncate">
                                <span class="text-muted small fw-semibold" data-i18n="testCase.batchCopy.originalTitle">來源標題:</span>
                                <span class="small text-dark font-monospace text-truncate" title="${escapeHtml(it.original_title)}">${escapeHtml(it.original_title || '無標題')}</span>
                            </div>
                            <div class="d-flex align-items-center gap-2 flex-shrink-0">
                                <span class="text-muted small fw-semibold" data-i18n="testCase.priority">優先級:</span>
                                <span class="badge ${priorityBadgeClass}">${escapeHtml(it.priority || 'NORMAL')}</span>
                            </div>
                        </div>
                        <!-- 三欄高度完美對齊內文區塊 -->
                        <div class="card-body p-3 bg-light-subtle">
                            <div class="row g-3 align-items-stretch">
                                <div class="col-md-4 d-flex flex-column">
                                    <div class="border bg-white rounded-3 flex-grow-1 d-flex flex-column overflow-hidden shadow-sm">
                                        <div class="px-3 py-2 bg-light border-bottom small fw-bold text-secondary d-flex align-items-center">
                                            <i class="fas fa-list-ul me-2 text-info"></i><span data-i18n="testCase.preconditions">前置條件</span>
                                        </div>
                                        <div class="p-3 text-secondary flex-grow-1" style="white-space: pre-wrap; height: 130px; overflow-y: auto; font-size: 0.84rem; line-height: 1.55;">${it.precondition ? escapeHtml(it.precondition) : '<span class="text-muted fst-italic">無</span>'}</div>
                                    </div>
                                </div>
                                <div class="col-md-4 d-flex flex-column">
                                    <div class="border bg-white rounded-3 flex-grow-1 d-flex flex-column overflow-hidden shadow-sm">
                                        <div class="px-3 py-2 bg-light border-bottom small fw-bold text-secondary d-flex align-items-center">
                                            <i class="fas fa-shoe-prints me-2 text-primary"></i><span data-i18n="testCase.steps">測試步驟</span>
                                        </div>
                                        <div class="p-3 text-secondary flex-grow-1" style="white-space: pre-wrap; height: 130px; overflow-y: auto; font-size: 0.84rem; line-height: 1.55;">${it.steps ? escapeHtml(it.steps) : '<span class="text-muted fst-italic">無</span>'}</div>
                                    </div>
                                </div>
                                <div class="col-md-4 d-flex flex-column">
                                    <div class="border bg-white rounded-3 flex-grow-1 d-flex flex-column overflow-hidden shadow-sm">
                                        <div class="px-3 py-2 bg-light border-bottom small fw-bold text-secondary d-flex align-items-center">
                                            <i class="fas fa-circle-check me-2 text-success"></i><span data-i18n="testCase.expectedResults">預期結果</span>
                                        </div>
                                        <div class="p-3 text-secondary flex-grow-1" style="white-space: pre-wrap; height: 130px; overflow-y: auto; font-size: 0.84rem; line-height: 1.55;">${it.expected_result ? escapeHtml(it.expected_result) : '<span class="text-muted fst-italic">無</span>'}</div>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                </td>
            </tr>
        `;
    });

    tbody.innerHTML = html;

    // 事件繫結
    tbody.querySelectorAll('.batch-copy-checkbox').forEach(cb => {
        cb.addEventListener('click', (e) => {
            const checkboxes = Array.from(tbody.querySelectorAll('.batch-copy-checkbox'));
            const currentIndex = checkboxes.indexOf(e.target);
            const idx = parseInt(e.target.getAttribute('data-idx'), 10);
            const checked = e.target.checked;
            if (e.shiftKey && lastBatchCopyCheckboxIndex !== null && lastBatchCopyCheckboxIndex !== -1) {
                const start = Math.min(lastBatchCopyCheckboxIndex, currentIndex);
                const end = Math.max(lastBatchCopyCheckboxIndex, currentIndex);
                for (let i = start; i <= end; i++) {
                    const c = checkboxes[i];
                    const idxx = parseInt(c.getAttribute('data-idx'),10);
                    c.checked = checked;
                    batchCopyItems[idxx].selected = checked;
                }
            } else {
                batchCopyItems[idx].selected = checked;
            }
            lastBatchCopyCheckboxIndex = currentIndex;
        });
    });

    tbody.querySelectorAll('input[data-field="number"]').forEach(inp => {
        inp.addEventListener('input', (e) => {
            const idx = parseInt(e.target.getAttribute('data-idx'),10);
            batchCopyItems[idx].new_number = e.target.value.trim();
            // 內部重複即時標示
            markInternalDuplicates();
        });
    });
    tbody.querySelectorAll('input[data-field="title"]').forEach(inp => {
        inp.addEventListener('input', (e) => {
            const idx = parseInt(e.target.getAttribute('data-idx'),10);
            batchCopyItems[idx].new_title = e.target.value;
        });
    });

    tbody.querySelectorAll('.toggle-details-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            const targetBtn = e.currentTarget;
            const idx = targetBtn.getAttribute('data-idx');
            const row = document.getElementById(`batchCopyDetailsRow_${idx}`);
            const icon = document.getElementById(`toggleIcon_${idx}`);
            if (row) {
                row.classList.toggle('d-none');
                if (icon) {
                    if (row.classList.contains('d-none')) {
                        icon.className = 'fas fa-chevron-down me-1';
                    } else {
                        icon.className = 'fas fa-chevron-up me-1';
                    }
                }
            }
        });
    });
}

function markInternalDuplicates() {
    const seen = new Map();
    batchCopyItems.forEach((it, idx) => {
        it.conflict = false;
        if (it.new_number) {
            const arr = seen.get(it.new_number) || [];
            arr.push(idx);
            seen.set(it.new_number, arr);
        }
    });
    for (const [k, arr] of seen.entries()) {
        if (arr.length > 1) arr.forEach(i => batchCopyItems[i].conflict = true);
    }
}

async function onSaveBatchCopy() {
    // 內部重複檢查
    markInternalDuplicates();
    if (batchCopyItems.some(it => it.conflict)) {
        AppUtils.showError(window.i18n ? window.i18n.t('errors.duplicateInternal') : '清單內有重複的 Case Number');
        renderBatchCopyTable();
        return;
    }
    // 外部重複檢查（以目前快取資料檢查）
    const existing = new Set((testCases || []).map(tc => tc.test_case_number).filter(Boolean));
    const externalDup = [];
    batchCopyItems.forEach(it => { if (existing.has(it.new_number)) externalDup.push(it.new_number); });
    if (externalDup.length) {
        AppUtils.showError((window.i18n ? window.i18n.t('errors.duplicateExternal', {numbers: externalDup.join(', ')}) : `與既有 Case Number 衝突：${externalDup.join(', ')}`));
        batchCopyItems.forEach(it => { if (externalDup.includes(it.new_number)) it.conflict = true; });
        renderBatchCopyTable();
        return;
    }

    // 直接發送確認複製 API，免去雙重 Modal 冗餘
    await confirmBatchCopyRequest();
}

async function confirmBatchCopyRequest() {
    try {
        const currentTeam = AppUtils.getCurrentTeam();
        if (!currentTeam || !currentTeam.id) throw new Error(window.i18n ? window.i18n.t('errors.pleaseSelectTeam', {}, '請先選擇團隊') : '請先選擇團隊');

        const btn = document.getElementById('saveBatchCopyBtn');
        const originalHtml = btn ? btn.innerHTML : '';
        if (btn) {
            btn.disabled = true;
            btn.innerHTML = `<i class="fas fa-spinner fa-spin me-2"></i>${window.i18n ? window.i18n.t('messages.saving', {}, '複製中...') : '複製中...'}`;
        }

        const payload = {
            items: batchCopyItems.map(it => ({
                source_record_id: it.source_record_id,
                test_case_number: it.new_number,
                title: it.new_title
            }))
        };
        const resp = await window.AuthClient.fetch(`/api/teams/${currentTeam.id}/testcases/bulk_clone`, {
            method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(payload)
        });
        const data = await resp.json();

        if (!resp.ok || !data || data.success === false) {
            if (data && Array.isArray(data.duplicates) && data.duplicates.length) {
                // 標記外部衝突
                const setDup = new Set(data.duplicates);
                batchCopyItems.forEach(it => { if (setDup.has(it.new_number)) it.conflict = true; });
                AppUtils.showError((window.i18n ? window.i18n.t('errors.duplicateExternal', {numbers: data.duplicates.join(', ')}) : `與既有 Case Number 衝突：${data.duplicates.join(', ')}`));
                renderBatchCopyTable();
                return;
            }
            const msg = (data && data.errors && data.errors.join('; ')) || resp.statusText ||
                (window.i18n ? window.i18n.t('messages.createFailed', {}, '複製失敗') : '複製失敗');
            AppUtils.showError(msg);
            return;
        }

        // 成功
        AppUtils.showSuccess(window.i18n ? window.i18n.t('messages.batchCopySuccess', {count: data.created_count || payload.items.length}) : `已成功複製 ${data.created_count || payload.items.length} 筆測試案例`);
        if (batchCopyModalInstance) batchCopyModalInstance.hide();
        // 刷新列表
        clearTestCasesCache();
        await loadTestCases(false, null, true);

        // 清除主列表的選取
        try {
            if (selectedTestCases && typeof selectedTestCases.clear === 'function') {
                selectedTestCases.clear();
            }
            const selectAll = document.getElementById('selectAllCheckbox');
            if (selectAll) selectAll.checked = false;
            if (typeof updateBatchToolbar === 'function') updateBatchToolbar();
        } catch (_) {}
    } catch (e) {
        console.error('confirmBatchCopyRequest error:', e);
        AppUtils.showError(window.i18n ? window.i18n.t('testCase.batchCopy.failed', {}, '批次複製失敗') : '批次複製失敗');
    } finally {
        const btn = document.getElementById('saveBatchCopyBtn');
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = `<i class="fas fa-check me-2"></i><span data-i18n="testCase.batchCopy.confirmSubmit">${window.i18n ? window.i18n.t('testCase.batchCopy.confirmSubmit', {}, '確認批次複製') : '確認批次複製'}</span>`;
        }
    }
}


/* ============================================================
   15. 大量新增 (Bulk Create)
   ============================================================ */

// NOTE: bulkModalInstance, bulkPreviewModalInstance, bulkTextParsedItems 已統一定義於 Section 2

/**
 * 正規化批次 TCG 編號輸入
 */
function normalizeBulkTcgNumbers(rawValue) {
    const result = {
        tcgNumbers: [],
        invalidTokens: []
    };

    if (!rawValue) {
        return result;
    }

    const parts = rawValue
        .split('|')
        .map(part => part.trim())
        .filter(Boolean);

    if (!parts.length) {
        return result;
    }

    const seen = new Set();

    for (const part of parts) {
        const normalized = normalizeSingleTcg(part);
        if (!normalized) {
            result.invalidTokens.push(part);
            continue;
        }
        if (!seen.has(normalized)) {
            seen.add(normalized);
            result.tcgNumbers.push(normalized);
        }
    }

    return result;
}

function normalizeSingleTcg(input) {
    if (!input) return null;

    const upper = String(input).trim().toUpperCase().replace(/\s+/g, '');
    if (!upper) return null;

    let digits = '';

    if (/^TCG-?\d+$/.test(upper)) {
        digits = upper.replace(/^TCG-?/, '');
    } else if (/^\d+$/.test(upper)) {
        digits = upper;
    } else {
        return null;
    }

    if (!digits) return null;

    return `TCG-${digits}`;
}

// NOTE: BULK_PRIORITY_ALLOWED 已統一定義於 Section 1 (常數定義)

// test_data 第 8 欄「共用可 round-trip 判定」：與後端 export helper 同一規則
// （schema 型別 + normalize_test_data_items 穩定性），限制值須與 server 一致
const BULK_TEST_DATA_CATEGORIES = ['text', 'number', 'credential', 'email', 'url', 'identifier', 'date', 'json', 'other'];
const BULK_TEST_DATA_MAX_ITEMS = 100;
const BULK_TEST_DATA_MAX_NAME_LEN = 500;
const BULK_TEST_DATA_MAX_VALUE_LEN = 100000;

// Python str.strip() 的空白集合（與 server strip 對齊；和 JS String.trim 不同：
// 含 \x85(NEL)、不含 \uFEFF(BOM)）
const BULK_TEST_DATA_PY_STRIP_RE = /^[\t\n\v\f\r \x1c-\x1f\x85\xa0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+|[\t\n\v\f\r \x1c-\x1f\x85\xa0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+$/g;

// 與 server 一致以 Unicode code point 計長度（JS .length 是 UTF-16 code unit，
// emoji 等 astral 字元會被多算而破壞與 export 的共用 round-trip 判定）
function bulkCodePointLength(text) {
    let count = 0;
    for (const _ch of String(text)) count++;
    return count;
}

// 與 server normalize_test_data_items 相同的 name 清洗（穩定性判定用）：
// 移除 C0 控制字元（保留 \t）、bidi override，\n/\r 轉空白後做 Python 等價 strip
function cleanBulkTestDataName(rawName) {
    return String(rawName)
        .replace(/[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]/g, '')
        .replace(/[\u202A-\u202E\u2066-\u2069]/g, '')
        .replace(/\n/g, ' ')
        .replace(/\r/g, ' ')
        .replace(BULK_TEST_DATA_PY_STRIP_RE, '');
}

function bulkTestDataEffectiveCategory(category) {
    if (category === undefined || category === null || category === '') return 'text';
    return String(category).toLowerCase();
}

/**
 * 驗證第 8 欄 test_data 陣列是否可 round-trip（未通過 → 該行格式錯誤）
 * @param {any} parsed - JSON.parse 後的值
 * @returns {boolean}
 */
function validateBulkTestDataArray(parsed) {
    if (!Array.isArray(parsed)) return false;
    if (parsed.length > BULK_TEST_DATA_MAX_ITEMS) return false;
    const seenNames = new Set();
    for (const element of parsed) {
        if (!element || typeof element !== 'object' || Array.isArray(element)) return false;
        if (typeof element.name !== 'string') return false;
        if (!Object.prototype.hasOwnProperty.call(element, 'value') || typeof element.value !== 'string') return false;
        if (element.id !== undefined && element.id !== null && typeof element.id !== 'string') return false;
        const category = element.category;
        if (category !== undefined && category !== null && category !== '') {
            if (typeof category !== 'string' || !BULK_TEST_DATA_CATEGORIES.includes(category.toLowerCase())) return false;
        }
        const cleanedName = cleanBulkTestDataName(element.name);
        if (!cleanedName || cleanedName !== element.name || bulkCodePointLength(cleanedName) > BULK_TEST_DATA_MAX_NAME_LEN) return false;
        if (element.value.indexOf('\u0000') !== -1 || bulkCodePointLength(element.value) > BULK_TEST_DATA_MAX_VALUE_LEN) return false;
        if (seenNames.has(cleanedName)) return false;
        seenNames.add(cleanedName);
    }
    return true;
}

function parseCsvLine(line) {
    const result = [];
    let current = '';
    let inQuotes = false;
    for (let i = 0; i < line.length; i++) {
        const char = line[i];
        if (char === '"') {
            if (inQuotes && line[i + 1] === '"') {
                current += '"';
                i++; // skip escaped quote
            } else {
                inQuotes = !inQuotes;
            }
        } else if (char === ',' && !inQuotes) {
            result.push(current.trim());
            current = '';
        } else {
            current += char;
        }
    }
    result.push(current.trim());
    return result;
}

function normalizePriority(value) {
    if (!value) return 'Medium';
    const trimmed = value.trim();
    if (!trimmed) return 'Medium';
    const matched = BULK_PRIORITY_ALLOWED.find(opt => opt.toLowerCase() === trimmed.toLowerCase());
    return matched || null;
}

function truncateText(text, maxLength = 80) {
    if (!text) return '';
    const value = text.trim();
    if (value.length <= maxLength) return value;
    return `${value.slice(0, maxLength - 1)}…`;
}

function openBulkCreateModal() {
    resetBulkTextState();
    const modalEl = document.getElementById('bulkCreateModal');
    if (!bulkModalInstance) bulkModalInstance = new bootstrap.Modal(modalEl);
    if (window.i18n && window.i18n.isReady()) window.i18n.retranslate(modalEl);
    bulkModalInstance.show();

    // 初始化 Section 選擇框
    populateBulkCreateSectionSelect();

    // 聚焦到 textarea
    setTimeout(() => {
        const textarea = document.getElementById('bulkTextInput');
        if (textarea) textarea.focus();
    }, 150);
}

async function populateBulkCreateSectionSelect() {
    const select = document.getElementById('bulkCreateSectionSelect');
    if (!select) return;

    try {
        const currentTeam = AppUtils.getCurrentTeam();
        if (!currentTeam || !currentTeam.id || !currentSetId) {
            // 如果沒有指定 Set，禁用 Section 選擇
            select.disabled = true;
            return;
        }

        // 獲取當前 Set 的 Sections
        const response = await window.AuthClient.fetch(
            `/api/teams/${currentTeam.id}/test-case-sets/${currentSetId}`
        );

        if (!response.ok) {
            select.disabled = true;
            return;
        }

        const setData = await response.json();
        const sections = setData.sections || [];

        // 構建 Section 選項（遞迴處理子 Section）
        const defaultOption = '<option value="" data-i18n="testCase.selectSection" data-i18n-fallback="不指定（使用 Unassigned）">不指定（使用 Unassigned）</option>';

        function buildSectionOptions(sectionList, depth = 0) {
            const parts = [];
            sectionList.forEach(section => {
                const prefix = depth > 0 ? '　'.repeat(depth) + '└─ ' : '';
                const displayName = section.name || '';
                parts.push(`<option value="${section.id}">${prefix}${escapeHtml(displayName)}</option>`);

                // 遞迴處理子 Section（使用 child_sections）
                if (Array.isArray(section.child_sections) && section.child_sections.length > 0) {
                    parts.push(...buildSectionOptions(section.child_sections, depth + 1));
                }
            });
            return parts;
        }

        const optionsHtml = buildSectionOptions(sections).join('');

        select.innerHTML = defaultOption + optionsHtml;
        select.disabled = false;

        if (window.i18n && window.i18n.isReady()) {
            window.i18n.retranslate(select);
        }
    } catch (error) {
        console.error('Error populating bulk section select:', error);
        select.disabled = true;
    }
}

function resetBulkTextState() {
    // 清除文字輸入區內容
    const textarea = document.getElementById('bulkTextInput');
    if (textarea) textarea.value = '';

    // 清除狀態顯示
    const statusEl = document.getElementById('bulkTextStatus');
    const validationEl = document.getElementById('bulkTextValidation');
    if (statusEl) statusEl.textContent = '';
    if (validationEl) validationEl.textContent = '';

    // 隱藏進度條
    hideBulkProgress();

    // 重設解析結果
    bulkTextParsedItems = [];
}

/**
 * 解析文字輸入的 CSV 格式資料
 * @param {string} rawText - 原始文字輸入
 * @returns {object} - { items: [{line, case_no, title, tcg_numbers}], errors: [{line, code, message, raw}], duplicates: [{case_no, lines}] }
 */
function parseBulkText(rawText) {
    const normalizedText = rawText.replace(/\r\n?/g, '\n');
    const lines = normalizedText.split('\n').map((line, index) => ({
        line: index + 1,
        raw: line,
        content: line.trim()
    }));

    const items = [];
    const errors = [];
    const caseNumbers = new Map(); // case_no -> [line numbers]

    for (const lineObj of lines) {
        const { line, raw, content } = lineObj;

        if (!content) continue;

        let cleanContent = content;
        if (cleanContent.startsWith('(Conflict)')) {
            cleanContent = cleanContent.replace(/^\(Conflict\)\s*/, '').trim();
        }

        const columns = parseCsvLine(cleanContent);

        if (columns.length < 2) {
            errors.push({
                line,
                code: 'not_enough_columns',
                message: window.i18n ? window.i18n.t('testCase.bulkText.notEnoughColumns') : '格式需包含至少「單號,標題」兩欄',
                raw
            });
            continue;
        }

        if (columns.length > 8) {
            errors.push({
                line,
                code: 'too_many_columns',
                message: window.i18n ? window.i18n.t('testCase.bulkText.tooManyColumns') : '欄位數量過多，請確認格式',
                raw
            });
            continue;
        }

        while (columns.length < 8) {
            columns.push('');
        }

        const [caseNoRaw, titleRaw, preconditionRaw, stepsRaw, expectedRaw, tcgRaw, priorityRaw, testDataRaw] = columns;

        const case_no = (caseNoRaw || '').trim();
        const title = (titleRaw || '').trim();
        const precondition = (preconditionRaw || '').trim();
        const steps = (stepsRaw || '').trim();
        const expected_result = (expectedRaw || '').trim();
        const normalizedPriority = normalizePriority(priorityRaw);
        const tcgInput = (tcgRaw || '').trim();

        if (!case_no) {
            errors.push({
                line,
                code: 'empty_case_no',
                message: window.i18n ? window.i18n.t('testCase.bulkText.emptyCaseNo') : '單號不可為空',
                raw
            });
            continue;
        }

        if (!title) {
            errors.push({
                line,
                code: 'empty_title',
                message: window.i18n ? window.i18n.t('testCase.bulkText.emptyTitle') : '標題不可為空',
                raw
            });
            continue;
        }

        if (priorityRaw && !normalizedPriority) {
            errors.push({
                line,
                code: 'invalid_priority',
                message: window.i18n ? window.i18n.t('testCase.bulkText.invalidPriority') : '優先級僅支援 High / Medium / Low',
                raw
            });
            continue;
        }

        const { tcgNumbers, invalidTokens } = normalizeBulkTcgNumbers(tcgInput);
        if (invalidTokens.length > 0) {
            const invalidMessage = window.i18n ?
                window.i18n.t('testCase.bulkText.invalidTcg', { numbers: invalidTokens.join(' | ') }) :
                `TCG 單號格式錯誤：${invalidTokens.join(' | ')}`;
            errors.push({
                line,
                code: 'invalid_tcg',
                message: invalidMessage,
                raw
            });
            continue;
        }

        // 第 8 欄（可選）：test_data JSON 陣列，需通過與 export 相同的可 round-trip 判定
        let testData = null;
        const testDataInput = (testDataRaw || '').trim();
        if (testDataInput) {
            let parsedTestData = null;
            try {
                parsedTestData = JSON.parse(testDataInput);
            } catch (_) {
                parsedTestData = null;
            }
            if (!validateBulkTestDataArray(parsedTestData)) {
                errors.push({
                    line,
                    code: 'invalid_test_data',
                    message: window.i18n ? window.i18n.t('testCase.bulkText.invalidTestData') : 'test_data 欄位需為合法 JSON 陣列且符合格式限制',
                    raw
                });
                continue;
            }
            if (parsedTestData.length > 0) testData = parsedTestData;
        }

        if (!caseNumbers.has(case_no)) {
            caseNumbers.set(case_no, []);
        }
        caseNumbers.get(case_no).push(line);

        items.push({
            line,
            case_no,
            title,
            precondition,
            steps,
            expected_result,
            priority: normalizedPriority || 'Medium',
            tcg_numbers: tcgNumbers,
            test_data: testData
        });
    }

    const duplicates = [];
    for (const [case_no, occupiedLines] of caseNumbers) {
        if (occupiedLines.length > 1) {
            duplicates.push({ case_no, lines: occupiedLines });
        }
    }

    return { items, errors, duplicates };
}

/**
 * 更新狀態顯示
 */
function updateBulkTextStatus(parseResult) {
    const statusEl = document.getElementById('bulkTextStatus');
    const validationEl = document.getElementById('bulkTextValidation');

    if (!statusEl || !validationEl) return;

    const { items, errors, duplicates } = parseResult;

    // 顯示基本統計
    if (items.length > 0 || errors.length > 0) {
        const statusText = window.i18n ?
            window.i18n.t('testCase.bulkText.statusText', { valid: items.length, errors: errors.length }) :
            `已解析 ${items.length} 筆，${errors.length} 筆錯誤`;
        statusEl.textContent = statusText;
    } else {
        statusEl.textContent = '';
    }

    // 顯示錯誤訊息
    if (errors.length > 0 || duplicates.length > 0) {
        const messages = [];
        if (errors.length > 0) {
            const errorMsg = window.i18n ?
                window.i18n.t('testCase.bulkText.validationErrors', { count: errors.length }) :
                `${errors.length} 行格式錯誤`;
            messages.push(errorMsg);
        }
        if (duplicates.length > 0) {
            const dupCount = duplicates.reduce((sum, d) => sum + d.lines.length, 0);
            const dupMsg = window.i18n ?
                window.i18n.t('testCase.bulkText.validationDuplicates', { count: dupCount }) :
                `${dupCount} 筆重複單號`;
            messages.push(dupMsg);
        }
        validationEl.textContent = messages.join(' / ');
        validationEl.className = 'text-danger small';
    } else {
        validationEl.textContent = '';
        validationEl.className = 'text-muted small';
    }
}

/**
 * 在編輯器中標記衝突的行
 */
function annotateConflictsInEditor(conflicts) {
    const textarea = document.getElementById('bulkTextInput');
    if (!textarea || !conflicts.length) return;

    const lines = textarea.value.split('\n');
    const conflictNumbers = new Set(conflicts);

    // 先移除所有現有的 (Conflict) 標記
    const cleanedLines = lines.map(line =>
        line.replace(/^\(Conflict\)\s*/, '')
    );

    // 重新加上衝突標記
    const annotatedLines = cleanedLines.map(line => {
        if (!line.trim()) return line;

        const columns = parseCsvLine(line.trim());
        if (!columns.length) return line;
        const case_no = (columns[0] || '').trim();
        if (conflictNumbers.has(case_no)) {
            return `(Conflict) ${line}`;
        }
        return line;
    });

    textarea.value = annotatedLines.join('\n');
}

/**
 * 在編輯器中標記有格式錯誤的行
 */
function annotateErrorsInEditor(errors) {
    const textarea = document.getElementById('bulkTextInput');
    if (!textarea || !errors.length) return;

    const lines = textarea.value.split('\n');
    const errorLineNumbers = new Set(errors.map(e => e.line));

    // 先移除所有現有的 (Error) 標記和 (Conflict) 標記
    const cleanedLines = lines.map(line =>
        line.replace(/^\((Error|Conflict)\)\s*/, '')
    );

    // 重新加上錯誤標記
    const annotatedLines = cleanedLines.map((line, index) => {
        const lineNumber = index + 1;
        if (!line.trim()) return line;
        if (errorLineNumbers.has(lineNumber)) {
            return `(Error) ${line}`;
        }
        return line;
    });

    textarea.value = annotatedLines.join('\n');
}

/**
 * 開始文字模式批次建立
 */
async function startBulkTextCreate() {
    const textarea = document.getElementById('bulkTextInput');
    if (!textarea) return;

    const rawText = textarea.value.trim();
    if (!rawText) {
        const emptyMessage = window.i18n ? window.i18n.t('testCase.bulkTextToast.emptyInput') : '請輸入資料';
        AppUtils.showWarning(emptyMessage);
        return;
    }

    // 解析輸入
    const parseResult = parseBulkText(rawText);
    updateBulkTextStatus(parseResult);

    const { items, errors, duplicates } = parseResult;

    // 檢查格式錯誤
    if (errors.length > 0) {
        // 標記有錯誤的行
        annotateErrorsInEditor(errors);
        const message = window.i18n ?
            window.i18n.t('testCase.bulkTextToast.invalid', { count: errors.length }) :
            `有 ${errors.length} 行格式錯誤，請修正後再試。`;
        AppUtils.showError(message);
        return;
    }

    // 檢查輸入內部重複
    if (duplicates.length > 0) {
        const message = window.i18n ?
            window.i18n.t('testCase.bulkTextToast.duplicateInInput') :
            '輸入中有重複的單號';
        AppUtils.showError(message);
        return;
    }

    if (items.length === 0) {
        const noItemsMessage = window.i18n ? window.i18n.t('testCase.bulkTextToast.noValidItems') : '沒有有效的資料可以建立';
        AppUtils.showWarning(noItemsMessage);
        return;
    }

    // 檢查與資料庫的衝突
    try {
        const conflicts = await checkBulkConflicts(items.map(item => item.case_no));

        if (conflicts.length > 0) {
            // 標記衝突的行
            annotateConflictsInEditor(conflicts);

            const message = window.i18n ?
                window.i18n.t('testCase.bulkTextToast.conflict', { count: conflicts.length }) :
                `發現單號衝突，共 ${conflicts.length} 筆。已在文字前加上「(Conflict)」標記。`;
            AppUtils.showWarning(message);
            return;
        }

        // 無衝突，顯示預覽
        bulkTextParsedItems = items;
        showBulkPreviewModal(items);

    } catch (error) {
        console.error('Check conflicts failed:', error);
        const message = window.i18n ?
            window.i18n.t('testCase.bulkTextToast.networkError') :
            '網路錯誤，請稍後再試';
        AppUtils.showError(message);
    }
}

/**
 * 檢查與資料庫的衝突
 */
async function checkBulkConflicts(caseNumbers) {
    const currentTeam = AppUtils.getCurrentTeam();
    if (!currentTeam || !currentTeam.id) {
        throw new Error(window.i18n ? window.i18n.t('errors.pleaseSelectTeam', {}, '請先選擇團隊') : '請先選擇團隊');
    }

    // 簡化版：直接檢查現有 testCases 陣列
    const existing = new Set(testCases.map(tc => tc.test_case_number).filter(Boolean));
    return caseNumbers.filter(caseNo => existing.has(caseNo));
}

/**
 * 顯示預覽對話框
 */
function showBulkPreviewModal(items) {
    const modalEl = document.getElementById('bulkPreviewModal');
    const descEl = document.getElementById('bulkPreviewDesc');
    const listEl = document.getElementById('bulkPreviewList');

    if (!modalEl || !descEl || !listEl) return;

    // 設定描述
        const descText = window.i18n ?
        window.i18n.t('testCase.bulkText.confirmDesc', { count: items.length }) :
        `將新增以下 ${items.length} 筆測試案例：`;
    descEl.textContent = descText;

    // 渲染列表
    listEl.innerHTML = items.map((item, index) => {
        const prioritySuffix = (item.priority || 'Medium');
        const priorityLabel = window.i18n ? window.i18n.t(`testCase.priority${prioritySuffix}`, {}, prioritySuffix) : prioritySuffix;
        const title = item.title || '';
        const precondition = item.precondition || '';
        const steps = item.steps || '';
        const expected = item.expected_result || '';
        const tcgDisplay = (item.tcg_numbers || []).join(', ');
        // Test Data 摘要只顯示 name 與 canonical category，一律不顯示 value（credential 遮罩）
        const testDataDisplay = (item.test_data || [])
            .map(td => `${td.name} (${bulkTestDataEffectiveCategory(td.category)})`)
            .join(', ');

        // 將字面的 \n 轉換為真正的換行符號，然後轉換為 <br> 用於 HTML 顯示
        const convertNewlinesForDisplay = (text) => {
            if (!text) return '';
            return escapeHtml(truncateText(text.replace(/\\n/g, '\n'))).replace(/\n/g, '<br>');
        };

        // 為 title 屬性轉換換行符號（不使用 <br>）
        const convertNewlinesForTitle = (text) => {
            if (!text) return '';
            return escapeHtml(text.replace(/\\n/g, '\n'));
        };

        return `
        <tr>
            <td>${index + 1}</td>
            <td><code>${escapeHtml(item.case_no)}</code></td>
            <td style="width: 220px;" title="${convertNewlinesForTitle(title)}">${escapeHtml(truncateText(title))}</td>
            <td style="white-space: pre-wrap;" title="${convertNewlinesForTitle(precondition)}">${convertNewlinesForDisplay(precondition)}</td>
            <td style="white-space: pre-wrap;" title="${convertNewlinesForTitle(steps)}">${convertNewlinesForDisplay(steps)}</td>
            <td style="white-space: pre-wrap;" title="${convertNewlinesForTitle(expected)}">${convertNewlinesForDisplay(expected)}</td>
            <td style="width: 280px; min-width: 21ch;" title="${escapeHtml(tcgDisplay)}">${escapeHtml(truncateText(tcgDisplay, 120))}</td>
            <td style="width: 200px;" title="${escapeHtml(testDataDisplay)}">${escapeHtml(truncateText(testDataDisplay, 120))}</td>
            <td>${escapeHtml(priorityLabel)}</td>
        </tr>
        `;
    }).join('');

    // 顯示 Modal
    if (!bulkPreviewModalInstance) {
        bulkPreviewModalInstance = new bootstrap.Modal(modalEl);
    }

    if (window.i18n && window.i18n.isReady()) {
        window.i18n.retranslate(modalEl);
    }

    bulkPreviewModalInstance.show();
}

/**
 * 確認建立批次測試案例
 */
async function confirmBulkTextCreate() {
    if (!bulkTextParsedItems.length) {
        AppUtils.showError(window.i18n ? window.i18n.t('testCase.bulkTextToast.noValidItems', {}, '沒有項目可以建立') : '沒有項目可以建立');
        return;
    }

    const currentTeam = AppUtils.getCurrentTeam();
    if (!currentTeam || !currentTeam.id) {
        AppUtils.showError(window.i18n ? window.i18n.t('errors.pleaseSelectTeam', {}, '請先選擇團隊') : '請先選擇團隊');
        return;
    }

    // 顯示進度條
    showBulkProgress(bulkTextParsedItems.length);

    // 更新按鈕狀態
    const confirmBtn = document.getElementById('confirmBulkCreateBtn');
    const originalHtml = confirmBtn ? confirmBtn.innerHTML : '';

    if (confirmBtn) {
        confirmBtn.disabled = true;
        const creatingText = window.i18n ? window.i18n.t('testCase.bulk.creating') : '建立中...';
        confirmBtn.innerHTML = `<i class="fas fa-spinner fa-spin me-2"></i>${creatingText}`;
    }

    try {
        // 輔助函數：將字面的 \n 轉換為真正的換行符號
        const convertLiteralNewlines = (text) => {
            if (!text) return text;
            return text.replace(/\\n/g, '\n');
        };

        // 注意：test_data 為 JSON 解析結果，不得套用正文欄位的 \n 轉換
        const items = bulkTextParsedItems.map(item => ({
            test_case_number: item.case_no,
            title: item.title,
            precondition: convertLiteralNewlines(item.precondition) || null,
            steps: convertLiteralNewlines(item.steps) || null,
            expected_result: convertLiteralNewlines(item.expected_result) || null,
            priority: item.priority || 'Medium',
            tcg_numbers: Array.isArray(item.tcg_numbers) ? item.tcg_numbers : [],
            ...(Array.isArray(item.test_data) && item.test_data.length ? { test_data: item.test_data } : {})
        }));

        // 包含當前選擇的 Test Case Set ID 和 Section ID（如果有的話）
        const bulkSectionSelect = document.getElementById('bulkCreateSectionSelect');
        const selectedSectionId = bulkSectionSelect && bulkSectionSelect.value ? parseInt(bulkSectionSelect.value) : null;

        const requestBody = {
            items,
            ...(currentSetId && { test_case_set_id: currentSetId }),
            ...(selectedSectionId && { test_case_section_id: selectedSectionId })
        };

        const response = await window.AuthClient.fetch(`/api/teams/${currentTeam.id}/testcases/bulk_create`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(requestBody)
        });

        const data = await response.json();

        if (!response.ok || !data.success) {
            // 檢查是否有新的衝突
            if (data.duplicates && data.duplicates.length > 0) {
                // 關閉預覽對話框，回到編輯模式
                if (bulkPreviewModalInstance) {
                    bulkPreviewModalInstance.hide();
                }

                // 標記衝突
                annotateConflictsInEditor(data.duplicates);

                const message = window.i18n ?
                    window.i18n.t('testCase.bulkTextToast.conflict', { count: data.duplicates.length }) :
                    `發現單號衝突，共 ${data.duplicates.length} 筆。已在文字前加上「(Conflict)」標記。`;
                AppUtils.showWarning(message);
                return;
            }

            const errorMsg = (data.errors && data.errors.join('; ')) || response.statusText ||
                (window.i18n ? window.i18n.t('messages.createFailed', {}, '建立失敗') : '建立失敗');
            throw new Error(errorMsg);
        }

        // 成功建立
        updateBulkProgress(bulkTextParsedItems.length, bulkTextParsedItems.length);

        const message = window.i18n ?
            window.i18n.t('testCase.bulkTextToast.success', { count: data.created_count || bulkTextParsedItems.length }) :
            `已成功新增 ${data.created_count || bulkTextParsedItems.length} 筆測試案例`;
        AppUtils.showSuccess(message);

        // 關閉所有 Modal
        if (bulkPreviewModalInstance) bulkPreviewModalInstance.hide();
        if (bulkModalInstance) bulkModalInstance.hide();

        // 清除快取並強制重新載入測試案例列表，確保顯示最新新增資料
        clearTestCasesCache();
        await loadTestCases(false, null, true);

    } catch (error) {
        console.error('Bulk create failed:', error);
        const message = error.message || (window.i18n ? window.i18n.t('messages.createFailed', {}, '建立失敗') : '建立失敗');
        AppUtils.showError(message);

    } finally {
        // 恢復按鈕狀態
        if (confirmBtn) {
            confirmBtn.disabled = false;
            confirmBtn.innerHTML = originalHtml;
        }
        hideBulkProgress();
    }
}

// 簡單的 HTML 轉義，供動態模板使用
function escapeHtml(text) {
    if (text === undefined || text === null) return '';
    const map = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' };
    return String(text).replace(/[&<>"']/g, (m) => map[m]);
}

function showBulkProgress(total) {
    document.getElementById('bulkProgress').style.display = 'block';
    updateBulkProgress(0, total);
}
function hideBulkProgress() {
    document.getElementById('bulkProgress').style.display = 'none';
}
function updateBulkProgress(done, total) {
    const pct = total > 0 ? Math.round((done / total) * 100) : 0;
    document.getElementById('bulkProgressText').textContent = `${done}/${total}`;
    document.getElementById('bulkProgressBar').style.width = `${pct}%`;
}

// 舊的 startBulkCreate 函式已移除，使用 startBulkTextCreate 取代

// 複製 Test Case：開啟與「新增/編輯」相同的 Modal，預填欄位
function copyTestCase(id) {
    const source = testCases.find(tc => tc.record_id === id);
    if (!source) return;
    // 標記為複製模式，供 showTestCaseModal 判斷隱藏「儲存並新增下一筆」
    try {
        const modal = document.getElementById('testCaseModal');
        if (modal && modal.dataset) modal.dataset.copyMode = '1';
    } catch (_) {}
    // 先以新增模式打開，確保狀態正確（不帶 record_id，附件清空，按鈕狀態正確）
    showTestCaseModal(null);

    // 設定 Modal 標題為「複製測試案例」
    const modalTitle = document.getElementById('testCaseModalTitle');
    if (modalTitle) {
        const copyText = window.i18n ? window.i18n.t('common.copy') : '複製';
        const baseTitle = window.i18n ? window.i18n.t('testCase.createTestCase') : '新增測試案例';
        modalTitle.textContent = `${copyText} ${baseTitle}`;
    }

    // 預填欄位（編號留空，避免重複；標題前綴「複製 - 」）
    const copyWord = window.i18n ? window.i18n.t('common.copy') : '複製';
    document.getElementById('testCaseId').value = '';
    document.getElementById('title').value = `${copyWord} - ${source.title || ''}`;
    document.getElementById('testCaseNumber').value = '';
    document.getElementById('priority').value = source.priority || 'Medium';

    // 保留來源 TCG 單號（單一或多個以逗號分隔的字串）
    const tcgValue = source.tcg ? source.tcg.map(t => t.text || t).join(', ') : '';
    document.getElementById('tcg').value = tcgValue;

    // 初始化 Modal TCG 多選顯示（每一個單號一個 tag）
    modalTCGSelected = tcgValue ? tcgValue.split(', ').filter(Boolean) : [];
    renderModalTCGDisplay();

    document.getElementById('precondition').value = source.precondition || '';
    document.getElementById('test_steps').value = source.steps || '';
    document.getElementById('expected_result').value = source.expected_result || '';

    // 更新 Markdown 預覽
    try {
        markdownFields.forEach(fieldId => updateMarkdownPreview(fieldId));
    } catch (_) {}

    // 新增模式下的按鈕狀態
    const saveBtn = document.getElementById('saveTestCaseBtn');
    const saveAndAddNextBtn = document.getElementById('saveAndAddNextBtn');
    if (saveBtn) saveBtn.disabled = false;
    if (saveAndAddNextBtn) {
        // 複製模式：不提供「儲存並新增下一筆」
        saveAndAddNextBtn.disabled = true;
        saveAndAddNextBtn.style.display = 'none';
    }

    // 編輯器模式採用 split（與新增一致）
    try { setEditorMode('split'); } catch (_) {}
}

// 顯示複製選擇器：在 Modal 中選擇要複製的測試案例
function showCloneSelector() {
    if (testCases.length === 0) {
        const message = window.i18n ? window.i18n.t('errors.noTestCasesAvailable') : '沒有可用的測試案例';
        AppUtils.showError(message);
        return;
    }

    // 創建動態 modal 來選擇測試案例
    const modalId = 'cloneSelectorModal';
    const existingModal = document.getElementById(modalId);
    if (existingModal) {
        existingModal.remove();
    }

    // 創建選擇器 modal HTML
    const modalHtml = `
        <div class="modal fade" id="${modalId}" tabindex="-1" aria-hidden="true">
            <div class="modal-dialog modal-dialog-centered">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title">
                            <i class="fas fa-clone me-2"></i>
                            ${window.i18n ? window.i18n.t('testCase.cloneAndAddNext') : '複製並新增下一筆'}
                        </h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        <div class="mb-3">
                            <label class="form-label">${window.i18n ? window.i18n.t('testCase.selectSourceTestCase') : '選擇要複製的測試案例'}</label>
                            <select class="form-select" id="cloneSourceSelect">
                                <option value="">${window.i18n ? window.i18n.t('common.pleaseSelect') : '請選擇...'}</option>
                                ${testCases.map(tc =>
                                    `<option value="${tc.record_id}">${tc.test_case_number || (window.i18n ? window.i18n.t('testCase.batchCopy.notAvailable', {}, 'N/A') : 'N/A')} - ${tc.title || (window.i18n ? window.i18n.t('testCase.batchCopy.untitled', {}, '無標題') : '無標題')}</option>`
                                ).join('')}
                            </select>
                        </div>
                    </div>
                    <div class="modal-footer">
                        <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">
                            ${window.i18n ? window.i18n.t('common.cancel') : '取消'}
                        </button>
                        <button type="button" class="btn btn-primary" id="confirmCloneBtn">
                            <i class="fas fa-check me-2"></i>
                            ${window.i18n ? window.i18n.t('common.confirm') : '確認'}
                        </button>
                    </div>
                </div>
            </div>
        </div>
    `;

    // 將 modal 添加到頁面
    document.body.insertAdjacentHTML('beforeend', modalHtml);

    // 初始化 modal
    const cloneSelectorModal = new bootstrap.Modal(document.getElementById(modalId));

    // 綁定確認按鈕事件
    document.getElementById('confirmCloneBtn').addEventListener('click', function() {
        const selectedId = document.getElementById('cloneSourceSelect').value;
        if (!selectedId) {
            AppUtils.showError(window.i18n ? window.i18n.t('errors.pleaseSelectTestCase') : '請選擇測試案例');
            return;
        }

        // 檢查是否有未儲存的變更
        if (hasUnsavedChanges()) {
            // 關閉選擇器 modal 先
            cloneSelectorModal.hide();

            // 顯示儲存確認對話框
            const confirmTitle = window.i18n ? window.i18n.t('common.confirm') : '確認';
            const confirmMessage = window.i18n ? window.i18n.t('testCase.unsavedChangesPrompt') : '您有未儲存的變更，是否要先儲存？';
            const saveAndContinue = window.i18n ? window.i18n.t('testCase.saveAndContinue') : '儲存並繼續';
            const continueWithoutSave = window.i18n ? window.i18n.t('testCase.continueWithoutSave') : '不儲存直接繼續';
            const cancelAction = window.i18n ? window.i18n.t('common.cancel') : '取消';

            const confirmModalHtml = `
                <div class="modal fade" id="saveConfirmModal" tabindex="-1" aria-hidden="true">
                    <div class="modal-dialog modal-dialog-centered">
                        <div class="modal-content">
                            <div class="modal-header">
                                <h5 class="modal-title">
                                    <i class="fas fa-exclamation-triangle text-warning me-2"></i>
                                    ${confirmTitle}
                                </h5>
                                <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                            </div>
                            <div class="modal-body">
                                <p>${confirmMessage}</p>
                            </div>
                            <div class="modal-footer">
                                <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">${cancelAction}</button>
                                <button type="button" class="btn btn-danger" id="continueWithoutSaveBtn">${continueWithoutSave}</button>
                                <button type="button" class="btn btn-primary" id="saveAndContinueBtn">
                                    <i class="fas fa-save me-2"></i>${saveAndContinue}
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
            `;

            // 移除舊的確認 modal
            const existingConfirmModal = document.getElementById('saveConfirmModal');
            if (existingConfirmModal) {
                existingConfirmModal.remove();
            }

            // 添加確認 modal
            document.body.insertAdjacentHTML('beforeend', confirmModalHtml);
            const saveConfirmModal = new bootstrap.Modal(document.getElementById('saveConfirmModal'));
            saveConfirmModal.show();

            // 綁定按鈕事件
            document.getElementById('saveAndContinueBtn').addEventListener('click', async function() {
                saveConfirmModal.hide();

                // 嘗試儲存當前表單
                try {
                    const saveBtn = document.getElementById('saveTestCaseBtn');
                    if (saveBtn) {
                        saveBtn.click();

                        // 等待儲存完成，然後執行複製
                        setTimeout(() => {
                            executeCloneAction(selectedId);
                        }, 500);
                    }
                } catch (error) {
                    console.error('儲存失敗:', error);
                    AppUtils.showError(window.i18n ? window.i18n.t('errors.saveFailed') : '儲存失敗');
                }
            });

            document.getElementById('continueWithoutSaveBtn').addEventListener('click', function() {
                saveConfirmModal.hide();
                executeCloneAction(selectedId);
            });

        } else {
            // 沒有未儲存變更，直接執行複製
            executeCloneAction(selectedId);
        }
    });

    // 執行複製操作的共用函數
    function executeCloneAction(selectedId) {
        // 關閉選擇器 modal（如果還開著）
        if (cloneSelectorModal) {
            cloneSelectorModal.hide();
        }

        // 關閉當前測試案例 modal
        const testCaseModal = document.getElementById('testCaseModal');
        const testCaseModalInstance = bootstrap.Modal.getInstance(testCaseModal);
        if (testCaseModalInstance) {
            testCaseModalInstance.hide();
        }

        // 延遲執行複製，確保 modal 完全關閉
        setTimeout(() => {
            cloneAndAddNext(selectedId);
        }, 300);
    }

    // Modal 關閉後清理
    document.getElementById(modalId).addEventListener('hidden.bs.modal', function() {
        this.remove();
    });

    // 顯示 modal
    cloneSelectorModal.show();
}

// 複製並新增下一筆 Test Case：基於 copyTestCase 邏輯，但保持「儲存並新增下一筆」功能
function cloneAndAddNext(id) {
    const source = testCases.find(tc => tc.record_id === id);
    if (!source) return;

    // 先以新增模式打開，確保狀態正確（不帶 record_id，附件清空，按鈕狀態正確）
    showTestCaseModal(null);

    // 設定 Modal 標題為「複製並新增下一筆測試案例」
    const modalTitle = document.getElementById('testCaseModalTitle');
    if (modalTitle) {
        const cloneText = window.i18n ? window.i18n.t('testCase.cloneAndAddNext') : '複製並新增下一筆';
        const baseTitle = window.i18n ? window.i18n.t('testCase.testCase') : '測試案例';
        modalTitle.textContent = `${cloneText} ${baseTitle}`;
    }

    // 預填欄位（編號自動遞增，標題保持原樣）
    document.getElementById('testCaseId').value = '';
    document.getElementById('title').value = source.title || '';

    // 自動生成下一個測試案例編號
    const nextNumber = generateNextTestCaseNumber(source.test_case_number);
    document.getElementById('testCaseNumber').value = nextNumber;

    document.getElementById('priority').value = source.priority || 'MEDIUM';

    // 保留來源 TCG 單號（單一或多個以逗號分隔的字串）
    const tcgValue = source.tcg ? source.tcg.map(t => t.text || t).join(', ') : '';
    const tcgDisplay = document.getElementById('tcg');
    if (tcgDisplay) tcgDisplay.value = tcgValue;

    document.getElementById('precondition').value = source.precondition || '';
    document.getElementById('test_steps').value = source.steps || '';
    document.getElementById('expected_result').value = source.expected_result || '';

    // 更新 Markdown 預覽
    try {
        const markdownFields = ['precondition', 'test_steps', 'expected_result'];
        markdownFields.forEach(fieldId => updateMarkdownPreview(fieldId));
    } catch (_) {}

    // 新增模式下的按鈕狀態（保持「儲存並新增下一筆」可用）
    const saveBtn = document.getElementById('saveTestCaseBtn');
    const saveAndAddNextBtn = document.getElementById('saveAndAddNextBtn');
    if (saveBtn) saveBtn.disabled = false;
    if (saveAndAddNextBtn) {
        // 與一般新增模式相同，保持「儲存並新增下一筆」可用
        saveAndAddNextBtn.disabled = false;
        saveAndAddNextBtn.style.display = 'inline-block';
        // 重置按鈕文字為正常狀態
        const saveAndNextText = window.i18n ? window.i18n.t('form.saveAndNext') : '儲存並新增下一筆';
        saveAndAddNextBtn.innerHTML = `<i class=\"fas fa-plus me-2\"></i>${saveAndNextText}`;
    }

    // 編輯器模式採用 split（與新增一致）
    try { setEditorMode('split'); } catch (_) {}
}

// 生成下一個測試案例編號的輔助函數
// 統一處理各種格式：TC001, TC-001, TCG-93178.020.050 等
function generateNextTestCaseNumber(currentNumber, options = {}) {
    if (!currentNumber) return '';

    const { increment = 1 } = options; // 預設遞增 1，TCG 格式用 10

    // 優先處理 TCG 格式：TCG-93178.020.050（多段式，最後一段遞增）
    const tcgMatch = currentNumber.match(/^(.+\.)(\d+)$/);
    if (tcgMatch) {
        const prefix = tcgMatch[1];  // TCG-93178.020.
        const lastNumber = parseInt(tcgMatch[2]);
        // TCG 格式預設遞增 10
        const tcgIncrement = (increment === 1) ? 10 : increment;
        const nextNumber = (lastNumber + tcgIncrement).toString().padStart(tcgMatch[2].length, '0');
        return prefix + nextNumber;
    }

    // 嘗試匹配常見的測試案例編號格式
    const patterns = [
        /^([A-Z]+)(\d+)$/,           // TC001, TEST123
        /^([A-Z]+)-(\d+)$/,         // TC-001, TEST-123
        /^([A-Z]+)_(\d+)$/,         // TC_001, TEST_123
        /^(\d+)$/,                  // 001, 123
    ];

    for (let pattern of patterns) {
        const match = currentNumber.match(pattern);
        if (match) {
            const prefix = match[1] || '';
            const number = parseInt(match[2] || match[1]);
            const nextNum = number + increment;

            // 保持原有的數字位數（零填充）
            const originalNumStr = match[2] || match[1];
            const paddedNext = nextNum.toString().padStart(originalNumStr.length, '0');

            if (pattern.source.includes('-')) {
                return `${prefix}-${paddedNext}`;
            } else if (pattern.source.includes('_')) {
                return `${prefix}_${paddedNext}`;
            } else if (prefix) {
                return `${prefix}${paddedNext}`;
            } else {
                return paddedNext;
            }
        }
    }

    // 如果沒有匹配到任何模式，返回原編號 + "_NEXT"
    return currentNumber + '_NEXT';
}
