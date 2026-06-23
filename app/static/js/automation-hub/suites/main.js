(function () {
  const state = {
    teamId: null,
    scripts: [],
    groups: [],
    selectedScriptIds: new Set(),
    previewOpenIds: new Set(),
    suiteDetailOpenIds: new Set(),
    editingGroup: null,
    modal: null,
    // Section 5: Script ↔ Test view toggle. Persisted per-team in localStorage.
    viewMode: 'script', // 'script' | 'test'
    // Test view grouping: 'script' (by source file) | 'tc' (by test case number).
    testGroupBy: 'script',
    // Both views default to COLLAPSED — track the nodes/groups the user expanded
    // so the browser stays readable with hundreds of scripts/tests.
    scriptTreeExpanded: new Set(),    // Script view: directory node paths
    testGroupExpanded: new Set(),     // Test view: 'script::<path>' | 'tc::<id>'
    // Suite modal picker: collapsed directory groups.
    pickerGroupCollapsed: new Set()
  };

  const VIEW_STORAGE_PREFIX = 'automationHub.viewMode.';
  const TEST_GROUP_STORAGE_PREFIX = 'automationHub.testGroupBy.';

  function viewStorageKey() {
    return state.teamId ? `${VIEW_STORAGE_PREFIX}${state.teamId}` : null;
  }

  function loadViewPreference() {
    return 'script';
  }

  function persistViewPreference(mode) {
    const key = viewStorageKey();
    if (!key) return;
    try {
      window.localStorage.setItem(key, mode);
    } catch (_e) {
      /* localStorage may be disabled; non-fatal */
    }
  }

  function testGroupStorageKey() {
    return state.teamId ? `${TEST_GROUP_STORAGE_PREFIX}${state.teamId}` : null;
  }

  function loadTestGroupPreference() {
    const key = testGroupStorageKey();
    if (!key) return 'script';
    try {
      return window.localStorage.getItem(key) === 'tc' ? 'tc' : 'script';
    } catch (_e) {
      return 'script';
    }
  }

  function persistTestGroupPreference(mode) {
    const key = testGroupStorageKey();
    if (!key) return;
    try {
      window.localStorage.setItem(key, mode);
    } catch (_e) {
      /* non-fatal */
    }
  }

  const RUN_STATUS_BADGE = {
    QUEUED: 'bg-secondary',
    RUNNING: 'bg-info text-dark',
    SUCCEEDED: 'bg-success',
    FAILED: 'bg-danger',
    CANCELLED: 'bg-warning text-dark',
    UNKNOWN: 'bg-dark'
  };

  document.addEventListener('DOMContentLoaded', init);
  document.addEventListener('i18nReady', refreshTexts);
  document.addEventListener('languageChanged', () => {
    renderScripts();
    renderGroups();
    renderSuitePicker();
    initLinkTypeHelp();
    refreshTexts();
  });
  window.addEventListener('pageshow', refreshTexts);

  function init() {
    state.teamId = resolveTeamId();
    const suiteModalEl = document.getElementById('suiteModal');
    if (suiteModalEl && window.bootstrap) {
      state.modal = new bootstrap.Modal(suiteModalEl);
    }
    bindEvents();

    if (!state.teamId) {
      showNoTeam();
      return;
    }

    applyTeamLinks();
    showTeamBadge();
    const automationContent = document.getElementById('automation-content');
    if (automationContent) automationContent.classList.remove('d-none');
    state.viewMode = loadViewPreference();
    state.testGroupBy = loadTestGroupPreference();
    applyViewToggleVisual();
    applyTestGroupByVisual();
    initLinkTypeHelp();
    loadAll();
    loadDashboardLink();
    bindSettingsTab();
  }

  function applyViewToggleVisual() {
    const scriptBtn = document.getElementById('viewToggleScript');
    const testBtn = document.getElementById('viewToggleTest');
    if (!scriptBtn || !testBtn) return;
    scriptBtn.classList.toggle('active', state.viewMode === 'script');
    testBtn.classList.toggle('active', state.viewMode === 'test');
    const tree = document.getElementById('scriptTree');
    const flat = document.getElementById('testFlatList');
    const testToolbar = document.getElementById('testViewToolbar');
    if (tree) tree.classList.toggle('d-none', state.viewMode !== 'script');
    if (flat) flat.classList.toggle('d-none', state.viewMode !== 'test');
    if (testToolbar) {
      testToolbar.classList.toggle('d-none', state.viewMode !== 'test');
      testToolbar.classList.toggle('d-flex', state.viewMode === 'test');
    }
  }

  function applyTestGroupByVisual() {
    const byScript = document.getElementById('testGroupByScript');
    const byTc = document.getElementById('testGroupByTc');
    if (byScript) byScript.classList.toggle('active', state.testGroupBy === 'script');
    if (byTc) byTc.classList.toggle('active', state.testGroupBy === 'tc');
  }

  function setViewMode(mode) {
    if (mode !== 'script' && mode !== 'test') return;
    if (state.viewMode === mode) return;
    state.viewMode = mode;
    persistViewPreference(mode);
    applyViewToggleVisual();
    renderScripts();
  }

  function setTestGroupBy(mode) {
    if (mode !== 'script' && mode !== 'tc') return;
    if (state.testGroupBy === mode) return;
    state.testGroupBy = mode;
    persistTestGroupPreference(mode);
    applyTestGroupByVisual();
    renderScripts();
  }

  function bindSettingsTab() {
    const settingsTab = document.getElementById('settings-tab');
    if (!settingsTab) return;
    let loaded = false;
    settingsTab.addEventListener('shown.bs.tab', () => {
      if (loaded) return;
      loaded = true;
      loadSettingsDashboard();
    });
  }

  async function loadSettingsDashboard() {
    // Fire all three in parallel; each is best-effort and may 401/403 silently.
    const [providers, webhooks] = await Promise.all([
      apiFetch(`/api/teams/${state.teamId}/automation-providers`).catch(() => null),
      apiFetch(`/api/teams/${state.teamId}/automation-webhooks`).catch(() => null),
    ]);
    renderSettingsProviders(providers);
    renderSettingsWebhooks(webhooks);
    renderSettingsSystem();
    if (window.i18n) window.i18n.retranslate(document.getElementById('settings-pane'));
  }

  function renderSettingsProviders(providers) {
    const list = Array.isArray(providers) ? providers : [];
    const buckets = { storage: [], ci: [], result: [] };
    for (const p of list) {
      const slot = String(p.provider_slot || '').toLowerCase();
      if (buckets[slot]) buckets[slot].push(p);
    }
    const apply = (slot, countId, healthId) => {
      const items = buckets[slot];
      const count = items.length;
      document.getElementById(countId).textContent = String(count);
      const healthEl = document.getElementById(healthId);
      if (!count) {
        healthEl.textContent = '—';
        healthEl.className = 'automation-stat-sub text-muted small';
        return;
      }
      const active = items.filter((p) => p.is_active).length;
      const healthy = items.filter((p) => (p.last_health_status || '').toUpperCase() === 'OK').length;
      const failed = items.filter((p) => (p.last_health_status || '').toUpperCase() === 'FAILED').length;
      const parts = [];
      parts.push(`${active}/${count} ${t('automationHub.providers.active', 'Active').toLowerCase()}`);
      if (healthy) parts.push(`${healthy} ✅`);
      if (failed) parts.push(`${failed} ⚠`);
      healthEl.textContent = parts.join(' · ');
      healthEl.className = 'automation-stat-sub small ' + (failed ? 'text-danger' : 'text-success');
    };
    apply('storage', 'settingsProviderStorageCount', 'settingsProviderStorageHealth');
    apply('ci', 'settingsProviderCiCount', 'settingsProviderCiHealth');
    apply('result', 'settingsProviderResultCount', 'settingsProviderResultHealth');
    const empty = document.getElementById('settingsProviderEmpty');
    empty.classList.toggle('d-none', list.length > 0);
  }

  function renderSettingsWebhooks(webhooks) {
    const list = Array.isArray(webhooks) ? webhooks : [];
    const inbound = list.filter((w) => String(w.direction || '').toUpperCase() === 'INBOUND');
    const outbound = list.filter((w) => String(w.direction || '').toUpperCase() === 'OUTBOUND');
    const apply = (items, countId, activeId, labelKey, labelFallback) => {
      document.getElementById(countId).textContent = String(items.length);
      const activeEl = document.getElementById(activeId);
      if (!items.length) {
        activeEl.textContent = '—';
        activeEl.className = 'automation-stat-sub text-muted small';
        return;
      }
      const active = items.filter((w) => w.is_active).length;
      activeEl.textContent = `${active}/${items.length} ${t(labelKey, labelFallback).toLowerCase()}`;
      activeEl.className = 'automation-stat-sub small ' + (active === items.length ? 'text-success' : 'text-warning');
    };
    apply(inbound, 'settingsWebhookInboundCount', 'settingsWebhookInboundActive', 'automationHub.webhooks.active', 'Active');
    apply(outbound, 'settingsWebhookOutboundCount', 'settingsWebhookOutboundActive', 'automationHub.webhooks.active', 'Active');
    const empty = document.getElementById('settingsWebhookEmpty');
    empty.classList.toggle('d-none', list.length > 0);
  }

  function renderSettingsSystem() {
    const cfg = window.automationResultConfig;
    const statusEl = document.getElementById('settingsEncryptionStatus');
    // Encryption key status is inferred: if any provider with credentials_set
    // returned successfully OR provider list call succeeded, the key works.
    // We default to OK because failure would have raised before this point.
    if (statusEl) {
      statusEl.textContent = t('automationHub.settings.encryptionOk', 'Configured');
      statusEl.className = 'badge bg-success';
      statusEl.removeAttribute('data-i18n');
    }
    const link = document.getElementById('settingsDashboardLink');
    const empty = document.getElementById('settingsDashboardEmpty');
    if (cfg && cfg.configured && cfg.dashboard_url) {
      link.href = cfg.dashboard_url;
      link.classList.remove('d-none');
      empty.classList.add('d-none');
    } else {
      link.classList.add('d-none');
      empty.classList.remove('d-none');
    }
  }

  async function loadDashboardLink() {
    const link = document.getElementById('teamDashboardLink');
    try {
      const data = await apiFetch(`/api/teams/${state.teamId}/automation-result/dashboard`);
      // Stash for runs/panel modules to read embed_mode
      window.automationResultConfig = data || null;
      if (link) {
        if (data && data.configured && data.dashboard_url) {
          link.href = data.dashboard_url;
          link.classList.remove('d-none');
        } else {
          link.classList.add('d-none');
        }
      }
      installIframeReportInterceptor();
    } catch (_e) {
      window.automationResultConfig = null;
      if (link) link.classList.add('d-none');
    }
  }

  let _iframeInterceptorInstalled = false;
  function installIframeReportInterceptor() {
    if (_iframeInterceptorInstalled) return;
    _iframeInterceptorInstalled = true;
    document.addEventListener('click', (event) => {
      const cfg = window.automationResultConfig;
      if (!cfg || cfg.embed_mode !== 'iframe') return;
      const link = event.target.closest('a[target="_blank"]');
      if (!link) return;
      const href = link.getAttribute('href') || '';
      // Heuristic: any anchor pointing at the result provider's base_url
      // is treated as a report link and gets embedded.
      const baseUrl = (cfg.base_url || '').trim();
      if (!baseUrl || !href.startsWith(baseUrl)) return;
      event.preventDefault();
      openReportEmbed(href);
    });
  }

  function openReportEmbed(url) {
    const frame = document.getElementById('reportEmbedFrame');
    const fallback = document.getElementById('reportEmbedOpenLink');
    const warning = document.getElementById('reportEmbedWarning');
    if (!frame) {
      window.open(url, '_blank', 'noopener');
      return;
    }
    let loaded = false;
    let fallbackOpened = false;
    let fallbackTimer = null;
    const showFallback = () => {
      if (fallbackOpened || loaded) return;
      fallbackOpened = true;
      if (warning) warning.classList.remove('d-none');
      if (window.automationResultConfig) {
        window.automationResultConfig = { ...window.automationResultConfig, embed_mode: 'link' };
      }
      window.open(url, '_blank', 'noopener');
    };
    frame.onload = () => {
      loaded = true;
      if (warning) warning.classList.add('d-none');
    };
    frame.onerror = showFallback;
    frame.src = url;
    if (fallback) fallback.href = url;
    const modalEl = document.getElementById('reportEmbedModal');
    if (modalEl && window.bootstrap) {
      const modal = window.bootstrap.Modal.getOrCreateInstance(modalEl);
      modal.show();
      fallbackTimer = window.setTimeout(showFallback, 3500);
      modalEl.addEventListener('hidden.bs.modal', () => {
        fallbackOpened = true;
        if (fallbackTimer) window.clearTimeout(fallbackTimer);
        frame.src = 'about:blank';
        frame.onload = null;
        frame.onerror = null;
      }, { once: true });
    } else {
      window.open(url, '_blank', 'noopener');
    }
  }

  function bindEvents() {
    const newSuiteBtn = document.getElementById('newSuiteBtn');
    if (newSuiteBtn) newSuiteBtn.addEventListener('click', () => openSuiteModal());

    const newSuiteInlineBtn = document.getElementById('newSuiteInlineBtn');
    if (newSuiteInlineBtn) newSuiteInlineBtn.addEventListener('click', () => openSuiteModal());

    const rescanScriptsBtn = document.getElementById('rescanScriptsBtn');
    if (rescanScriptsBtn) rescanScriptsBtn.addEventListener('click', syncScripts);

    const scriptSearch = document.getElementById('scriptSearch');
    if (scriptSearch) scriptSearch.addEventListener('input', renderScripts);

    const saveSuiteBtn = document.getElementById('saveSuiteBtn');
    if (saveSuiteBtn) saveSuiteBtn.addEventListener('click', saveSuite);

    // Section 5: view toggle buttons + delegated handler for Test view.
    const viewScriptBtn = document.getElementById('viewToggleScript');
    const viewTestBtn = document.getElementById('viewToggleTest');
    if (viewScriptBtn) viewScriptBtn.addEventListener('click', () => setViewMode('script'));
    if (viewTestBtn) viewTestBtn.addEventListener('click', () => setViewMode('test'));

    const groupByScriptBtn = document.getElementById('testGroupByScript');
    const groupByTcBtn = document.getElementById('testGroupByTc');
    if (groupByScriptBtn) groupByScriptBtn.addEventListener('click', () => setTestGroupBy('script'));
    if (groupByTcBtn) groupByTcBtn.addEventListener('click', () => setTestGroupBy('tc'));

    const flatList = document.getElementById('testFlatList');
    if (flatList) {
      flatList.addEventListener('click', (event) => {
        const groupToggle = event.target.closest('[data-test-group-toggle]');
        if (groupToggle) {
          toggleTestGroup(groupToggle.dataset.testGroupToggle);
          return;
        }
        const goToFile = event.target.closest('[data-test-source-file]');
        if (goToFile) {
          setViewMode('script');
          state.previewOpenIds.add(Number(goToFile.dataset.testSourceFile));
          renderScripts();
        }
      });
    }

    const expandAllBtn = document.getElementById('treeExpandAllBtn');
    const collapseAllBtn = document.getElementById('treeCollapseAllBtn');
    if (expandAllBtn) expandAllBtn.addEventListener('click', () => setAllExpanded(true));
    if (collapseAllBtn) collapseAllBtn.addEventListener('click', () => setAllExpanded(false));

    const scriptTree = document.getElementById('scriptTree');
    if (scriptTree) {
      scriptTree.addEventListener('click', (event) => {
        const dirToggle = event.target.closest('[data-tree-toggle]');
        if (dirToggle) {
          toggleScriptNode(dirToggle.dataset.treeToggle);
          return;
        }
        const runButton = event.target.closest('[data-script-run]');
        if (runButton) {
          // Historical "Run Now" trigger has been removed (move-automation-execution-to-test-run-set).
          // Fall through — no-op. The button itself was removed from the markup; this
          // is a defensive guard in case an old cached bundle still renders it.
          return;
        }
        const previewButton = event.target.closest('[data-script-preview]');
        if (previewButton) {
          togglePreview(Number(previewButton.dataset.scriptPreview));
        }
      });
    }

    // Suite modal: in-modal script picker (search + checkable list).
    const picker = document.getElementById('suitePickerList');
    if (picker) {
      picker.addEventListener('change', (event) => {
        if (!event.target.matches('[data-pick-script]')) return;
        const scriptId = Number(event.target.dataset.pickScript);
        if (event.target.checked) state.selectedScriptIds.add(scriptId);
        else state.selectedScriptIds.delete(scriptId);
        updateSelectedCount();
      });
      picker.addEventListener('click', (event) => {
        const groupToggle = event.target.closest('[data-pick-group-toggle]');
        if (groupToggle) togglePickerGroup(groupToggle.dataset.pickGroupToggle);
      });
    }
    const pickerSearch = document.getElementById('suitePickerSearch');
    if (pickerSearch) pickerSearch.addEventListener('input', renderSuitePicker);

    const suiteList = document.getElementById('suiteList');
    if (suiteList) {
      suiteList.addEventListener('click', (event) => {
        const button = event.target.closest('[data-suite-action]');
        if (!button) return;
        const group = state.groups.find((item) => String(item.id) === button.dataset.groupId);
        if (!group) return;
        if (button.dataset.suiteAction === 'edit') openSuiteModal(group);
        if (button.dataset.suiteAction === 'delete') deleteSuite(group);
        // Historical 'data-suite-action="run"' handler has been removed —
        // execution is now triggered from the Test Run Set detail page.
        if (button.dataset.suiteAction === 'toggle-detail') toggleSuiteDetail(group.id);
      });
    }
  }

  function toggleSuiteDetail(groupId) {
    if (state.suiteDetailOpenIds.has(groupId)) {
      state.suiteDetailOpenIds.delete(groupId);
    } else {
      state.suiteDetailOpenIds.add(groupId);
    }
    renderGroups();
  }

  async function loadAll() {
    setLoading(true);
    try {
      const [scriptResult, groupResult] = await Promise.all([
        apiFetch(`/api/teams/${state.teamId}/automation-scripts?limit=200`),
        apiFetch(`/api/teams/${state.teamId}/automation-script-groups?limit=100`)
      ]);
      state.scripts = scriptResult.items || [];
      state.groups = groupResult.items || [];
      renderScripts();
      renderGroups();

      // First-time entry: if no scripts yet, auto-trigger discovery
      // (§4.3 — only fires once per session to avoid loops on truly empty repos)
      if (state.scripts.length === 0 && !state.autoSyncTried) {
        state.autoSyncTried = true;
        try {
          await syncScripts({ silent: true });
        } catch (_e) {}
      }
    } catch (error) {
      showError(error.message || t('automationHub.loadFailed', 'Failed to load Automation Hub'));
    } finally {
      setLoading(false);
      refreshTexts();
    }
  }

  async function syncScripts(opts) {
    const silent = Boolean(opts && opts.silent);
    const button = document.getElementById('rescanScriptsBtn');
    if (button) button.disabled = true;
    try {
      const result = await apiFetch(`/api/teams/${state.teamId}/automation-scripts/sync`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({})
      });
      if (!silent) {
        showSuccess(
          t('automationHub.scripts.rescanDone', 'Scripts rescanned')
            + ` (${result.added}/${result.updated}/${result.removed})`
        );
      }
      // Re-fetch but guard against the auto-sync loop by leaving autoSyncTried set.
      const prev = state.autoSyncTried;
      await loadAll();
      state.autoSyncTried = prev || state.autoSyncTried;
    } catch (error) {
      if (!silent) {
        showError(error.message || t('automationHub.scripts.rescanFailed', 'Failed to rescan scripts'));
      }
    } finally {
      if (button) button.disabled = false;
    }
  }

  function renderScripts() {
    const treeContainer = document.getElementById('scriptTree');
    const flatContainer = document.getElementById('testFlatList');
    const emptyState = document.getElementById('scriptEmpty');
    const query = document.getElementById('scriptSearch').value.trim().toLowerCase();
    state.searchQuery = query;   // read by highlightMatch() while rendering labels

    document.getElementById('scriptCount').textContent = String(state.scripts.length);

    if (state.viewMode === 'test') {
      // Flatten cached_content-derived test entries, then group by script or TC#.
      const rows = collectTestRows().filter((row) => {
        if (!query) return true;
        const tcs = (row.markers || []).flatMap((m) => m.tc_ids || []).join(' ');
        return `${row.name} ${row.refPath} ${tcs}`.toLowerCase().includes(query);
      });
      emptyState.classList.toggle('d-none', rows.length > 0);
      flatContainer.innerHTML = renderTestGroups(rows);
      refreshTexts(flatContainer);
    } else {
      const scripts = state.scripts.filter((script) => {
        if (!query) return true;
        if (`${script.name} ${script.ref_path}`.toLowerCase().includes(query)) return true;
        // Also match inside the file's source (only present after a content sync).
        const content = script.cached_content;
        return typeof content === 'string' && content.toLowerCase().includes(query);
      });
      emptyState.classList.toggle('d-none', scripts.length > 0);
      treeContainer.innerHTML = renderScriptGroups(scripts);
      refreshTexts(treeContainer);
      applySyntaxHighlight(treeContainer);
    }
    updateSelectedCount();
  }

  // ── Grouping helpers ─────────────────────────────────────────────
  function renderGroupHeader({ key, toggleAttr, icon, label, count, collapsed, depth }) {
    const caret = collapsed ? 'fa-chevron-right' : 'fa-chevron-down';
    const indent = depth ? ` style="padding-left:${0.5 + depth * 1.1}rem"` : '';
    return `
      <div class="automation-group-header" ${toggleAttr}="${escapeAttr(key)}" role="button"${indent}>
        <i class="fas ${caret} automation-group-caret"></i>
        <i class="fas ${icon} text-primary"></i>
        <span class="automation-group-label" title="${escapeAttr(label)}">${highlightMatch(label)}</span>
        <span class="badge bg-light text-dark border ms-auto">${count}</span>
      </div>`;
  }

  // ── Script view: recursive folder tree (default collapsed) ───────
  function buildScriptTree(scripts) {
    const root = { name: '', path: '', dirs: new Map(), files: [] };
    for (const script of scripts) {
      const parts = String(script.ref_path || '').split('/').filter(Boolean);
      const fileName = parts.pop();
      let node = root;
      let acc = '';
      for (const part of parts) {
        acc = acc ? `${acc}/${part}` : part;
        if (!node.dirs.has(part)) {
          node.dirs.set(part, { name: part, path: acc, dirs: new Map(), files: [] });
        }
        node = node.dirs.get(part);
      }
      node.files.push({ script, fileName });
    }
    return root;
  }

  function countTreeFiles(node) {
    let total = node.files.length;
    for (const child of node.dirs.values()) total += countTreeFiles(child);
    return total;
  }

  // Render one directory level at a time so the user expands folder by folder
  // (no path compression / flattening — every directory is its own node).
  function renderScriptTree(node, depth, expandAll) {
    let html = '';
    const dirNames = Array.from(node.dirs.keys()).sort();
    for (const name of dirNames) {
      const dir = node.dirs.get(name);
      const expanded = expandAll || state.scriptTreeExpanded.has(dir.path);
      html += renderGroupHeader({
        key: dir.path, toggleAttr: 'data-tree-toggle',
        icon: expanded ? 'fa-folder-open' : 'fa-folder',
        label: dir.name, count: countTreeFiles(dir), collapsed: !expanded, depth,
      });
      if (expanded) {
        html += `<div class="automation-tree-children">${renderScriptTree(dir, depth + 1, expandAll)}</div>`;
      }
    }
    const files = node.files.slice().sort((a, b) => a.fileName.localeCompare(b.fileName));
    for (const f of files) html += renderScriptItem(f.script, depth);
    return html;
  }

  function renderScriptGroups(scripts) {
    if (scripts.length === 0) return '';
    const expandAll = Boolean(document.getElementById('scriptSearch').value.trim());
    return renderScriptTree(buildScriptTree(scripts), 0, expandAll);
  }

  // Test view: group rows by source script or by test case number.
  function renderTestGroups(rows) {
    if (rows.length === 0) return '';
    const expandAll = Boolean(document.getElementById('scriptSearch').value.trim());
    return state.testGroupBy === 'tc'
      ? renderTestGroupsByTc(rows, expandAll)
      : renderTestGroupsByScript(rows, expandAll);
  }

  function renderTestGroupsByScript(rows, expandAll) {
    const groups = new Map();
    for (const row of rows) {
      if (!groups.has(row.refPath)) groups.set(row.refPath, []);
      groups.get(row.refPath).push(row);
    }
    return Array.from(groups.keys()).sort().map((path) => {
      const items = groups.get(path);
      const key = `script::${path}`;
      const collapsed = !expandAll && !state.testGroupExpanded.has(key);
      const header = renderGroupHeader({
        key, toggleAttr: 'data-test-group-toggle',
        icon: 'fa-file-code', label: path, count: items.length, collapsed,
      });
      const body = collapsed
        ? ''
        : `<div class="automation-group-body">${items.map(renderTestRow).join('')}</div>`;
      return header + body;
    }).join('');
  }

  function renderTestGroupsByTc(rows, expandAll) {
    const NO_TC = '__none__';
    const groups = new Map();
    for (const row of rows) {
      const tcIds = Array.from(new Set((row.markers || []).flatMap((m) => m.tc_ids || [])));
      const keys = tcIds.length ? tcIds : [NO_TC];
      for (const tc of keys) {
        if (!groups.has(tc)) groups.set(tc, []);
        groups.get(tc).push(row);
      }
    }
    // Real TC numbers first (sorted), the "no test case" bucket last.
    const ordered = Array.from(groups.keys()).filter((k) => k !== NO_TC).sort();
    if (groups.has(NO_TC)) ordered.push(NO_TC);
    return ordered.map((tc) => {
      const items = groups.get(tc);
      const isNone = tc === NO_TC;
      const key = `tc::${tc}`;
      const collapsed = !expandAll && !state.testGroupExpanded.has(key);
      const header = renderGroupHeader({
        key, toggleAttr: 'data-test-group-toggle',
        icon: isNone ? 'fa-circle-question' : 'fa-hashtag',
        label: isNone ? t('automationHub.tests.groupNoTc', 'No test case') : tc,
        count: items.length, collapsed,
      });
      const body = collapsed
        ? ''
        : `<div class="automation-group-body">${items.map(renderTestRow).join('')}</div>`;
      return header + body;
    }).join('');
  }

  function toggleScriptNode(path) {
    if (state.scriptTreeExpanded.has(path)) state.scriptTreeExpanded.delete(path);
    else state.scriptTreeExpanded.add(path);
    renderScripts();
  }

  function toggleTestGroup(key) {
    if (state.testGroupExpanded.has(key)) state.testGroupExpanded.delete(key);
    else state.testGroupExpanded.add(key);
    renderScripts();
  }

  // Expand/collapse every node/group in the currently active view.
  function setAllExpanded(expanded) {
    if (state.viewMode === 'test') {
      state.testGroupExpanded.clear();
      if (expanded) {
        for (const row of collectTestRows()) {
          if (state.testGroupBy === 'tc') {
            const tcIds = Array.from(new Set((row.markers || []).flatMap((m) => m.tc_ids || [])));
            (tcIds.length ? tcIds : [' none']).forEach((tc) => state.testGroupExpanded.add(`tc::${tc}`));
          } else {
            state.testGroupExpanded.add(`script::${row.refPath}`);
          }
        }
      }
    } else {
      state.scriptTreeExpanded.clear();
      if (expanded) {
        for (const script of state.scripts) {
          const parts = String(script.ref_path || '').split('/').filter(Boolean);
          parts.pop();
          let acc = '';
          for (const part of parts) {
            acc = acc ? `${acc}/${part}` : part;
            state.scriptTreeExpanded.add(acc);
          }
        }
      }
    }
    renderScripts();
  }

  function collectTestRows() {
    const rows = [];
    for (const script of state.scripts) {
      const entries = Array.isArray(script.test_entries) ? script.test_entries : [];
      if (entries.length === 0) {
        // Script known but no test_entries (e.g., never synced content / oversize).
        rows.push({
          scriptId: script.id,
          refPath: script.ref_path,
          name: script.name,
          kind: 'unknown',
          line: 1,
          markers: [],
          scriptFormat: script.script_format,
          contentUnverified: true,
        });
        continue;
      }
      for (const entry of entries) {
        rows.push({
          scriptId: script.id,
          refPath: script.ref_path,
          name: entry.name,
          kind: entry.kind,
          line: entry.line || 1,
          markers: entry.markers || [],
          scriptFormat: script.script_format,
          contentUnverified: false,
        });
      }
    }
    return rows;
  }

  const LINK_TYPE_BADGE = {
    primary: 'bg-primary',
    references: 'bg-info text-dark',
    covers: 'bg-success',
  };

  // "?" popover explaining the three link types (primary / covers / references).
  function initLinkTypeHelp() {
    const btn = document.getElementById('linkTypeHelpBtn');
    if (!btn || !window.bootstrap || !window.bootstrap.Popover) return;
    const existing = window.bootstrap.Popover.getInstance(btn);
    if (existing) existing.dispose();
    const row = (cls, label, descKey, descFallback) =>
      `<div class="automation-linktype-row">
         <span class="badge ${cls}">${label}</span>
         <span>${escapeHtml(t(descKey, descFallback))}</span>
       </div>`;
    const content =
      `<div class="automation-linktype-pop">
         ${row('bg-primary', 'primary', 'automationHub.tests.linkTypePrimaryDesc', 'fully verifies this case end-to-end.')}
         ${row('bg-success', 'covers', 'automationHub.tests.linkTypeCoversDesc', 'partially covers this case (default).')}
         ${row('bg-info text-dark', 'references', 'automationHub.tests.linkTypeReferencesDesc', 'related / supporting context only.')}
       </div>`;
    new window.bootstrap.Popover(btn, {
      html: true,
      sanitize: false,
      trigger: 'focus hover',
      placement: 'bottom',
      customClass: 'automation-linktype-popover',
      title: t('automationHub.tests.linkTypeHelpTitle', 'Link types'),
      content,
    });
  }

  // One clean line per test. Context-aware so the grouping dimension is never
  // repeated: by-script groups show TC badges (+ just :line); by-TC groups show
  // only the link type (+ the full source path).
  function renderTestRow(row) {
    const groupedByTc = state.testGroupBy === 'tc';
    const kindTitle = {
      function: t('automationHub.tests.kindFunction', 'function'),
      class: t('automationHub.tests.kindClass', 'class'),
      js_test: t('automationHub.tests.kindJsTest', 'test'),
      unknown: t('automationHub.tests.kindUnknown', 'unknown'),
    }[row.kind] || row.kind;
    const locText = groupedByTc ? `${row.refPath}:${row.line}` : `:${row.line}`;
    return `
      <div class="automation-test-row" data-test-row="${escapeAttr(row.scriptId + '::' + row.name)}">
        <i class="fas fa-vial automation-test-icon" title="${escapeAttr(kindTitle)}"></i>
        <span class="automation-test-name" title="${escapeAttr(row.name)}">${highlightMatch(row.name)}</span>
        <span class="automation-test-badges">${renderTestLinkBadges(row, groupedByTc)}</span>
        <button type="button" class="automation-test-loc" data-test-source-file="${escapeAttr(row.scriptId)}"
                title="${escapeAttr(t('automationHub.tests.openSource', 'Open source in script view'))}">
          <i class="fas fa-file-code me-1"></i>${highlightMatch(locText)}
        </button>
      </div>`;
  }

  function renderTestLinkBadges(row, groupedByTc) {
    if (row.contentUnverified) {
      return `<span class="automation-test-flag" title="${escapeAttr(t('automationHub.tests.contentUnverifiedHint', 'No cached content yet — re-sync to populate test entries'))}">
                <i class="fas fa-circle-exclamation me-1"></i>${escapeHtml(t('automationHub.tests.contentUnverified', 'unverified'))}</span>`;
    }
    const markers = Array.isArray(row.markers) ? row.markers : [];
    if (markers.length === 0) {
      return `<span class="automation-test-flag" title="${escapeAttr(t('automationHub.tests.noMarkerHint', 'Add a tcrt marker in code and re-sync to link this test'))}">
                <i class="fas fa-circle-notch me-1"></i>${escapeHtml(t('automationHub.tests.noMarker', 'no link'))}</span>`;
    }
    if (groupedByTc) {
      // TC already shown in the group header → show only the link type(s).
      const types = Array.from(new Set(markers.map((m) => m.link_type)));
      return types.map((lt) =>
        `<span class="badge ${LINK_TYPE_BADGE[lt] || 'bg-secondary'}">${escapeHtml(lt)}</span>`
      ).join(' ');
    }
    const badges = [];
    for (const marker of markers) {
      const cls = LINK_TYPE_BADGE[marker.link_type] || 'bg-secondary';
      for (const tc of (marker.tc_ids || [])) {
        badges.push(`<span class="badge ${cls}" title="${escapeAttr(marker.link_type)}">${highlightMatch(tc)}</span>`);
      }
    }
    return badges.join(' ');
  }

  function renderScriptItem(script, depth) {
    const previewOpen = state.previewOpenIds.has(script.id);
    const preview = previewOpen ? renderScriptPreview(script) : '';
    const fileName = String(script.ref_path || '').split('/').pop();
    const testCount = Array.isArray(script.test_entries) ? script.test_entries.length : 0;
    const indent = depth ? ` style="padding-left:${0.5 + (depth + 1) * 1.1}rem"` : '';
    const testBadge = testCount
      ? `<span class="badge bg-light text-dark border ms-1" title="${escapeAttr(t('automationHub.scripts.testCountHint', 'Declared tests in this file'))}">${testCount} <i class="fas fa-vial"></i></span>`
      : '';
    const caret = previewOpen ? 'fa-chevron-down' : 'fa-chevron-right';
    return `
      <article class="automation-script-item">
        <div class="automation-script-row"${indent}>
          <button type="button" class="automation-script-toggle" data-script-preview="${script.id}"
                  aria-expanded="${previewOpen}" title="${escapeAttr(t('automationHub.scripts.togglePreview', 'Show / hide source'))}">
            <i class="fas ${caret} automation-group-caret"></i>
            <i class="fas fa-file-code text-primary"></i>
            <div class="automation-script-main">
              <div class="automation-path fw-semibold" title="${escapeAttr(script.ref_path)}">${highlightMatch(fileName)}${testBadge}</div>
              <div class="text-muted small">
                ${escapeHtml(script.script_format || 'OTHER')} · ${escapeHtml(script.ref_branch || '')}
              </div>
            </div>
          </button>
          <!-- Historical "Run Now" button removed (move-automation-execution-to-test-run-set).
               Execution is now triggered from the Test Run Set detail page. -->
        </div>
        ${preview}
      </article>`;
  }

  function renderScriptPreview(script) {
    const hasContent = Boolean(script.cached_content);
    const content = script.cached_content || t('automationHub.scripts.previewUnavailable', 'Preview unavailable');
    const editHint = escapeHtml(t('automationHub.scripts.editInIde', 'Read-only preview — edit this file in your IDE and push to git.'));
    const langClass = hasContent ? langClassFor(script.ref_path) : 'nohighlight';
    return `
      <div class="automation-preview">
        <pre class="automation-code" title="${escapeAttr(editHint)}"><code class="${langClass}">${escapeHtml(content)}</code></pre>
        <div class="automation-preview-hint text-muted small">
          <i class="fas fa-info-circle me-1"></i>${editHint}
        </div>
      </div>`;
  }

  // Map a file path to a highlight.js language class (empty → auto-detect).
  function langClassFor(refPath) {
    const p = String(refPath || '').toLowerCase();
    if (p.endsWith('.py')) return 'language-python';
    if (p.endsWith('.ts') || p.endsWith('.tsx')) return 'language-typescript';
    if (p.endsWith('.js') || p.endsWith('.jsx') || p.endsWith('.mjs')) return 'language-javascript';
    return '';
  }

  // Highlight any freshly-rendered code blocks (idempotent via data-hl marker).
  function applySyntaxHighlight(root) {
    if (!root || !window.hljs) return;
    root.querySelectorAll('pre.automation-code > code:not([data-hl])').forEach((el) => {
      if (!el.classList.contains('nohighlight')) {
        try { window.hljs.highlightElement(el); } catch (_e) { /* non-fatal */ }
      }
      el.setAttribute('data-hl', '1');
    });
  }

  // (run history rendering removed: Automation Hub no longer surfaces
  // script-level recent runs; run history now lives in Test Run Set detail)

  function renderSuiteRunsPlaceholder() {
    return `
      <div class="automation-suite-detail-runs mt-2">
        <div class="text-muted small">${escapeHtml(t('automationHub.suites.runsMoved', 'Run history is now in Test Run Set detail.'))}</div>
      </div>`;
  }

  function formatTimestamp(value) {
    if (!value) return '';
    try {
      const date = new Date(value);
      if (Number.isNaN(date.getTime())) return value;
      return date.toLocaleString();
    } catch (_e) {
      return value;
    }
  }

  function formatDuration(ms) {
    if (ms === null || ms === undefined) return '';
    const value = Number(ms);
    if (!Number.isFinite(value) || value < 0) return '';
    if (value < 1000) return `${value} ms`;
    const seconds = value / 1000;
    if (seconds < 60) return `${seconds.toFixed(1)} s`;
    const minutes = Math.floor(seconds / 60);
    const remainder = Math.round(seconds - minutes * 60);
    return `${minutes}m ${remainder}s`;
  }

  async function togglePreview(scriptId) {
    const script = state.scripts.find((item) => item.id === scriptId);
    if (!script) return;

    if (state.previewOpenIds.has(scriptId)) {
      state.previewOpenIds.delete(scriptId);
      renderScripts();
      return;
    }

    state.previewOpenIds.add(scriptId);
    const tasks = [];
    if (!script.cached_content) {
      tasks.push((async () => {
        try {
          const updated = await apiFetch(`/api/teams/${state.teamId}/automation-scripts/${scriptId}/sync`, { method: 'POST' });
          state.scripts = state.scripts.map((item) => (item.id === scriptId ? updated : item));
        } catch (error) {
          showError(error.message || t('automationHub.scripts.previewFailed', 'Failed to load preview'));
        }
      })());
    }
    // (script-level recent runs are not loaded here; run history is owned by
    //  Test Run Set detail — see the header at the top of this file)
    renderScripts();
    if (tasks.length > 0) {
      await Promise.all(tasks);
      renderScripts();
    }
  }

  // (script-level recent runs loader removed: run history now lives in
  // Test Run Set detail; see the header at the top of this file)

  function renderGroups() {
    const container = document.getElementById('suiteList');
    const emptyState = document.getElementById('suiteEmpty');
    const countEl = document.getElementById('suiteCount');
    if (countEl) countEl.textContent = String(state.groups.length);
    emptyState.classList.toggle('d-none', state.groups.length > 0);
    container.innerHTML = state.groups.map(renderSuiteItem).join('');
    refreshTexts(container);
  }

  function renderSuiteItem(group) {
    const ciJob = group.ci_job_name || t('common.notSet', 'Not set');
    const detailOpen = state.suiteDetailOpenIds.has(group.id);
    const detailIcon = detailOpen ? 'fa-chevron-up' : 'fa-chevron-down';
    const detailBlock = detailOpen ? renderSuiteDetail(group) : '';
    return `
      <article class="automation-suite-item">
        <div class="automation-suite-row">
          <i class="fas fa-layer-group text-primary"></i>
          <div class="automation-suite-main">
            <div class="automation-suite-name fw-semibold" title="${escapeAttr(group.name)}">${escapeHtml(group.name)}</div>
            <div class="text-muted small">
              ${group.script_count} ${escapeHtml(t('automationHub.suites.scripts', 'scripts'))} · ${escapeHtml(ciJob)}
            </div>
          </div>
           <div class="automation-suite-actions">
            <!-- Historical "Run suite" button removed (move-automation-execution-to-test-run-set).
                 Execution is now triggered from the Test Run Set detail page. -->
            <button type="button" class="btn btn-secondary btn-sm" data-suite-action="toggle-detail" data-group-id="${group.id}" title="${escapeAttr(t('automationHub.suites.toggleDetail', 'Toggle details'))}">
              <i class="fas ${detailIcon}"></i>
            </button>
            <button type="button" class="btn btn-secondary btn-sm" data-suite-action="edit" data-group-id="${group.id}" title="${escapeAttr(t('common.edit', 'Edit'))}">
              <i class="fas fa-pen"></i>
            </button>
            <button type="button" class="btn btn-danger btn-sm" data-suite-action="delete" data-group-id="${group.id}" title="${escapeAttr(t('common.delete', 'Delete'))}">
              <i class="fas fa-trash"></i>
            </button>
          </div>
        </div>
        ${detailBlock}
      </article>`;
  }

  function renderSuiteDetail(group) {
    const description = group.description
      ? `<div class="automation-suite-detail-desc text-muted small mb-2">${escapeHtml(group.description)}</div>`
      : '';
    const scripts = Array.isArray(group.scripts) ? group.scripts : [];
    const scriptList = scripts.length
      ? `<ul class="automation-suite-detail-scripts">${scripts.map((s) => `
          <li class="font-monospace small" title="${escapeAttr(s.ref_path || '')}">
            <i class="fas fa-file-code text-primary me-1"></i>${escapeHtml(s.ref_path || s.name || '')}
          </li>`).join('')}</ul>`
      : `<div class="text-muted small">${escapeHtml(t('automationHub.suites.detailEmpty', 'This suite has no scripts.'))}</div>`;
    return `
      <div class="automation-suite-detail">
        ${description}
        ${scriptList}
        <div class="automation-suite-detail-runs mt-2">
          <div class="text-muted small">${escapeHtml(t('automationHub.suites.runsMoved', 'Run history is now in Test Run Set detail.'))}</div>
        </div>
      </div>`;
  }

  function openSuiteModal(group) {
    if (!state.modal) return;
    state.editingGroup = group || null;
    document.getElementById('suiteId').value = group ? group.id : '';
    document.getElementById('suiteName').value = group ? group.name : '';
    document.getElementById('suiteDescription').value = group ? (group.description || '') : '';
    document.getElementById('suiteModalTitle').textContent = group
      ? t('automationHub.suites.editTitle', 'Edit Suite')
      : t('automationHub.suites.createTitle', 'Create Suite');

    state.selectedScriptIds = new Set(group ? (group.script_ids || []) : []);
    state.pickerGroupCollapsed = new Set();
    const searchInput = document.getElementById('suitePickerSearch');
    if (searchInput) searchInput.value = '';
    renderSuitePicker();
    state.modal.show();
    refreshTexts();
  }

  // In-modal script picker: directory-grouped, checkable, searchable.
  function renderSuitePicker() {
    const container = document.getElementById('suitePickerList');
    if (!container) return;
    updateSelectedCount();
    const query = (document.getElementById('suitePickerSearch')?.value || '').trim().toLowerCase();
    const scripts = state.scripts
      .filter((s) => !query || String(s.ref_path || '').toLowerCase().includes(query))
      .slice()
      .sort((a, b) => String(a.ref_path || '').localeCompare(String(b.ref_path || '')));

    if (scripts.length === 0) {
      container.innerHTML = `<div class="text-muted small p-3">${escapeHtml(t('automationHub.suites.pickerEmpty', 'No scripts match'))}</div>`;
      return;
    }

    const groups = new Map();
    for (const s of scripts) {
      const parts = String(s.ref_path || '').split('/');
      parts.pop();
      const dir = parts.join('/') || '/';
      if (!groups.has(dir)) groups.set(dir, []);
      groups.get(dir).push(s);
    }
    // When searching, force every group open so matches are visible.
    container.innerHTML = Array.from(groups.keys()).sort().map((dir) => {
      const items = groups.get(dir);
      const collapsed = !query && state.pickerGroupCollapsed.has(dir);
      const caret = collapsed ? 'fa-chevron-right' : 'fa-chevron-down';
      const selectedInGroup = items.filter((s) => state.selectedScriptIds.has(s.id)).length;
      const header = `
        <div class="automation-group-header" data-pick-group-toggle="${escapeAttr(dir)}" role="button">
          <i class="fas ${caret} automation-group-caret"></i>
          <i class="fas fa-folder text-primary"></i>
          <span class="automation-group-label" title="${escapeAttr(dir)}">${escapeHtml(dir)}</span>
          <span class="badge bg-light text-dark border ms-auto">${selectedInGroup}/${items.length}</span>
        </div>`;
      const body = collapsed ? '' : `<div class="automation-group-body">${items.map((s) => {
        const checked = state.selectedScriptIds.has(s.id) ? 'checked' : '';
        const fileName = String(s.ref_path || '').split('/').pop();
        return `
          <label class="automation-pick-row">
            <input class="form-check-input mt-0" type="checkbox" data-pick-script="${s.id}" ${checked}>
            <span class="text-truncate" title="${escapeAttr(s.ref_path)}">${escapeHtml(fileName)}</span>
            <span class="text-muted small ms-auto">${escapeHtml(s.script_format || 'OTHER')}</span>
          </label>`;
      }).join('')}</div>`;
      return header + body;
    }).join('');
  }

  function togglePickerGroup(dir) {
    if (state.pickerGroupCollapsed.has(dir)) state.pickerGroupCollapsed.delete(dir);
    else state.pickerGroupCollapsed.add(dir);
    renderSuitePicker();
  }

  async function saveSuite() {
    const nameInput = document.getElementById('suiteName');
    if (!nameInput) return;
    const name = nameInput.value.trim();
    const scriptIds = Array.from(state.selectedScriptIds);
    if (!name) {
      showError(t('automationHub.suites.nameRequired', 'Suite name is required'));
      nameInput.focus();
      return;
    }
    if (scriptIds.length === 0) {
      showError(t('automationHub.suites.scriptsRequired', 'Pick at least one script for the suite'));
      return;
    }

    const groupId = document.getElementById('suiteId').value;
    const payload = {
      name,
      description: document.getElementById('suiteDescription').value.trim() || null,
      script_ids: scriptIds
    };

    try {
      const saved = await apiFetch(
        groupId
          ? `/api/teams/${state.teamId}/automation-script-groups/${groupId}`
          : `/api/teams/${state.teamId}/automation-script-groups`,
        {
          method: groupId ? 'PUT' : 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        }
      );
      if (state.modal) state.modal.hide();
      showSuccess(t('automationHub.suites.saveDone', 'Suite saved'));
      // Surface backend notices (e.g. a rename that discarded the suite's old
      // Allure report) so the user knows the side effect happened.
      (saved && Array.isArray(saved.warnings) ? saved.warnings : []).forEach(showWarning);
      await loadAll();
    } catch (error) {
      showError(error.message || t('automationHub.suites.saveFailed', 'Failed to save suite'));
    }
  }

  async function deleteSuite(group) {
    const confirmed = await AppUtils.showConfirm(t('automationHub.suites.deleteConfirm', 'Delete this suite?'));
    if (!confirmed) return;
    try {
      await apiFetch(`/api/teams/${state.teamId}/automation-script-groups/${group.id}`, { method: 'DELETE' });
      showSuccess(t('automationHub.suites.deleteDone', 'Suite deleted'));
      await loadAll();
    } catch (error) {
      showError(error.message || t('automationHub.suites.deleteFailed', 'Failed to delete suite'));
    }
  }

  function runSuite(group) {
    // Deprecated stub: the historical "Run suite" trigger has been removed
    // (move-automation-execution-to-test-run-set). Retained so older cached
    // bundles that still emit 'automation:run-suite' events do not throw.
    document.dispatchEvent(new CustomEvent('automation:run-suite-deprecated', { detail: { group } }));
  }

  function runScript(scriptId) {
    // Deprecated stub — see runSuite() above.
    const script = state.scripts.find((item) => item.id === scriptId);
    if (!script) return;
    document.dispatchEvent(new CustomEvent('automation:run-script-deprecated', { detail: { script } }));
  }

  function selectedScripts() {
    return state.scripts.filter((script) => state.selectedScriptIds.has(script.id));
  }

  function updateSelectedCount() {
    const el = document.getElementById('suiteModalSelectedCount');
    if (el) el.textContent = String(state.selectedScriptIds.size);
  }

  function setLoading(isLoading) {
    const scriptLoading = document.getElementById('scriptLoading');
    const suiteLoading = document.getElementById('suiteLoading');
    if (scriptLoading) scriptLoading.classList.toggle('d-none', !isLoading);
    if (suiteLoading) suiteLoading.classList.toggle('d-none', !isLoading);
  }

  function showNoTeam() {
    const noTeam = document.getElementById('automation-no-team');
    const automationContent = document.getElementById('automation-content');
    if (noTeam) noTeam.classList.remove('d-none');
    if (automationContent) automationContent.classList.add('d-none');
  }

  function showTeamBadge() {
    const team = window.AppUtils && window.AppUtils.getCurrentTeam ? window.AppUtils.getCurrentTeam() : null;
    if (!team || !team.name) return;
    const badge = document.getElementById('team-name-badge');
    const text = document.getElementById('team-name-text');
    if (badge && text) {
      text.textContent = team.name;
      badge.classList.remove('d-none');
    }
  }

  function applyTeamLinks() {
    const suffix = `?team_id=${encodeURIComponent(state.teamId)}`;
    const providerSettingsLink = document.getElementById('providerSettingsLink');
    const settingsProviderLink = document.getElementById('settingsProviderLink');
    const webhookSettingsLink = document.getElementById('webhookSettingsLink');
    const settingsWebhookLink = document.getElementById('settingsWebhookLink');
    if (providerSettingsLink) providerSettingsLink.href = `/automation-provider-settings${suffix}`;
    if (settingsProviderLink) settingsProviderLink.href = `/automation-provider-settings${suffix}`;
    if (webhookSettingsLink) webhookSettingsLink.href = `/automation-webhook-config${suffix}`;
    if (settingsWebhookLink) settingsWebhookLink.href = `/automation-webhook-config${suffix}`;

    // Git 來源設定含加密 GitHub PAT / SSH key；只對 Admin 以上顯示。
    applyProviderSettingsVisibility();
  }

  async function applyProviderSettingsVisibility() {
    try {
      if (!window.AuthClient) return;
      const resp = await window.AuthClient.fetch('/api/auth/me');
      if (!resp.ok) {
        hideProviderSettingsEntries();
        return;
      }
      const me = await resp.json().catch(() => ({}));
      const role = String((me && me.role) || '').toLowerCase();
      if (!['admin', 'super_admin'].includes(role)) {
        hideProviderSettingsEntries();
      }
    } catch (_e) {
      // Fail closed — hide on any error.
      hideProviderSettingsEntries();
    }
  }

  function hideProviderSettingsEntries() {
    ['providerSettingsLink', 'settingsProviderLink'].forEach((id) => {
      const el = document.getElementById(id);
      if (el) el.classList.add('d-none');
    });
    // If the settings tab card is now empty, hide its wrapper too. Best-effort:
    // we only hide the link, leaving the card title visible can confuse users,
    // so collapse the whole card if it exists.
    const card = document.querySelector('.automation-settings-dashboard .card.automation-panel');
    // Don't aggressively hide the whole settings card; non-admin roles just
    // won't see the action button to navigate. The card may still show stats.
    void card;
  }

  async function apiFetch(url, options) {
    const response = await window.AuthClient.fetch(url, options || {});
    if (response.status === 204) return null;
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(extractApiErrorMessage(data, response));
    }
    return data;
  }

  function extractApiErrorMessage(data, response) {
    if (Array.isArray(data && data.detail) && data.detail.length) {
      return data.detail.map((entry) => {
        const loc = Array.isArray(entry && entry.loc) ? entry.loc.filter((p) => p !== 'body') : [];
        const field = loc.join('.');
        const msg = (entry && entry.msg) || '';
        return field ? `${field}: ${msg}` : msg;
      }).filter(Boolean).join('; ');
    }
    if (data && data.detail && typeof data.detail === 'object') {
      return data.detail.message || data.detail.detail || data.detail.code || (response && response.statusText) || 'Request failed';
    }
    if (typeof (data && data.detail) === 'string') return data.detail;
    if (typeof (data && data.message) === 'string') return data.message;
    return (response && response.statusText) || 'Request failed';
  }

  function resolveTeamId() {
    const params = new URLSearchParams(window.location.search);
    const queryTeamId = params.get('team_id');
    if (queryTeamId) return queryTeamId;
    if (window.AppUtils && window.AppUtils.getCurrentTeamId) return window.AppUtils.getCurrentTeamId();
    const stored = localStorage.getItem('currentTeam');
    if (!stored) return null;
    try {
      const team = JSON.parse(stored);
      return team && team.id ? String(team.id) : null;
    } catch (error) {
      return null;
    }
  }

  function refreshTexts(root) {
    if (window.i18n) window.i18n.retranslate(root || document);
  }

  function showSuccess(message) {
    if (window.AppUtils) window.AppUtils.showSuccess(message);
  }

  function showError(message) {
    if (window.AppUtils) window.AppUtils.showError(message);
  }

  function showWarning(message) {
    if (window.AppUtils && window.AppUtils.showWarning) window.AppUtils.showWarning(message);
  }

  function t(key, fallback) {
    return window.i18n && window.i18n.t ? window.i18n.t(key, {}, fallback) : fallback;
  }

  function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>"']/g, (char) => ({
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#39;'
    }[char]));
  }

  function escapeAttr(value) {
    return escapeHtml(value);
  }

  // Escape `text`, wrapping case-insensitive matches of the current search
  // query in <mark>. Scans the raw string so escaping stays correct.
  function highlightMatch(text, query) {
    const str = String(text ?? '');
    const q = query || state.searchQuery;
    if (!q) return escapeHtml(str);
    const lower = str.toLowerCase();
    let out = '';
    let i = 0;
    while (i < str.length) {
      const idx = lower.indexOf(q, i);
      if (idx === -1) {
        out += escapeHtml(str.slice(i));
        break;
      }
      out += escapeHtml(str.slice(i, idx));
      out += `<mark class="automation-hl">${escapeHtml(str.slice(idx, idx + q.length))}</mark>`;
      i = idx + q.length;
    }
    return out;
  }

})();
