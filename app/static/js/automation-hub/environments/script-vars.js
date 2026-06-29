/* ============================================================
   AUTOMATION HUB — Per-script variable matrix ("Configure variables").

   Opened from a script row in the Suites/Scripts view when the script
   declares variables. GETs
     /api/teams/{team}/automation-scripts/{id}/env-vars
   and renders a matrix: rows = declared_vars, columns = environments.
   Each cell shows the effective value + a source badge
   (shared / override / unset). Clicking a cell lets the user set a
   per-script OVERRIDE (PUT) or clear it (DELETE → back to shared).

   Secret cells never reveal the value — only the fingerprint; an empty
   input keeps the stored secret. Declared required vars that are unset
   for an environment are flagged.

   Public surface (consumed by automation-hub/suites/main.js):
     - AutomationScriptVars.open(teamId, scriptId)
   ============================================================ */
(function () {
  const state = {
    teamId: null,
    scriptId: null,
    data: null,          // last env-vars payload
    matrixModal: null,
    cellModal: null,
  };

  document.addEventListener('DOMContentLoaded', initModals);

  function initModals() {
    const matrixEl = document.getElementById('scriptVarsModal');
    if (matrixEl && window.bootstrap) state.matrixModal = new bootstrap.Modal(matrixEl);
    const cellEl = document.getElementById('scriptVarsCellModal');
    if (cellEl && window.bootstrap) state.cellModal = new bootstrap.Modal(cellEl);

    const matrixBody = document.getElementById('scriptVarsMatrix');
    if (matrixBody) matrixBody.addEventListener('click', onMatrixClick);
    const saveCellBtn = document.getElementById('scriptVarsCellSaveBtn');
    if (saveCellBtn) saveCellBtn.addEventListener('click', saveCell);
    const clearCellBtn = document.getElementById('scriptVarsCellClearBtn');
    if (clearCellBtn) clearCellBtn.addEventListener('click', clearCell);
  }

  async function open(teamId, scriptId) {
    state.teamId = teamId;
    state.scriptId = scriptId;
    if (!state.matrixModal) return;
    setMatrixLoading(true);
    state.matrixModal.show();
    await reload();
  }

  async function reload() {
    setMatrixLoading(true);
    try {
      state.data = await apiFetch(`/api/teams/${state.teamId}/automation-scripts/${state.scriptId}/env-vars`);
      renderMatrix();
    } catch (error) {
      state.data = null;
      renderMatrixError(error.message || t('automationHub.environments.varsLoadFailed', 'Failed to load script variables'));
    } finally {
      setMatrixLoading(false);
    }
  }

  function setMatrixLoading(loading) {
    const loadingEl = document.getElementById('scriptVarsLoading');
    const contentEl = document.getElementById('scriptVarsContent');
    if (loadingEl) loadingEl.classList.toggle('d-none', !loading);
    if (contentEl) contentEl.classList.toggle('d-none', loading);
  }

  function renderMatrixError(message) {
    const contentEl = document.getElementById('scriptVarsContent');
    if (contentEl) {
      contentEl.classList.remove('d-none');
      contentEl.innerHTML = `<div class="alert alert-danger mb-0">${escapeHtml(message)}</div>`;
    }
  }

  // Build a lookup: cells keyed by `${environment_id}::${key}`.
  function cellMap() {
    const map = new Map();
    const cells = state.data && Array.isArray(state.data.cells) ? state.data.cells : [];
    for (const cell of cells) {
      map.set(`${cell.environment_id}::${cell.key}`, cell);
    }
    return map;
  }

  function getCell(envId, key) {
    return cellMap().get(`${envId}::${key}`) || null;
  }

  function renderMatrix() {
    const refPathEl = document.getElementById('scriptVarsRefPath');
    if (refPathEl) refPathEl.textContent = (state.data && state.data.ref_path) || '';

    const declared = state.data && Array.isArray(state.data.declared_vars) ? state.data.declared_vars : [];
    const environments = state.data && Array.isArray(state.data.environments) ? state.data.environments : [];
    const contentEl = document.getElementById('scriptVarsContent');
    if (!contentEl) return;

    if (declared.length === 0) {
      contentEl.innerHTML = `<div class="text-muted small" data-i18n="automationHub.environments.varsNoDeclared">${escapeHtml(t('automationHub.environments.varsNoDeclared', 'This script does not declare any variables.'))}</div>`;
      refreshTexts(contentEl);
      return;
    }

    const headCols = environments.map((env) => {
      const def = env.is_default
        ? ` <span class="badge bg-success">${escapeHtml(t('automationHub.environments.default', 'Default'))}</span>`
        : '';
      return `<th class="text-nowrap" title="${escapeAttr(env.name)}">${escapeHtml(env.name)}${def}</th>`;
    }).join('');

    const rows = declared.map((v) => renderVarRow(v, environments)).join('');

    contentEl.innerHTML = `
      <div class="text-muted small mb-2">
        <i class="fas fa-lock me-1"></i><span data-i18n="automationHub.environments.varsSecureNote">${escapeHtml(t('automationHub.environments.varsSecureNote', 'Values are stored encrypted in TCRT — never committed to git.'))}</span>
      </div>
      <div class="table-responsive">
        <table class="table table-sm table-bordered align-middle mb-0" id="scriptVarsMatrix">
          <thead class="table-light">
            <tr>
              <th data-i18n="automationHub.environments.varsColVariable">Variable</th>
              ${headCols}
            </tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
      </div>`;

    // The matrix table is re-created each render, so (re)bind the click handler.
    const matrixBody = document.getElementById('scriptVarsMatrix');
    if (matrixBody) matrixBody.addEventListener('click', onMatrixClick);

    refreshTexts(contentEl);
  }

  function renderVarRow(declaredVar, environments) {
    const requiredFlag = declaredVar.required
      ? ` <span class="text-danger" title="${escapeAttr(t('automationHub.environments.varsRequired', 'required'))}">*</span>`
      : '';
    const secretFlag = declaredVar.secret
      ? ` <i class="fas fa-lock text-muted small" title="${escapeAttr(t('automationHub.environments.varsSecret', 'secret'))}"></i>`
      : '';
    const descTitle = declaredVar.description ? escapeAttr(declaredVar.description) : '';
    const nameCell = `<td class="font-monospace small fw-semibold" title="${descTitle}">${escapeHtml(declaredVar.name)}${requiredFlag}${secretFlag}</td>`;

    const cells = environments.map((env) => renderCell(declaredVar, env)).join('');
    return `<tr>${nameCell}${cells}</tr>`;
  }

  function renderCell(declaredVar, env) {
    const cell = getCell(env.id, declaredVar.name);
    const source = cell ? cell.source : 'unset';
    const isSecret = cell ? cell.is_secret : Boolean(declaredVar.secret);
    const isSet = cell ? cell.is_set : false;

    // Required but unset for this env → flag.
    const missingRequired = Boolean(declaredVar.required) && !isSet;

    const badgeMap = {
      shared: { cls: 'bg-info text-dark', label: t('automationHub.environments.varsSourceShared', 'shared'), titleKey: 'automationHub.environments.varsSourceSharedTitle' },
      override: { cls: 'bg-primary', label: t('automationHub.environments.varsSourceOverride', 'override'), titleKey: 'automationHub.environments.varsSourceOverrideTitle' },
      unset: { cls: 'bg-secondary', label: t('automationHub.environments.varsSourceUnset', 'unset'), titleKey: 'automationHub.environments.varsSourceUnsetTitle' },
    };
    const badge = badgeMap[source] || badgeMap.unset;
    const badgeTitle = escapeAttr(t(badge.titleKey, badge.label));

    let valueText;
    if (!isSet) {
      valueText = `<span class="text-muted small">—</span>`;
    } else if (isSecret) {
      valueText = `<span class="font-monospace small text-muted" title="${escapeAttr(cell && cell.fingerprint || '')}">${escapeHtml((cell && cell.fingerprint) || '••••')}</span>`;
    } else {
      const v = cell && cell.value != null ? String(cell.value) : '';
      valueText = `<span class="font-monospace small text-truncate d-inline-block" style="max-width: 220px;" title="${escapeAttr(v)}">${escapeHtml(v)}</span>`;
    }

    const missingMark = missingRequired
      ? `<i class="fas fa-exclamation-triangle text-warning ms-1" title="${escapeAttr(t('automationHub.environments.varsMissingRequired', 'Required variable is missing for this environment'))}"></i>`
      : '';

    return `
      <td class="automation-vars-cell${missingRequired ? ' table-warning' : ''}" role="button"
          data-vars-cell data-env-id="${env.id}" data-env-name="${escapeAttr(env.name)}"
          data-var-name="${escapeAttr(declaredVar.name)}" data-is-secret="${isSecret ? '1' : '0'}"
          title="${escapeAttr(t('automationHub.environments.varsEditCellTitle', 'Set or clear the value for this environment'))}">
        <div class="d-flex align-items-center justify-content-between gap-2">
          <span class="badge ${badge.cls}" title="${badgeTitle}">${escapeHtml(badge.label)}</span>
          ${missingMark}
        </div>
        <div class="mt-1">${valueText}</div>
      </td>`;
  }

  function onMatrixClick(event) {
    const cellEl = event.target.closest('[data-vars-cell]');
    if (!cellEl) return;
    openCellModal({
      envId: Number(cellEl.dataset.envId),
      envName: cellEl.dataset.envName,
      varName: cellEl.dataset.varName,
      isSecret: cellEl.dataset.isSecret === '1',
    });
  }

  // ── Cell editor (set / clear an override) ────────────────────────
  function openCellModal(ctx) {
    if (!state.cellModal) return;
    const cell = getCell(ctx.envId, ctx.varName);
    document.getElementById('scriptVarsCellEnvId').value = ctx.envId;
    document.getElementById('scriptVarsCellVarName').value = ctx.varName;
    document.getElementById('scriptVarsCellIsSecret').value = ctx.isSecret ? '1' : '0';

    document.getElementById('scriptVarsCellEnvLabel').textContent = ctx.envName;
    document.getElementById('scriptVarsCellVarLabel').textContent = ctx.varName;

    const valueInput = document.getElementById('scriptVarsCellValue');
    valueInput.type = ctx.isSecret ? 'password' : 'text';
    // Never prefill secret values; for a non-secret override, prefill the
    // current override value so the user can tweak it.
    const isOverride = cell && cell.source === 'override';
    valueInput.value = (!ctx.isSecret && isOverride && cell.value != null) ? String(cell.value) : '';

    const hint = document.getElementById('scriptVarsCellValueHint');
    if (hint) hint.classList.toggle('d-none', !ctx.isSecret);

    // "Clear override" only makes sense when an override currently exists.
    const clearBtn = document.getElementById('scriptVarsCellClearBtn');
    if (clearBtn) clearBtn.classList.toggle('d-none', !isOverride);

    state.cellModal.show();
    refreshTexts();
  }

  async function saveCell() {
    const envId = document.getElementById('scriptVarsCellEnvId').value;
    const varName = document.getElementById('scriptVarsCellVarName').value;
    const isSecret = document.getElementById('scriptVarsCellIsSecret').value === '1';
    const value = document.getElementById('scriptVarsCellValue').value;

    const payload = { is_secret: isSecret };
    if (isSecret) {
      // Empty keeps the stored secret value (when overriding an existing one).
      if (value !== '') payload.value = value;
    } else {
      payload.value = value;
    }

    try {
      await apiFetch(`/api/teams/${state.teamId}/automation-scripts/${state.scriptId}/env-vars/${envId}/${encodeURIComponent(varName)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (state.cellModal) state.cellModal.hide();
      showSuccess(t('automationHub.environments.varsSaveDone', 'Variable override saved'));
      await reload();
    } catch (error) {
      showError(error.message || t('automationHub.environments.varsSaveFailed', 'Failed to save variable override'));
    }
  }

  async function clearCell() {
    const envId = document.getElementById('scriptVarsCellEnvId').value;
    const varName = document.getElementById('scriptVarsCellVarName').value;
    const confirmed = await showConfirm(t('automationHub.environments.varsClearConfirm', 'Remove this override and fall back to the shared value?'));
    if (!confirmed) return;
    try {
      await apiFetch(`/api/teams/${state.teamId}/automation-scripts/${state.scriptId}/env-vars/${envId}/${encodeURIComponent(varName)}`, { method: 'DELETE' });
      if (state.cellModal) state.cellModal.hide();
      showSuccess(t('automationHub.environments.varsClearDone', 'Override removed'));
      await reload();
    } catch (error) {
      showError(error.message || t('automationHub.environments.varsClearFailed', 'Failed to remove override'));
    }
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

  // Keep the secret-input behaviour in sync if the modal is reused.
  document.addEventListener('change', (event) => {
    if (event.target && event.target.id === 'scriptVarsCellIsSecret') {
      const valueInput = document.getElementById('scriptVarsCellValue');
      if (valueInput) valueInput.type = event.target.value === '1' ? 'password' : 'text';
    }
  });

  window.AutomationScriptVars = { open };
})();
