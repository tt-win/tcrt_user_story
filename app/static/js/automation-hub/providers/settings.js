(function () {
  const state = {
    teamId: null,
    providerTypes: [],
    providers: [],
    modal: null,
    healthModal: null,
    addRepoModal: null
  };

  document.addEventListener('DOMContentLoaded', init);
  document.addEventListener('i18nReady', refreshTexts);
  document.addEventListener('languageChanged', refreshTexts);
  window.addEventListener('pageshow', refreshTexts);

  function init() {
    state.teamId = resolveTeamId();
    state.modal = new bootstrap.Modal(document.getElementById('providerModal'));
    const healthModalEl = document.getElementById('providerHealthModal');
    if (healthModalEl) state.healthModal = new bootstrap.Modal(healthModalEl);
    const addRepoModalEl = document.getElementById('addRepoModal');
    if (addRepoModalEl) state.addRepoModal = new bootstrap.Modal(addRepoModalEl);
    bindEvents();

    if (!state.teamId) {
      showNoTeam();
      return;
    }

    if (window.TeamNav) {
      window.TeamNav.refresh();
    } else {
      const team = window.AppUtils && window.AppUtils.getCurrentTeam ? window.AppUtils.getCurrentTeam() : null;
      if (team && team.name) {
        const wrapper = document.getElementById('team-nav-badge-wrapper');
        const text = document.getElementById('team-name-text');
        if (wrapper && text) {
          text.textContent = team.name;
          wrapper.classList.remove('d-none');
        }
      }
    }

    applyTeamLinks();
    loadAll();
  }

  function applyTeamLinks() {
    const suffix = `?team_id=${encodeURIComponent(state.teamId)}`;
    const hubLink = document.getElementById('automationHubLink');
    if (hubLink) hubLink.href = `/automation-hub${suffix}`;
  }

  function bindEvents() {
    document.getElementById('addProviderBtn').addEventListener('click', () => openProviderModal());
    document.getElementById('refreshProvidersBtn').addEventListener('click', loadAll);
    document.getElementById('saveProviderBtn').addEventListener('click', saveProvider);
    const testBtn = document.getElementById('testProviderConfigBtn');
    if (testBtn) testBtn.addEventListener('click', testProviderConfig);
    const emptyAdd = document.getElementById('emptyStateAddProviderBtn');
    if (emptyAdd) emptyAdd.addEventListener('click', () => openProviderModal());
    const addRepoSave = document.getElementById('addRepoSaveBtn');
    if (addRepoSave) addRepoSave.addEventListener('click', submitAddRepo);

    const configFields = document.getElementById('configFields');
    if (configFields) {
      // Switching GitHub auth_method (pat ↔ github_app) changes which
      // credential fields apply, so re-render the credentials block.
      configFields.addEventListener('change', (event) => {
        if (event.target && event.target.id === 'config-auth_method') {
          const typeInfo = currentTypeInfo();
          if (typeInfo) {
            renderFieldGroup(document.getElementById('credentialFields'), typeInfo.credential_schema, {}, true);
            refreshTexts();
          }
        }
      });
    }
  }

  async function loadAll() {
    setLoading(true);
    try {
      const [types, providers] = await Promise.all([
        apiFetch(`/api/teams/${state.teamId}/automation-providers/types`),
        apiFetch(`/api/teams/${state.teamId}/automation-providers`)
      ]);
      state.providerTypes = types;
      state.providers = providers;
      renderProviders();
    } catch (error) {
      showError(error.message || t('automationHub.providers.loadFailed', 'Failed to load providers'));
    } finally {
      setLoading(false);
      refreshTexts();
    }
  }

  // This page is Git 來源設定 (storage-only) — CI / Result providers moved to
  // the org-level system router (team-management's 組織與系統設定 modal). New
  // providers are always GitHub; editing a legacy row (e.g. storage:local_git)
  // keeps its stored type via the hidden #providerType input.
  const DEFAULT_PROVIDER_TYPE = 'storage:github';

  function slotOptionLabel(providerType) {
    const slot = providerType.split(':')[0];
    const slotName = {
      storage: t('automationHub.settings.slotStorage', 'Storage'),
      ci: t('automationHub.settings.slotCi', 'CI'),
      result: t('automationHub.settings.slotResult', 'Result'),
    }[slot] || slot;
    return slotName;
  }

  // Icon + colour pair per slot. Used in the provider table to replace the
  // colored-text badge with a more glanceable visual cue. Icons are chosen
  // for shape distinction: database (storage), gears (CI build pipeline),
  // chart-bar (result report).
  function slotIcon(providerType) {
    const slot = String(providerType || '').split(':')[0];
    return ({
      storage: { icon: 'fa-database', color: 'text-info' },
      ci: { icon: 'fa-cogs', color: 'text-warning' },
      result: { icon: 'fa-chart-bar', color: 'text-success' },
    }[slot]) || { icon: 'fa-puzzle-piece', color: 'text-secondary' };
  }

  function renderSlotSummary() {
    const buckets = { storage: 0, ci: 0, result: 0 };
    for (const p of state.providers) {
      const slot = String(p.provider_slot || '').toLowerCase();
      if (slot in buckets) buckets[slot] += 1;
    }
    const apply = (id, value) => {
      const el = document.getElementById(id);
      if (el) el.textContent = String(value);
    };
    apply('providerSlotStorage', buckets.storage);
    apply('providerSlotCi', buckets.ci);
    apply('providerSlotResult', buckets.result);
  }

  function renderProviders() {
    const rows = document.getElementById('providerRows');
    const emptyState = document.getElementById('empty-state');
    const contentCard = document.getElementById('provider-content');
    document.getElementById('provider-count').textContent = String(state.providers.length);
    const isEmpty = state.providers.length === 0;
    emptyState.classList.toggle('d-none', !isEmpty);
    contentCard.classList.toggle('d-none', isEmpty);
    renderSlotSummary();

    rows.innerHTML = state.providers.map((provider) => {
      const activeBadge = provider.is_active
        ? `<span class="badge bg-success">${escapeHtml(t('automationHub.providers.active', 'Active'))}</span>`
        : `<span class="badge bg-secondary">${escapeHtml(t('automationHub.providers.inactive', 'Inactive'))}</span>`;
      const health = provider.last_health_status
        ? `<span class="badge ${provider.last_health_status === 'OK' ? 'bg-success' : 'bg-warning text-dark'}">${escapeHtml(provider.last_health_status)}</span>`
        : `<span class="text-muted">${escapeHtml(t('common.notSet', 'Not set'))}</span>`;
      const credential = provider.credentials_set
        ? escapeHtml(provider.credentials_fingerprint || t('automationHub.providers.credentialsSet', 'Set'))
        : `<span class="text-muted">${escapeHtml(t('automationHub.providers.noCredentials', 'No credentials'))}</span>`;
      const slotMeta = slotIcon(provider.provider_type);
      const slotLabel = slotOptionLabel(provider.provider_type);
      return `
        <tr>
          <td class="text-center" title="${escapeAttr(slotLabel)}">
            <i class="fas ${slotMeta.icon} ${slotMeta.color} fa-lg" aria-hidden="true"></i>
            <span class="visually-hidden">${escapeHtml(slotLabel)}</span>
          </td>
          <td>
            <div class="fw-semibold">${escapeHtml(provider.name)}</div>
            <div class="text-muted small">${escapeHtml(provider.provider_type)}</div>
          </td>
          <td>${renderRepoCell(provider)}</td>
          <td>${credential}</td>
          <td>${health}</td>
          <td>${activeBadge}</td>
          <td class="text-end provider-actions">
            <button type="button" class="btn btn-info btn-sm me-1" data-action="test" data-provider-id="${provider.id}" title="${escapeAttr(t('automationHub.providers.testConnection', 'Test connection'))}">
              <i class="fas fa-vial"></i>
            </button>
            <button type="button" class="btn btn-secondary btn-sm me-1" data-action="edit" data-provider-id="${provider.id}" title="${escapeAttr(t('common.edit', 'Edit'))}">
              <i class="fas fa-pen"></i>
            </button>
            <button type="button" class="btn btn-danger btn-sm" data-action="delete" data-provider-id="${provider.id}" title="${escapeAttr(t('common.delete', 'Delete'))}">
              <i class="fas fa-trash"></i>
            </button>
          </td>
        </tr>`;
    }).join('');

    rows.querySelectorAll('[data-action]').forEach((button) => {
      button.addEventListener('click', () => {
        const provider = state.providers.find((item) => String(item.id) === button.dataset.providerId);
        if (!provider) return;
        if (button.dataset.action === 'edit') openProviderModal(provider);
        if (button.dataset.action === 'delete') deleteProvider(provider);
        if (button.dataset.action === 'test') testConnection(provider);
        if (button.dataset.action === 'add-repo') openAddRepoModal(provider);
        if (button.dataset.action === 'remove-repo') removeRepo(provider, button.dataset.repoSlug);
      });
    });
  }

  // Repositories belong to a GitHub storage provider and are managed one at a
  // time, right on the row — each add/remove persists immediately (PUT).
  // Rendered as plain text lines (no badges/borders): the remove × stays
  // subtle until the line is hovered; "add" is a quiet link-style button.
  function renderRepoCell(provider) {
    if (provider.provider_type !== 'storage:github') return '<span class="text-muted">—</span>';
    const repos = provider.config && Array.isArray(provider.config.repos) ? provider.config.repos : [];
    const items = repos.map((r) => {
      const slug = `${r.owner}/${r.repo}`;
      const branch = r.default_branch
        ? ` <span class="text-muted">@${escapeHtml(r.default_branch)}</span>`
        : '';
      return `<div class="provider-repo-item">
        <i class="fas fa-code-branch text-muted"></i>
        <span class="text-truncate">${escapeHtml(slug)}${branch}</span>
        <button type="button" class="provider-repo-remove" data-action="remove-repo" data-provider-id="${provider.id}" data-repo-slug="${escapeAttr(slug)}" title="${escapeAttr(t('common.remove', 'Remove'))}" aria-label="${escapeAttr(t('common.remove', 'Remove'))} ${escapeAttr(slug)}"><i class="fas fa-times"></i></button>
      </div>`;
    }).join('');
    const addLabel = escapeHtml(t('automationHub.providers.addRepo', 'Add repository'));
    return `${items}
      <button type="button" class="btn btn-link btn-sm p-0 provider-repo-add" data-action="add-repo" data-provider-id="${provider.id}">
        <i class="fas fa-plus me-1"></i>${addLabel}
      </button>`;
  }

  function openProviderModal(provider) {
    document.getElementById('providerModalTitle').textContent = provider
      ? t('automationHub.providers.editTitle', 'Edit Provider')
      : t('automationHub.providers.createTitle', 'Add Provider');
    document.getElementById('providerId').value = provider ? provider.id : '';
    document.getElementById('providerName').value = provider ? provider.name : '';
    document.getElementById('providerActive').checked = provider ? provider.is_active : true;
    document.getElementById('clearCredentials').checked = false;
    document.getElementById('clearCredentialsWrap').classList.toggle('d-none', !provider);
    document.getElementById('providerType').value = provider ? (provider.provider_type || '') : DEFAULT_PROVIDER_TYPE;
    renderSchemaFields(provider);
    state.modal.show();
    refreshTexts();
  }

  function renderSchemaFields(provider) {
    const typeInfo = currentTypeInfo();
    if (!typeInfo) return;
    // `repos` is managed on the provider row (one at a time), not in this modal.
    renderFieldGroup(document.getElementById('configFields'), typeInfo.config_schema, provider ? provider.config : {}, false, ['repos']);
    renderFieldGroup(document.getElementById('credentialFields'), typeInfo.credential_schema, {}, true);

    // A new GitHub source needs its first repo here (the rest are added from
    // the row). Editing manages repos on the row, so this section is hidden.
    const firstRepo = document.getElementById('firstRepoSection');
    if (firstRepo) {
      const show = !provider && document.getElementById('providerType').value === 'storage:github';
      firstRepo.classList.toggle('d-none', !show);
      if (show) ['firstRepoOwner', 'firstRepoName', 'firstRepoBranch'].forEach((id) => { document.getElementById(id).value = ''; });
    }
  }

  function renderFieldGroup(container, schema, values, isCredential, exclude) {
    const properties = schema.properties || {};
    const skip = new Set(exclude || []);
    const required = new Set(schema.required || []);
    const entries = Object.entries(properties).filter(([name]) => !skip.has(name));
    container.innerHTML = entries.length ? entries.map(([name, property]) => renderSchemaField(name, property, values[name], required.has(name), Boolean(isCredential))).join('') : `
      <div class="col-12 text-muted small">${escapeHtml(t('automationHub.providers.noFields', 'No fields required'))}</div>`;
    initFieldTooltips(container);
  }

  function initFieldTooltips(container) {
    if (!window.bootstrap || !window.bootstrap.Tooltip) return;
    container.querySelectorAll('[data-bs-toggle="tooltip"]').forEach((el) => {
      const existing = window.bootstrap.Tooltip.getInstance(el);
      if (existing) existing.dispose();
      // eslint-disable-next-line no-new
      new window.bootstrap.Tooltip(el);
    });
  }

  function renderSchemaField(name, property, value, required, isCredential) {
    // GitHub credentials differ by auth_method (pat vs github_app); hide the
    // fields that don't apply to the current selection.
    if (isCredential && shouldHideForAuthMethod(name)) return '';

    const id = `${propertyGroup(property)}-${name}`;
    const label = property.title || name;
    const description = property.description || '';
    const type = resolveSchemaType(property);
    const isSecret = /token|password|secret|private_key|pat|api_key/i.test(name);
    const currentValue = value === undefined || value === null ? (property.default ?? '') : value;
    let control = '';

    // `?` icon next to the label — shows the schema description as a
    // Bootstrap tooltip on hover. Skipped when description is empty.
    const helpIcon = description
      ? ` <i class="fas fa-question-circle text-muted ms-1 provider-help-icon" data-bs-toggle="tooltip" data-bs-placement="top" tabindex="0" role="button" aria-label="${escapeAttr(label)} help" title="${escapeAttr(description)}"></i>`
      : '';

    if (property.enum && property.enum.length) {
      control = `<select id="${escapeAttr(id)}" class="form-select" data-schema-field="${escapeAttr(name)}" data-schema-type="${escapeAttr(type)}" ${required ? 'required' : ''}>
        ${property.enum.map((option) => `<option value="${escapeAttr(option)}" ${option === currentValue ? 'selected' : ''}>${escapeHtml(option)}</option>`).join('')}
      </select>`;
    } else if (type === 'boolean') {
      control = `<div class="form-check mt-2">
        <input id="${escapeAttr(id)}" class="form-check-input" type="checkbox" data-schema-field="${escapeAttr(name)}" data-schema-type="boolean" ${currentValue ? 'checked' : ''}>
        <label for="${escapeAttr(id)}" class="form-check-label">${escapeHtml(label)}${helpIcon}</label>
      </div>`;
    } else if (/private_key|pem/i.test(name)) {
      control = `<textarea id="${escapeAttr(id)}" class="form-control" rows="4" data-schema-field="${escapeAttr(name)}" data-schema-type="string" ${required ? 'required' : ''}>${escapeHtml(currentValue)}</textarea>`;
    } else {
      const inputType = type === 'integer' || type === 'number' ? 'number' : (isSecret ? 'password' : 'text');
      control = `<input id="${escapeAttr(id)}" type="${inputType}" class="form-control" value="${escapeAttr(currentValue)}" data-schema-field="${escapeAttr(name)}" data-schema-type="${escapeAttr(type)}" ${required && !isSecret ? 'required' : ''}>`;
    }

    return `
      <div class="col-md-6" data-field-name="${escapeAttr(name)}">
        ${type === 'boolean' ? control : `<label for="${escapeAttr(id)}" class="form-label">${escapeHtml(label)}${required ? ' *' : ''}${helpIcon}</label>${control}`}
      </div>`;
  }

  async function saveProvider() {
    const typeInfo = currentTypeInfo();
    if (!typeInfo) return;
    const providerId = document.getElementById('providerId').value;
    const nameInput = document.getElementById('providerName');
    const name = nameInput.value.trim();
    if (!name) {
      showError(t('automationHub.providers.nameRequired', 'Name is required'));
      nameInput.focus();
      return;
    }
    const providerType = document.getElementById('providerType').value;
    const config = buildModalConfig(providerType, providerId);
    if (config === null) return;

    const payload = {
      provider_slot: typeInfo.provider_slot,
      provider_type: providerType,
      name,
      config,
      credentials: collectFieldGroup(document.getElementById('credentialFields'), true),
      is_active: document.getElementById('providerActive').checked
    };

    if (providerId) {
      payload.clear_credentials = document.getElementById('clearCredentials').checked;
      if (Object.keys(payload.credentials).length === 0) delete payload.credentials;
    }

    try {
      await apiFetch(
        providerId
          ? `/api/teams/${state.teamId}/automation-providers/${providerId}`
          : `/api/teams/${state.teamId}/automation-providers`,
        {
          method: providerId ? 'PUT' : 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        }
      );
      state.modal.hide();
      showSuccess(t('automationHub.providers.saveDone', 'Provider saved'));
      await loadAll();
    } catch (error) {
      showError(error.message || t('automationHub.providers.saveFailed', 'Failed to save provider'));
    }
  }

  // Build the full provider config from the modal. `repos` isn't among the
  // rendered config fields (managed on the row): on create it's seeded from
  // the First repository section; on edit the rendered fields are overlaid
  // onto the stored config so repos and non-rendered keys (e.g. smart_scan)
  // survive a full-config replace. Returns null (after showing an error) when
  // the first repo is required but missing. Shared by Save and Test connection.
  function buildModalConfig(providerType, providerId) {
    const config = collectFieldGroup(document.getElementById('configFields'));
    if (providerType === 'storage:github') {
      if (providerId) {
        const existing = state.providers.find((p) => String(p.id) === String(providerId));
        const stored = existing && existing.config ? existing.config : {};
        Object.keys(stored).forEach((key) => { if (!(key in config)) config[key] = stored[key]; });
      } else {
        const first = readRepoInputs('firstRepo');
        if (!first) {
          showError(t('automationHub.providers.repoRequired', 'Owner and repository are required'));
          return null;
        }
        config.repos = [first];
      }
      delete config.owner;
      delete config.repo;
    }
    return config;
  }

  function collectFieldGroup(container, skipEmpty) {
    const result = {};
    container.querySelectorAll('[data-schema-field]').forEach((input) => {
      const name = input.dataset.schemaField;
      const type = input.dataset.schemaType;
      let value = type === 'boolean' ? input.checked : input.value;
      if (type === 'integer') value = value === '' ? null : Number.parseInt(value, 10);
      if (type === 'number') value = value === '' ? null : Number.parseFloat(value);
      if (skipEmpty && (value === '' || value === null)) return;
      result[name] = value;
    });
    return result;
  }

  async function deleteProvider(provider) {
    const confirmed = await AppUtils.showConfirm(t('automationHub.providers.deleteConfirm', 'Delete this provider?'));
    if (!confirmed) return;
    try {
      await apiFetch(`/api/teams/${state.teamId}/automation-providers/${provider.id}`, { method: 'DELETE' });
      showSuccess(t('automationHub.providers.deleteDone', 'Provider deleted'));
      await loadAll();
    } catch (error) {
      showError(error.message || t('automationHub.providers.deleteFailed', 'Failed to delete provider'));
    }
  }

  function readRepoInputs(prefix) {
    const owner = (document.getElementById(`${prefix}Owner`).value || '').trim();
    const repo = (document.getElementById(`${prefix}Name`).value || '').trim();
    const branch = (document.getElementById(`${prefix}Branch`).value || '').trim();
    if (!owner || !repo) return null;
    const entry = { owner, repo };
    if (branch) entry.default_branch = branch;
    return entry;
  }

  function openAddRepoModal(provider) {
    document.getElementById('addRepoProviderId').value = provider.id;
    ['addRepoOwner', 'addRepoName', 'addRepoBranch'].forEach((id) => { document.getElementById(id).value = ''; });
    if (state.addRepoModal) state.addRepoModal.show();
  }

  async function submitAddRepo() {
    const providerId = document.getElementById('addRepoProviderId').value;
    const provider = state.providers.find((p) => String(p.id) === String(providerId));
    if (!provider) return;
    const entry = readRepoInputs('addRepo');
    if (!entry) {
      showError(t('automationHub.providers.repoRequired', 'Owner and repository are required'));
      return;
    }
    const slug = `${entry.owner}/${entry.repo}`;
    const repos = (provider.config && Array.isArray(provider.config.repos) ? provider.config.repos : []).slice();
    if (repos.some((r) => `${r.owner}/${r.repo}` === slug)) {
      showError(t('automationHub.providers.repoDuplicate', 'This repository is already added'));
      return;
    }
    repos.push(entry);
    if (await putProviderRepos(provider, repos)) {
      if (state.addRepoModal) state.addRepoModal.hide();
    }
  }

  async function removeRepo(provider, slug) {
    const repos = (provider.config && Array.isArray(provider.config.repos) ? provider.config.repos : [])
      .filter((r) => `${r.owner}/${r.repo}` !== slug);
    if (repos.length === 0) {
      showError(t('automationHub.providers.lastRepoBlock', 'A source must keep at least one repository. Delete the provider instead.'));
      return;
    }
    const confirmed = await AppUtils.showConfirm(
      `${t('automationHub.providers.removeRepoConfirm', 'Remove repository')} ${slug}?`
    );
    if (!confirmed) return;
    await putProviderRepos(provider, repos);
  }

  // Persist a repos change via the existing PUT (full-config replace). Omitting
  // credentials keeps the stored PAT. Returns true on success.
  async function putProviderRepos(provider, repos) {
    const config = { ...(provider.config || {}), repos };
    delete config.owner;
    delete config.repo;
    try {
      await apiFetch(`/api/teams/${state.teamId}/automation-providers/${provider.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          provider_type: provider.provider_type,
          name: provider.name,
          config,
          is_active: provider.is_active,
        }),
      });
      showSuccess(t('automationHub.providers.saveDone', 'Provider saved'));
      await loadAll();
      return true;
    } catch (error) {
      showError(error.message || t('automationHub.providers.saveFailed', 'Failed to save provider'));
      return false;
    }
  }

  async function testConnection(provider) {
    openHealthModalLoading();
    try {
      const result = await apiFetch(`/api/teams/${state.teamId}/automation-providers/${provider.id}/test-connection`, { method: 'POST' });
      renderHealthResult(result);
      await loadAll();
    } catch (error) {
      renderHealthResult({
        status: 'FAILED',
        message: error.message || t('automationHub.providers.testFailed', 'Connection test failed'),
        details: {},
      });
    }
  }

  async function testProviderConfig() {
    const typeInfo = currentTypeInfo();
    if (!typeInfo) return;
    const editingId = document.getElementById('providerId').value;
    const nameInput = document.getElementById('providerName');
    const name = nameInput.value.trim() || 'test-probe';
    const credentials = collectFieldGroup(document.getElementById('credentialFields'), true);

    // Edit mode + no typed credentials → use the saved-provider endpoint so the
    // stored (encrypted) credentials are used. Avoids "credentials required"
    // errors when the user just wants to re-test an existing provider's URL.
    if (editingId && Object.keys(credentials).length === 0) {
      const saved = state.providers.find((p) => String(p.id) === String(editingId));
      if (saved) {
        return testConnection(saved);
      }
    }

    const config = buildModalConfig(typeInfo.provider_type, editingId);
    if (config === null) return;

    const payload = {
      provider_slot: typeInfo.provider_slot,
      provider_type: typeInfo.provider_type,
      name,
      config,
      credentials,
      is_active: true,
    };

    openHealthModalLoading();
    try {
      const result = await apiFetch(
        `/api/teams/${state.teamId}/automation-providers/test-config`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        }
      );
      renderHealthResult(result);
    } catch (error) {
      renderHealthResult({
        status: 'FAILED',
        message: error.message || t('automationHub.providers.testFailed', 'Connection test failed'),
        details: {},
      });
    }
  }

  function openHealthModalLoading() {
    if (!state.healthModal) return;
    document.getElementById('providerHealthLoading').classList.remove('d-none');
    document.getElementById('providerHealthContent').classList.add('d-none');
    state.healthModal.show();
  }

  function renderHealthResult(result) {
    if (!state.healthModal) return;
    document.getElementById('providerHealthLoading').classList.add('d-none');
    const content = document.getElementById('providerHealthContent');
    content.classList.remove('d-none');

    const status = String(result.status || 'FAILED').toUpperCase();
    const badgeMap = {
      OK: { cls: 'bg-success', icon: 'fa-check-circle', labelKey: 'automationHub.providers.healthStatusOk', labelFallback: 'Connection successful' },
      LIMITED: { cls: 'bg-warning text-dark', icon: 'fa-exclamation-triangle', labelKey: 'automationHub.providers.healthStatusLimited', labelFallback: 'Limited — see details' },
      FAILED: { cls: 'bg-danger', icon: 'fa-times-circle', labelKey: 'automationHub.providers.healthStatusFailed', labelFallback: 'Connection failed' },
    };
    const badgeInfo = badgeMap[status] || badgeMap.FAILED;

    const badge = document.getElementById('providerHealthStatusBadge');
    badge.className = `badge ${badgeInfo.cls}`;
    badge.innerHTML = `<i class="fas ${badgeInfo.icon} me-1"></i>${escapeHtml(status)}`;

    document.getElementById('providerHealthStatusLabel').textContent = t(badgeInfo.labelKey, badgeInfo.labelFallback);
    document.getElementById('providerHealthMessage').textContent = result.message || '';

    const details = result.details || {};
    const warningEl = document.getElementById('providerHealthWarning');
    if (details.warning) {
      warningEl.textContent = details.warning;
      warningEl.classList.remove('d-none');
    } else {
      warningEl.classList.add('d-none');
      warningEl.textContent = '';
    }

    renderHealthDetails(details);
  }

  function renderHealthDetails(details) {
    const wrap = document.getElementById('providerHealthDetailsWrap');
    const dl = document.getElementById('providerHealthDetails');
    const keys = Object.keys(details || {}).filter((k) => k !== 'warning');
    if (!keys.length) {
      wrap.classList.add('d-none');
      dl.innerHTML = '';
      return;
    }
    wrap.classList.remove('d-none');
    dl.innerHTML = keys.map((key) => {
      const value = details[key];
      const rendered = Array.isArray(value)
        ? value.map((v) => escapeHtml(String(v))).join(', ') || '—'
        : escapeHtml(String(value));
      return `
        <dt class="col-sm-5 text-muted text-truncate" title="${escapeAttr(key)}">${escapeHtml(formatHealthDetailKey(key))}</dt>
        <dd class="col-sm-7 mb-1">${rendered}</dd>`;
    }).join('');
  }

  function formatHealthDetailKey(key) {
    return String(key)
      .split('_')
      .filter(Boolean)
      .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
      .join(' ');
  }

  function currentTypeInfo() {
    const value = document.getElementById('providerType').value;
    return state.providerTypes.find((item) => item.provider_type === value);
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
    // Pydantic v2 422 → { detail: [ {loc:[...], msg:"...", type:"..."}, ... ] }
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

  // GitHub storage credentials are split by auth_method: `pat` needs only the
  // PAT field; `github_app` needs app_id / installation_id / private_key_pem.
  // Hiding the unused ones keeps the modal from leading users to fill noise.
  function shouldHideForAuthMethod(name) {
    const typeInfo = currentTypeInfo();
    if (!typeInfo || typeInfo.provider_type !== 'storage:github') return false;
    const authMethod = getCurrentAuthMethod();
    if (authMethod === 'pat') return name !== 'pat';
    if (authMethod === 'github_app') return name === 'pat';
    return false;
  }

  function getCurrentAuthMethod() {
    const el = document.getElementById('config-auth_method');
    if (el && el.value) return el.value;
    // Pre-render fallback: the schema's declared default.
    const typeInfo = currentTypeInfo();
    const prop = typeInfo && typeInfo.config_schema && typeInfo.config_schema.properties
      ? typeInfo.config_schema.properties.auth_method
      : null;
    return (prop && prop.default) || '';
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

  function showNoTeam() {
    document.getElementById('no-team-state').classList.remove('d-none');
    document.getElementById('provider-content').classList.add('d-none');
  }

  function setLoading(isLoading) {
    document.getElementById('loading-state').classList.toggle('d-none', !isLoading);
    if (isLoading) {
      document.getElementById('empty-state').classList.add('d-none');
      document.getElementById('provider-content').classList.add('d-none');
    }
  }

  function refreshTexts() {
    if (window.i18n) window.i18n.retranslate(document);
  }

  function showSuccess(message) {
    if (window.AppUtils) window.AppUtils.showSuccess(message);
  }

  function showError(message) {
    if (window.AppUtils) window.AppUtils.showError(message);
  }

  function t(key, fallback) {
    return window.i18n && window.i18n.t ? window.i18n.t(key, {}, fallback) : fallback;
  }

  function resolveSchemaType(property) {
    if (property.type) return property.type;
    if (Array.isArray(property.anyOf)) {
      const concrete = property.anyOf.find((item) => item.type && item.type !== 'null');
      if (concrete) return concrete.type;
    }
    return 'string';
  }

  function propertyGroup(property) {
    return property.writeOnly ? 'credential' : 'config';
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
})();
