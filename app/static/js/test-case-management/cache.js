/* ============================================================
   TEST CASE MANAGEMENT - CACHE/TEAM/PERMISSIONS
   ============================================================ */

/* ============================================================
   4. 快取管理 (Cache Management)
   ============================================================ */

/* ------------------------------------------------------------
   4.1 執行快取 (Exec Cache)
   ------------------------------------------------------------ */

/**
 * 設定執行快取的測試案例
 * @param {string} testCaseNumber - 測試案例編號
 * @param {object} data - 測試案例資料
 */
function setExecCachedTestCase(testCaseNumber, data) {
    try {
        const teamId = getTeamIdForCache(false);
        if (!teamId) {
            console.debug('[CACHE] SKIP WRITE exec: no valid teamId', { testCaseNumber });
            return;
        }
        console.debug('[CACHE] QUEUE WRITE exec', { teamId, testCaseNumber });
        // 非阻塞寫入 TRCache（IndexedDB + gzip）
        Promise.resolve().then(() => TRCache.setExecDetail(teamId, testCaseNumber, data)).catch(() => {});
    } catch (_) {}
}

/**
 * 移除執行快取的測試案例
 * @param {string} testCaseNumber - 測試案例編號
 */
function removeExecCachedTestCase(testCaseNumber) {
    try {
        const teamId = getTeamIdForCache(false);
        if (!teamId || !testCaseNumber) return;
        Promise.resolve().then(() => TRCache.removeExecDetail(teamId, testCaseNumber)).catch(() => {});
    } catch (_) {}
}

/* ------------------------------------------------------------
   4.2 廣播更新 (Broadcast Updates)
   ------------------------------------------------------------ */

/**
 * 廣播測試案例更新事件（跨分頁同步）
 * @param {object} testCase - 測試案例物件
 * @param {object} overrides - 覆蓋的屬性
 */
function broadcastTestCaseUpdate(testCase, overrides = {}) {
    try {
        const teamId = getTeamIdForCache(true);
        if (!teamId || !testCase || !testCase.test_case_number) return;
        const priorityValue = (() => {
            if (!testCase.priority) return '';
            if (typeof testCase.priority === 'string') return testCase.priority;
            if (testCase.priority && typeof testCase.priority === 'object') {
                if (typeof testCase.priority.value === 'string') return testCase.priority.value;
                if (typeof testCase.priority.name === 'string') return testCase.priority.name;
            }
            return '';
        })();
        const payload = {
            teamId: String(teamId),
            test_case_number: testCase.test_case_number,
            title: testCase.title || '',
            priority: priorityValue,
            precondition: testCase.precondition || '',
            steps: testCase.steps || '',
            expected_result: testCase.expected_result || '',
            timestamp: Date.now(),
            ...overrides
        };
        localStorage.setItem(TEST_CASE_UPDATE_EVENT_KEY, JSON.stringify(payload));
    } catch (err) {
        console.debug('broadcastTestCaseUpdate skipped:', err);
    }
}

/* ------------------------------------------------------------
   4.3 篩選器儲存 (Filters Storage)
   ------------------------------------------------------------ */

/**
 * 取得篩選器儲存的 key（依團隊隔離）
 */
function getTcmFiltersStorageKey() {
    try {
        const teamId = getTeamIdForCache(false);
        return teamId ? `${TCM_FILTERS_STORAGE_PREFIX}:${String(teamId)}` : null;
    } catch (_) { return null; }
}

/**
 * 儲存篩選器到 localStorage
 */
function saveTcmFiltersToStorage(filters) {
    try {
        const key = getTcmFiltersStorageKey();
        if (!key) return;
        const payload = {
            testCaseNumberSearch: String(filters.testCaseNumberSearch || ''),
            searchInput: String(filters.searchInput || ''),
            tcgFilter: String(filters.tcgFilter || ''),
            priorityFilter: String(filters.priorityFilter || ''),
            ts: Date.now()
        };
        localStorage.setItem(key, JSON.stringify(payload));
    } catch (_) {}
}

function loadTcmFiltersFromStorage() {
    try {
        const key = getTcmFiltersStorageKey();
        if (!key) return null;
        const raw = localStorage.getItem(key);
        if (!raw) return null;
        const obj = JSON.parse(raw);
        if (!obj || typeof obj !== 'object') return null;
        return {
            testCaseNumberSearch: obj.testCaseNumberSearch || '',
            searchInput: obj.searchInput || '',
            tcgFilter: obj.tcgFilter || '',
            priorityFilter: obj.priorityFilter || ''
        };
    } catch (_) { return null; }
}

function clearTcmFiltersInStorage() {
    try {
        const key = getTcmFiltersStorageKey();
        if (!key) return;
        localStorage.removeItem(key);
    } catch (_) {}
}

function restoreTcmFiltersToUI() {
    const saved = loadTcmFiltersFromStorage();
    if (!saved) return false;
    try {
        const elNum = document.getElementById('testCaseNumberSearch');
        const elSearch = document.getElementById('searchInput');
        const elTCG = document.getElementById('tcgFilter');
        const elPri = document.getElementById('priorityFilter');
        if (elNum) elNum.value = saved.testCaseNumberSearch || '';
        if (elSearch) elSearch.value = saved.searchInput || '';
        if (elTCG) elTCG.value = saved.tcgFilter || '';
        if (elPri) elPri.value = saved.priorityFilter || '';
        updateFilterStatus();
        // 同步到記憶體中的目前過濾器
        tcmCurrentFilters.testCaseNumberSearch = saved.testCaseNumberSearch || '';
        tcmCurrentFilters.searchInput = saved.searchInput || '';
        tcmCurrentFilters.tcgFilter = saved.tcgFilter || '';
        tcmCurrentFilters.priorityFilter = saved.priorityFilter || '';
        return (saved.testCaseNumberSearch || saved.searchInput || saved.tcgFilter || saved.priorityFilter) ? true : false;
    } catch (_) { return false; }
}

// NOTE: tcmCurrentFilters 已統一定義於 Section 2 (全域變數)

function computeFilteredTestCases(list) {
    try {
        const numKW = String(tcmCurrentFilters.testCaseNumberSearch || '').toLowerCase();
        const kw = String(tcmCurrentFilters.searchInput || '').toLowerCase();
        const tcgKW = String(tcmCurrentFilters.tcgFilter || '').toLowerCase();
        const pri = String(tcmCurrentFilters.priorityFilter || '');
        const res = (list || []).filter(testCase => {
            // 如果指定了 currentSetId，則只顯示該 set 的 test case
            // 通過檢查 section 的 test_case_set_id 或記錄是否在當前 set 的 sections 中
            if (currentSetId) {
                // 如果 test case 有 section id，檢查該 section 是否屬於當前 set
                // 這需要維護一個 section id 到 set id 的映射，或者檢查 API 返回的數據
                // 暫時：如果後端返回了不正確的數據，前端應該過濾
                // 注意：這個檢查取決於後端如何組織數據
                // 如果後端沒有正確過濾，這裡可能無法精確過濾
                // 最好的方案是依賴後端 API 使用 set_id 參數進行過濾
            }

            // Test Case Number 或 TCG（綜合）搜尋
            const matchNum = !numKW ||
                (testCase.test_case_number && String(testCase.test_case_number).toLowerCase().includes(numKW)) ||
                (testCase.tcg && testCase.tcg.some(tcgItem => {
                    const tcgText = (tcgItem && (tcgItem.text || tcgItem)) || '';
                    return String(tcgText).toLowerCase().includes(numKW);
                }));
            // 專用 TCG 單號過濾器（精確針對 TCG 欄位）
            const matchTCG = !tcgKW || (testCase.tcg && testCase.tcg.some(tcgItem => {
                // 支援 text 與 text_arr
                const texts = [];
                if (typeof tcgItem === 'string') {
                    texts.push(tcgItem);
                }
                if (tcgItem && Array.isArray(tcgItem.text_arr) && tcgItem.text_arr.length) {
                    texts.push(...tcgItem.text_arr);
                }
                if (tcgItem && tcgItem.text) {
                    texts.push(tcgItem.text);
                }
                return texts.some(t => String(t || '').toLowerCase().includes(tcgKW));
            }));
            // 標題/描述關鍵字
            const matchSearch = !kw ||
                (testCase.title && String(testCase.title).toLowerCase().includes(kw)) ||
                (testCase.description && String(testCase.description).toLowerCase().includes(kw));
            // 優先級
            const matchPri = !pri || testCase.priority === pri;
            return matchNum && matchTCG && matchSearch && matchPri;
        });
        return res;
    } catch (_) { return Array.isArray(list) ? list.slice() : []; }
}

function applyCurrentFiltersAndRender() {
    try {
        filteredTestCases = computeFilteredTestCases(testCases);
        currentPage = 1;
        renderTestCasesTable();
        updatePagination();
        updateFilterStatus();
    } catch (_) {
        // 回退：顯示全量
        filteredTestCases = Array.isArray(testCases) ? testCases.slice() : [];
        currentPage = 1;
        renderTestCasesTable();
        updatePagination();
        updateFilterStatus();
    }
}

function updateTcmSortIndicators() {
    try {
        document.querySelectorAll('.section-table').forEach(table => {
            const sectionId = table.getAttribute('data-section-id');
            const state = sectionSortStates.get(sectionId);
            const field = state?.field || tcmSortField;
            const order = state?.order || tcmSortOrder;
            table.querySelectorAll('.sort-indicator').forEach(el => el.textContent = '');
            const attr = mapFieldToAttr(field);
            const indicator = table.querySelector(`th[data-sort-field="${attr}"] .sort-indicator`);
            if (indicator) {
                indicator.textContent = order === 'asc' ? '▲' : '▼';
            }
        });
    } catch (_) {}
}

// 強制同步篩選欄位的 placeholder（防止極端情境未翻譯）
function updateTcmPlaceholders() {
    try {
        if (!window.i18n || !window.i18n.isReady()) return;
        const elNum = document.getElementById('testCaseNumberSearch');
        const elSearch = document.getElementById('searchInput');
        const elTCG = document.getElementById('tcgFilter');
        if (elNum) elNum.setAttribute('placeholder', window.i18n.t('testCase.testCaseNumberPlaceholder', {}, elNum.getAttribute('data-i18n-placeholder-fallback') || ''));
        if (elSearch) elSearch.setAttribute('placeholder', window.i18n.t('testCase.searchPlaceholder', {}, elSearch.getAttribute('data-i18n-placeholder-fallback') || ''));
        if (elTCG) elTCG.setAttribute('placeholder', window.i18n.t('testCase.tcgFilterPlaceholder', {}, elTCG.getAttribute('data-i18n-placeholder-fallback') || ''));
    } catch (_) {}
}

// NOTE: PRIORITY_RANK 已統一定義於 Section 1 (常數定義)

function parseNumberSegments(str) {
    try {
        if (!str) return [];
        const ms = String(str).match(/\d+/g);
        return ms ? ms.map(s => parseInt(s, 10)) : [];
    } catch (_) { return []; }
}

function compareByNumericParts(aStr, bStr) {
    const aSeg = parseNumberSegments(aStr);
    const bSeg = parseNumberSegments(bStr);
    const len = Math.min(aSeg.length, bSeg.length);
    for (let i = 0; i < len; i++) {
        if (aSeg[i] !== bSeg[i]) return aSeg[i] - bSeg[i];
    }
    return aSeg.length - bSeg.length;
}

function getFirstTCGNumber(tc) {
    try {
        if (!tc || !tc.tcg || !tc.tcg.length) return '';
        for (const r of tc.tcg) {
            if (r && Array.isArray(r.text_arr) && r.text_arr.length) return r.text_arr[0];
            if (r && r.text) return r.text;
        }
        return '';
    } catch (_) { return ''; }
}

function compareTestCaseField(a, b, field) {
    switch (field) {
        case 'number':
            return compareByNumericParts(a.test_case_number || '', b.test_case_number || '');
        case 'title':
            return (a.title || '').toLowerCase().localeCompare((b.title || '').toLowerCase());
        case 'tcg':
            return compareByNumericParts(getFirstTCGNumber(a), getFirstTCGNumber(b));
        case 'priority':
            return (PRIORITY_RANK[a.priority] || 0) - (PRIORITY_RANK[b.priority] || 0);
        case 'created':
            return new Date(a.created_at || 0) - new Date(b.created_at || 0);
        case 'updated':
            return new Date(a.updated_at || 0) - new Date(b.updated_at || 0);
        default:
            return 0;
    }
}

function sortTestCaseList(list, field, order = 'asc') {
    if (!Array.isArray(list) || !field) return;
    list.sort((a, b) => {
        const result = compareTestCaseField(a, b, field);
        return order === 'asc' ? result : -result;
    });
}

function sortFilteredTestCases() {
    sortTestCaseList(filteredTestCases, tcmSortField, tcmSortOrder);
}

// NOTE: UNASSIGNED_SECTION_ID 已統一定義於 Section 1 (常數定義)
function isUnassignedSectionIdValue(sectionId) {
    const key = String(sectionId);
    if (key === UNASSIGNED_SECTION_ID) return true;
    if (tcmUnassignedSectionIds && tcmUnassignedSectionIds.has(key)) return true;
    return false;
}

function resolveSectionIdForGrouping(testCase) {
    if (testCase && testCase.test_case_section_id !== null && testCase.test_case_section_id !== undefined) {
        return testCase.test_case_section_id;
    }
    if (tcmUnassignedSectionIds && tcmUnassignedSectionIds.size > 0) {
        const fallbackId = Array.from(tcmUnassignedSectionIds)[0];
        if (fallbackId !== undefined) {
            return fallbackId;
        }
    }
    return UNASSIGNED_SECTION_ID;
}

function groupTestCasesBySection(testCases) {
    const grouped = {};

    // 首先，為所有已知的 sections 創建 groups（包括空的）
    if (Array.isArray(tcmSectionsTree) && tcmSectionsTree.length > 0) {
        // 扁平化 sections tree，包含所有層級的 sections
        const flattenAllSections = (sections, result = []) => {
            for (const section of sections) {
                result.push(section);
                // 檢查多種可能的子節點屬性名稱
                const children = section.children || section.child_sections || [];
                if (Array.isArray(children) && children.length > 0) {
                    flattenAllSections(children, result);
                }
            }
            return result;
        };

        const allSections = flattenAllSections(tcmSectionsTree);
        console.log('[groupTestCasesBySection] All sections found:', allSections.length, allSections);

        // 為每個 section 創建一個 group（使用最新的 section 數據）
        for (const section of allSections) {
            const sectionId = section.id;
            if (!grouped[sectionId]) {
                const sectionPath = buildSectionPath(section, allSections);
                grouped[sectionId] = {
                    sectionId,
                    sectionName: section.name || '(未命名)',
                    sectionPath: sectionPath,
                    sectionLevel: section.level || 1,
                    testCases: []
                };
                console.log(`[groupTestCasesBySection] Created group for section ${sectionId}:`, grouped[sectionId]);
            }
        }
    }

    // 然後，將 test cases 分配到對應的 sections
    for (const tc of testCases) {
        const sectionId = resolveSectionIdForGrouping(tc);
        if (!grouped[sectionId]) {
            // 如果 test case 的 section 不在 sections tree 中，仍然創建一個 group
            // 但這通常不應該發生，除非數據不同步
            console.warn('[groupTestCasesBySection] Test case references unknown section:', sectionId, tc);
            grouped[sectionId] = {
                sectionId,
                sectionName: tc.section_name || (sectionId === UNASSIGNED_SECTION_ID ? 'Unassigned' : '(未命名)'),
                sectionPath: tc.section_path || tc.section_name || '',
                sectionLevel: determineSectionLevel(tc, sectionId),
                testCases: []
            };
        }
        grouped[sectionId].testCases.push(tc);
    }

    console.log('[groupTestCasesBySection] Final grouped sections:', Object.keys(grouped).length, grouped);

    // 排序每個 section 內的 test cases
    Object.values(grouped).forEach(group => {
        const sortState = sectionSortStates.get(String(group.sectionId));
        const field = sortState?.field || tcmSortField;
        const order = sortState?.order || tcmSortOrder;
        sortTestCaseList(group.testCases, field, order);
    });

    return grouped;
}

// 輔助函數：為 section 建立完整路徑
function buildSectionPath(section, allSections) {
    if (!section) return '';

    const path = [];
    let current = section;
    const visited = new Set(); // 防止循環引用

    while (current && !visited.has(current.id)) {
        visited.add(current.id);
        path.unshift(current.name || '(未命名)');

        if (current.parent_section_id) {
            current = allSections.find(s => s.id === current.parent_section_id);
        } else {
            break;
        }
    }

    const fullPath = path.join('/');
    // 只在首次建立或有變化時輸出日誌
    if (window.DEBUG_SECTIONS) {
        console.log(`[buildSectionPath] Section ${section.id} (${section.name}): ${fullPath}, level=${section.level}, parent=${section.parent_section_id}`);
    }
    return fullPath;
}

function determineSectionLevel(testCase, sectionId) {
    if (!sectionId || sectionId === UNASSIGNED_SECTION_ID) return 1;
    if (typeof testCase.section_level === 'number' && !Number.isNaN(testCase.section_level)) {
        return testCase.section_level;
    }
    const pathLevel = deriveSectionLevelFromPath(testCase.section_path);
    if (pathLevel !== null) return pathLevel;
    return 1;
}

function deriveSectionLevelFromPath(path) {
    if (!path) return null;
    const segments = path.split('/').map(seg => seg.trim()).filter(Boolean);
    return segments.length || null;
}

function getDisplaySectionName(sectionGroup) {
    const name = (sectionGroup.sectionName || '').trim();
    if (name) return name;
    const path = (sectionGroup.sectionPath || '').trim();
    if (!path) return '(未分類)';
    const parts = path.split('/').map(seg => seg.trim()).filter(Boolean);
    return parts.length ? parts[parts.length - 1] : path;
}

function sortSectionIds(sectionIds, grouped) {
    const ids = Array.isArray(sectionIds) ? [...sectionIds] : [];
    if (!ids.length) return ids;

    const legacyCompare = (a, b) => {
        const ga = grouped[a];
        const gb = grouped[b];
        if (!ga || !gb) return 0;
        const aRoot = ga.sectionLevel <= 1;
        const bRoot = gb.sectionLevel <= 1;
        if (aRoot && !bRoot) return -1;
        if (!aRoot && bRoot) return 1;
        const aUnassigned = isUnassignedSectionIdValue(a) || isUnassignedSectionName(ga.sectionName);
        const bUnassigned = isUnassignedSectionIdValue(b) || isUnassignedSectionName(gb.sectionName);
        if (aUnassigned && !bUnassigned) return 1;
        if (!aUnassigned && bUnassigned) return -1;
        const aKey = (ga.sectionPath || ga.sectionName || '').toLowerCase();
        const bKey = (gb.sectionPath || gb.sectionName || '').toLowerCase();
        return aKey.localeCompare(bKey);
    };

    if (!Array.isArray(tcmSectionOrder) || tcmSectionOrder.length === 0) {
        return ids.sort((a, b) => legacyCompare(a, b));
    }

    const orderMap = new Map();
    tcmSectionOrder.forEach((id, index) => {
        orderMap.set(String(id), index);
    });

    return ids.sort((a, b) => {
        const aKey = String(a);
        const bKey = String(b);
        const aOrder = orderMap.has(aKey) ? orderMap.get(aKey) : Number.MAX_SAFE_INT;
        const bOrder = orderMap.has(bKey) ? orderMap.get(bKey) : Number.MAX_SAFE_INT;
        if (aOrder !== bOrder) {
            return aOrder - bOrder;
        }
        return legacyCompare(a, b);
    });
}

function mapAttrToField(attr) {
    switch (attr) {
        case 'test_case_number': return 'number';
        case 'title': return 'title';
        case 'tcg': return 'tcg';
        case 'priority': return 'priority';
        case 'created_at': return 'created';
        case 'updated_at': return 'updated';
        default: return attr;
    }
}

function mapFieldToAttr(field) {
    switch (field) {
        case 'number': return 'test_case_number';
        case 'title': return 'title';
        case 'tcg': return 'tcg';
        case 'priority': return 'priority';
        case 'created': return 'created_at';
        case 'updated': return 'updated_at';
        default: return field;
    }
}

function renderTestCaseRow(testCase) {
    const caseNumber = String(testCase.test_case_number || testCase.record_id || '');
    const safeCaseNumber = caseNumber.replace(/"/g, '&quot;');
    const highlightedCases = window.__tcHelperCreatedNumbers instanceof Set
        ? window.__tcHelperCreatedNumbers
        : null;
    const rowClass = highlightedCases && caseNumber && highlightedCases.has(caseNumber)
        ? ' class="tc-helper-created-row"'
        : '';

    return `
        <tr${rowClass} data-test-case-number="${safeCaseNumber}">
            <td class="align-middle text-center">
                <input type="checkbox" class="form-check-input test-case-checkbox"
                       value="${testCase.record_id}" ${selectedTestCases.has(testCase.record_id) ? 'checked' : ''}>
            </td>
            <td class="align-middle position-relative hover-editable" data-field="test_case_number" data-record-id="${testCase.record_id}">
                <div style="padding-right: 45px;">
                    <code style="color: rgb(194, 54, 120); font-weight: 500;">${testCase.test_case_number || testCase.record_id}</code>
                </div>
                <button type="button" class="btn btn-sm btn-edit position-absolute hover-edit-btn"
                        style="top: 50%; right: 5px; transform: translateY(-50%); z-index: 10;"
                        onclick="quickEdit('${testCase.record_id}', 'test_case_number')" data-i18n-title="tooltips.quickEdit">
                    <i class="fas fa-edit"></i>
                </button>
            </td>
            <td class="align-middle position-relative hover-editable" data-field="title" data-record-id="${testCase.record_id}">
                <div class="d-flex align-items-center" style="padding-right: 45px;">
                    <div style="flex-grow: 1; min-width: 0;">
                        <div class="fw-medium text-truncate" title="${testCase.title}">${testCase.title}</div>
                        <div class="small text-muted text-truncate">
                            ${testCase.description ? testCase.description.substring(0, 60) + '...' : ''}
                        </div>
                    </div>
                </div>
                <button type="button" class="btn btn-sm btn-edit position-absolute hover-edit-btn"
                        style="top: 50%; right: 5px; transform: translateY(-50%); z-index: 10;"
                        onclick="quickEdit('${testCase.record_id}', 'title')" data-i18n-title="tooltips.quickEdit">
                    <i class="fas fa-edit"></i>
                </button>
            </td>
            <td class="align-middle text-center position-relative" data-field="tcg" data-record-id="${testCase.record_id}" style="max-width: 180px;">
                <div class="tcg-edit-area ${hasTestCasePermission('tcgEditContainer') ? 'tcg-editable' : 'tcg-readonly'}"
                     ${hasTestCasePermission('tcgEditContainer') ?
                       `onclick="editTCG('${testCase.record_id}')" data-i18n-title="tooltips.clickEditTcg" style="display: flex; flex-wrap: wrap; gap: 2px; justify-content: center; align-items: center; min-height: 24px; padding: 2px; cursor: pointer;"` :
                       'style="display: flex; flex-wrap: wrap; gap: 2px; justify-content: center; align-items: center; min-height: 24px; padding: 2px; cursor: default;"'}>
                    ${getTCGTags(testCase)}
                </div>
            </td>
            <td class="align-middle text-center">
                <span class="badge ${getPriorityBadgeClass(testCase.priority)}">${getPriorityText(testCase.priority)}</span>
            </td>
            <td class="align-middle text-center">
                <div class="small text-muted text-nowrap">
                    ${formatDate(testCase.created_at, 'date')}
                </div>
            </td>
            <td class="align-middle text-center">
                <div class="small text-muted text-nowrap">
                    ${formatDate(testCase.updated_at, 'date')}
                </div>
            </td>
            <td class="align-middle text-center" style="width: 100px;">
                <div class="test-case-actions d-flex justify-content-center gap-2">
                    <button type="button" class="btn btn-sm btn-view"
                            onclick="viewTestCase('${testCase.record_id}')" data-i18n-title="tooltips.viewEdit">
                        <i class="fas fa-eye"></i>
                    </button>
                    ${hasTestCasePermission('testCaseActionCopy') ? `
                    <button type="button" class="btn btn-sm btn-secondary"
                            onclick="copyTestCase('${testCase.record_id}')" title="${(window.i18n && window.i18n.isReady()) ? window.i18n.t('common.copy') : '複製'}">
                        <i class="fas fa-copy"></i>
                    </button>` : ''}
                    ${hasTestCasePermission('testCaseActionDelete') ? `
                    <button type="button" class="btn btn-sm btn-danger"
                            onclick="deleteTestCase('${testCase.record_id}')" data-i18n-title="tooltips.delete">
                        <i class="fas fa-trash"></i>
                    </button>` : ''}
                </div>
            </td>
        </tr>`;
}

function renderSectionBlockHTML(sectionGroup, rowsHtml, visible = true) {
    const displayName = getDisplaySectionName(sectionGroup);
    const indent = Math.max(sectionGroup.sectionLevel - 1, 0);
    const rowClass = sectionGroup.sectionLevel <= 1 ? 'section-card-row root-divider' : 'section-card-row';
    const headerStyle = sectionGroup.sectionLevel > 1 ? 'background: linear-gradient(90deg, #f9fbff, #eef2f7);' : 'background: #f7f9fc;';
    const testCaseCount = sectionGroup.testCases.length;
    // 使用字符串化的 ID 查檢（Set 區分類型）
    const isCollapsed = sectionCollapsedState && sectionCollapsedState.has(String(sectionGroup.sectionId));
    const displayStyle = visible ? '' : 'display: none;';

    // 即使沒有 test cases，也要提供收合功能
    if (testCaseCount === 0) {
        return `
            <div class="${rowClass}" data-section-row-id="${sectionGroup.sectionId}" style="${displayStyle}">
                <div class="section-card-container">
                    <div class="section-card" data-section-id="${sectionGroup.sectionId}" style="--section-indent: ${indent};">
                        <div class="section-card-header" style="${headerStyle}; cursor: pointer;" onclick="toggleSectionCollapse('${sectionGroup.sectionId}')">
                            <div class="section-title">
                                <i class="fas fa-chevron-${isCollapsed ? 'right' : 'down'} me-2 section-toggle-icon" id="icon-${sectionGroup.sectionId}" data-section-id="${sectionGroup.sectionId}"></i>
                                <i class="fas fa-folder"></i>
                                <span>${displayName}</span>
                            </div>
                            <small class="text-muted">${testCaseCount} 筆</small>
                        </div>
                    </div>
                </div>
            </div>
        `;
    }

    return `
        <div class="${rowClass}" data-section-row-id="${sectionGroup.sectionId}" style="${displayStyle}">
            <div class="section-card-container">
                <div class="section-card" data-section-id="${sectionGroup.sectionId}" style="--section-indent: ${indent};">
                    <div class="section-card-header" style="${headerStyle}; cursor: pointer;" onclick="toggleSectionCollapse('${sectionGroup.sectionId}')">
                        <div class="section-title">
                            <i class="fas fa-chevron-${isCollapsed ? 'right' : 'down'} me-2 section-toggle-icon" id="icon-${sectionGroup.sectionId}" data-section-id="${sectionGroup.sectionId}"></i>
                            <i class="fas fa-folder"></i>
                            <span>${displayName}</span>
                        </div>
                        <small class="text-muted">${testCaseCount} 筆</small>
                    </div>
                    <div class="section-card-body table-responsive" data-section-id="${sectionGroup.sectionId}" style="display: ${isCollapsed ? 'none' : 'block'};" id="section-body-${sectionGroup.sectionId}">
                        <table class="table table-hover table-sm section-table" data-section-id="${sectionGroup.sectionId}">
                            <thead>
                                <tr class="section-table-header">
                                    <th width="30" class="text-center" style="padding: 0.35rem 0.5rem !important;">
                                        <input type="checkbox" class="form-check-input section-select-all" data-section-id="${sectionGroup.sectionId}">
                                    </th>
                                    <th class="sortable section-sortable" width="220" style="cursor: pointer;" data-section-id="${sectionGroup.sectionId}" data-sort-field="test_case_number">
                                        <span data-i18n="testCase.testCaseNumber">Test Case Number</span>
                                        <span class="sort-indicator ms-1"></span>
                                    </th>
                                    <th class="sortable section-sortable" style="cursor: pointer;" data-section-id="${sectionGroup.sectionId}" data-sort-field="title">
                                        <span data-i18n="common.title">標題</span>
                                        <span class="sort-indicator ms-1"></span>
                                    </th>
                                    <th class="sortable section-sortable text-center" width="180" style="cursor: pointer;" data-section-id="${sectionGroup.sectionId}" data-sort-field="tcg">
                                        <span>JIRA Tickets</span>
                                        <span class="sort-indicator ms-1"></span>
                                    </th>
                                    <th class="sortable section-sortable text-center" width="80" style="cursor: pointer;" data-section-id="${sectionGroup.sectionId}" data-sort-field="priority">
                                        <span data-i18n="testCase.priority">優先級</span>
                                        <span class="sort-indicator ms-1"></span>
                                    </th>
                                    <th class="sortable section-sortable text-center" width="100" style="cursor: pointer;" data-section-id="${sectionGroup.sectionId}" data-sort-field="created_at">
                                        <span data-i18n="common.createDate">建立日期</span>
                                        <span class="sort-indicator ms-1"></span>
                                    </th>
                                    <th class="sortable section-sortable text-center" width="100" style="cursor: pointer;" data-section-id="${sectionGroup.sectionId}" data-sort-field="updated_at">
                                        <span data-i18n="common.updateDate">更新日期</span>
                                        <span class="sort-indicator ms-1"></span>
                                    </th>
                                    <th width="100" class="text-center" data-i18n="common.actions">操作</th>
                                </tr>
                            </thead>
                            <tbody>
                                ${rowsHtml}
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>
        </div>
    `;
}

function handleSectionSort(sectionId, fieldKey) {
    if (!sectionId || !fieldKey) return;
    const key = String(sectionId);
    const prev = sectionSortStates.get(key);
    let order = 'asc';
    if (prev && prev.field === fieldKey) {
        order = prev.order === 'asc' ? 'desc' : 'asc';
    }
    sectionSortStates.set(key, { field: fieldKey, order });
    renderTestCasesTable();
}

// 檢查是否應該顯示某個 section (基於父 section 的收合狀態)
function isSectionVisible(sectionId) {
    let currentId = parseInt(sectionId);
    let parentId = findSectionParentId(currentId);
    
    while (parentId) {
        // 如果任何一層父 section 被收合，則此 section 不可見
        if (sectionCollapsedState.has(String(parentId))) {
            return false;
        }
        parentId = findSectionParentId(parentId);
    }
    return true;
}

function updateAllSectionsVisibility() {
    const rows = document.querySelectorAll('.section-card-row');
    rows.forEach(row => {
        const id = row.dataset.sectionRowId;
        if (!id) return;
        
        if (isSectionVisible(id)) {
            row.style.display = '';
        } else {
            row.style.display = 'none';
        }
    });
}

function toggleSectionCollapse(sectionId) {
    // 確保使用字符串化的 ID（Set 區分類型，數字 6 和字符串 "6" 不同）
    const sectionIdStr = String(sectionId);
    const isCollapsing = !sectionCollapsedState.has(sectionIdStr);

    // 1. 更新狀態
    if (isCollapsing) {
        saveChildrenCollapseState(sectionIdStr);
        sectionCollapsedState.add(sectionIdStr);
        // collapseChildSections(sectionIdStr); // 不需要了，由 updateAllSectionsVisibility 處理
    } else {
        sectionCollapsedState.delete(sectionIdStr);
        restoreChildrenCollapseState(sectionIdStr);
    }

    // 2. 更新當前 Section 的 Body 顯示/隱藏
    const body = document.getElementById(`section-body-${sectionId}`);
    if (body) {
        body.style.display = isCollapsing ? 'none' : 'block';
    }

    // 3. 更新 Icon
    const icon = document.getElementById(`icon-${sectionId}`);
    if (icon) {
        icon.className = `fas fa-chevron-${isCollapsing ? 'right' : 'down'} me-2 section-toggle-icon`;
    }

    // 4. 更新所有子/後代 Section 的 Row 可見性 (取代 renderTestCasesTable)
    updateAllSectionsVisibility();
    // 收合後補足渲染，避免尾端區段（如 Unassigned）尚未載入
    setTimeout(() => fillViewportIfNeeded('collapse'), 0);
}

/**
 * 保存父 section 的所有子 section 的當前收合狀態
 * 當父 section 被收合時調用，以便在重新展開時恢復子 section 的狀態
 */
function saveChildrenCollapseState(parentSectionId) {
    // 扁平化 section tree 並找到所有子 section
    const flattenAllSections = (sections, result = []) => {
        for (const section of sections) {
            result.push(section);
            const children = section.children || section.child_sections || [];
            if (Array.isArray(children) && children.length > 0) {
                flattenAllSections(children, result);
            }
        }
        return result;
    };

    const allSections = flattenAllSections(tcmSectionsTree);
    const parentIdNum = Number(parentSectionId);

    // 收集該父 section 的所有直接和間接子 section
    const childrenState = {};

    const collectChildren = (searchParentId) => {
        const searchParentIdNum = Number(searchParentId);
        for (const section of allSections) {
            if (section.parent_section_id === searchParentIdNum) {
                const childIdStr = String(section.id);
                // 記錄該子 section 是否被收合
                childrenState[childIdStr] = sectionCollapsedState.has(childIdStr);
                // 遞迴地收集該子 section 的子 section
                collectChildren(section.id);
            }
        }
    };

    collectChildren(parentSectionId);

    // 保存到 Map 中
    if (Object.keys(childrenState).length > 0) {
        savedChildrenCollapseState.set(parentSectionId, childrenState);
        console.log(`[Section] Saved collapse state for parent ${parentSectionId}:`, childrenState);
    }
}

/**
 * 恢復父 section 的所有子 section 的之前保存的收合狀態
 * 當父 section 被展開時調用
 */
function restoreChildrenCollapseState(parentSectionId) {
    const savedState = savedChildrenCollapseState.get(parentSectionId);
    if (!savedState) {
        console.log(`[Section] No saved state for parent ${parentSectionId}`);
        return;
    }

    // 恢復所有子 section 的狀態
    for (const [childIdStr, wasCollapsed] of Object.entries(savedState)) {
        if (wasCollapsed) {
            // 如果之前是收合的，就恢復為收合
            sectionCollapsedState.add(childIdStr);
        } else {
            // 如果之前是展開的，就確保它是展開的
            sectionCollapsedState.delete(childIdStr);
        }
    }

    console.log(`[Section] Restored collapse state for parent ${parentSectionId}`);

    // 清除該父 section 的保存狀態（已恢復）
    savedChildrenCollapseState.delete(parentSectionId);
}

function collapseChildSections(parentSectionId) {
    // 扁平化 section tree 並找到所有子 section
    const flattenAllSections = (sections, result = []) => {
        for (const section of sections) {
            result.push(section);
            const children = section.children || section.child_sections || [];
            if (Array.isArray(children) && children.length > 0) {
                flattenAllSections(children, result);
            }
        }
        return result;
    };

    const allSections = flattenAllSections(tcmSectionsTree);

    // 遞迴地找到所有子 section 並添加到收合狀態
    const addChildSections = (parentId) => {
        const parentIdNum = Number(parentId);  // 轉換為數字進行比較
        for (const section of allSections) {
            if (section.parent_section_id === parentIdNum) {
                sectionCollapsedState.add(String(section.id));  // 使用字符串化的 ID
                addChildSections(section.id);
            }
        }
    };

    addChildSections(parentSectionId);
}

function findSectionParentId(sectionId) {
    // 扁平化 section tree 並找到指定 section 的父 ID
    const flattenAllSections = (sections, result = []) => {
        for (const section of sections) {
            result.push(section);
            const children = section.children || section.child_sections || [];
            if (Array.isArray(children) && children.length > 0) {
                flattenAllSections(children, result);
            }
        }
        return result;
    };

    const allSections = flattenAllSections(tcmSectionsTree);
    // 使用寬鬆相等比較（==）以支援 number 和 string 的相互匹配
    const section = allSections.find(s => s.id == sectionId);
    return section ? section.parent_section_id : null;
}


/* ============================================================
   5. 團隊管理 (Team Management)
   ============================================================ */

// NOTE: TEST_CASES_CACHE_KEY, TEST_CASES_CACHE_TTL 已統一定義於 Section 1 (常數定義)

/**
 * 取得用於快取的 teamId
 * 優先順序: URL > AppUtils > sessionStorage
 * @param {boolean} strict - 嚴格模式下無法解析就回傳 null
 */
function getTeamIdForCache(strict = true) {
    // 1) 以 URL 為權威（使用者導航後最準確）
    try {
        const p = new URLSearchParams(window.location.search);
        const id = p.get('team_id') || p.get('teamId') || p.get('team');
        if (id) {
            try { sessionStorage.setItem('lastTeamId', String(id)); } catch (_) {}
            return String(id);
        }
    } catch (_) {}
    // 2) 次選 AppUtils（有時初始化較慢或不同步）
    try {
        if (typeof AppUtils !== 'undefined' && AppUtils.getCurrentTeam) {
            const t = AppUtils.getCurrentTeam();
            if (t && t.id) {
                try { sessionStorage.setItem('lastTeamId', String(t.id)); } catch (_) {}
                return String(t.id);
            }
        }
    } catch (_) {}
    // 3) 非嚴格模式時，退回上一個已知值
    if (!strict) {
        try {
            const last = sessionStorage.getItem('lastTeamId');
            if (last) return String(last);
        } catch (_) {}
    }
    return null;
}

// NOTE: teamContextPromise, teamsCache, teamsCacheLastLoaded, TEAMS_CACHE_TTL 已統一定義於 Section 1/2

async function fetchTeamsList(forceRefresh = false) {
    if (!window.AuthClient) {
        return [];
    }
    const now = Date.now();
    if (!forceRefresh && teamsCache && (now - teamsCacheLastLoaded) < TEAMS_CACHE_TTL) {
        return teamsCache;
    }
    try {
        const resp = await window.AuthClient.fetch('/api/teams/');
        if (!resp.ok) {
            console.warn('取得可用團隊列表失敗:', resp.status, resp.statusText);
            return teamsCache || [];
        }
        const data = await resp.json();
        teamsCache = Array.isArray(data) ? data : [];
        teamsCacheLastLoaded = now;
        return teamsCache;
    } catch (error) {
        console.error('取得可用團隊列表時發生錯誤:', error);
        return teamsCache || [];
    }
}

async function ensureTeamContext() {
    if (typeof AppUtils === 'undefined') {
        return null;
    }

    // 共享連結：URL 的 team_id 優先，確保不同 team 時能正確導向
    const urlTeamId = getTeamIdForCache(false);
    let existing = AppUtils.getCurrentTeam ? AppUtils.getCurrentTeam() : null;
    if (urlTeamId && existing && existing.id && String(existing.id) !== String(urlTeamId)) {
        // URL 指定了不同的 team，以 URL 為準，強制重新解析
        existing = null;
    }
    if (existing && existing.id) {
        try { sessionStorage.setItem('lastTeamId', String(existing.id)); } catch (_) {}
        return existing;
    }

    if (teamContextPromise) {
        return teamContextPromise;
    }

    teamContextPromise = (async () => {
        try {
            const teams = await fetchTeamsList();
            if (!Array.isArray(teams) || teams.length === 0) {
                return null;
            }

            let candidateId = getTeamIdForCache(false);
            let matched = candidateId
                ? teams.find(team => String(team.id) === String(candidateId))
                : null;

            if (!matched) {
                matched = teams[0];
            }

            AppUtils.setCurrentTeam(matched);
            if (typeof AppUtils.updateTeamNameBadge === 'function') {
                AppUtils.updateTeamNameBadge();
            }
            try { sessionStorage.setItem('lastTeamId', String(matched.id)); } catch (_) {}
            if (typeof ensureTeamIdInUrl_TCM === 'function') {
                ensureTeamIdInUrl_TCM(matched.id);
            }

            return matched;
        } catch (error) {
            console.error('解析團隊資訊失敗:', error);
            return null;
        } finally {
            teamContextPromise = null;
        }
    })();

    return teamContextPromise;
}



function getTestCasesCache(teamIdOverride = null) {
    try {
        const teamId = teamIdOverride ? String(teamIdOverride) : getTeamIdForCache(true);
        if (!teamId) return null; // 無有效 teamId，避免讀取共享或錯誤快取
        const cacheKey = `${TEST_CASES_CACHE_KEY}:${teamId}`;
        const cached = localStorage.getItem(cacheKey);
        if (cached) {
            const data = JSON.parse(cached);
            if (data && data.timestamp && data.testCases && Array.isArray(data.testCases)) {
                const age = Date.now() - data.timestamp;
                if (age < TEST_CASES_CACHE_TTL) {
                    console.log(`使用快取的測試案例清單 (${data.testCases.length} 筆，${Math.round(age/1000)}秒前)`);
                    console.debug('[CACHE] HIT list', { teamId, cacheKey, ageMs: age, count: data.testCases.length });
                    return data.testCases;
                }
                console.debug('[CACHE] MISS list: expired', { teamId, cacheKey, ageMs: age });
            }
            else { console.debug('[CACHE] MISS list: malformed cache payload', { teamId, cacheKey }); }
        }
        else { console.debug('[CACHE] MISS list: not found', { teamId, cacheKey }); }
    } catch (error) {
        console.debug('讀取測試案例快取失敗:', error);
    }
    return null;
}

function setTestCasesCache(testCases, teamIdOverride = null) {
    try {
        const teamId = teamIdOverride ? String(teamIdOverride) : getTeamIdForCache(true);
        if (!teamId) { console.debug('[CACHE] SKIP WRITE list: no valid teamId', { count: Array.isArray(testCases) ? testCases.length : 0 }); return; }
        const cacheKey = `${TEST_CASES_CACHE_KEY}:${teamId}`;
        const cacheData = { timestamp: Date.now(), testCases: testCases || [] };

        const trySet = (dataObj) => {
            localStorage.setItem(cacheKey, JSON.stringify(dataObj));
        };

        let wrote = false;
        try {
            trySet(cacheData);
            wrote = true;
        } catch (err) {
            if (err && (err.name === 'QuotaExceededError' || err.code === 22)) {
                console.warn('[CACHE] WRITE list failed: quota exceeded. Trying compact payload...', { teamId, cacheKey });
                // 1) 建立精簡版 payload（只保留列表需要欄位）
                const compactCases = (testCases || []).map(tc => ({
                    record_id: tc.record_id,
                    test_case_number: tc.test_case_number,
                    title: tc.title,
                    priority: tc.priority,
                    created_at: tc.created_at,
                    updated_at: tc.updated_at,
                    // 精簡 TCG 結構，保留必要顯示資訊
                    tcg: Array.isArray(tc.tcg) ? tc.tcg.map(r => ({
                        text: r && r.text ? r.text : undefined,
                        text_arr: r && Array.isArray(r.text_arr) ? r.text_arr.slice(0, 3) : undefined
                    })) : []
                }));
                const compactData = { timestamp: Date.now(), testCases: compactCases };
                try {
                    trySet(compactData);
                    wrote = true;
                    console.warn('[CACHE] WRITE list using compact payload succeeded', { teamId, count: compactCases.length });
                } catch (err2) {
                    if (err2 && (err2.name === 'QuotaExceededError' || err2.code === 22)) {
                        console.warn('[CACHE] Compact payload still exceeds quota. Trying to shrink list size...', { teamId });
                        // 2) 逐步縮減筆數直到可以寫入或降到 0
                        let low = 0;
                        let high = compactCases.length;
                        let best = -1;
                        while (low <= high) {
                            const mid = Math.floor((low + high) / 2);
                            const sliceData = { timestamp: Date.now(), testCases: compactCases.slice(0, mid) };
                            try {
                                trySet(sliceData);
                                best = mid;
                                low = mid + 1; // 試更大
                            } catch (e3) {
                                if (e3 && (e3.name === 'QuotaExceededError' || e3.code === 22)) {
                                    high = mid - 1; // 試更小
                                } else {
                                    throw e3;
                                }
                            }
                        }
                        if (best >= 0) {
                            wrote = true;
                            console.warn('[CACHE] WRITE list succeeded after shrinking', { teamId, writtenCount: best });
                        } else {
                            console.warn('[CACHE] WRITE list failed even after shrinking. Skipping persistent cache.', { teamId });
                        }
                    } else {
                        console.debug('儲存測試案例快取失敗:', err2);
                    }
                }
            } else {
                console.debug('儲存測試案例快取失敗:', err);
            }
        }

        if (wrote) {
            console.log(`測試案例清單已快取 (${(testCases && testCases.length) || 0} 筆)`);
            console.debug('[CACHE] WRITE list', { teamId, cacheKey, count: testCases ? testCases.length : 0 });
        }
        // 同時更新個別快取
        if (testCases && Array.isArray(testCases)) {
            testCases.forEach(tc => {
                if (tc.test_case_number) setExecCachedTestCase(tc.test_case_number, tc);
            });
        }
    } catch (error) {
        console.debug('儲存測試案例快取失敗:', error);
    }
}

function clearTestCasesCache() {
    try {
        const teamId = getTeamIdForCache(true);
        if (!teamId) { console.debug('[CACHE] SKIP CLEAR list: no valid teamId'); return; }
        const cacheKey = `${TEST_CASES_CACHE_KEY}:${teamId}`;
        // 清除列表快取
        localStorage.removeItem(cacheKey);
        // 清除所有相關的個別快取
        const keys = Object.keys(localStorage);
        keys.forEach(key => {
            if (key.startsWith(EXEC_TC_CACHE_PREFIX) && key.includes(`:${teamId}:`)) {
                localStorage.removeItem(key);
            }
        });
        console.log('測試案例快取已清除');
    } catch (error) {
        console.debug('清除測試案例快取失敗:', error);
    }
}

function updateTestCaseInCache(testCase) {
    try {
        const teamId = getTeamIdForCache(true);
        if (!teamId) { console.debug('[CACHE] SKIP UPDATE list: no valid teamId', { testCase: testCase && testCase.test_case_number }); return; }
        const cacheKey = `${TEST_CASES_CACHE_KEY}:${teamId}`;
        const cached = localStorage.getItem(cacheKey);
        if (cached) {
            const data = JSON.parse(cached);
            if (data && data.testCases && Array.isArray(data.testCases)) {
                // 優先使用 test_case_number 查找，因為 record_id 可能不匹配（API 返回數字 ID，快取中是 Lark ID）
                let index = -1;
                if (testCase.test_case_number) {
                    index = data.testCases.findIndex(tc => tc.test_case_number === testCase.test_case_number);
                }
                // 備用：如果找不到，再嘗試使用 record_id
                if (index < 0) {
                    index = data.testCases.findIndex(tc => tc.record_id === testCase.record_id);
                }

                if (index >= 0) {
                    // 保留原本的 record_id（Lark ID），但更新其他欄位
                    const originalRecordId = data.testCases[index].record_id;
                    data.testCases[index] = { ...testCase, record_id: originalRecordId };
                    localStorage.setItem(cacheKey, JSON.stringify(data));
                    console.log(`測試案例快取已更新: ${testCase.test_case_number}`);
                    console.debug('[CACHE] UPDATE list item', { teamId, cacheKey, testCase: testCase.test_case_number, originalRecordId });
                }
                else {
                    console.debug('[CACHE] UPDATE skipped: record not found in cache list', {
                        teamId,
                        searchedBy: testCase.test_case_number || testCase.record_id
                    });
                }
            }
            else { console.debug('[CACHE] UPDATE skipped: malformed cache payload', { teamId }); }
        }
        else { console.debug('[CACHE] UPDATE skipped: list cache not found', { teamId }); }
        if (testCase.test_case_number) setExecCachedTestCase(testCase.test_case_number, testCase);
        broadcastTestCaseUpdate(testCase);
    } catch (error) {
        console.debug('更新測試案例快取失敗:', error);
    }
}

function removeTestCaseFromCache(recordId, fallbackTestCase = null) {
    try {
        const teamId = getTeamIdForCache(true);
        if (!teamId) { console.debug('[CACHE] SKIP REMOVE list: no valid teamId', { recordId }); return; }
        const cacheKey = `${TEST_CASES_CACHE_KEY}:${teamId}`;
        const cached = localStorage.getItem(cacheKey);
        if (cached) {
            const data = JSON.parse(cached);
            if (data && data.testCases && Array.isArray(data.testCases)) {
                const removedTestCase = data.testCases.find(tc => tc.record_id === recordId);
                data.testCases = data.testCases.filter(tc => tc.record_id !== recordId);
                localStorage.setItem(cacheKey, JSON.stringify(data));
                let payloadCase = removedTestCase || fallbackTestCase || null;
                if (payloadCase && payloadCase.test_case_number) {
                    removeExecCachedTestCase(payloadCase.test_case_number);
                    broadcastTestCaseUpdate(payloadCase, { deleted: true });
                }
                console.log(`測試案例已從快取移除: ${recordId}`);
                console.debug('[CACHE] REMOVE list item', { teamId, cacheKey, recordId });
            }
            else { console.debug('[CACHE] REMOVE skipped: malformed cache payload', { teamId }); }
        }
        else {
            const payloadCase = fallbackTestCase || null;
            if (payloadCase && payloadCase.test_case_number) {
                removeExecCachedTestCase(payloadCase.test_case_number);
                broadcastTestCaseUpdate(payloadCase, { deleted: true });
            }
            console.debug('[CACHE] REMOVE skipped: list cache not found', { teamId, recordId });
        }
    } catch (error) {
        console.debug('從快取移除測試案例失敗:', error);
    }
}


/* ============================================================
   6. 權限管理 (Permissions)
   ============================================================ */

/**
 * 套用測試案例管理權限設定
 * 根據使用者權限顯示/隱藏 UI 元素
 */
async function applyTestCaseManagementPermissions() {
    try {
        if (!window.AuthClient) {
            console.warn('AuthClient not available, skipping permission check');
            return;
        }

        const resp = await window.AuthClient.fetch('/api/permissions/ui-config?page=test_case_management');
        if (!resp.ok) {
            console.warn('Failed to fetch UI permissions');
            return;
        }

        const config = await resp.json();
        const permissions = config.components ? { ...config.components } : {};

        let userRole = 'viewer';
        try {
            const userInfo = await window.AuthClient.getUserInfo();
            if (userInfo && userInfo.role) {
                userRole = String(userInfo.role).toLowerCase();
            }
        } catch (error) {
            console.warn('取得使用者角色失敗，使用預設 viewer:', error);
        }

        const isViewer = userRole === 'viewer';
        if (!isViewer) {
            const editingKeys = [
                'addTestCaseBtn',
                'aiTestCaseHelperBtn',
                'bulkModeDropdownGroup',
                'saveTestCaseBtn',
                'saveAndAddNextBtn',
                'cloneAndAddNextBtn',
                'splitModeBtn',
                'tcgEditContainer',
                'modalTcgContainer',
                'attachmentUpload',
                'batchInlineToolbar',
                'batchModifyBtn',
                'batchCopyBtn',
                'batchDeleteBtn',
                'testCaseActionCopy',
                'testCaseActionDelete'
            ];
            editingKeys.forEach((key) => {
                permissions[key] = true;
            });
        }

        // Header 區按鈕控制
        setElementVisibility('addTestCaseBtn', permissions.addTestCaseBtn);
        if (permissions.aiTestCaseHelperBtn === undefined) {
            permissions.aiTestCaseHelperBtn = permissions.addTestCaseBtn;
        }
        setElementVisibility('aiTestCaseHelperBtn', permissions.aiTestCaseHelperBtn);
        setElementVisibility('bulkModeDropdownGroup', permissions.bulkModeDropdownGroup);

        // Modal 按鈕控制
        setElementVisibility('saveTestCaseBtn', permissions.saveTestCaseBtn);
        setElementVisibility('saveAndAddNextBtn', permissions.saveAndAddNextBtn);
        setElementVisibility('cloneAndAddNextBtn', permissions.cloneAndAddNextBtn);

        // 模式切換按鈕控制
        if (permissions.splitModeBtn) {
            setElementVisibility('modeToggleGroup', true);
            setElementVisibility('splitModeBtn', true);
            // 如果有編輯權限，顯示取消按鈕
            const cancelBtn = document.querySelector('[data-bs-dismiss="modal"][data-i18n="common.cancel"]');
            if (cancelBtn) cancelBtn.style.display = '';
        } else {
            // Viewer 模式：只顯示預覽按鈕組，隱藏編輯相關按鈕
            setElementVisibility('modeToggleGroup', true);
            setElementVisibility('splitModeBtn', false);
            // 隱藏取消按鈕，Viewer 只能用右上角 X 關閉
            const cancelBtn = document.querySelector('[data-bs-dismiss="modal"][data-i18n="common.cancel"]');
            if (cancelBtn) cancelBtn.style.display = 'none';
        }

        // TCG 編輯權限控制
        const tcgContainer = document.getElementById('modalTcgContainer');
        if (tcgContainer) {
            if (permissions.tcgEditContainer) {
                tcgContainer.style.cursor = 'text';
                tcgContainer.removeAttribute('data-readonly');
            } else {
                tcgContainer.style.cursor = 'default';
                tcgContainer.setAttribute('data-readonly', 'true');
                // 移除點擊事件，但保留 TCG 預覽功能
                tcgContainer.style.pointerEvents = 'none';
            }
        }

        // 附件上傳權限控制
        const attachmentUpload = document.getElementById('attachmentUpload');
        const attachmentLabel = document.querySelector('label[for="attachmentUpload"]');
        const attachmentHelp = attachmentUpload ? attachmentUpload.nextElementSibling : null;

        if (permissions.attachmentUpload) {
            // 有上傳權限：顯示上傳控制項
            setElementVisibility('attachmentUpload', true);
            if (attachmentLabel) attachmentLabel.style.display = '';
            if (attachmentHelp) attachmentHelp.style.display = '';
        } else {
            // 無上傳權限：隱藏上傳控制項，但保留附件列表顯示
            if (attachmentUpload) attachmentUpload.style.display = 'none';
            if (attachmentLabel) attachmentLabel.style.display = 'none';
            if (attachmentHelp) attachmentHelp.style.display = 'none';
        }

        // 批次操作工具控制
        const batchToolbar = document.getElementById('batchInlineToolbar');
        if (!permissions.batchInlineToolbar) {
            if (batchToolbar) {
                batchToolbar.dataset.permissionsEnabled = 'false';
                batchToolbar.classList.add('d-none');
                batchToolbar.style.setProperty('display', 'none', 'important');
            }
        } else {
            if (batchToolbar) {
                if (!batchToolbar.dataset.defaultDisplay || batchToolbar.dataset.defaultDisplay === 'none') {
                    const computed = window.getComputedStyle(batchToolbar).display;
                    batchToolbar.dataset.defaultDisplay = (computed && computed !== 'none') ? computed : 'flex';
                }
                batchToolbar.dataset.permissionsEnabled = 'true';
            }
            setElementVisibility('batchModifyBtn', permissions.batchModifyBtn);
            setElementVisibility('batchCopyBtn', permissions.batchCopyBtn);
            setElementVisibility('batchDeleteBtn', permissions.batchDeleteBtn);
            updateBatchToolbar();
        }

        // 儲存權限狀態供後續使用
        window._testCasePermissions = permissions;

    } catch (error) {
        console.error('Apply test case management permissions failed:', error);
    }
}

// 輔助函數：設定元素可見性
function setElementVisibility(elementId, isVisible) {
    const element = document.getElementById(elementId);
    if (!element) return;

    if (!element.dataset.defaultDisplay || element.dataset.defaultDisplay === 'none') {
        let defaultDisplay = '';
        if (element.classList.contains('d-flex')) {
            defaultDisplay = 'flex';
        } else if (element.classList.contains('btn-group')) {
            defaultDisplay = 'inline-flex';
        } else if (element.tagName === 'BUTTON' || element.classList.contains('btn')) {
            defaultDisplay = 'inline-block';
        } else if (element.tagName === 'INPUT' || element.tagName === 'SELECT' || element.tagName === 'TEXTAREA') {
            defaultDisplay = 'block';
        } else {
            const computed = window.getComputedStyle(element).display;
            if (computed && computed !== 'none') {
                defaultDisplay = computed;
            }
        }
        element.dataset.defaultDisplay = defaultDisplay || '';
    }

    if (isVisible) {
        element.classList.remove('d-none');
        const displayValue = element.dataset.defaultDisplay;
        if (displayValue) {
            element.style.setProperty('display', displayValue, 'important');
        } else {
            element.style.removeProperty('display');
        }
    } else {
        element.classList.add('d-none');
        element.style.setProperty('display', 'none', 'important');
    }
}

// 檢查是否有特定權限
function hasTestCasePermission(permissionKey) {
    if (!window._testCasePermissions) return true; // 預設允許（向下相容）
    return !!window._testCasePermissions[permissionKey];
}

// 停用編輯功能（for Viewer）
function disableEditingFeatures() {
    // 停用所有 textarea 和 input 欄位
    const modal = document.getElementById('testCaseModal');
    if (modal) {
        const inputs = modal.querySelectorAll('input, textarea, select');
        inputs.forEach(input => {
            // 不停用附件上傳欄位（會由權限控制隱藏）
            if (input.id !== 'attachmentUpload') {
                input.disabled = true;
                input.style.backgroundColor = '#f8f9fa';
                input.style.cursor = 'not-allowed';
            }
        });

        // 停用 TCG 編輯容器，但保留預覽功能
        const tcgContainer = document.getElementById('modalTcgContainer');
        if (tcgContainer) {
            tcgContainer.style.cursor = 'default';
            // 不設定 pointerEvents = 'none'，保留 TCG hover 預覽功能
            tcgContainer.classList.add('tcg-readonly');
        }

        // 隱藏 Markdown 工具列
        const toolbars = modal.querySelectorAll('.markdown-toolbar');
        toolbars.forEach(toolbar => {
            toolbar.style.display = 'none';
        });
    }
}

document.addEventListener('DOMContentLoaded', async function() {
    // 初始化權限檢查
    await applyTestCaseManagementPermissions();

    let activeTeam = null;

    // 監聽全域 team 變更事件，隨時更新 URL 的 team_id
    try {
        window.addEventListener('teamChanged', function(e) {
            const newTeam = e && e.detail && e.detail.team;
            if (newTeam && newTeam.id) {
                activeTeam = newTeam;
                ensureTeamIdInUrl_TCM(newTeam.id);
                try { sessionStorage.setItem('lastTeamId', String(newTeam.id)); } catch (_) {}
                // 切換 team 後：依新 team 的儲存狀態還原（若無儲存則等同清空），並重新渲染
                try {
                    // 嘗試載入該 team 的列表資料（若已載入則僅套用 UI 與篩選）
                    // 先重置 UI 欄位，再依新 team 的儲存覆蓋
                    const elNum = document.getElementById('testCaseNumberSearch');
                    const elSearch = document.getElementById('searchInput');
                    const elPri = document.getElementById('priorityFilter');
                    if (elNum) elNum.value = '';
                    if (elSearch) elSearch.value = '';
                    if (elPri) elPri.value = '';
                    updateFilterStatus();
                    // 還原新 team 的持久化條件（若有）並同步到記憶體
                    restoreTcmFiltersToUI();
                    // 依記憶體中的過濾器立即渲染（不清除快取、不重打 API）
                    filteredTestCases = computeFilteredTestCases(testCases);
                    currentPage = 1;
                    renderTestCasesTable();
                    updatePagination();
                    updateFilterStatus();
                } catch (_) {}
            }
        });
    } catch (_) {}
    try {
        updateTcmPlaceholders();
        activeTeam = await ensureTeamContext();
        if (activeTeam && activeTeam.id) {
            ensureTeamIdInUrl_TCM(activeTeam.id);
        }
    } catch (error) {
        console.error('初始化團隊資訊失敗:', error);
    }

    if (!activeTeam || !activeTeam.id) {
        const selectTeamMessage = window.i18n ? window.i18n.t('errors.selectTeamFirst', {}, '請先選擇團隊') : '請先選擇團隊';
        showError(selectTeamMessage);
        hideLoadingProgress();
        hideLoadingState();
        return;
    }

    const urlParams = new URLSearchParams(window.location.search);
    const minimal = urlParams.get('minimal') === '1' || urlParams.get('editor') === '1';
    const tcNumber = urlParams.get('tc') || urlParams.get('test_case_number');
    const mode = urlParams.get('mode') || 'preview';
    const openReference = urlParams.get('ref') === '1' || urlParams.get('ref') === 'true';
    currentSetId = urlParams.get('set_id') ? parseInt(urlParams.get('set_id')) : null;

    // 如果提供了 set_id，加載該 Set 的 Sections
    if (currentSetId && activeTeam && activeTeam.id) {
        try {
            console.log(`Loading sections for set ${currentSetId}`);
            const resp = await window.AuthClient.fetch(`/api/teams/${activeTeam.id}/test-case-sets/${currentSetId}`);
            if (resp.ok) {
                const setData = await resp.json();
                console.log('Set data loaded:', setData);
                // 觸發事件讓 TestCaseSectionList 初始化
                const event = new CustomEvent('testCaseSetLoaded', {
                    detail: {
                        setId: setData.id,
                        teamId: activeTeam.id,
                        sections: setData.sections || []
                    }
                });
                window.dispatchEvent(event);
            } else {
                console.warn(`Failed to load set ${currentSetId}`);
            }
        } catch (error) {
            console.error('Error loading set sections:', error);
        }
    }

    if (minimal && tcNumber) {
        // 最小模式：不載入列表，直接開啟指定測試案例
        try {
            // 綁定事件（包含儲存按鈕）
            bindEvents();
            initializeMarkdownEditor();
            // 隱藏列表與搜尋區塊
            const page = document.getElementById('testCasesPage');
            if (page) {
                const searchCard = document.getElementById('searchFilterCard');
                const tableCard = document.getElementById('testCasesCard');
                if (searchCard) searchCard.style.display = 'none';
                if (tableCard) tableCard.style.display = 'none';
            }
            // 套用最小模式樣式：隱藏頁首/頁尾與背景容器
            try {
                document.body.classList.add('minimal-mode');
                if (!document.getElementById('minimal-mode-style')) {
                    const style = document.createElement('style');
                    style.id = 'minimal-mode-style';
                    style.textContent = `
                        .minimal-mode .app-header, .minimal-mode .app-footer { display: none !important; }
                        .minimal-mode #testCasesPage, .minimal-mode #searchFilterCard, .minimal-mode #loadingProgress { display: none !important; }
                        body.minimal-mode { overflow: hidden; }
                    `;
                    document.head.appendChild(style);
                }
            } catch (_) {}

            // 直接從 API 抓此測試案例
            const currentTeam = activeTeam || (await ensureTeamContext());
            if (!currentTeam || !currentTeam.id) throw new Error('請先選擇團隊');
            const resp = await window.AuthClient.fetch(`/api/teams/${currentTeam.id}/testcases/?search=${encodeURIComponent(tcNumber)}&limit=1`);
            if (!resp.ok) throw new Error('載入測試案例失敗');
            const arr = await resp.json();
            const target = Array.isArray(arr) ? arr.find(tc => tc.test_case_number === tcNumber) : null;
            if (target) {
                // 設定最小模式旗標，供顯示 Modal 時使用無背板
                window.__MINIMAL_MODE__ = true;
                showTestCaseModal(target);
                if (mode === 'edit' || mode === 'split') {
                    // 切換為可編輯模式（若可行）
                    try { setEditorMode('split'); } catch (_) {}
                }
            } else {
                showError(window.i18n ? window.i18n.t('errors.testCaseNotFound', {}, '找不到指定的測試案例') : '找不到指定的測試案例');
            }
        } catch (e) {
            console.error('最小模式開啟測試案例失敗:', e);
            // 回退到完整載入
            await initTestCaseManagement();
            bindEvents();
            initializeMarkdownEditor();
        }
    } else {
        // 原本完整流程
        await initTestCaseManagement();
        bindEvents();
        initializeMarkdownEditor();
        // 初始化列表高度（等待初始排版完成）
        setTimeout(adjustTestCasesScrollHeight, 0);
        // 延遲初始化「跳至」菜單，確保所有數據已加載
        setTimeout(() => {
            if (currentSetId) {
                initJumpToSetMenu().catch(e => console.error('Failed to init jump menu:', e));
            }
        }, 1000);
        try {
            if (tcNumber) {
                const openAfterLoad = async () => {
                    if (!Array.isArray(testCases) || testCases.length === 0) {
                        await loadTestCases(false);
                    }
                    const target = testCases.find(tc => (tc.test_case_number === tcNumber) || (tc.record_id === tcNumber));
                    if (target) {
                        showTestCaseModal(target);
                    }
                };
                setTimeout(openAfterLoad, 0);
            }
        } catch (_) {}

        // 若指定 ref=1，載入完成後開啟參考測試案例彈窗
        if (openReference) {
            setTimeout(() => {
                try { openReferenceTestCasePopup(); } catch (e) { console.debug('openReferenceTestCasePopup error:', e); }
            }, 0);
        }
    }

    // 添加Modal TCG容器的事件委託（與列表一致）
    document.addEventListener('click', function(e) {
        if (e.target.closest('#modalTcgContainer')) {
            editModalTCG();
        }
    });
});
