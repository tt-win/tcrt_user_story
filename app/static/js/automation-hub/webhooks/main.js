(function () {
  const state = {
    teamId: null,
    webhooks: [],
    scriptGroups: [],
    editingWebhook: null,
    webhookModal: null,
    credentialModal: null,
    runsModal: null,
    runsWebhookId: null,
    lastTriggerCurl: ''
  };

  document.addEventListener('DOMContentLoaded', init);
  document.addEventListener('i18nReady', refreshTexts);
  document.addEventListener('languageChanged', () => {
    renderWebhooks();
    refreshTexts();
  });
  window.addEventListener('pageshow', refreshTexts);

  function init() {
    state.teamId = resolveTeamId();
    const webhookModalEl = document.getElementById('webhookModal');
    const credentialModalEl = document.getElementById('webhookCredentialModal');
    const runsModalEl = document.getElementById('webhookRunsModal');
    if (webhookModalEl && window.bootstrap) {
      state.webhookModal = new bootstrap.Modal(webhookModalEl);
    }
    if (credentialModalEl && window.bootstrap) {
      state.credentialModal = new bootstrap.Modal(credentialModalEl);
    }
    if (runsModalEl && window.bootstrap) {
      state.runsModal = new bootstrap.Modal(runsModalEl);
    }
    bindEvents();

    if (!state.teamId) {
      showNoTeam();
      return;
    }

    applyTeamLinks();
    showTeamBadge();
    loadScriptGroups();
    loadWebhooks();
  }

  async function loadScriptGroups() {
    try {
      const data = await apiFetch(`/api/teams/${state.teamId}/automation-script-groups?limit=200`);
      state.scriptGroups = (data && data.items) || [];
    } catch (error) {
      state.scriptGroups = [];
    }
  }

  function bindEvents() {
    const addWebhookBtn = document.getElementById('addWebhookBtn');
    if (addWebhookBtn) addWebhookBtn.addEventListener('click', () => openWebhookModal());

    const refreshWebhooksBtn = document.getElementById('refreshWebhooksBtn');
    if (refreshWebhooksBtn) refreshWebhooksBtn.addEventListener('click', loadWebhooks);

    const emptyAdd = document.getElementById('emptyStateAddWebhookBtn');
    if (emptyAdd) emptyAdd.addEventListener('click', () => openWebhookModal());

    const saveWebhookBtn = document.getElementById('saveWebhookBtn');
    if (saveWebhookBtn) saveWebhookBtn.addEventListener('click', saveWebhook);

    const copyTokenBtn = document.getElementById('copyTokenBtn');
    if (copyTokenBtn) copyTokenBtn.addEventListener('click', () => copyField('webhookToken'));

    const copySecretBtn = document.getElementById('copySecretBtn');
    if (copySecretBtn) copySecretBtn.addEventListener('click', () => copyField('webhookSecret'));

    const copyTriggerBtn = document.getElementById('copyTriggerBtn');
    if (copyTriggerBtn) copyTriggerBtn.addEventListener('click', () => copyField('webhookTriggerEndpoint'));

    const copyTriggerCurlBtn = document.getElementById('copyTriggerCurlBtn');
    if (copyTriggerCurlBtn) copyTriggerCurlBtn.addEventListener('click', () => copyText(state.lastTriggerCurl));

    const copyPollCurlBtn = document.getElementById('copyPollCurlBtn');
    if (copyPollCurlBtn) copyPollCurlBtn.addEventListener('click', () => copyText(state.lastPollCurl));

    const webhookRows = document.getElementById('webhookRows');
    if (webhookRows) {
      webhookRows.addEventListener('click', (event) => {
        const button = event.target.closest('[data-webhook-action]');
        if (!button) return;
        const webhook = state.webhooks.find((item) => String(item.id) === button.dataset.webhookId);
        if (!webhook) return;
        if (button.dataset.webhookAction === 'edit') openWebhookModal(webhook);
        if (button.dataset.webhookAction === 'regenerate') regenerateSecret(webhook);
        if (button.dataset.webhookAction === 'delete') deleteWebhook(webhook);
        if (button.dataset.webhookAction === 'runs') openRuns(webhook);
      });

      webhookRows.addEventListener('change', (event) => {
        if (!event.target.matches('[data-active-toggle]')) return;
        const webhook = state.webhooks.find((item) => String(item.id) === event.target.dataset.webhookId);
        if (webhook) toggleWebhookActive(webhook, event.target.checked);
      });
    }
  }

  async function loadWebhooks() {
    setLoading(true);
    try {
      state.webhooks = await apiFetch(`/api/teams/${state.teamId}/automation-webhooks`);
      renderWebhooks();
    } catch (error) {
      showError(error.message || t('automationHub.webhooks.loadFailed', 'Failed to load webhooks'));
    } finally {
      setLoading(false);
      refreshTexts();
    }
  }

  function renderWebhooks() {
    const contentCard = document.getElementById('webhook-content');
    const emptyCard = document.getElementById('webhook-empty');
    const isEmpty = state.webhooks.length === 0;
    emptyCard.classList.toggle('d-none', !isEmpty);
    contentCard.classList.toggle('d-none', isEmpty);
    document.getElementById('webhook-count').textContent = String(state.webhooks.length);
    const rows = document.getElementById('webhookRows');
    rows.innerHTML = state.webhooks.map(renderWebhookRow).join('');
    refreshTexts(rows);
  }

  function renderWebhookRow(webhook) {
    const suiteName = webhook.script_group_id != null ? scriptGroupName(webhook.script_group_id) : '';
    const suite = suiteName
      ? `<div class="small mt-1"><span class="badge bg-light text-dark border"><i class="fas fa-layer-group me-1"></i>${escapeHtml(suiteName)}</span></div>`
      : '';
    const activeLabel = webhook.is_active
      ? t('automationHub.webhooks.active', 'Active')
      : t('automationHub.webhooks.inactive', 'Inactive');
    const lastTriggered = webhook.last_triggered_at
      ? formatDateTime(webhook.last_triggered_at)
      : t('common.notSet', 'Not set');
    const lastStatus = webhook.last_status
      ? `<span class="badge ${lastStatusBadgeClass(webhook.last_status)}">${escapeHtml(webhook.last_status)}</span>`
      : `<span class="text-muted">${escapeHtml(t('common.notSet', 'Not set'))}</span>`;
    const runsButton = webhook.script_group_id != null ? `
      <button type="button" class="btn btn-secondary btn-sm me-1" data-webhook-action="runs" data-webhook-id="${webhook.id}" title="${escapeAttr(t('automationHub.webhooks.runsTitle', 'Trigger history'))}">
        <i class="fas fa-play-circle"></i>
      </button>` : '';

    return `
      <tr>
        <td>
          <div class="fw-semibold">${escapeHtml(webhook.name)}</div>
          ${suite}
        </td>
        <td class="font-monospace small">
          <div>${escapeHtml(t('automationHub.webhooks.tokenShort', 'tok'))}: ${escapeHtml(webhook.token_fingerprint || '-')}</div>
          <div>${escapeHtml(t('automationHub.webhooks.secretShort', 'sec'))}: ${escapeHtml(webhook.secret_fingerprint || '-')}</div>
        </td>
        <td>
          <div>${escapeHtml(lastTriggered)}</div>
          <div class="mt-1">${lastStatus}</div>
        </td>
        <td>
          <div class="form-check form-switch m-0">
            <input class="form-check-input" type="checkbox" role="switch" id="webhook-active-${webhook.id}" data-active-toggle data-webhook-id="${webhook.id}" ${webhook.is_active ? 'checked' : ''}>
            <label class="form-check-label small" for="webhook-active-${webhook.id}">${escapeHtml(activeLabel)}</label>
          </div>
        </td>
        <td class="text-end automation-webhook-actions">
          ${runsButton}
          <button type="button" class="btn btn-secondary btn-sm me-1" data-webhook-action="edit" data-webhook-id="${webhook.id}" title="${escapeAttr(t('common.edit', 'Edit'))}">
            <i class="fas fa-pen"></i>
          </button>
          <button type="button" class="btn btn-warning btn-sm me-1" data-webhook-action="regenerate" data-webhook-id="${webhook.id}" title="${escapeAttr(t('automationHub.webhooks.regenerateSecret', 'Regenerate secret'))}">
            <i class="fas fa-key"></i>
          </button>
          <button type="button" class="btn btn-danger btn-sm" data-webhook-action="delete" data-webhook-id="${webhook.id}" title="${escapeAttr(t('common.delete', 'Delete'))}">
            <i class="fas fa-trash"></i>
          </button>
        </td>
      </tr>`;
  }

  function openWebhookModal(webhook) {
    if (!state.webhookModal) return;
    state.editingWebhook = webhook || null;
    const title = document.getElementById('webhookModalTitle');
    title.setAttribute('data-i18n', webhook ? 'automationHub.webhooks.editTitle' : 'automationHub.webhooks.createTitle');
    title.textContent = webhook
      ? t('automationHub.webhooks.editTitle', 'Edit Webhook')
      : t('automationHub.webhooks.createTitle', 'Add Webhook');
    document.getElementById('webhookId').value = webhook ? webhook.id : '';
    document.getElementById('webhookName').value = webhook ? webhook.name : '';
    document.getElementById('webhookActive').checked = webhook ? webhook.is_active : true;
    populateScriptGroupOptions(webhook && webhook.script_group_id != null ? String(webhook.script_group_id) : '');
    state.webhookModal.show();
    refreshTexts();
  }

  function populateScriptGroupOptions(selectedId) {
    const select = document.getElementById('webhookScriptGroup');
    if (!select) return;
    const placeholder = `<option value="" disabled ${selectedId ? '' : 'selected'} data-i18n="automationHub.webhooks.bindSuitePlaceholder">${escapeHtml(t('automationHub.webhooks.bindSuitePlaceholder', 'Select a suite…'))}</option>`;
    const options = state.scriptGroups.map((group) =>
      `<option value="${escapeAttr(String(group.id))}" ${String(group.id) === selectedId ? 'selected' : ''}>${escapeHtml(group.name)}</option>`
    ).join('');
    select.innerHTML = placeholder + options;
  }

  async function saveWebhook() {
    const webhookId = document.getElementById('webhookId').value;
    const name = document.getElementById('webhookName').value.trim();

    if (!name) {
      showError(t('automationHub.webhooks.nameRequired', 'Name is required'));
      document.getElementById('webhookName').focus();
      return;
    }

    const scriptGroupRaw = document.getElementById('webhookScriptGroup').value;
    const scriptGroupId = scriptGroupRaw ? Number(scriptGroupRaw) : null;
    if (scriptGroupId == null) {
      showError(t('automationHub.webhooks.suiteRequired', 'Inbound webhooks must be bound to a suite'));
      document.getElementById('webhookScriptGroup').focus();
      return;
    }

    const payload = {
      name,
      script_group_id: scriptGroupId,
      is_active: document.getElementById('webhookActive').checked
    };
    if (!webhookId) payload.direction = 'INBOUND';

    try {
      const result = await apiFetch(
        webhookId
          ? `/api/teams/${state.teamId}/automation-webhooks/${webhookId}`
          : `/api/teams/${state.teamId}/automation-webhooks`,
        {
          method: webhookId ? 'PATCH' : 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        }
      );
      if (state.webhookModal) state.webhookModal.hide();
      showSuccess(t('automationHub.webhooks.saveDone', 'Webhook saved'));
      await loadWebhooks();
      if (!webhookId) showCredentialModal(result, scriptGroupId);
    } catch (error) {
      showError(error.message || t('automationHub.webhooks.saveFailed', 'Failed to save webhook'));
    }
  }

  async function toggleWebhookActive(webhook, isActive) {
    try {
      await apiFetch(`/api/teams/${state.teamId}/automation-webhooks/${webhook.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ is_active: isActive })
      });
      webhook.is_active = isActive;
      renderWebhooks();
    } catch (error) {
      showError(error.message || t('automationHub.webhooks.saveFailed', 'Failed to save webhook'));
      await loadWebhooks();
    }
  }

  async function openRuns(webhook) {
    state.runsWebhookId = webhook.id;
    if (state.runsModal) state.runsModal.show();
    await loadRuns(webhook.id);
  }

  async function loadRuns(webhookId) {
    const loading = document.getElementById('webhookRunsLoading');
    if (loading) loading.classList.remove('d-none');
    try {
      const data = await apiFetch(`/api/teams/${state.teamId}/automation-webhooks/${webhookId}/runs`);
      renderRuns(data.items || []);
    } catch (error) {
      showError(error.message || t('automationHub.webhooks.runsLoadFailed', 'Failed to load runs'));
    } finally {
      if (loading) loading.classList.add('d-none');
    }
  }

  function renderRuns(items) {
    const rows = document.getElementById('webhookRunRows');
    const empty = document.getElementById('webhookRunsEmpty');
    empty.classList.toggle('d-none', items.length > 0);
    rows.innerHTML = items.map((item) => {
      const statusClass = lastStatusBadgeClass(item.status);
      const started = item.started_at ? formatDateTime(item.started_at) : '—';
      const duration = item.duration_ms != null ? `${item.duration_ms} ms` : '—';
      const jenkinsLink = item.external_run_url
        ? `<a href="${escapeAttr(item.external_run_url)}" target="_blank" rel="noopener" class="btn btn-outline-secondary btn-sm me-1"><i class="fas fa-external-link-alt me-1"></i>${escapeHtml(t('automationHub.webhooks.runJenkins', 'Jenkins'))}</a>`
        : '';
      const reportLink = item.report_url
        ? `<a href="${escapeAttr(item.report_url)}" target="_blank" rel="noopener" class="btn btn-outline-secondary btn-sm"><i class="fas fa-chart-bar me-1"></i>${escapeHtml(t('automationHub.webhooks.runReport', 'Report'))}</a>`
        : '';
      const links = (jenkinsLink || reportLink) ? `${jenkinsLink}${reportLink}` : '<span class="text-muted">—</span>';
      return `
        <tr>
          <td><span class="badge ${statusClass}">${escapeHtml(item.status)}</span></td>
          <td class="font-monospace small">${escapeHtml(item.branch || '—')}</td>
          <td>${escapeHtml(started)}</td>
          <td>${escapeHtml(duration)}</td>
          <td class="text-end">${links}</td>
        </tr>`;
    }).join('');
    refreshTexts(document.getElementById('webhookRunsModal'));
  }

  async function regenerateSecret(webhook) {
    const confirmed = await AppUtils.showConfirm(t('automationHub.webhooks.regenerateConfirm', 'Regenerate this webhook secret? Existing clients must update their secret.'));
    if (!confirmed) return;
    try {
      const result = await apiFetch(`/api/teams/${state.teamId}/automation-webhooks/${webhook.id}/regenerate-secret`, { method: 'POST' });
      showSuccess(t('automationHub.webhooks.regenerateDone', 'Secret regenerated'));
      await loadWebhooks();
      showCredentialModal(result, webhook.script_group_id != null ? webhook.script_group_id : null);
    } catch (error) {
      showError(error.message || t('automationHub.webhooks.regenerateFailed', 'Failed to regenerate secret'));
    }
  }

  async function deleteWebhook(webhook) {
    const confirmed = await AppUtils.showConfirm(t('automationHub.webhooks.deleteConfirm', 'Delete this webhook?'));
    if (!confirmed) return;
    try {
      await apiFetch(`/api/teams/${state.teamId}/automation-webhooks/${webhook.id}`, { method: 'DELETE' });
      showSuccess(t('automationHub.webhooks.deleteDone', 'Webhook deleted'));
      await loadWebhooks();
    } catch (error) {
      showError(error.message || t('automationHub.webhooks.deleteFailed', 'Failed to delete webhook'));
    }
  }

  function showCredentialModal(credentials, scriptGroupId) {
    if (!state.credentialModal) return;
    document.getElementById('webhookToken').value = credentials.token || '';
    document.getElementById('webhookSecret').value = credentials.secret || '';
    const hasSuite = scriptGroupId != null;
    const triggerEndpoint = hasSuite ? `${window.location.origin}/api/v1/webhooks/ci/${encodeURIComponent(credentials.token)}/trigger` : '';
    document.getElementById('webhookTriggerEndpoint').value = triggerEndpoint;
    document.getElementById('webhookTriggerWrap').classList.toggle('d-none', !hasSuite);
    state.lastTriggerCurl = hasSuite ? buildTriggerCurlExample(triggerEndpoint) : '';
    document.getElementById('webhookTriggerCurlExample').textContent = state.lastTriggerCurl;
    document.getElementById('copyTriggerCurlBtn').disabled = !hasSuite;
    state.lastPollCurl = hasSuite ? buildPollCurlExample(triggerEndpoint) : '';
    document.getElementById('webhookPollCurlExample').textContent = state.lastPollCurl;
    document.getElementById('copyPollCurlBtn').disabled = !hasSuite;
    state.credentialModal.show();
    refreshTexts();
  }

  function buildTriggerCurlExample(endpoint) {
    // The URL token is the credential — paste-and-run, no HMAC step required.
    // (Optional: add -H "X-TCRT-Signature: sha256=<hmac>" for payload integrity.)
    return `curl -X POST '${endpoint}'`;
  }

  function buildPollCurlExample(triggerEndpoint) {
    // Pure poll — pairs with the trigger example above as step 2. Paste the
    // tcrt_correlation_id from the trigger response, then loop until terminal.
    // The token in the URL is the credential; no signature needed.
    const pollBase = triggerEndpoint.replace(/\/trigger$/, '/runs');
    return [
      '# Requires jq. Paste the tcrt_correlation_id from the trigger response above.',
      "CID='<tcrt_correlation_id>'",
      'while :; do',
      `  RESULT=$(curl -fsS '${pollBase}/'"$CID")`,
      '  case "$(echo "$RESULT" | jq -r .status)" in',
      '    SUCCEEDED|FAILED|CANCELLED) echo "$RESULT" | jq; break ;;',
      '    *) sleep 10 ;;',
      '  esac',
      'done',
    ].join('\n');
  }

  function scriptGroupName(groupId) {
    const group = state.scriptGroups.find((item) => String(item.id) === String(groupId));
    return group ? group.name : '';
  }

  function applyTeamLinks() {
    const suffix = `?team_id=${encodeURIComponent(state.teamId)}`;
    const automationHubLink = document.getElementById('automationHubLink');
    if (automationHubLink) automationHubLink.href = `/automation-hub${suffix}`;
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

  function showNoTeam() {
    const noTeam = document.getElementById('webhook-no-team');
    const content = document.getElementById('webhook-content');
    if (noTeam) noTeam.classList.remove('d-none');
    if (content) content.classList.add('d-none');
  }

  function setLoading(isLoading) {
    const loading = document.getElementById('webhook-loading');
    if (loading) loading.classList.toggle('d-none', !isLoading);
    if (isLoading) {
      const empty = document.getElementById('webhook-empty');
      const content = document.getElementById('webhook-content');
      if (empty) empty.classList.add('d-none');
      if (content) content.classList.add('d-none');
    }
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

  function formatDateTime(value) {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    return date.toLocaleString();
  }

  function lastStatusBadgeClass(status) {
    if (!status) return 'bg-secondary';
    const upper = String(status).toUpperCase();
    if (upper.includes('FAIL') || upper.includes('ERROR') || upper.includes('5')) return 'bg-danger';
    if (upper.includes('OK') || upper.includes('COMPLETED')) return 'bg-success';
    if (upper.includes('TEST')) return 'bg-info text-dark';
    if (upper.includes('RECEIVED') || upper.includes('TRACKED')) return 'bg-secondary';
    return 'bg-warning text-dark';
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

  function t(key, fallback) {
    return window.i18n && window.i18n.t ? window.i18n.t(key, {}, fallback) : fallback;
  }

  async function copyField(fieldId) {
    const field = document.getElementById(fieldId);
    await copyText(field.value);
  }

  async function copyText(value) {
    if (!value) return;
    try {
      await navigator.clipboard.writeText(value);
    } catch (error) {
      const textarea = document.createElement('textarea');
      textarea.value = value;
      textarea.setAttribute('readonly', 'readonly');
      textarea.style.position = 'fixed';
      textarea.style.opacity = '0';
      document.body.appendChild(textarea);
      textarea.select();
      document.execCommand('copy');
      document.body.removeChild(textarea);
    }
    showSuccess(t('common.copied', 'Copied'));
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
