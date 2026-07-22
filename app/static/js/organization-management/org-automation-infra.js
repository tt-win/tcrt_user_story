/*
 * Org Automation Infra tab — manages org-level CI / Result providers.
 *
 * Calls `/api/system/automation-providers/*` (Super Admin gated).
 * Mirrors the per-team git-source-settings UI but with a separate set of
 * DOM ids (orgInfra*) so the two can co-exist if both pages are ever opened
 * in the same window context.
 *
 * Lazy-loads on tab show — initial render of the page does NOT hit
 * the API until the user actually clicks "組織自動化基礎設施" tab.
 *
 * Tab visibility is driven by the same declarative `page=organization`
 * ui-config endpoint used by the other tabs on this page (see
 * organization-management/main.js's applyOrganizationUiVisibility), not by
 * a separate /api/auth/me role check — this keeps the fail-closed default
 * (hidden until confirmed) consistent across all five tabs and matches the
 * `tab-org-automation-infra` component key in config/permissions/ui_capabilities.yaml.
 */
(function () {
  const state = {
    providerTypes: [],
    providers: [],
    editingProvider: null,
    modal: null,
    healthModal: null,
    loaded: false,
  };

  const CANONICAL_TYPES = ['ci:jenkins', 'result:allure'];

  document.addEventListener('DOMContentLoaded', init);

  function init() {
    const tabBtn = document.getElementById('tab-org-automation-infra');
    if (!tabBtn) return;

    // Fail-closed: hidden by default (see template inline style), only
    // revealed once the ui-config response confirms the caller may see it.
    applyTabVisibility(tabBtn);

    // Lazy-load on first tab show
    tabBtn.addEventListener('shown.bs.tab', () => {
      if (!state.loaded) {
        loadAll();
      }
      loadEntryToggle();
    });

    const modalEl = document.getElementById('orgInfraProviderModal');
    if (modalEl) state.modal = new bootstrap.Modal(modalEl);
    const healthEl = document.getElementById('orgInfraProviderHealthModal');
    if (healthEl) state.healthModal = new bootstrap.Modal(healthEl);

    bindEvents();
  }

  async function applyTabVisibility(tabBtn) {
    // Already hidden by default in the template; only call showTab() once
    // the backend confirms permission. Any failure keeps it hidden.
    try {
      if (!window.AuthClient) return;
      const resp = await window.AuthClient.fetch('/api/permissions/ui-config?page=organization');
      if (!resp.ok) return;
      const json = await resp.json().catch(() => ({}));
      const map = (json && json.components) || {};
      if (map['tab-org-automation-infra']) {
        showTab(tabBtn);
      }
    } catch (_e) {
      // Fail closed — stay hidden.
    }
  }

  function showTab(tabBtn) {
    const li = tabBtn.closest('li.nav-item');
    if (li) li.style.display = '';
  }

  function bindEvents() {
    const entryToggle = document.getElementById('automationHubEntryToggle');
    if (entryToggle) {
      entryToggle.addEventListener('change', () => saveEntryToggle(entryToggle.checked));
    }
    const addBtn = document.getElementById('orgInfraAddProviderBtn');
    if (addBtn) addBtn.addEventListener('click', () => openProviderModal());
    const refreshBtn = document.getElementById('orgInfraRefreshBtn');
    if (refreshBtn) refreshBtn.addEventListener('click', loadAll);
    const typeSel = document.getElementById('orgInfraProviderType');
    if (typeSel) typeSel.addEventListener('change', () => renderSchemaFields());
    const saveBtn = document.getElementById('orgInfraSaveProviderBtn');
    if (saveBtn) saveBtn.addEventListener('click', saveProvider);
    const testBtn = document.getElementById('orgInfraTestProviderConfigBtn');
    if (testBtn) testBtn.addEventListener('click', testProviderConfig);

    // Delegated: runner-discovery dropdown lives inside dynamically rendered
    // config fields (only when provider_type is ci:*). The dropdown toggle is
    // Bootstrap-controlled — we just hook show.bs.dropdown to kick off a fresh
    // fetch each time the user opens it.
    const configFields = document.getElementById('orgInfraConfigFields');
    if (configFields) {
      configFields.addEventListener('show.bs.dropdown', (event) => {
        const trigger = event.target;
        if (trigger && (trigger.id === 'orgInfraDiscoverRunnersBtn' || (trigger.closest && trigger.closest('#orgInfraDiscoverRunnersBtn')))) {
          discoverRunners();
        }
      });
    }
  }

  // ─── Automation Hub 入口開關 ───
  async function loadEntryToggle() {
    const toggle = document.getElementById('automationHubEntryToggle');
    if (!toggle) return;
    try {
      const data = await apiFetch('/api/system/automation-hub/settings');
      toggle.checked = !data || data.enabled !== false;
    } catch (_error) {
      // 讀取失敗時保留預設（顯示），非致命。
    }
  }

  async function saveEntryToggle(enabled) {
    const toggle = document.getElementById('automationHubEntryToggle');
    try {
      await apiFetch('/api/system/automation-hub/settings', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled }),
      });
      showSuccess(t('automationHubEntryToggle.saveDone', 'Automation Hub 入口設定已更新'));
      if (window.AppUtils && window.AppUtils.resetAutomationHubEntryEnabledCache) {
        window.AppUtils.resetAutomationHubEntryEnabledCache();
      }
      window.dispatchEvent(new CustomEvent('automationHubEntryToggled', { detail: { enabled } }));
    } catch (error) {
      // 失敗時還原開關狀態，避免 UI 與後端不一致。
      if (toggle) toggle.checked = !enabled;
      showError(error.message || t('automationHubEntryToggle.saveFailed', '更新 Automation Hub 入口設定失敗'));
    }
  }

  async function loadAll() {
    setLoading(true);
    try {
      const [types, providers] = await Promise.all([
        apiFetch('/api/system/automation-providers/types'),
        apiFetch('/api/system/automation-providers'),
      ]);
      state.providerTypes = Array.isArray(types) ? types : [];
      state.providers = Array.isArray(providers) ? providers : [];
      state.loaded = true;
      renderProviderTypeOptions();
      renderProviders();
    } catch (error) {
      showError(error.message || 'Failed to load org-level providers');
    } finally {
      setLoading(false);
      refreshTexts();
    }
  }

  function renderProviderTypeOptions(extraType) {
    const select = document.getElementById('orgInfraProviderType');
    if (!select) return;
    const seen = new Set();
    const ordered = CANONICAL_TYPES.slice();
    if (extraType && !ordered.includes(extraType)) ordered.push(extraType);
    select.innerHTML = ordered
      .filter((pt) => state.providerTypes.some((info) => info.provider_type === pt))
      .filter((pt) => { if (seen.has(pt)) return false; seen.add(pt); return true; })
      .map((pt) => `<option value="${escapeHtml(pt)}">${escapeHtml(slotOptionLabel(pt))}</option>`)
      .join('');
  }

  function slotOptionLabel(providerType) {
    const slot = providerType.split(':')[0];
    return {
      ci: t('automationHub.settings.slotCi', 'CI'),
      result: t('automationHub.settings.slotResult', 'Result'),
    }[slot] || slot;
  }

  function slotIcon(providerType) {
    const slot = String(providerType || '').split(':')[0];
    return ({
      ci: { icon: 'fa-cogs', color: 'text-warning' },
      result: { icon: 'fa-chart-bar', color: 'text-success' },
    }[slot]) || { icon: 'fa-puzzle-piece', color: 'text-secondary' };
  }

  function renderProviders() {
    const rows = document.getElementById('orgInfraProviderRows');
    const empty = document.getElementById('orgInfraEmptyState');
    const content = document.getElementById('orgInfraContent');
    if (!rows) return;
    const isEmpty = state.providers.length === 0;
    empty.classList.toggle('d-none', !isEmpty);
    content.classList.toggle('d-none', isEmpty);

    rows.innerHTML = state.providers.map((provider) => {
      const slotMeta = slotIcon(provider.provider_type);
      const slotLabel = slotOptionLabel(provider.provider_type);
      const activeBadge = provider.is_active
        ? `<span class="badge bg-success">${escapeHtml(t('automationHub.providers.active', 'Active'))}</span>`
        : `<span class="badge bg-secondary">${escapeHtml(t('automationHub.providers.inactive', 'Inactive'))}</span>`;
      const health = provider.last_health_status
        ? `<span class="badge ${provider.last_health_status === 'OK' ? 'bg-success' : 'bg-warning text-dark'}">${escapeHtml(provider.last_health_status)}</span>`
        : `<span class="text-muted">${escapeHtml(t('common.notSet', 'Not set'))}</span>`;
      const credential = provider.credentials_set
        ? escapeHtml(provider.credentials_fingerprint || t('automationHub.providers.credentialsSet', 'Set'))
        : `<span class="text-muted">${escapeHtml(t('automationHub.providers.noCredentials', 'No credentials'))}</span>`;
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
          <td class="text-end">
            <button type="button" class="btn btn-info btn-sm me-1" data-action="test" data-provider-id="${provider.id}" title="${escapeAttr(t('automationHub.providers.testConnection', 'Test connection'))}"><i class="fas fa-vial"></i></button>
            <button type="button" class="btn btn-secondary btn-sm me-1" data-action="edit" data-provider-id="${provider.id}" title="${escapeAttr(t('common.edit', 'Edit'))}"><i class="fas fa-pen"></i></button>
            <button type="button" class="btn btn-danger btn-sm" data-action="delete" data-provider-id="${provider.id}" title="${escapeAttr(t('common.delete', 'Delete'))}"><i class="fas fa-trash"></i></button>
          </td>
        </tr>`;
    }).join('');

    rows.querySelectorAll('[data-action]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const provider = state.providers.find((item) => String(item.id) === btn.dataset.providerId);
        if (!provider) return;
        if (btn.dataset.action === 'edit') openProviderModal(provider);
        if (btn.dataset.action === 'delete') deleteProvider(provider);
        if (btn.dataset.action === 'test') testConnection(provider);
      });
    });
  }

  function openProviderModal(provider) {
    state.editingProvider = provider || null;
    document.getElementById('orgInfraProviderModalTitle').textContent = provider
      ? t('automationHub.providers.editTitle', 'Edit Provider')
      : t('orgAutomationInfra.addProvider', '新增 Provider');
    document.getElementById('orgInfraProviderId').value = provider ? provider.id : '';
    document.getElementById('orgInfraProviderName').value = provider ? provider.name : '';
    document.getElementById('orgInfraProviderActive').checked = provider ? provider.is_active : true;
    document.getElementById('orgInfraClearCredentials').checked = false;
    document.getElementById('orgInfraClearCredentialsWrap').classList.toggle('d-none', !provider);

    const providerType = provider ? provider.provider_type : CANONICAL_TYPES[0];
    renderProviderTypeOptions(provider ? provider.provider_type : null);
    document.getElementById('orgInfraProviderType').value = providerType || '';
    renderSchemaFields(provider);
    state.modal.show();
    refreshTexts();
  }

  function renderSchemaFields(provider) {
    const typeInfo = currentTypeInfo();
    if (!typeInfo) return;
    renderFieldGroup(document.getElementById('orgInfraConfigFields'), typeInfo.config_schema, provider ? provider.config : {}, false);
    renderFieldGroup(document.getElementById('orgInfraCredentialFields'), typeInfo.credential_schema, {}, true);
  }

  function renderFieldGroup(container, schema, values, isCredential) {
    const properties = schema.properties || {};
    const required = new Set(schema.required || []);
    const entries = Object.entries(properties);
    container.innerHTML = entries.length
      ? entries.map(([name, property]) => renderSchemaField(name, property, values[name], required.has(name), Boolean(isCredential))).join('')
      : `<div class="col-12 text-muted small">${escapeHtml(t('automationHub.providers.noFields', 'No fields required'))}</div>`;
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
    const id = `orgInfra-${isCredential ? 'credential' : 'config'}-${name}`;
    const label = property.title || name;
    const description = property.description || '';
    const type = resolveSchemaType(property);
    const isSecret = /token|password|secret|private_key|pat|api_key/i.test(name);
    let currentValue = value === undefined || value === null ? (property.default ?? '') : value;
    // Don't substitute {team_name} here — org-level config is team-agnostic.
    const typeInfo = currentTypeInfo();
    const isCiProvider = typeInfo && typeof typeInfo.provider_type === 'string' && typeInfo.provider_type.startsWith('ci:');
    const isRunnerLabelField = name === 'default_runner_label' && isCiProvider && !isCredential;
    let control = '';

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
      // Mirror per-team git-source-settings: a Bootstrap dropdown anchored to
      // the Discover button. Click opens the menu, triggers a fresh fetch,
      // populates items in-place — form layout never shifts.
      const discoverLabel = escapeHtml(t('automationHub.providers.discoverRunners', 'Discover'));
      const initialHint = escapeHtml(t('automationHub.providers.discoverHint', 'Click to fetch runners'));
      control = `
        <div class="input-group">
          <input id="${escapeAttr(id)}" type="text" class="form-control"
                 value="${escapeAttr(currentValue)}"
                 autocomplete="off"
                 data-schema-field="${escapeAttr(name)}"
                 data-schema-type="${escapeAttr(type)}"
                 ${required && !isSecret ? 'required' : ''}>
          <button type="button" class="btn btn-secondary dropdown-toggle" id="orgInfraDiscoverRunnersBtn"
                  data-bs-toggle="dropdown" aria-expanded="false" title="${escapeAttr(discoverLabel)}">
            <i class="fas fa-search me-1"></i><span data-i18n="automationHub.providers.discoverRunners">Discover</span>
          </button>
          <ul class="dropdown-menu dropdown-menu-end provider-runner-dropdown" id="orgInfraDiscoveredRunnersMenu" aria-labelledby="orgInfraDiscoverRunnersBtn">
            <li><span class="dropdown-item-text text-muted small" id="orgInfraDiscoverRunnersStatus">${initialHint}</span></li>
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

  // ─── Runner discovery (CI provider only) ───
  async function discoverRunners() {
    const typeInfo = currentTypeInfo();
    if (!typeInfo) return;
    const status = document.getElementById('orgInfraDiscoverRunnersStatus');
    const menu = document.getElementById('orgInfraDiscoveredRunnersMenu');
    if (!menu) return;

    const editingId = document.getElementById('orgInfraProviderId').value;
    const credentials = collectFieldGroup(document.getElementById('orgInfraCredentialFields'), true);
    // Edit mode + no typed credentials: the modal never echoes stored secrets
    // back, so the form's credential fields are empty. Hit the by-id endpoint
    // that reuses the DB-encrypted credentials instead of failing with 401.
    const useSavedCreds = editingId && Object.keys(credentials).length === 0;

    clearRunnerMenuItems();
    if (status) {
      status.textContent = t('automationHub.providers.discovering', 'Discovering runners...');
      status.classList.remove('text-success', 'text-danger');
      status.classList.add('text-muted');
    }

    const url = useSavedCreds
      ? `/api/system/automation-providers/${encodeURIComponent(editingId)}/discover-runners`
      : '/api/system/automation-providers/discover-runners';
    const options = useSavedCreds
      ? { method: 'POST' }
      : {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            provider_slot: typeInfo.provider_slot,
            provider_type: typeInfo.provider_type,
            name: document.getElementById('orgInfraProviderName').value.trim() || 'discover-probe',
            config: collectFieldGroup(document.getElementById('orgInfraConfigFields')),
            credentials,
            is_active: true,
          }),
        };
    try {
      const data = await apiFetch(url, options);
      const labels = Array.isArray(data && data.labels) ? data.labels : [];
      renderRunnerMenu(labels);
      if (status) {
        if (data && data.error) {
          const failedLabel = t('automationHub.providers.discoverFailed', 'Discovery failed');
          status.textContent = `${failedLabel}: ${data.error}`;
          status.classList.remove('text-muted', 'text-success');
          status.classList.add('text-danger');
        } else if (!labels.length) {
          status.textContent = t('automationHub.providers.discoverEmpty', 'No runners returned.');
          status.classList.remove('text-success', 'text-danger');
          status.classList.add('text-muted');
        } else {
          const foundLabel = t('automationHub.providers.discoverFound', 'Found');
          const foundSuffix = t('automationHub.providers.discoverFoundSuffix', 'labels — pick from the list.');
          status.textContent = `${foundLabel} ${labels.length} ${foundSuffix}`;
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
    const menu = document.getElementById('orgInfraDiscoveredRunnersMenu');
    if (!menu) return;
    while (menu.children.length > 1) menu.removeChild(menu.lastElementChild);
  }

  function renderRunnerMenu(labels) {
    clearRunnerMenuItems();
    const menu = document.getElementById('orgInfraDiscoveredRunnersMenu');
    if (!menu || !labels || !labels.length) return;

    const input = document.getElementById('orgInfra-config-default_runner_label');
    const currentValue = (input && input.value) || '';

    const divider = document.createElement('li');
    divider.innerHTML = '<hr class="dropdown-divider">';
    menu.appendChild(divider);

    labels.forEach((label) => {
      const li = document.createElement('li');
      const isSelected = label === currentValue;
      const activeCls = isSelected ? ' active' : '';
      const isAny = String(label || '').trim().toLowerCase() === 'any';
      const description = isAny ? t('automationHub.providers.runnerAny', 'Any available agent') : '';
      const icon = isAny ? 'fa-globe' : 'fa-server';
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
        const target = document.getElementById('orgInfra-config-default_runner_label');
        if (!target) return;
        target.value = value;
        target.dispatchEvent(new Event('input', { bubbles: true }));
      });
    });
  }

  async function saveProvider() {
    const typeInfo = currentTypeInfo();
    if (!typeInfo) return;
    const providerId = document.getElementById('orgInfraProviderId').value;
    const nameInput = document.getElementById('orgInfraProviderName');
    const name = nameInput.value.trim();
    if (!name) {
      showError(t('automationHub.providers.nameRequired', 'Name is required'));
      nameInput.focus();
      return;
    }
    const payload = {
      provider_slot: typeInfo.provider_slot,
      provider_type: document.getElementById('orgInfraProviderType').value,
      name,
      config: collectFieldGroup(document.getElementById('orgInfraConfigFields')),
      credentials: collectFieldGroup(document.getElementById('orgInfraCredentialFields'), true),
      is_active: document.getElementById('orgInfraProviderActive').checked,
    };
    if (providerId) {
      payload.clear_credentials = document.getElementById('orgInfraClearCredentials').checked;
      if (Object.keys(payload.credentials).length === 0) delete payload.credentials;
    }
    try {
      await apiFetch(
        providerId ? `/api/system/automation-providers/${providerId}` : '/api/system/automation-providers',
        {
          method: providerId ? 'PUT' : 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
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
      await apiFetch(`/api/system/automation-providers/${provider.id}`, { method: 'DELETE' });
      showSuccess(t('automationHub.providers.deleteDone', 'Provider deleted'));
      await loadAll();
    } catch (error) {
      showError(error.message || t('automationHub.providers.deleteFailed', 'Failed to delete provider'));
    }
  }

  async function testConnection(provider) {
    openHealthModalLoading();
    try {
      const result = await apiFetch(`/api/system/automation-providers/${provider.id}/test-connection`, { method: 'POST' });
      renderHealthResult(result);
      await loadAll();
    } catch (error) {
      renderHealthResult({ status: 'FAILED', message: error.message || 'Connection test failed', details: {} });
    }
  }

  async function testProviderConfig() {
    const typeInfo = currentTypeInfo();
    if (!typeInfo) return;
    const editingId = document.getElementById('orgInfraProviderId').value;
    const credentials = collectFieldGroup(document.getElementById('orgInfraCredentialFields'), true);
    if (editingId && Object.keys(credentials).length === 0) {
      const saved = state.providers.find((p) => String(p.id) === String(editingId));
      if (saved) return testConnection(saved);
    }
    const name = document.getElementById('orgInfraProviderName').value.trim() || 'test-probe';
    const payload = {
      provider_slot: typeInfo.provider_slot,
      provider_type: typeInfo.provider_type,
      name,
      config: collectFieldGroup(document.getElementById('orgInfraConfigFields')),
      credentials,
      is_active: true,
    };
    openHealthModalLoading();
    try {
      const result = await apiFetch('/api/system/automation-providers/test-config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      renderHealthResult(result);
    } catch (error) {
      renderHealthResult({ status: 'FAILED', message: error.message || 'Connection test failed', details: {} });
    }
  }

  function openHealthModalLoading() {
    if (!state.healthModal) return;
    document.getElementById('orgInfraProviderHealthLoading').classList.remove('d-none');
    document.getElementById('orgInfraProviderHealthContent').classList.add('d-none');
    state.healthModal.show();
  }

  function renderHealthResult(result) {
    if (!state.healthModal) return;
    document.getElementById('orgInfraProviderHealthLoading').classList.add('d-none');
    document.getElementById('orgInfraProviderHealthContent').classList.remove('d-none');
    const status = String(result.status || 'FAILED').toUpperCase();
    const badgeMap = {
      OK: { cls: 'bg-success', icon: 'fa-check-circle', labelKey: 'automationHub.providers.healthStatusOk', labelFallback: 'Connection successful' },
      LIMITED: { cls: 'bg-warning text-dark', icon: 'fa-exclamation-triangle', labelKey: 'automationHub.providers.healthStatusLimited', labelFallback: 'Limited — see details' },
      FAILED: { cls: 'bg-danger', icon: 'fa-times-circle', labelKey: 'automationHub.providers.healthStatusFailed', labelFallback: 'Connection failed' },
    };
    const info = badgeMap[status] || badgeMap.FAILED;
    const badge = document.getElementById('orgInfraProviderHealthStatusBadge');
    badge.className = `badge ${info.cls}`;
    badge.innerHTML = `<i class="fas ${info.icon} me-1"></i>${escapeHtml(status)}`;
    document.getElementById('orgInfraProviderHealthStatusLabel').textContent = t(info.labelKey, info.labelFallback);
    document.getElementById('orgInfraProviderHealthMessage').textContent = result.message || '';
    const details = result.details || {};
    const warningEl = document.getElementById('orgInfraProviderHealthWarning');
    if (details.warning) {
      warningEl.textContent = details.warning;
      warningEl.classList.remove('d-none');
    } else {
      warningEl.classList.add('d-none');
    }
    const dl = document.getElementById('orgInfraProviderHealthDetails');
    const wrap = document.getElementById('orgInfraProviderHealthDetailsWrap');
    const keys = Object.keys(details).filter((k) => k !== 'warning');
    if (!keys.length) {
      wrap.classList.add('d-none');
      dl.innerHTML = '';
    } else {
      wrap.classList.remove('d-none');
      dl.innerHTML = keys.map((key) => {
        const value = details[key];
        const rendered = Array.isArray(value)
          ? value.map((v) => escapeHtml(String(v))).join(', ') || '—'
          : escapeHtml(String(value));
        return `
          <dt class="col-sm-5 text-muted text-truncate" title="${escapeAttr(key)}">${escapeHtml(formatKey(key))}</dt>
          <dd class="col-sm-7 mb-1">${rendered}</dd>`;
      }).join('');
    }
  }

  function formatKey(key) {
    return String(key).split('_').filter(Boolean).map((p) => p.charAt(0).toUpperCase() + p.slice(1)).join(' ');
  }

  function currentTypeInfo() {
    const value = document.getElementById('orgInfraProviderType').value;
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

  function setLoading(isLoading) {
    document.getElementById('orgInfraLoadingState').classList.toggle('d-none', !isLoading);
    if (isLoading) {
      document.getElementById('orgInfraEmptyState').classList.add('d-none');
      document.getElementById('orgInfraContent').classList.add('d-none');
    }
  }

  function refreshTexts() {
    if (window.i18n) window.i18n.retranslate(document);
  }

  function showSuccess(message) { if (window.AppUtils) window.AppUtils.showSuccess(message); }
  function showError(message) { if (window.AppUtils) window.AppUtils.showError(message); }

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

  function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }
  function escapeAttr(value) { return escapeHtml(value); }
})();
