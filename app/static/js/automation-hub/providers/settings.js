(function () {
  const state = {
    teamId: null,
    providerTypes: [],
    providers: [],
    editingProvider: null,
    modal: null,
    healthModal: null
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
    bindEvents();

    if (!state.teamId) {
      showNoTeam();
      return;
    }

    const team = window.AppUtils && window.AppUtils.getCurrentTeam ? window.AppUtils.getCurrentTeam() : null;
    if (team && team.name) {
      const badge = document.getElementById('team-name-badge');
      const text = document.getElementById('team-name-text');
      if (badge && text) {
        text.textContent = team.name;
        badge.classList.remove('d-none');
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
    document.getElementById('providerType').addEventListener('change', () => renderSchemaFields());
    document.getElementById('saveProviderBtn').addEventListener('click', saveProvider);
    const testBtn = document.getElementById('testProviderConfigBtn');
    if (testBtn) testBtn.addEventListener('click', testProviderConfig);
    const emptyAdd = document.getElementById('emptyStateAddProviderBtn');
    if (emptyAdd) emptyAdd.addEventListener('click', () => openProviderModal());

    // Delegated: the discover-runners button lives inside dynamically rendered
    // config fields (only for CI providers' default_runner_label). It is a
    // Bootstrap dropdown toggle — opening the dropdown triggers a fresh fetch
    // and populates menu items in-place, so the form layout never shifts.
    const configFields = document.getElementById('configFields');
    if (configFields) {
      configFields.addEventListener('show.bs.dropdown', (event) => {
        const trigger = event.target;
        if (trigger && (trigger.id === 'discoverRunnersBtn' || (trigger.closest && trigger.closest('#discoverRunnersBtn')))) {
          discoverRunners();
        }
      });
      // Switching Jenkins auth_method changes which credential fields apply,
      // so re-render the credentials block to hide/show the right ones.
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
      renderProviderTypeOptions();
      renderProviders();
    } catch (error) {
      showError(error.message || t('automationHub.providers.loadFailed', 'Failed to load providers'));
    } finally {
      setLoading(false);
      refreshTexts();
    }
  }

  // Canonical mapping — this page is now Git 來源設定 (storage-only).
  // CI / Result providers moved to the org-level system router and are
  // managed from team-management's 同步組織架構 modal.
  // Existing rows with non-canonical types still load but are not offered for new providers.
  const CANONICAL_TYPES = ['storage:github'];

  function renderProviderTypeOptions(extraType) {
    const select = document.getElementById('providerType');
    const seen = new Set();
    const ordered = CANONICAL_TYPES.slice();
    if (extraType && !ordered.includes(extraType)) {
      // When editing a provider with a non-canonical type (e.g. storage:local_git),
      // expose it as a one-off option so the dropdown matches the stored value.
      ordered.push(extraType);
    }
    select.innerHTML = ordered
      .filter((pt) => state.providerTypes.some((info) => info.provider_type === pt))
      .filter((pt) => {
        if (seen.has(pt)) return false;
        seen.add(pt);
        return true;
      })
      .map((pt) => `<option value="${escapeHtml(pt)}">${escapeHtml(slotOptionLabel(pt))}</option>`)
      .join('');
  }

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
      });
    });
  }

  function openProviderModal(provider) {
    state.editingProvider = provider || null;
    document.getElementById('providerModalTitle').textContent = provider
      ? t('automationHub.providers.editTitle', 'Edit Provider')
      : t('automationHub.providers.createTitle', 'Add Provider');
    document.getElementById('providerId').value = provider ? provider.id : '';
    document.getElementById('providerName').value = provider ? provider.name : '';
    document.getElementById('providerActive').checked = provider ? provider.is_active : true;
    document.getElementById('clearCredentials').checked = false;
    document.getElementById('clearCredentialsWrap').classList.toggle('d-none', !provider);

    const providerType = provider ? provider.provider_type : CANONICAL_TYPES[0];
    // Re-render the slot dropdown so it includes the editing row's legacy type
    // (if any) before we try to set the value.
    renderProviderTypeOptions(provider ? provider.provider_type : null);
    document.getElementById('providerType').value = providerType || '';
    renderSchemaFields(provider);
    state.modal.show();
    refreshTexts();
  }

  function renderSchemaFields(provider) {
    const typeInfo = currentTypeInfo();
    if (!typeInfo) return;
    renderFieldGroup(document.getElementById('configFields'), typeInfo.config_schema, provider ? provider.config : {}, false);
    renderFieldGroup(document.getElementById('credentialFields'), typeInfo.credential_schema, {}, true);
  }

  function renderFieldGroup(container, schema, values, isCredential) {
    const properties = schema.properties || {};
    const required = new Set(schema.required || []);
    const entries = Object.entries(properties);
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
    // Jenkins-specific: hide credential fields that don't apply to the
    // currently selected auth_method. api_token mode uses username + api_token
    // (no job_token); trigger_token mode uses only job_token. Skipping the
    // unused ones avoids leading users to fill noise that the provider ignores.
    if (isCredential && shouldHideForAuthMethod(name)) return '';

    const id = `${propertyGroup(property)}-${name}`;
    const label = property.title || name;
    const description = property.description || '';
    const type = resolveSchemaType(property);
    const isSecret = /token|password|secret|private_key|pat|api_key/i.test(name);
    let currentValue = value === undefined || value === null ? (property.default ?? '') : value;
    // Substitute `{team_name}` placeholders coming from schema defaults
    // (e.g. Jenkins view_name_template = "TCRT_{team_name}") so the form
    // pre-fills "TCRT_ARD" for team ARD. Editing existing rows shows the
    // stored value as-is unless the user re-introduces the placeholder.
    if (typeof currentValue === 'string' && currentValue.includes('{team_name}')) {
      const teamName = getCurrentTeamName();
      if (teamName) currentValue = currentValue.split('{team_name}').join(teamName);
    }
    const typeInfo = currentTypeInfo();
    const isCiProvider = typeInfo && typeof typeInfo.provider_type === 'string' && typeInfo.provider_type.startsWith('ci:');
    const isRunnerLabelField = name === 'default_runner_label' && isCiProvider && propertyGroup(property) === 'config';
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
    } else if (isRunnerLabelField) {
      // Special-case: default_runner_label on CI providers. The Discover button
      // is a Bootstrap dropdown toggle — clicking it fetches live runners and
      // shows them as overlay menu items, so picking one fills the input
      // without ever changing the form's layout.
      const discoverLabel = escapeHtml(t('automationHub.providers.discoverRunners', 'Discover runners'));
      const initialHint = escapeHtml(t('automationHub.providers.discoverHint', 'Click to fetch runners'));
      control = `
        <div class="input-group">
          <input id="${escapeAttr(id)}" type="text" class="form-control"
                 value="${escapeAttr(currentValue)}"
                 autocomplete="off"
                 data-schema-field="${escapeAttr(name)}"
                 data-schema-type="${escapeAttr(type)}"
                 ${required && !isSecret ? 'required' : ''}>
          <button type="button" class="btn btn-secondary dropdown-toggle" id="discoverRunnersBtn"
                  data-bs-toggle="dropdown" aria-expanded="false" title="${escapeAttr(discoverLabel)}">
            <i class="fas fa-search me-1"></i><span data-i18n="automationHub.providers.discoverRunners">Discover</span>
          </button>
          <ul class="dropdown-menu dropdown-menu-end provider-runner-dropdown" id="discoveredRunnersMenu" aria-labelledby="discoverRunnersBtn">
            <li><span class="dropdown-item-text text-muted small" id="discoverRunnersStatus">${initialHint}</span></li>
          </ul>
        </div>`;
    } else {
      const inputType = type === 'integer' || type === 'number' ? 'number' : (isSecret ? 'password' : 'text');
      control = `<input id="${escapeAttr(id)}" type="${inputType}" class="form-control" value="${escapeAttr(currentValue)}" data-schema-field="${escapeAttr(name)}" data-schema-type="${escapeAttr(type)}" ${required && !isSecret ? 'required' : ''}>`;
    }

    const colClass = isRunnerLabelField ? 'col-12' : 'col-md-6';
    return `
      <div class="${colClass}" data-field-name="${escapeAttr(name)}">
        ${type === 'boolean' ? control : `<label for="${escapeAttr(id)}" class="form-label">${escapeHtml(label)}${required ? ' *' : ''}${helpIcon}</label>${control}`}
      </div>`;
  }

  async function discoverRunners() {
    const typeInfo = currentTypeInfo();
    if (!typeInfo) return;
    const status = document.getElementById('discoverRunnersStatus');
    const menu = document.getElementById('discoveredRunnersMenu');
    if (!menu) return;

    const payload = {
      provider_slot: typeInfo.provider_slot,
      provider_type: typeInfo.provider_type,
      name: document.getElementById('providerName').value.trim() || 'discover-probe',
      config: collectFieldGroup(document.getElementById('configFields')),
      credentials: collectFieldGroup(document.getElementById('credentialFields'), true),
      is_active: true,
    };

    clearRunnerMenuItems();
    if (status) {
      status.textContent = t('automationHub.providers.discovering', 'Discovering runners...');
      status.classList.remove('text-success', 'text-danger');
      status.classList.add('text-muted');
    }
    try {
      const data = await apiFetch(
        `/api/teams/${state.teamId}/automation-providers/discover-runners`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        }
      );
      const labels = Array.isArray(data && data.labels) ? data.labels : [];
      renderRunnerMenu(labels);
      if (status) {
        if (data && data.error) {
          status.textContent = `${t('automationHub.providers.discoverFailed', 'Discovery failed')}: ${data.error}`;
          status.classList.remove('text-muted', 'text-success');
          status.classList.add('text-danger');
        } else if (!labels.length) {
          status.textContent = t('automationHub.providers.discoverEmpty', 'No runners returned.');
          status.classList.remove('text-success', 'text-danger');
          status.classList.add('text-muted');
        } else {
          status.textContent = `${t('automationHub.providers.discoverFound', 'Found')} ${labels.length} ${t('automationHub.providers.discoverFoundSuffix', 'labels — pick one to use it.')}`;
          status.classList.remove('text-muted', 'text-danger');
          status.classList.add('text-success');
        }
      }
    } catch (error) {
      renderRunnerMenu([]);
      if (status) {
        status.textContent = error.message || t('automationHub.providers.discoverFailed', 'Discovery failed');
        status.classList.remove('text-muted', 'text-success');
        status.classList.add('text-danger');
      }
    }
  }

  function clearRunnerMenuItems() {
    const menu = document.getElementById('discoveredRunnersMenu');
    if (!menu) return;
    // Keep only the first <li> (the status header); strip stale results.
    while (menu.children.length > 1) {
      menu.removeChild(menu.lastElementChild);
    }
  }

  function renderRunnerMenu(labels) {
    clearRunnerMenuItems();
    const menu = document.getElementById('discoveredRunnersMenu');
    if (!menu || !labels || !labels.length) return;

    const currentValue = (document.getElementById('config-default_runner_label') || {}).value || '';

    const divider = document.createElement('li');
    divider.innerHTML = '<hr class="dropdown-divider">';
    menu.appendChild(divider);

    labels.forEach((label) => {
      const li = document.createElement('li');
      const isSelected = label === currentValue;
      const activeCls = isSelected ? ' active' : '';
      const description = runnerLabelDescription(label);
      const icon = isAnyRunnerLabel(label) ? 'fa-globe' : 'fa-server';
      const descriptionHtml = description
        ? `<small class="text-muted ms-1">· ${escapeHtml(description)}</small>`
        : '';
      li.innerHTML = `
        <button type="button" class="dropdown-item d-flex align-items-center gap-2${activeCls}" data-runner-chip="${escapeAttr(label)}">
          <i class="fas ${icon} text-muted"></i>
          <span class="flex-grow-1 text-truncate">${escapeHtml(label)}${descriptionHtml}</span>
          ${isSelected ? '<i class="fas fa-check text-success"></i>' : ''}
        </button>`;
      menu.appendChild(li);
    });

    menu.querySelectorAll('[data-runner-chip]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const value = btn.dataset.runnerChip;
        const input = document.getElementById('config-default_runner_label');
        if (!input) return;
        input.value = value;
        input.dispatchEvent(new Event('input', { bubbles: true }));
        // Bootstrap auto-closes the dropdown after a dropdown-item click.
      });
    });
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
    const payload = {
      provider_slot: typeInfo.provider_slot,
      provider_type: document.getElementById('providerType').value,
      name,
      config: collectFieldGroup(document.getElementById('configFields')),
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

    const payload = {
      provider_slot: typeInfo.provider_slot,
      provider_type: typeInfo.provider_type,
      name,
      config: collectFieldGroup(document.getElementById('configFields')),
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

  function providerTypeLabel(providerType, fallback) {
    const key = providerType.replace(':', '.');
    return t(`automationHub.providers.types.${key}`, fallback);
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

  // Caller passes isCredential separately (see renderSchemaField), so this
  // function only needs the field name + current Jenkins auth_method.
  function shouldHideForAuthMethod(name) {
    const typeInfo = currentTypeInfo();
    if (!typeInfo || typeInfo.provider_type !== 'ci:jenkins') return false;
    const authMethod = getCurrentAuthMethod();
    if (authMethod === 'api_token' && name === 'job_token') return true;
    if (authMethod === 'trigger_token' && (name === 'username' || name === 'api_token')) return true;
    return false;
  }

  function getCurrentAuthMethod() {
    const el = document.getElementById('config-auth_method');
    if (el && el.value) return el.value;
    // Pre-render fallback: Jenkins config schema default.
    return 'api_token';
  }

  // Reserved Jenkins "any" label means "use any available agent". The stored
  // value MUST stay literally "any" (Jenkins parses it), so we only translate
  // the description shown next to it in the dropdown — the chip's value is
  // unchanged.
  function isAnyRunnerLabel(label) {
    return String(label || '').trim().toLowerCase() === 'any';
  }

  function runnerLabelDescription(label) {
    if (isAnyRunnerLabel(label)) {
      return t('automationHub.providers.runnerAny', 'Any available agent');
    }
    return '';
  }

  function getCurrentTeamName() {
    if (window.AppUtils && window.AppUtils.getCurrentTeam) {
      const team = window.AppUtils.getCurrentTeam();
      if (team && team.name) return String(team.name);
    }
    return '';
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
