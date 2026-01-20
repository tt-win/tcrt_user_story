/* Test Run Execution - Data */

const TEST_CASE_CACHE_PREFIX = 'tr_exec_tc_cache_v1';
const TEST_CASE_CACHE_TTL_MS = 60 * 60 * 1000; // 1 小時
const TEST_CASE_UPDATE_EVENT_KEY = 'testCaseUpdatedEvent';

async function loadTestRunConfig() {
    try {
        const response = await window.AuthClient.fetch(`/api/teams/${currentTeamId}/test-run-configs/${currentConfigId}`);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);

        testRunConfig = await response.json();
        updateHeader();
        await loadTreSections();
        await loadTestRunItems();
        await updateStatistics();

    } catch (error) {
        console.error('Failed to load Test Run config:', error);
        AppUtils.showError(`${treTranslate('testRun.loadFailed', '載入失敗')}: ${error.message}`);
    } finally {
        hideItemsLoading();
    }
}

async function loadTestRunItems() {
    try {
        showItemsLoading();
        const response = await window.AuthClient.fetch(`/api/teams/${currentTeamId}/test-run-configs/${currentConfigId}/items/?limit=10000`);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);

        testRunItems = await response.json();
        // 預設按 Test Case Number 升冪排序（與 Test Case Management 一致）
        try {
            testRunItems.sort((a, b) => {
                const aNumber = a && a.test_case_number ? a.test_case_number : '';
                const bNumber = b && b.test_case_number ? b.test_case_number : '';
                return aNumber.localeCompare(bNumber);
            });
        } catch (_) { /* 忽略排序中的非致命錯誤 */ }
        // 先用現有資料渲染，避免因預抓而阻塞頁面
        normalizeRunItemSectionInfo(testRunItems);
        rebuildSectionIndexFromItems(testRunItems);
        renderTestRunItems();
        renderTreSectionTree();
        hideItemsLoading();
        scheduleSectionHydration(testRunItems);

    } catch (error) {
        console.error('Failed to load test items:', error);
        AppUtils.showError(`${treTranslate('testRun.loadItemsFailed', '載入測試項目失敗')}: ${error.message}`);
        hideItemsLoading();
    }
}

// 不顯示載入動畫的版本（用於 Refresh）
async function loadTestRunItemsWithoutLoading() {
    try {
        const response = await window.AuthClient.fetch(`/api/teams/${currentTeamId}/test-run-configs/${currentConfigId}/items/?limit=10000`);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);

        testRunItems = await response.json();
        // 預設按 Test Case Number 升冪排序（與 Test Case Management 一致）
        try {
            testRunItems.sort((a, b) => {
                const aNumber = a && a.test_case_number ? a.test_case_number : '';
                const bNumber = b && b.test_case_number ? b.test_case_number : '';
                return aNumber.localeCompare(bNumber);
            });
        } catch (_) { /* 忽略排序中的非致命錯誤 */ }

        normalizeRunItemSectionInfo(testRunItems);
        rebuildSectionIndexFromItems(testRunItems);
        // 直接渲染，不顯示載入動畫
        renderTestRunItems();
        renderTreSectionTree();
        scheduleSectionHydration(testRunItems);

    } catch (error) {
        console.error('Failed to load test items:', error);
        AppUtils.showError(`${treTranslate('testRun.loadItemsFailed', '載入測試項目失敗')}: ${error.message}`);
    }
}

async function loadTreSections() {
    if (!testRunConfig || !testRunConfig.set_id) {
        treSections = [];
        sectionIndexById = new Map();
        renderTreSectionTree();
        return;
    }
    try {
        const resp = await window.AuthClient.fetch(`/api/test-case-sets/${testRunConfig.set_id}/sections`);
        if (resp.ok) {
            treSections = await resp.json();
        } else {
            treSections = [];
        }
    } catch (e) {
        console.warn('loadTreSections failed', e);
        treSections = [];
    }
    // 建立扁平索引，方便還原完整 parent chain
    sectionIndexById = new Map();
    const upsertIndex = (id, name, parentId) => {
        const key = String(id);
        const existing = sectionIndexById.get(key) || {};
        sectionIndexById.set(key, {
            name: name || existing.name || `Section ${key}`,
            parentId: parentId !== undefined ? (parentId !== null ? String(parentId) : null) : (existing.parentId ?? null)
        });
    };
    const indexSections = (nodes, parentId = null) => {
        (nodes || []).forEach(node => {
            const id = node && node.id != null ? String(node.id) : null;
            if (!id) return;
            const pId = node.parent_id ?? (node.parent && node.parent.id != null ? node.parent.id : parentId);
            upsertIndex(id, node.name, pId);
            if (node.children && node.children.length) {
                indexSections(node.children, id);
            }
        });
    };
    indexSections(treSections, null);
    resetSectionDisplayNameCache();
    renderTreSectionTree();
}

// 顯示統計載入狀態
function showStatsLoading() {
    const statIds = ['total-count', 'executed-count', 'passed-count', 'failed-count', 'execution-rate', 'pass-rate', 'bug-tickets-count'];
    statIds.forEach(id => {
        const element = document.getElementById(id);
        if (element) {
            element.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';
        }
    });
}

// 隱藏統計載入狀態並恢復數字顯示
function hideStatsLoading() {
    const statIds = ['total-count', 'executed-count', 'passed-count', 'failed-count', 'execution-rate', 'pass-rate', 'bug-tickets-count'];
    statIds.forEach(id => {
        const element = document.getElementById(id);
        if (element && element.innerHTML.includes('fa-spinner')) {
            element.textContent = '0';
        }
    });
}

async function updateStatistics() {
    try {
        // 顯示載入動畫
        showStatsLoading();

        const response = await window.AuthClient.fetch(`/api/teams/${currentTeamId}/test-run-configs/${currentConfigId}/items/statistics`);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);

        const stats = await response.json();

        document.getElementById('total-count').textContent = stats.total_runs;
        document.getElementById('executed-count').textContent = stats.executed_runs;
        document.getElementById('passed-count').textContent = stats.passed_runs;
        document.getElementById('failed-count').textContent = stats.failed_runs;
        document.getElementById('bug-tickets-count').textContent = stats.unique_bug_tickets_count || 0;
        // 顯示為無條件捨去之整數百分比
        document.getElementById('execution-rate').textContent = Math.floor(stats.execution_rate) + '%';
        // 通過率顯示為無條件捨去之整數百分比
        document.getElementById('pass-rate').textContent = Math.floor(stats.pass_rate) + '%';

        // 添加前端診斷日誌來驗證 API 返回的數據
        console.warn('FRONTEND_PASS_RATE_DEBUG: 接收到的統計數據:', {
            total_runs: stats.total_runs,
            executed_runs: stats.executed_runs,
            passed_runs: stats.passed_runs,
            failed_runs: stats.failed_runs,
            execution_rate: stats.execution_rate,
            pass_rate: stats.pass_rate,
            total_pass_rate: stats.total_pass_rate
        });
        console.warn('FRONTEND_PASS_RATE_DEBUG: 計算驗證:', {
            expected_pass_rate: stats.executed_runs > 0 ? (stats.passed_runs / stats.executed_runs * 100) : 0,
            received_pass_rate: stats.pass_rate,
            is_match: Math.abs((stats.executed_runs > 0 ? (stats.passed_runs / stats.executed_runs * 100) : 0) - stats.pass_rate) < 0.01
        });

        // 同步配置統計
        await window.AuthClient.fetch(`/api/teams/${currentTeamId}/test-run-configs/${currentConfigId}/sync`);

    } catch (error) {
        console.error('Failed to update statistics:', error);
        // 錯誤時也要隱藏載入動畫
        hideStatsLoading();
    }
}

// ====== 跨頁快取（IndexedDB + gzip）工具 ======
async function getCachedTestCase(testCaseNumber) {
    try {
        const res = await TRCache.getExecDetail(currentTeamId, testCaseNumber, TEST_CASE_CACHE_TTL_MS);
        if (res) {
            console.debug('[CACHE][EXEC] HIT', { teamId: currentTeamId, testCaseNumber, ts: res.ts });
        } else {
            console.debug('[CACHE][EXEC] MISS', { teamId: currentTeamId, testCaseNumber });
        }
        return res;
    } catch (e) {
        console.debug('[CACHE][EXEC] MISS (error)', { teamId: currentTeamId, testCaseNumber, error: e && e.message });
        return null;
    }
}

async function setCachedTestCase(testCaseNumber, testCaseData) {
    try {
        if (!currentTeamId) { console.debug('[CACHE][EXEC] SKIP WRITE: no teamId', { testCaseNumber }); return; }
        if (!testCaseNumber) { console.debug('[CACHE][EXEC] SKIP WRITE: no testCaseNumber'); return; }

        // 若快取已存在且內容相同，避免重覆寫入
        try {
            const existing = await TRCache.getExecDetail(currentTeamId, testCaseNumber, TEST_CASE_CACHE_TTL_MS);
            const pick = (tc) => {
                if (!tc) return null;
                return {
                    record_id: tc.record_id || null,
                    test_case_number: tc.test_case_number || null,
                    title: tc.title || null,
                    priority: tc.priority || null,
                    precondition: tc.precondition || null,
                    steps: tc.steps || null,
                    expected_result: tc.expected_result || null,
                    updated_at: tc.updated_at || null,
                    attachment_count: Array.isArray(tc.attachments) ? tc.attachments.length : 0,
                };
            };
            const eq = (a, b) => JSON.stringify(a) === JSON.stringify(b);
            if (existing && eq(pick(existing.data), pick(testCaseData))) {
                console.debug('[CACHE][EXEC] SKIP WRITE: identical', { teamId: currentTeamId, testCaseNumber });
                return;
            }
        } catch (_) {}

        console.debug('[CACHE][EXEC] WRITE', { teamId: currentTeamId, testCaseNumber });
        await TRCache.setExecDetail(currentTeamId, testCaseNumber, testCaseData);
    } catch (e) {
        console.debug('[CACHE][EXEC] WRITE FAILED', { teamId: currentTeamId, testCaseNumber, error: e && e.message });
    }
}

// 判斷是否為新鮮快取
function isFreshCache(cached) {
    return cached && (Date.now() - cached.ts) < TEST_CASE_CACHE_TTL_MS;
}

// 以 test_case_number 從後端取得詳細並寫入快取
async function fetchAndCacheTestCase(testCaseNumber) {
    if (!testCaseNumber) return;
    try {
        const url = new URL(`/api/teams/${currentTeamId}/testcases/`, window.location.origin);
        url.searchParams.set('search', testCaseNumber);
        url.searchParams.set('limit', '1');
        const resp = await window.AuthClient.fetch(url);
        if (!resp.ok) return;
        const list = await resp.json();
        const tc = Array.isArray(list) ? list.find(t => t.test_case_number === testCaseNumber) : null;
        if (tc) await setCachedTestCase(testCaseNumber, tc);
    } catch (_) {}
}

// 針對目前的 Test Run Items 預先載入所有 Test Case 詳細
async function prefetchTestCasesForItems(items) {
    try {
        const numbers = (items || []).map(i => i.test_case_number).filter(Boolean);
        if (numbers.length === 0) return;
        // 過濾已新鮮快取者（非同步檢查）
        const toFetch = [];
        for (const n of numbers) {
            const cached = await getCachedTestCase(n);
            if (!isFreshCache(cached)) toFetch.push(n);
        }
        console.debug('[CACHE][EXEC] Prefetch plan', { teamId: currentTeamId, total: numbers.length, needFetch: toFetch.length });
        if (toFetch.length === 0) return;
        // 控制併發量，避免過多同時請求
        const queue = Array.from(new Set(toFetch)); // 去重
        const concurrency = 5;
        const workers = new Array(Math.min(concurrency, queue.length)).fill(0).map(async () => {
            while (queue.length > 0) {
                const n = queue.pop(); // 先取出，再 await，避免競態
                await fetchAndCacheTestCase(n);
            }
        });
        await Promise.all(workers);
    } catch (e) {
        console.debug('prefetch test cases skipped:', e);
    }
}

// 避免一次性抓取全團隊：僅預先抓取缺少 section 的 items
async function preloadAllTeamTestCasesForRun(items) {
    try {
        const targets = (items || []).filter(it => !hasSectionInfo(it));
        if (!targets.length) return;
        await prefetchTestCasesForItems(targets);
    } catch (e) {
        console.debug('preloadAllTeamTestCasesForRun failed, fallback to prefetch each:', e);
        await prefetchTestCasesForItems(items);
    }
}

// 補齊 items 的 Section 資訊（從快取/預抓資料帶入）
async function hydrateItemSections(items) {
    if (!Array.isArray(items)) return 0;
    const targets = items.filter(it => !hasSectionInfo(it));
    if (!targets.length) return 0;
    let changed = 0;
    const queue = [...targets];
    const concurrency = Math.min(6, queue.length);
    const workers = new Array(concurrency).fill(0).map(async () => {
        while (queue.length > 0) {
            const it = queue.pop();
            if (!it) continue;
            // 若已經有 section id / 名稱就跳過
            const hasId = it.test_case_section_id || (it.test_case_section && (it.test_case_section.id || it.test_case_section.section_id || it.test_case_section.record_id));
            const hasName = it.test_case_section && it.test_case_section.name;
            if (hasId && hasName) continue;

            // 嘗試從預抓的 __exec_section_* 帶入
            if (it.__exec_section_id || it.__exec_section_name) {
                it.test_case_section = it.test_case_section || {};
                if (it.__exec_section_id) {
                    it.test_case_section.id = it.__exec_section_id;
                    it.test_case_section_id = it.test_case_section_id || it.__exec_section_id;
                }
                if (it.__exec_section_name && !it.test_case_section.name) {
                    it.test_case_section.name = it.__exec_section_name;
                }
                continue;
            }

            // 從快取撈 test case 詳細補上 section
            try {
                const cached = await getCachedTestCase(it.test_case_number);
                if (cached && cached.data) {
                    const tc = cached.data;
                    const sec = tc.test_case_section || {};
                    if (sec.id || sec.section_id || sec.record_id) {
                        const sid = sec.id || sec.section_id || sec.record_id;
                        it.test_case_section = it.test_case_section || {};
                        it.test_case_section.id = sid;
                        it.test_case_section_id = it.test_case_section_id || sid;
                        it.__exec_section_id = it.__exec_section_id || sid;
                    }
                    if (sec.name) {
                        it.test_case_section = it.test_case_section || {};
                        it.test_case_section.name = it.test_case_section.name || sec.name;
                        it.__exec_section_name = it.__exec_section_name || sec.name;
                    }
                    changed += 1;
                }
            } catch (_) {
                /* ignore */
            }
        }
    });
    await Promise.all(workers);
    return changed;
}

function applyExternalTestCaseUpdate(update) {
    try {
        if (!update || !update.test_case_number) return;
        if (update.teamId && currentTeamId && String(update.teamId) !== String(currentTeamId)) return;
        if (!Array.isArray(testRunItems)) return;

        const index = testRunItems.findIndex(it => it.test_case_number === update.test_case_number);
        if (index === -1) return;

        const item = testRunItems[index];

        if (update.deleted) {
            ['title', 'priority', 'precondition', 'steps', 'expected_result'].forEach(field => {
                if (Object.prototype.hasOwnProperty.call(update, field)) {
                    item[field] = update[field] ?? '';
                } else if (field !== 'title') {
                    item[field] = '';
                }
            });
            item.__testCaseDeleted = true;
            try {
                TRCache.removeExecDetail(currentTeamId, item.test_case_number);
            } catch (_) {}

            if (currentDetailTestCase && currentDetailTestCase.test_case_number === update.test_case_number) {
                try {
                    const modalEl = document.getElementById('testCaseDetailModal');
                    if (modalEl) {
                        const modalInstance = bootstrap.Modal.getInstance(modalEl) || new bootstrap.Modal(modalEl);
                        modalInstance.hide();
                    }
                } catch (_) {}
                currentDetailTestCase = null;
            }
        } else {
            ['title', 'priority', 'precondition', 'steps', 'expected_result'].forEach(field => {
                if (Object.prototype.hasOwnProperty.call(update, field)) {
                    const value = update[field];
                    if (typeof value !== 'undefined' && value !== null) {
                        item[field] = value;
                    }
                }
            });
            item.__testCaseDeleted = false;
        }

        renderTestRunItems();

        try {
            initializeChartsAndReports();
        } catch (chartError) {
            console.debug('重新整理圖表失敗（忽略）:', chartError);
        }

        if (!update.deleted && currentDetailTestCase && currentDetailTestCase.test_case_number === update.test_case_number) {
            loadTestCaseDetail(update.test_case_number).catch(detailError => {
                console.debug('重新載入測試案例詳情失敗（忽略）:', detailError);
            });
        }

        try {
            updateStatistics();
        } catch (_) {}
    } catch (error) {
        console.debug('處理測試案例更新事件失敗:', error);
    }
}
