/* ============================================================
   AUTOMATION HUB — Environments (shared variable catalog).

   Renders the "Environments" card in the Automation Hub Settings tab:
   a list of automation environments (name / default badge /
   variable count + missing-required warnings), an Add/Edit environment
   modal, a per-environment shared-variable editor (add/edit/delete with
   is_secret toggle), set-default, and YAML import/export.

   Values are stored encrypted in TCRT and never committed to git; secret
   values are never displayed (only is_set + fingerprint). Mirrors the
   conventions in automation-hub/providers/settings.js.

   Public surface (consumed by automation-hub/suites/main.js):
     - AutomationEnvironments.load(teamId)   fetch + render the list
   ============================================================ */
(function () {
  const state = {
    teamId: null,
    environments: [],
    declaredVars: [],           // variable names scanned from the team's scripts (TCRT_VARS)
    activeEnvId: null,          // env id whose variables modal is open (kept in sync on reload)
    envModal: null,
    paramModal: null,
    importModal: null,
    exportModal: null,
    varsModal: null,
    loaded: false,
  };

  document.addEventListener('DOMContentLoaded', initModals);

  function initModals() {
    const envEl = document.getElementById('environmentModal');
    if (envEl && window.bootstrap) state.envModal = new bootstrap.Modal(envEl);
    const paramEl = document.getElementById('environmentParamModal');
    if (paramEl && window.bootstrap) {
      state.paramModal = new bootstrap.Modal(paramEl);
      // The variable editor opens stacked over the variables modal. Bootstrap
      // clears body scroll-lock when the top modal closes even though the
      // variables modal is still open — restore it so the page stays locked.
      paramEl.addEventListener('hidden.bs.modal', () => {
        if (document.querySelector('.modal.show')) document.body.classList.add('modal-open');
      });
    }
    const importEl = document.getElementById('environmentImportModal');
    if (importEl && window.bootstrap) state.importModal = new bootstrap.Modal(importEl);
    const exportEl = document.getElementById('environmentExportModal');
    if (exportEl && window.bootstrap) state.exportModal = new bootstrap.Modal(exportEl);
    const varsEl = document.getElementById('environmentVarsModal');
    if (varsEl && window.bootstrap) {
      state.varsModal = new bootstrap.Modal(varsEl);
      // Clear the active env once the modal closes so reloads stop syncing it.
      varsEl.addEventListener('hidden.bs.modal', () => { state.activeEnvId = null; });
    }
    bindEvents();
  }

  function bindEvents() {
    const addBtn = document.getElementById('environmentAddBtn');
    if (addBtn) addBtn.addEventListener('click', () => openEnvModal());
    const emptyAddBtn = document.getElementById('environmentEmptyAddBtn');
    if (emptyAddBtn) emptyAddBtn.addEventListener('click', () => openEnvModal());
    const saveEnvBtn = document.getElementById('environmentSaveBtn');
    if (saveEnvBtn) saveEnvBtn.addEventListener('click', saveEnvironment);
    const saveParamBtn = document.getElementById('environmentParamSaveBtn');
    if (saveParamBtn) saveParamBtn.addEventListener('click', saveParam);
    const paramKeyInput = document.getElementById('environmentParamKey');
    if (paramKeyInput) paramKeyInput.addEventListener('input', onParamKeyInput);
    const importConfirmBtn = document.getElementById('environmentImportConfirmBtn');
    if (importConfirmBtn) importConfirmBtn.addEventListener('click', confirmImport);
    const exportCopyBtn = document.getElementById('environmentExportCopyBtn');
    if (exportCopyBtn) exportCopyBtn.addEventListener('click', copyExport);

    const list = document.getElementById('environmentList');
    if (list) list.addEventListener('click', onListClick);
    // The variables editor lives inside the modal now; its param actions
    // (add/edit/delete) use the same delegated handler.
    const varsBody = document.getElementById('environmentVarsBody');
    if (varsBody) varsBody.addEventListener('click', onListClick);
  }

  async function load(teamId) {
    state.teamId = teamId || state.teamId;
    if (!state.teamId) return;
    try {
      const data = await apiFetch(`/api/teams/${state.teamId}/automation-environments`);
      state.environments = Array.isArray(data) ? data : [];
      state.loaded = true;
      // Best-effort: variable names scanned from the team's scripts, used to
      // suggest keys in the add-variable modal. A failure here must not break
      // the environments list.
      try {
        const declared = await apiFetch(`/api/teams/${state.teamId}/automation-environments/declared-variables`);
        state.declaredVars = Array.isArray(declared) ? declared : [];
      } catch (_e) {
        state.declaredVars = [];
      }
    } catch (error) {
      state.environments = [];
      showError(error.message || t('automationHub.environments.loadFailed', 'Failed to load environments'));
    }
    render();
  }

  function render() {
    const list = document.getElementById('environmentList');
    const empty = document.getElementById('environmentEmpty');
    const countEl = document.getElementById('environmentCount');
    if (!list) return;
    if (countEl) countEl.textContent = String(state.environments.length);

    const isEmpty = state.environments.length === 0;
    if (empty) empty.classList.toggle('d-none', !isEmpty);
    list.classList.toggle('d-none', isEmpty);

    list.innerHTML = state.environments.map(renderEnvItem).join('');
    refreshTexts(list);

    // Keep an open variables modal in sync after add/edit/delete/import reloads.
    if (state.activeEnvId != null) {
      const activeEnv = state.environments.find((e) => e.id === state.activeEnvId);
      if (activeEnv) renderVarsModal(activeEnv);
    }
  }

  function missingRequiredCount(env) {
    // The catalog endpoint does not flag required vars (that's per-script);
    // shared params have no "required" concept, so we surface unset secret
    // params as a soft warning only if value is missing. We keep this 0 by
    // default and rely on the per-script matrix for required coverage.
    return 0;
  }

  function renderEnvItem(env) {
    const params = Array.isArray(env.params) ? env.params : [];
    const defaultBadge = env.is_default
      ? `<span class="badge bg-success ms-2">${escapeHtml(t('automationHub.environments.default', 'Default'))}</span>`
      : '';
    const countLabel = tp('automationHub.environments.paramCount', { count: params.length }, `${params.length} variables`);
    const missing = missingRequiredCount(env);
    const missingBadge = missing
      ? `<span class="badge bg-warning text-dark ms-1">${escapeHtml(tp('automationHub.environments.missingRequired', { count: missing }, `${missing} required missing`))}</span>`
      : '';

    // The default env keeps the star in the same slot (rows stay aligned) but
    // lit bright gold (text-warning, same as the default Test Case Set) — a
    // non-interactive "this is the default" indicator. Non-default rows keep
    // the dim, clickable set-as-default star.
    const setDefaultBtn = env.is_default
      ? `<button type="button" class="btn btn-outline-secondary btn-sm pe-none" aria-disabled="true" tabindex="-1" title="${escapeAttr(t('automationHub.environments.default', 'Default'))}">
           <i class="fas fa-star text-warning"></i>
         </button>`
      : `<button type="button" class="btn btn-outline-secondary btn-sm" data-env-action="set-default" data-env-id="${env.id}" title="${escapeAttr(t('automationHub.environments.setDefault', 'Set as default'))}">
           <i class="fas fa-star"></i>
         </button>`;

    return `
      <article class="automation-env-item border rounded mb-2">
        <div class="d-flex align-items-center gap-2 p-2">
          <button type="button" class="btn btn-link p-0 text-decoration-none flex-grow-1 text-start d-flex align-items-center gap-2"
                  data-env-action="manage" data-env-id="${env.id}" title="${escapeAttr(t('automationHub.environments.manageVariables', 'Manage variables'))}">
            <i class="fas fa-layer-group text-primary"></i>
            <span class="fw-semibold">${escapeHtml(env.name)}</span>
            ${defaultBadge}
            <span class="badge bg-light text-dark border ms-auto">${escapeHtml(countLabel)}</span>
            ${missingBadge}
          </button>
          <div class="d-flex align-items-center gap-1 flex-shrink-0">
            ${setDefaultBtn}
            <button type="button" class="btn btn-outline-secondary btn-sm" data-env-action="export" data-env-id="${env.id}" title="${escapeAttr(t('automationHub.environments.export', 'Export YAML'))}">
              <i class="fas fa-file-export"></i>
            </button>
            <button type="button" class="btn btn-outline-secondary btn-sm" data-env-action="import" data-env-id="${env.id}" title="${escapeAttr(t('automationHub.environments.import', 'Import YAML'))}">
              <i class="fas fa-file-import"></i>
            </button>
            <button type="button" class="btn btn-secondary btn-sm" data-env-action="edit" data-env-id="${env.id}" title="${escapeAttr(t('common.edit', 'Edit'))}">
              <i class="fas fa-pen"></i>
            </button>
            <button type="button" class="btn btn-danger btn-sm" data-env-action="delete" data-env-id="${env.id}" title="${escapeAttr(t('common.delete', 'Delete'))}">
              <i class="fas fa-trash"></i>
            </button>
          </div>
        </div>
      </article>`;
  }

  function renderParamEditor(env) {
    const params = Array.isArray(env.params) ? env.params.slice() : [];
    params.sort((a, b) => String(a.key).localeCompare(String(b.key)));
    const rows = params.length
      ? params.map((p) => renderParamRow(env, p)).join('')
      : `<div class="text-muted small px-2 py-2" data-i18n="automationHub.environments.paramsEmpty">${escapeHtml(t('automationHub.environments.paramsEmpty', 'No variables yet.'))}</div>`;
    return `
      <div class="automation-env-params border-top px-2 py-2">
        <div class="d-flex align-items-center justify-content-between mb-2">
          <div class="text-muted small">
            <i class="fas fa-lock me-1"></i><span data-i18n="automationHub.environments.secureStorageNote">${escapeHtml(t('automationHub.environments.secureStorageNote', 'Values are stored encrypted in TCRT — never committed to git.'))}</span>
          </div>
          <button type="button" class="btn btn-outline-primary btn-sm" data-env-action="add-param" data-env-id="${env.id}">
            <i class="fas fa-plus me-1"></i><span data-i18n="automationHub.environments.addParam">${escapeHtml(t('automationHub.environments.addParam', 'Add variable'))}</span>
          </button>
        </div>
        <div class="table-responsive">
          <table class="table table-sm align-middle mb-0">
            <tbody>${rows}</tbody>
          </table>
        </div>
      </div>`;
  }

  function renderParamRow(env, param) {
    const secretBadge = param.is_secret
      ? `<span class="badge bg-secondary ms-1"><i class="fas fa-lock me-1"></i>${escapeHtml(t('automationHub.environments.paramSecret', 'secret'))}</span>`
      : '';
    let valueCell;
    if (param.is_secret) {
      valueCell = param.is_set
        ? `<span class="font-monospace small text-muted" title="${escapeAttr(param.fingerprint || '')}">${escapeHtml(param.fingerprint || '••••')}</span>`
        : `<span class="text-muted small" data-i18n="automationHub.environments.paramUnset">${escapeHtml(t('automationHub.environments.paramUnset', 'not set'))}</span>`;
    } else {
      valueCell = param.is_set
        ? `<span class="font-monospace small text-truncate d-inline-block" style="max-width: 320px;" title="${escapeAttr(String(param.value ?? ''))}">${escapeHtml(String(param.value ?? ''))}</span>`
        : `<span class="text-muted small" data-i18n="automationHub.environments.paramUnset">${escapeHtml(t('automationHub.environments.paramUnset', 'not set'))}</span>`;
    }
    return `
      <tr>
        <td class="font-monospace small fw-semibold">${escapeHtml(param.key)}${secretBadge}</td>
        <td>${valueCell}</td>
        <td class="text-end text-nowrap" style="width: 1%;">
          <div class="d-inline-flex align-items-center gap-3">
            <button type="button" class="btn btn-link btn-sm p-0" data-env-action="edit-param" data-env-id="${env.id}" data-param-key="${escapeAttr(param.key)}" title="${escapeAttr(t('common.edit', 'Edit'))}">
              <i class="fas fa-pen"></i>
            </button>
            <button type="button" class="btn btn-link btn-sm p-0 text-danger" data-env-action="delete-param" data-env-id="${env.id}" data-param-key="${escapeAttr(param.key)}" title="${escapeAttr(t('common.delete', 'Delete'))}">
              <i class="fas fa-trash"></i>
            </button>
          </div>
        </td>
      </tr>`;
  }

  function onListClick(event) {
    const button = event.target.closest('[data-env-action]');
    if (!button) return;
    const action = button.dataset.envAction;
    const envId = button.dataset.envId ? Number(button.dataset.envId) : null;
    const env = state.environments.find((e) => e.id === envId);
    if (action === 'manage') { if (env) openVarsModal(env); return; }
    if (!env) return;
    if (action === 'edit') openEnvModal(env);
    else if (action === 'delete') deleteEnvironment(env);
    else if (action === 'set-default') setDefault(env);
    else if (action === 'add-param') openParamModal(env, null);
    else if (action === 'edit-param') {
      const param = (env.params || []).find((p) => p.key === button.dataset.paramKey);
      if (param) openParamModal(env, param);
    } else if (action === 'delete-param') {
      deleteParam(env, button.dataset.paramKey);
    } else if (action === 'import') openImportModal(env);
    else if (action === 'export') openExportModal(env);
  }

  // ── Manage variables (modal) ─────────────────────────────────────
  function openVarsModal(env) {
    if (!state.varsModal) return;
    state.activeEnvId = env.id;
    renderVarsModal(env);
    state.varsModal.show();
  }

  function renderVarsModal(env) {
    const titleEl = document.getElementById('environmentVarsModalTitle');
    const bodyEl = document.getElementById('environmentVarsBody');
    if (titleEl) {
      titleEl.textContent = env.name;
    }
    if (bodyEl) {
      bodyEl.innerHTML = renderParamEditor(env);
      refreshTexts(bodyEl);
    }
  }

  // ── Add / Edit environment ───────────────────────────────────────
  function openEnvModal(env) {
    if (!state.envModal) return;
    document.getElementById('environmentModalTitle').textContent = env
      ? t('automationHub.environments.editTitle', 'Edit Environment')
      : t('automationHub.environments.createTitle', 'Add Environment');
    document.getElementById('environmentId').value = env ? env.id : '';
    const nameInput = document.getElementById('environmentName');
    nameInput.value = env ? env.name : '';
    document.getElementById('environmentIsDefault').checked = env ? Boolean(env.is_default) : false;
    state.envModal.show();
    refreshTexts();
  }

  async function saveEnvironment() {
    const envId = document.getElementById('environmentId').value;
    const nameInput = document.getElementById('environmentName');
    const name = nameInput.value.trim();
    const isDefault = document.getElementById('environmentIsDefault').checked;

    if (!name) {
      showError(t('automationHub.environments.nameRequired', 'Environment name is required'));
      nameInput.focus();
      return;
    }

    const url = envId
      ? `/api/teams/${state.teamId}/automation-environments/${envId}`
      : `/api/teams/${state.teamId}/automation-environments`;
    const payload = envId
      ? { name, is_default: isDefault }
      : { name, is_default: isDefault, params: [] };

    try {
      await apiFetch(url, {
        method: envId ? 'PUT' : 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      state.envModal.hide();
      showSuccess(t('automationHub.environments.saveDone', 'Environment saved'));
      await load();
    } catch (error) {
      showError(error.message || t('automationHub.environments.saveFailed', 'Failed to save environment'));
    }
  }

  async function deleteEnvironment(env) {
    const confirmed = await showConfirm(t('automationHub.environments.deleteConfirm', 'Delete this environment? Scripts that rely on it will fall back to other environments.'));
    if (!confirmed) return;
    try {
      await apiFetch(`/api/teams/${state.teamId}/automation-environments/${env.id}`, { method: 'DELETE' });
      showSuccess(t('automationHub.environments.deleteDone', 'Environment deleted'));
      if (state.activeEnvId === env.id) {
        state.activeEnvId = null;
        if (state.varsModal) state.varsModal.hide();
      }
      await load();
    } catch (error) {
      showError(error.message || t('automationHub.environments.deleteFailed', 'Failed to delete environment'));
    }
  }

  async function setDefault(env) {
    try {
      await apiFetch(`/api/teams/${state.teamId}/automation-environments/${env.id}/default`, { method: 'PUT' });
      showSuccess(t('automationHub.environments.setDefaultDone', 'Default environment updated'));
      await load();
    } catch (error) {
      showError(error.message || t('automationHub.environments.setDefaultFailed', 'Failed to set default environment'));
    }
  }

  // ── Add / Edit shared variable ───────────────────────────────────
  function openParamModal(env, param) {
    if (!state.paramModal) return;
    document.getElementById('environmentParamModalTitle').textContent = param
      ? t('automationHub.environments.editParam', 'Edit variable')
      : t('automationHub.environments.addParam', 'Add variable');
    document.getElementById('environmentParamEnvId').value = env.id;
    document.getElementById('environmentParamOriginalKey').value = param ? param.key : '';
    const keyInput = document.getElementById('environmentParamKey');
    keyInput.value = param ? param.key : '';
    keyInput.disabled = Boolean(param);
    const isSecret = document.getElementById('environmentParamIsSecret');
    isSecret.checked = param ? Boolean(param.is_secret) : false;
    isSecret.disabled = Boolean(param); // is_secret is fixed once created
    const valueInput = document.getElementById('environmentParamValue');
    // Never prefill secret values; non-secret existing values are editable.
    valueInput.value = param && !param.is_secret && param.is_set ? String(param.value ?? '') : '';
    valueInput.type = (param && param.is_secret) ? 'password' : 'text';
    updateParamSecretHint(param);
    // Suggest variable names scanned from the team's scripts (TCRT_VARS). Add
    // mode only; picking one auto-sets is_secret via onParamKeyInput, but a
    // brand-new name can still be typed (free entry).
    const datalist = document.getElementById('environmentParamKeyDatalist');
    const declaredHint = document.getElementById('environmentParamDeclaredHint');
    if (declaredHint) declaredHint.classList.add('d-none');
    if (datalist) {
      if (param) {
        datalist.innerHTML = '';
      } else {
        const existing = new Set((env.params || []).map((p) => p.key));
        datalist.innerHTML = state.declaredVars
          .filter((v) => !existing.has(v.name))
          .map((v) => `<option value="${escapeAttr(v.name)}"></option>`)
          .join('');
      }
    }
    state.paramModal.show();
    refreshTexts();
  }

  function onParamKeyInput() {
    // When the typed key matches a scanned declared variable, prefill is_secret
    // from its declaration and note how many scripts declare it. A name not in
    // the list is allowed (free entry) — no hint, manual is_secret.
    const keyInput = document.getElementById('environmentParamKey');
    const isSecret = document.getElementById('environmentParamIsSecret');
    const hint = document.getElementById('environmentParamDeclaredHint');
    if (!keyInput || !isSecret || isSecret.disabled) return; // edit mode: locked
    const match = state.declaredVars.find((v) => v.name === keyInput.value.trim());
    if (match) {
      isSecret.checked = Boolean(match.secret);
      if (hint) {
        const n = (match.scripts || []).length;
        hint.textContent = tp(
          'automationHub.environments.declaredVarHint', { count: n },
          `Declared by ${n} script(s) — selected from your scanned scripts.`,
        );
        hint.classList.remove('d-none');
      }
    } else if (hint) {
      hint.classList.add('d-none');
    }
  }

  function updateParamSecretHint(param) {
    const hint = document.getElementById('environmentParamValueHint');
    if (!hint) return;
    const isSecret = document.getElementById('environmentParamIsSecret').checked;
    if (isSecret && param && param.is_set) {
      hint.textContent = t('automationHub.environments.paramValueSecretKeep', 'Leave blank to keep the stored secret value.');
      hint.classList.remove('d-none');
    } else {
      hint.classList.add('d-none');
    }
  }

  async function saveParam() {
    const envId = document.getElementById('environmentParamEnvId').value;
    const originalKey = document.getElementById('environmentParamOriginalKey').value;
    const keyInput = document.getElementById('environmentParamKey');
    const key = keyInput.value.trim();
    const isSecret = document.getElementById('environmentParamIsSecret').checked;
    const value = document.getElementById('environmentParamValue').value;

    if (!key) {
      showError(t('automationHub.environments.paramKeyRequired', 'Key is required'));
      keyInput.focus();
      return;
    }
    const targetKey = originalKey || key;
    const payload = { key, is_secret: isSecret };
    // For secret params, omit/empty value to KEEP the stored value.
    // For non-secret params, always send the (possibly empty) value.
    if (isSecret) {
      if (value !== '') payload.value = value;
    } else {
      payload.value = value;
    }

    try {
      await apiFetch(`/api/teams/${state.teamId}/automation-environments/${envId}/params/${encodeURIComponent(targetKey)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      state.paramModal.hide();
      showSuccess(t('automationHub.environments.paramSaveDone', 'Variable saved'));
      await load();
    } catch (error) {
      showError(error.message || t('automationHub.environments.paramSaveFailed', 'Failed to save variable'));
    }
  }

  async function deleteParam(env, key) {
    if (!key) return;
    const confirmed = await showConfirm(t('automationHub.environments.paramDeleteConfirm', 'Delete this variable?'));
    if (!confirmed) return;
    try {
      await apiFetch(`/api/teams/${state.teamId}/automation-environments/${env.id}/params/${encodeURIComponent(key)}`, { method: 'DELETE' });
      showSuccess(t('automationHub.environments.paramDeleteDone', 'Variable deleted'));
      await load();
    } catch (error) {
      showError(error.message || t('automationHub.environments.paramDeleteFailed', 'Failed to delete variable'));
    }
  }

  // ── Import / Export YAML ─────────────────────────────────────────
  function openImportModal(env) {
    if (!state.importModal) return;
    document.getElementById('environmentImportEnvId').value = env.id;
    document.getElementById('environmentImportEnvName').textContent = env.name;
    document.getElementById('environmentImportText').value = '';
    state.importModal.show();
    refreshTexts();
  }

  async function confirmImport() {
    const envId = document.getElementById('environmentImportEnvId').value;
    const yaml = document.getElementById('environmentImportText').value;
    if (!yaml.trim()) {
      showError(t('automationHub.environments.importEmpty', 'Paste some YAML before importing'));
      return;
    }
    try {
      const result = await apiFetch(`/api/teams/${state.teamId}/automation-environments/${envId}/import`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ yaml }),
      });
      state.importModal.hide();
      const n = result && typeof result.imported === 'number' ? result.imported : 0;
      showSuccess(tp('automationHub.environments.importDone', { count: n }, `Imported ${n} variables`));
      await load();
    } catch (error) {
      showError(error.message || t('automationHub.environments.importFailed', 'Failed to import variables'));
    }
  }

  async function openExportModal(env) {
    if (!state.exportModal) return;
    document.getElementById('environmentExportEnvName').textContent = env.name;
    const textArea = document.getElementById('environmentExportText');
    textArea.value = '';
    try {
      const result = await apiFetch(`/api/teams/${state.teamId}/automation-environments/${env.id}/export`);
      textArea.value = (result && result.yaml) || '';
    } catch (error) {
      showError(error.message || t('automationHub.environments.exportFailed', 'Failed to export variables'));
      return;
    }
    state.exportModal.show();
    refreshTexts();
  }

  function copyExport() {
    const textArea = document.getElementById('environmentExportText');
    if (!textArea) return;
    const text = textArea.value;
    const done = () => showSuccess(t('automationHub.environments.copied', 'Copied to clipboard'));
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(done).catch(() => fallbackCopy(textArea, done));
    } else {
      fallbackCopy(textArea, done);
    }
  }

  function fallbackCopy(textArea, done) {
    textArea.select();
    try { document.execCommand('copy'); done(); } catch (_e) { /* non-fatal */ }
  }

  // ── helpers (mirror providers/settings.js) ───────────────────────
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

  function refreshTexts(root) {
    if (window.i18n) window.i18n.retranslate(root || document);
  }

  function showSuccess(message) {
    if (window.AppUtils) window.AppUtils.showSuccess(message);
  }

  function showError(message) {
    if (window.AppUtils) window.AppUtils.showError(message);
  }

  function showConfirm(message) {
    if (window.AppUtils && window.AppUtils.showConfirm) return window.AppUtils.showConfirm(message);
    return Promise.resolve(window.confirm(message));
  }

  function t(key, fallback) {
    return window.i18n && window.i18n.t ? window.i18n.t(key, {}, fallback) : fallback;
  }

  // t() with interpolation params (e.g. {count}).
  function tp(key, params, fallback) {
    return window.i18n && window.i18n.t ? window.i18n.t(key, params || {}, fallback) : fallback;
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

  // Re-bind the secret hint when the is_secret checkbox toggles in the modal.
  document.addEventListener('change', (event) => {
    if (event.target && event.target.id === 'environmentParamIsSecret') {
      const valueInput = document.getElementById('environmentParamValue');
      if (valueInput) valueInput.type = event.target.checked ? 'password' : 'text';
      updateParamSecretHint(null);
    }
  });

  window.AutomationEnvironments = { load };
})();
