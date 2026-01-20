/* Test Run Execution - Sections */

function getItemSectionId(item) {
    if (!item) return null;
    if (item.__exec_section_key) {
        return item.__exec_section_key === 'unassigned' ? null : item.__exec_section_key;
    }
    const sec = item.test_case_section || item.section || {};
    const explicit =
        item.__exec_section_id ||
        item.test_case_section_id ||
        sec.id || sec.section_id || sec.record_id || sec.parent_id ||
        item.section_id || item.section_record_id ||
        item.test_case_section_record_id;
    if (explicit) {
        item.__exec_section_id = item.__exec_section_id || explicit;
        item.test_case_section_id = item.test_case_section_id || explicit;
        item.__exec_section_key = String(explicit);
        return explicit;
    }
    // fallback：若只有名稱仍建立分組鍵，避免全部落到 Unassigned
    const nameKey = item.__exec_section_name || sec.name;
    if (nameKey) {
        item.__exec_section_key = `name:${nameKey}`;
        return item.__exec_section_key;
    }
    item.__exec_section_key = 'unassigned';
    return null;
}

function hasSectionInfo(item) {
    if (!item) return false;
    const sec = item.test_case_section || {};
    return !!(
        item.__exec_section_id ||
        item.test_case_section_id ||
        sec.id || sec.section_id || sec.record_id
    );
}

function normalizeRunItemSectionInfo(items) {
    (items || []).forEach(it => {
        if (!it) return;
        const sec = it.test_case_section || {};
        const sid = it.__exec_section_id || it.test_case_section_id || sec.id || sec.section_id || sec.record_id || null;
        if (sid) {
            it.__exec_section_id = it.__exec_section_id || sid;
            it.test_case_section_id = it.test_case_section_id || sid;
            it.test_case_section = it.test_case_section || {};
            if (!it.test_case_section.id) it.test_case_section.id = sid;
            it.__exec_section_key = String(sid);
        }
        const secName = it.__exec_section_name || sec.name;
        if (secName) {
            it.__exec_section_name = secName;
            it.test_case_section = it.test_case_section || {};
            if (!it.test_case_section.name) it.test_case_section.name = secName;
        }
        if (!it.__exec_section_key) {
            it.__exec_section_key = sid ? String(sid) : 'unassigned';
        }
    });
}

function resetSectionDisplayNameCache() {
    sectionDisplayNameCache = new Map();
}

function getSectionDisplayName(sid, sections) {
    if (sid === 'unassigned') {
        return window.i18n && window.i18n.isReady()
            ? (window.i18n.t('testRun.unassigned.label') || window.i18n.t('testRun.unassigned'))
            : 'Unassigned';
    }

    const key = String(sid);
    if (sectionDisplayNameCache.has(key)) {
        return sectionDisplayNameCache.get(key);
    }

    // 0. 透過索引從 parent chain 還原完整路徑
    if (sectionIndexById && sectionIndexById.size > 0) {
        const path = [];
        let cursor = key;
        let guard = 0;
        while (sectionIndexById.has(cursor) && guard < 50) {
            const entry = sectionIndexById.get(cursor);
            path.unshift(entry.name || `Section ${cursor}`);
            if (!entry.parentId) break;
            cursor = entry.parentId;
            guard += 1;
        }
        if (path.length) {
            const result = path.join(' > ');
            sectionDisplayNameCache.set(key, result);
            return result;
        }
    }

    // 1. Try to find path in treSections (Tree data)
    if (sections && sections.length > 0) {
        const findPath = (nodes, targetId, currentPath) => {
            for (const node of nodes) {
                if (String(node.id) === String(targetId)) {
                    return [...currentPath, node.name];
                }
                if (node.children && node.children.length > 0) {
                    const found = findPath(node.children, targetId, [...currentPath, node.name]);
                    if (found) return found;
                }
            }
            return null;
        };
        const pathArr = findPath(sections, key, []);
        if (pathArr) {
            const result = pathArr.join(' > ');
            sectionDisplayNameCache.set(key, result);
            return result;
        }
    }

    // 2. Fallback: Use item info (limited to immediate parent based on current API)
    const itemWithSec = (testRunItems || []).find(it => String(getItemSectionId(it)) === key);
    if (itemWithSec && itemWithSec.test_case_section) {
        const s = itemWithSec.test_case_section;
        if (s.parent) {
            const result = `${s.parent.name} > ${s.name}`;
            sectionDisplayNameCache.set(key, result);
            return result;
        }
        if (s.name) {
            const result = s.name;
            sectionDisplayNameCache.set(key, result);
            return result;
        }
    }

    const fallback = `Section ${key}`;
    sectionDisplayNameCache.set(key, fallback);
    return fallback;
}

function buildSectionCounts(items, sections) {
    const keyCounts = new Map();

    (items || []).forEach(item => {
        const sid = getItemSectionId(item);
        const key = (sid === null || typeof sid === 'undefined') ? 'unassigned' : String(sid);
        keyCounts.set(key, (keyCounts.get(key) || 0) + 1);
    });

    const totals = new Map();
    const countNode = (node) => {
        if (!node || node.id == null) return 0;
        const filterKeys = collectSectionFilterKeys(node, new Set());
        let total = 0;
        filterKeys.forEach(key => {
            total += keyCounts.get(key) || 0;
        });
        const sid = String(node.id);
        totals.set(sid, total);
        (node.children || []).forEach(child => countNode(child));
        return total;
    };

    (sections || []).forEach(sec => countNode(sec));

    return {
        sectionIdToCount: totals,
        unassignedCount: keyCounts.get('unassigned') || 0,
    };
}

function collectSectionIds(section, acc = new Set()) {
    if (!section || section.id == null) return acc;
    const sid = String(section.id);
    acc.add(sid);
    (section.children || []).forEach(child => collectSectionIds(child, acc));
    return acc;
}

function collectSectionFilterKeys(section, acc = new Set()) {
    if (!section) return acc;
    if (section.id != null) {
        acc.add(String(section.id));
    }
    if (section.name) {
        acc.add(`name:${section.name}`);
    }
    (section.children || []).forEach(child => collectSectionFilterKeys(child, acc));
    return acc;
}

function getSectionSelectionState(section) {
    if (!treSectionFilterIds || treSectionFilterIds.size === 0) {
        return { checked: false, indeterminate: false };
    }
    const subtreeIds = collectSectionIds(section, new Set());
    let selectedCount = 0;
    subtreeIds.forEach(id => {
        if (treSectionFilterIds.has(id)) selectedCount += 1;
    });
    if (selectedCount === 0) return { checked: false, indeterminate: false };
    if (selectedCount === subtreeIds.size) return { checked: true, indeterminate: false };
    return { checked: false, indeterminate: true };
}

function renderTreSectionTree() {
    const container = document.getElementById('treSectionTree');
    if (!container) return;
    const items = testRunItems || [];
    const { sectionIdToCount, unassignedCount } = buildSectionCounts(items, treSections);

    const renderNodes = (sections, level = 0) => {
        return sections.map(sec => {
            const sid = String(sec.id);
            const count = sectionIdToCount.get(sid) || 0;
            const indent = level * 16;
            const key = `tre-section-${sid}`;
            const collapsed = sessionStorage.getItem(key) === 'collapsed';
            const hasChildren = Array.isArray(sec.children) && sec.children.length > 0;
            const label = getSectionDisplayName(sid, treSections);
            const selectionState = getSectionSelectionState(sec);
            const checkedAttr = selectionState.checked ? 'checked' : '';
            const indeterminateAttr = selectionState.indeterminate ? 'data-indeterminate="true"' : '';
            const isActive = selectionState.checked || selectionState.indeterminate;
            return `
                <div class="tre-section-node ${isActive ? 'active' : ''}" data-section-id="${sid}" style="margin-left:${indent}px;">
                    <div class="d-flex align-items-center justify-content-between">
                        <div class="d-flex align-items-center gap-2 flex-grow-1">
                            ${hasChildren ? `
                                <button class="tre-section-toggle" data-toggle-id="${sid}" aria-label="toggle">
                                    <i class="fas fa-chevron-${collapsed ? 'right' : 'down'}"></i>
                                </button>` : `<span style="width:28px;"></span>`}
                            <div class="form-check m-0 d-flex align-items-center gap-2 flex-grow-1">
                                <input class="form-check-input tre-section-check" type="checkbox" id="treSectionCheck-${sid}" data-section-id="${sid}" ${checkedAttr} ${indeterminateAttr}>
                                <label class="form-check-label tre-section-label" for="treSectionCheck-${sid}">
                                    ${escapeHtml(label || sec.name || `Section #${sid}`)}
                                </label>
                            </div>
                        </div>
                        <span class="badge bg-light text-muted tre-section-count">${count}</span>
                    </div>
                    ${hasChildren ? `
                        <div class="${collapsed ? 'd-none' : ''}" data-children-of="${sid}">
                            ${renderNodes(sec.children, level + 1)}
                        </div>` : ''}
                </div>
            `;
        }).join('');
    };

    const isUnassignedActive = treSectionFilterIds && treSectionFilterIds.has('unassigned');
    const unassignedHtml = `
        <div class="tre-section-node ${isUnassignedActive ? 'active' : ''}">
            <div class="d-flex align-items-center justify-content-between">
                <div class="d-flex align-items-center gap-2 flex-grow-1">
                    <span style="width:28px;"></span>
                    <div class="form-check m-0 d-flex align-items-center gap-2 flex-grow-1">
                        <input class="form-check-input tre-section-check" type="checkbox" id="treSectionCheck-unassigned" data-section-id="unassigned" ${isUnassignedActive ? 'checked' : ''}>
                        <label class="form-check-label tre-section-label" for="treSectionCheck-unassigned">
                            ${window.i18n && window.i18n.isReady() ? (window.i18n.t('testRun.unassigned.label') || window.i18n.t('testRun.unassigned')) : 'Unassigned'}
                        </label>
                    </div>
                </div>
                <span class="badge bg-light text-muted tre-section-count">${unassignedCount}</span>
            </div>
        </div>`;

    if (!treSections || treSections.length === 0) {
        container.innerHTML = unassignedHtml;
    } else {
        container.innerHTML = renderNodes(treSections) + unassignedHtml;
    }

    container.querySelectorAll('.tre-section-check').forEach(input => {
        if (input.dataset.indeterminate === 'true') {
            input.indeterminate = true;
        }
        input.addEventListener('change', () => {
            const sid = input.getAttribute('data-section-id');
            if (!treSectionFilterIds) treSectionFilterIds = new Set();
            if (sid === 'unassigned') {
                if (input.checked) {
                    treSectionFilterIds.add('unassigned');
                } else {
                    treSectionFilterIds.delete('unassigned');
                }
            } else {
                const targetSection = findSectionById(sid, treSections);
                const targetKeys = targetSection
                    ? collectSectionFilterKeys(targetSection, new Set())
                    : new Set([String(sid)]);
                targetKeys.forEach(id => {
                    if (input.checked) {
                        treSectionFilterIds.add(String(id));
                    } else {
                        treSectionFilterIds.delete(String(id));
                    }
                });
            }
            if (treSectionFilterIds.size === 0) {
                treSectionFilterIds = null;
            }
            renderTreSectionTree();
            renderTestRunItems();
        });
    });

    container.querySelectorAll('.tre-section-toggle').forEach(btn => {
        btn.addEventListener('click', () => {
            const sid = btn.getAttribute('data-toggle-id');
            const key = `tre-section-${sid}`;
            const collapsed = sessionStorage.getItem(key) === 'collapsed';
            if (collapsed) sessionStorage.removeItem(key); else sessionStorage.setItem(key, 'collapsed');
            renderTreSectionTree();
        });
    });

    const clearBtn = document.getElementById('clearTreSectionFilterBtn');
    if (clearBtn) {
        clearBtn.onclick = () => {
            treSectionFilterIds = null;
            renderTreSectionTree();
            renderTestRunItems();
        };
    }

    if (window.i18n && window.i18n.isReady()) window.i18n.retranslate(container);
}

function findSectionById(id, sections) {
    for (const sec of sections || []) {
        if (String(sec.id) === String(id)) return sec;
        const child = findSectionById(id, sec.children || []);
        if (child) return child;
    }
    return null;
}

// 從 items 的 section parent 鏈補充索引（API 可能只給單層）
function rebuildSectionIndexFromItems(items) {
    if (!sectionIndexById) sectionIndexById = new Map();
    const upsert = (id, name, parentId) => {
        if (id == null) return;
        const key = String(id);
        const existing = sectionIndexById.get(key) || {};
        sectionIndexById.set(key, {
            name: name || existing.name || `Section ${key}`,
            parentId: parentId !== undefined ? (parentId !== null ? String(parentId) : null) : (existing.parentId ?? null)
        });
    };
    const visitSectionChain = (section) => {
        if (!section || section.id == null) return;
        const id = section.id || section.section_id || section.record_id;
        const parentId = section.parent?.id ?? section.parent_id ?? null;
        upsert(id, section.name, parentId);
        if (parentId && section.parent) {
            visitSectionChain(section.parent);
        }
    };
    (items || []).forEach(it => {
        if (it && it.test_case_section) {
            visitSectionChain(it.test_case_section);
        }
    });
    resetSectionDisplayNameCache();
}

function scheduleSectionHydration(items) {
    if (sectionHydrationInFlight) return;
    const targets = (items || []).filter(it => !hasSectionInfo(it));
    if (!targets.length) return;

    const run = async () => {
        sectionHydrationInFlight = true;
        try {
            await preloadAllTeamTestCasesForRun(targets);
            const changed = await hydrateItemSections(targets);
            if (changed > 0) {
                normalizeRunItemSectionInfo(items);
                rebuildSectionIndexFromItems(items);
                renderTestRunItems();
                renderTreSectionTree();
            }
        } catch (e) {
            console.debug('scheduleSectionHydration failed:', e);
        } finally {
            sectionHydrationInFlight = false;
        }
    };

    if (typeof requestIdleCallback === 'function') {
        requestIdleCallback(() => run(), { timeout: 1000 });
    } else {
        setTimeout(run, 0);
    }
}
