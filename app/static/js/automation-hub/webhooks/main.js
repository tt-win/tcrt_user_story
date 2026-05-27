(function () {
  const WEBHOOK_EVENTS = [
    { value: 'script.discovered', key: 'eventScriptDiscovered', fallback: 'script.discovered' },
    { value: 'script.synced', key: 'eventScriptSynced', fallback: 'script.synced' },
    { value: 'script.linked', key: 'eventScriptLinked', fallback: 'script.linked' },
    { value: 'script.unlinked', key: 'eventScriptUnlinked', fallback: 'script.unlinked' },
    { value: 'run.triggered', key: 'eventRunTriggered', fallback: 'run.triggered' },
    { value: 'run.tracked', key: 'eventRunTracked', fallback: 'run.tracked' },
    { value: 'run.completed', key: 'eventRunCompleted', fallback: 'run.completed' }
  ];

  const state = {
    teamId: null,
    webhooks: [],
    scriptGroups: [],
    editingWebhook: null,
    webhookModal: null,
    credentialModal: null,
    deliveriesModal: null,
    deliveriesWebhookId: null,
    lastCurlExample: '',
    lastTriggerCurl: ''
  };

  document.addEventListener('DOMContentLoaded', init);
  document.addEventListener('i18nReady', refreshTexts);
  document.addEventListener('languageChanged', () => {
    renderEventOptions(collectEvents());
    renderWebhooks();
    refreshTexts();
  });
  window.addEventListener('pageshow', refreshTexts);

  function init() {
    state.teamId = resolveTeamId();
    state.webhookModal = new bootstrap.Modal(document.getElementById('webhookModal'));
    state.credentialModal = new bootstrap.Modal(document.getElementById('webhookCredentialModal'));
    state.deliveriesModal = new bootstrap.Modal(document.getElementById('webhookDeliveriesModal'));
    bindEvents();

    if (!state.teamId) {
      showNoTeam();
      return;
    }

    applyTeamLinks();
    showTeamBadge();
    renderEventOptions([]);
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
    document.getElementById('addWebhookBtn').addEventListener('click', () => openWebhookModal());
    document.getElementById('refreshWebhooksBtn').addEventListener('click', loadWebhooks);
    const emptyAdd = document.getElementById('emptyStateAddWebhookBtn');
    if (emptyAdd) emptyAdd.addEventListener('click', () => openWebhookModal());
    document.getElementById('webhookDirection').addEventListener('change', updateDirectionFields);
    document.getElementById('saveWebhookBtn').addEventListener('click', saveWebhook);
    document.getElementById('copyTokenBtn').addEventListener('click', () => copyField('webhookToken'));
    document.getElementById('copySecretBtn').addEventListener('click', () => copyField('webhookSecret'));
    document.getElementById('copyEndpointBtn').addEventListener('click', () => copyField('webhookEndpoint'));
    document.getElementById('copyTriggerBtn').addEventListener('click', () => copyField('webhookTriggerEndpoint'));
    document.getElementById('copyTriggerCurlBtn').addEventListener('click', () => copyText(state.lastTriggerCurl));
    document.getElementById('copyCurlBtn').addEventListener('click', () => copyText(state.lastCurlExample));

    document.getElementById('webhookRows').addEventListener('click', (event) => {
      const button = event.target.closest('[data-webhook-action]');
      if (!button) return;
      const webhook = state.webhooks.find((item) => String(item.id) === button.dataset.webhookId);
      if (!webhook) return;
      if (button.dataset.webhookAction === 'edit') openWebhookModal(webhook);
      if (button.dataset.webhookAction === 'regenerate') regenerateSecret(webhook);
      if (button.dataset.webhookAction === 'delete') deleteWebhook(webhook);
      if (button.dataset.webhookAction === 'test') testPing(webhook);
      if (button.dataset.webhookAction === 'deliveries') openDeliveries(webhook);
    });

    document.getElementById('webhookDeliveryRows').addEventListener('click', (event) => {
      const button = event.target.closest('[data-webhook-action="replay"]');
      if (button) replayDelivery(button.dataset.deliveryId);
    });

    document.getElementById('webhookRows').addEventListener('change', (event) => {
      if (!event.target.matches('[data-active-toggle]')) return;
      const webhook = state.webhooks.find((item) => String(item.id) === event.target.dataset.webhookId);
      if (webhook) toggleWebhookActive(webhook, event.target.checked);
    });
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
    const direction = String(webhook.direction || '').toUpperCase();
    const isOutbound = direction === 'OUTBOUND';
    const directionClass = isOutbound ? 'bg-warning text-dark' : 'bg-info text-dark';
    const directionLabel = isOutbound
      ? t('automationHub.webhooks.directionOutbound', 'Outbound')
      : t('automationHub.webhooks.directionInbound', 'Inbound');
    const target = webhook.target_url
      ? `<div class="text-muted small text-truncate automation-webhook-target" title="${escapeAttr(webhook.target_url)}">${escapeHtml(webhook.target_url)}</div>`
      : '';
    const suiteName = webhook.script_group_id != null ? scriptGroupName(webhook.script_group_id) : '';
    const suite = suiteName
      ? `<div class="small mt-1"><span class="badge bg-light text-dark border"><i class="fas fa-layer-group me-1"></i>${escapeHtml(suiteName)}</span></div>`
      : '';
    const events = (webhook.events || []).length
      ? webhook.events.map((eventName) => `<span class="badge bg-light text-dark border">${escapeHtml(eventName)}</span>`).join('')
      : `<span class="text-muted">${escapeHtml(t('automationHub.webhooks.noEvents', 'None'))}</span>`;
    const activeLabel = webhook.is_active
      ? t('automationHub.webhooks.active', 'Active')
      : t('automationHub.webhooks.inactive', 'Inactive');
    const lastTriggered = webhook.last_triggered_at
      ? formatDateTime(webhook.last_triggered_at)
      : t('common.notSet', 'Not set');
    const lastStatus = webhook.last_status
      ? `<span class="badge ${lastStatusBadgeClass(webhook.last_status)}">${escapeHtml(webhook.last_status)}</span>`
      : `<span class="text-muted">${escapeHtml(t('common.notSet', 'Not set'))}</span>`;
    const testButton = isOutbound ? `
      <button type="button" class="btn btn-info btn-sm me-1" data-webhook-action="test" data-webhook-id="${webhook.id}" title="${escapeAttr(t('automationHub.webhooks.testPing', 'Send test ping'))}">
        <i class="fas fa-vial"></i>
      </button>` : '';

    return `
      <tr>
        <td><span class="badge ${directionClass}">${escapeHtml(directionLabel)}</span></td>
        <td>
          <div class="fw-semibold">${escapeHtml(webhook.name)}</div>
          ${target}
          ${suite}
        </td>
        <td class="font-monospace small">
          <div>${escapeHtml(t('automationHub.webhooks.tokenShort', 'tok'))}: ${escapeHtml(webhook.token_fingerprint || '-')}</div>
          <div>${escapeHtml(t('automationHub.webhooks.secretShort', 'sec'))}: ${escapeHtml(webhook.secret_fingerprint || '-')}</div>
        </td>
        <td><div class="automation-webhook-events">${events}</div></td>
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
          ${testButton}
          <button type="button" class="btn btn-secondary btn-sm me-1" data-webhook-action="edit" data-webhook-id="${webhook.id}" title="${escapeAttr(t('common.edit', 'Edit'))}">
            <i class="fas fa-pen"></i>
          </button>
          <button type="button" class="btn btn-secondary btn-sm me-1" data-webhook-action="deliveries" data-webhook-id="${webhook.id}" title="${escapeAttr(t('automationHub.webhooks.deliveriesTitle', 'Recent deliveries'))}">
            <i class="fas fa-history"></i>
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
    state.editingWebhook = webhook || null;
    const direction = webhook ? String(webhook.direction || 'INBOUND') : 'INBOUND';
    const title = document.getElementById('webhookModalTitle');
    title.setAttribute('data-i18n', webhook ? 'automationHub.webhooks.editTitle' : 'automationHub.webhooks.createTitle');
    title.textContent = webhook
      ? t('automationHub.webhooks.editTitle', 'Edit Webhook')
      : t('automationHub.webhooks.createTitle', 'Add Webhook');
    document.getElementById('webhookId').value = webhook ? webhook.id : '';
    document.getElementById('webhookDirection').value = direction;
    document.getElementById('webhookDirection').disabled = Boolean(webhook);
    document.getElementById('webhookName').value = webhook ? webhook.name : '';
    document.getElementById('webhookTargetUrl').value = webhook ? (webhook.target_url || '') : '';
    document.getElementById('webhookActive').checked = webhook ? webhook.is_active : true;
    renderEventOptions(webhook ? webhook.events || [] : []);
    populateScriptGroupOptions(webhook && webhook.script_group_id != null ? String(webhook.script_group_id) : '');
    updateDirectionFields();
    state.webhookModal.show();
    refreshTexts();
  }

  function updateDirectionFields() {
    const direction = document.getElementById('webhookDirection').value;
    const outbound = direction === 'OUTBOUND';
    document.getElementById('webhookTargetWrap').classList.toggle('d-none', !outbound);
    document.getElementById('webhookEventsWrap').classList.toggle('d-none', !outbound);
    document.getElementById('webhookSuiteWrap').classList.toggle('d-none', outbound);
    document.getElementById('webhookTargetUrl').required = outbound;
  }

  function populateScriptGroupOptions(selectedId) {
    const select = document.getElementById('webhookScriptGroup');
    if (!select) return;
    const none = `<option value="" data-i18n="automationHub.webhooks.bindSuiteNone">${escapeHtml(t('automationHub.webhooks.bindSuiteNone', 'No suite (status callback only)'))}</option>`;
    const options = state.scriptGroups.map((group) =>
      `<option value="${escapeAttr(String(group.id))}" ${String(group.id) === selectedId ? 'selected' : ''}>${escapeHtml(group.name)}</option>`
    ).join('');
    select.innerHTML = none + options;
  }

  function renderEventOptions(selectedEvents) {
    const selected = new Set(selectedEvents || []);
    const container = document.getElementById('webhookEventOptions');
    if (!container) return;
    container.innerHTML = WEBHOOK_EVENTS.map((eventInfo) => `
      <div class="form-check form-check-inline">
        <input class="form-check-input" type="checkbox" id="webhook-event-${eventInfo.value}" value="${escapeAttr(eventInfo.value)}" ${selected.has(eventInfo.value) ? 'checked' : ''}>
        <label class="form-check-label" for="webhook-event-${eventInfo.value}">${escapeHtml(t(`automationHub.webhooks.${eventInfo.key}`, eventInfo.fallback))}</label>
      </div>`).join('');
  }

  async function saveWebhook() {
    const webhookId = document.getElementById('webhookId').value;
    const direction = document.getElementById('webhookDirection').value;
    const outbound = direction === 'OUTBOUND';
    const name = document.getElementById('webhookName').value.trim();
    const targetUrl = document.getElementById('webhookTargetUrl').value.trim();
    const events = collectEvents();

    if (!name) {
      showError(t('automationHub.webhooks.nameRequired', 'Name is required'));
      document.getElementById('webhookName').focus();
      return;
    }
    if (outbound && !targetUrl) {
      showError(t('automationHub.webhooks.targetUrlRequired', 'Outbound webhooks require a target URL'));
      document.getElementById('webhookTargetUrl').focus();
      return;
    }
    if (outbound && events.length === 0) {
      showError(t('automationHub.webhooks.eventsRequired', 'Pick at least one event for outbound webhooks'));
      return;
    }

    const scriptGroupRaw = document.getElementById('webhookScriptGroup').value;
    const scriptGroupId = !outbound && scriptGroupRaw ? Number(scriptGroupRaw) : null;

    const payload = {
      name,
      target_url: outbound ? targetUrl : null,
      events: outbound ? events : [],
      script_group_id: outbound ? null : scriptGroupId,
      is_active: document.getElementById('webhookActive').checked
    };
    if (!webhookId) payload.direction = direction;

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
      state.webhookModal.hide();
      showSuccess(t('automationHub.webhooks.saveDone', 'Webhook saved'));
      await loadWebhooks();
      if (!webhookId) showCredentialModal(result, direction, scriptGroupId);
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

  async function openDeliveries(webhook) {
    state.deliveriesWebhookId = webhook.id;
    if (state.deliveriesModal) state.deliveriesModal.show();
    await loadDeliveries(webhook.id);
  }

  async function loadDeliveries(webhookId) {
    const loading = document.getElementById('webhookDeliveriesLoading');
    if (loading) loading.classList.remove('d-none');
    try {
      const data = await apiFetch(`/api/teams/${state.teamId}/automation-webhooks/${webhookId}/deliveries`);
      renderDeliveries(data.items || []);
    } catch (error) {
      showError(error.message || t('automationHub.webhooks.deliveriesLoadFailed', 'Failed to load deliveries'));
    } finally {
      if (loading) loading.classList.add('d-none');
    }
  }

  function renderDeliveries(items) {
    const rows = document.getElementById('webhookDeliveryRows');
    const empty = document.getElementById('webhookDeliveriesEmpty');
    empty.classList.toggle('d-none', items.length > 0);
    rows.innerHTML = items.map((item) => {
      const statusClass = lastStatusBadgeClass(item.status);
      const code = item.status_code ? ` ${item.status_code}` : '';
      const completed = item.completed_at ? formatDateTime(item.completed_at) : '—';
      return `
        <tr>
          <td><code>${escapeHtml(item.event)}</code></td>
          <td class="font-monospace small">${escapeHtml(item.delivery_id)}</td>
          <td><span class="badge ${statusClass}">${escapeHtml(item.status)}${escapeHtml(code)}</span></td>
          <td>${escapeHtml(item.duration_ms)} ms</td>
          <td>${escapeHtml(completed)}</td>
          <td class="text-end">
            <button type="button" class="btn btn-warning btn-sm" data-webhook-action="replay" data-webhook-id="${item.webhook_id}" data-delivery-id="${item.id}" title="${escapeAttr(t('automationHub.webhooks.replay', 'Replay'))}">
              <i class="fas fa-redo"></i>
            </button>
          </td>
        </tr>`;
    }).join('');
    refreshTexts(document.getElementById('webhookDeliveriesModal'));
  }

  async function replayDelivery(deliveryId) {
    if (!deliveryId) return;
    try {
      await apiFetch(`/api/teams/${state.teamId}/automation-webhooks/deliveries/${deliveryId}/replay`, { method: 'POST' });
      showSuccess(t('automationHub.webhooks.replayDone', 'Delivery replayed'));
      if (state.deliveriesWebhookId) await loadDeliveries(state.deliveriesWebhookId);
      await loadWebhooks();
    } catch (error) {
      showError(error.message || t('automationHub.webhooks.replayFailed', 'Failed to replay delivery'));
    }
  }

  async function regenerateSecret(webhook) {
    const confirmed = await AppUtils.showConfirm(t('automationHub.webhooks.regenerateConfirm', 'Regenerate this webhook secret? Existing clients must update their secret.'));
    if (!confirmed) return;
    try {
      const result = await apiFetch(`/api/teams/${state.teamId}/automation-webhooks/${webhook.id}/regenerate-secret`, { method: 'POST' });
      showSuccess(t('automationHub.webhooks.regenerateDone', 'Secret regenerated'));
      await loadWebhooks();
      showCredentialModal(result, webhook.direction, webhook.script_group_id != null ? webhook.script_group_id : null);
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

  async function testPing(webhook) {
    try {
      const result = await apiFetch(`/api/teams/${state.teamId}/automation-webhooks/${webhook.id}/test`, { method: 'POST' });
      const message = `${result.status}${result.status_code ? ` ${result.status_code}` : ''}: ${result.message || ''}`.trim();
      if (result.status === 'OK') {
        showSuccess(message || t('automationHub.webhooks.testDone', 'Test ping sent'));
      } else {
        showError(message || t('automationHub.webhooks.testFailed', 'Test ping failed'));
      }
      await loadWebhooks();
    } catch (error) {
      showError(error.message || t('automationHub.webhooks.testFailed', 'Test ping failed'));
    }
  }

  function showCredentialModal(credentials, direction, scriptGroupId) {
    const inbound = String(direction || '').toUpperCase() === 'INBOUND';
    const endpoint = inbound ? `${window.location.origin}/api/v1/webhooks/ci/${encodeURIComponent(credentials.token)}/run-status` : '';
    document.getElementById('webhookToken').value = credentials.token || '';
    document.getElementById('webhookSecret').value = credentials.secret || '';
    document.getElementById('webhookEndpoint').value = endpoint;
    document.getElementById('webhookEndpointWrap').classList.toggle('d-none', !inbound);
    const hasSuite = inbound && scriptGroupId != null;
    const triggerEndpoint = hasSuite ? `${window.location.origin}/api/v1/webhooks/ci/${encodeURIComponent(credentials.token)}/trigger` : '';
    document.getElementById('webhookTriggerEndpoint').value = triggerEndpoint;
    document.getElementById('webhookTriggerWrap').classList.toggle('d-none', !hasSuite);
    state.lastTriggerCurl = hasSuite ? buildTriggerCurlExample(triggerEndpoint, credentials.secret || '') : '';
    document.getElementById('webhookTriggerCurlExample').textContent = state.lastTriggerCurl;
    document.getElementById('copyTriggerCurlBtn').disabled = !hasSuite;
    document.getElementById('copyCurlBtn').disabled = !inbound;
    state.lastCurlExample = inbound ? buildCurlExample(endpoint, credentials.secret || '') : '';
    document.getElementById('webhookCurlExample').textContent = state.lastCurlExample || t('automationHub.webhooks.outboundSecretHint', 'Use this secret to verify outbound X-TCRT-Signature headers.');
    state.credentialModal.show();
    refreshTexts();
  }

  function buildCurlExample(endpoint, secret) {
    return [
      `TCRT_WEBHOOK_URL='${endpoint}'`,
      `TCRT_WEBHOOK_SECRET='${secret}'`,
      'BODY=\'{"tcrt_run_id":"<TCRT_RUN_ID>","status":"SUCCEEDED","external_run_id":"ci-run-123","report_url":"https://allure.example/runs/123"}\'',
      'SIG=$(printf \'%s\' "$BODY" | openssl dgst -sha256 -hmac "$TCRT_WEBHOOK_SECRET" -binary | xxd -p -c 256)',
      'curl -X POST "$TCRT_WEBHOOK_URL" \\',
      '  -H "Content-Type: application/json" \\',
      '  -H "X-TCRT-Signature: sha256=$SIG" \\',
      '  -H "X-TCRT-Delivery: $(uuidgen)" \\',
      '  -d "$BODY"'
    ].join('\n');
  }

  function buildTriggerCurlExample(endpoint, secret) {
    return [
      `TCRT_TRIGGER_URL='${endpoint}'`,
      `TCRT_WEBHOOK_SECRET='${secret}'`,
      "BODY='{}'",
      'SIG=$(printf \'%s\' "$BODY" | openssl dgst -sha256 -hmac "$TCRT_WEBHOOK_SECRET" -binary | xxd -p -c 256)',
      'curl -X POST "$TCRT_TRIGGER_URL" \\',
      '  -H "Content-Type: application/json" \\',
      '  -H "X-TCRT-Signature: sha256=$SIG" \\',
      '  -d "$BODY"'
    ].join('\n');
  }

  function collectEvents() {
    return Array.from(document.querySelectorAll('#webhookEventOptions input:checked')).map((input) => input.value);
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
    document.getElementById('webhook-no-team').classList.remove('d-none');
    document.getElementById('webhook-content').classList.add('d-none');
  }

  function setLoading(isLoading) {
    document.getElementById('webhook-loading').classList.toggle('d-none', !isLoading);
    if (isLoading) {
      document.getElementById('webhook-empty').classList.add('d-none');
      document.getElementById('webhook-content').classList.add('d-none');
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
