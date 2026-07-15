/* ============================================================
   TEST RUN MANAGEMENT — Run-as-Automation trigger.

   Sends POST /api/teams/{team_id}/test-run-sets/{set_id}/run-automation
   to trigger every automation suite associated with the set. See
   openspec/changes/move-automation-execution-to-test-run-set/.
   ============================================================ */

(function () {
  let _currentSetId = null;
  let _currentSuiteIds = [];
  let _currentSuiteSummaries = [];

  document.addEventListener('DOMContentLoaded', init);

  function init() {
    const btn = document.getElementById('setDetailRunAutomationBtn');
    if (btn) {
      btn.addEventListener('click', onRunAutomationClick);
    }
  }

  /**
   * Called by set-modal.js whenever a Test Run Set detail is rendered.
   * Re-renders the "Automation Suites" badge list and enables/disables
   * the "Run as Automation" button based on the suite count.
   */
  function setAutomationSuites(suiteIds, suiteSummaries = []) {
    _currentSetId = window._currentTestRunSetId || _currentSetId;
    _currentSuiteIds = Array.isArray(suiteIds) ? suiteIds.slice() : [];
    _currentSuiteSummaries = Array.isArray(suiteSummaries) ? suiteSummaries.slice() : [];
    updateButtonState();
  }

  function updateButtonState() {
    const btn = document.getElementById('setDetailRunAutomationBtn');
    if (!btn) return;
    const enabled = _currentSuiteIds.length > 0 && !!_currentSetId;
    btn.disabled = !enabled;
    btn.dataset.setId = _currentSetId ? String(_currentSetId) : '';
  }

  function refreshI18n(root) {
    if (window.i18n && window.i18n.isReady && window.i18n.isReady()) {
      window.i18n.retranslate(root);
    }
  }

  function translate(key, fallback, params = {}) {
    try {
      if (window.i18n && typeof window.i18n.t === 'function') {
        const value = window.i18n.t(key, params);
        if (value && value !== key) return value;
      }
    } catch (_) {}
    return fallback;
  }

  function getSuiteSummary(suiteId) {
    const normalizedId = Number(suiteId);
    return (_currentSuiteSummaries || []).find((suite) => Number(suite.id) === normalizedId) || null;
  }

  function describeSuite(suiteId) {
    const suite = getSuiteSummary(suiteId);
    if (!suite) return translate('testRun.sets.detail.automationSuiteFallback', 'Suite #{id}', { id: suiteId });
    const scriptCount = typeof suite.script_count === 'number'
      ? ` (${translate('testRun.sets.common.scriptsCount', '{count} scripts', { count: suite.script_count })})`
      : '';
    return `${suite.name}${scriptCount}`;
  }

  function errorMessageFromPayload(payload, fallback) {
    const detail = payload && payload.detail;
    if (detail && typeof detail === 'object' && detail.message) return detail.message;
    if (typeof detail === 'string') return detail;
    return fallback;
  }

  async function onRunAutomationClick(event) {
    await runAllAutomationSuites(event?.currentTarget || null);
  }

  async function runAllAutomationSuites(button) {
    await runAutomation(_currentSuiteIds, { single: false, button });
  }

  async function runAutomationSuite(suiteId, button) {
    const normalizedId = Number(suiteId);
    if (!normalizedId || !_currentSuiteIds.includes(normalizedId)) {
      showToast('error', translate('testRun.sets.detail.automationSuiteNotInSet', 'Automation suite 不在目前 Set 中'));
      return;
    }
    await runAutomation([normalizedId], { single: true, button });
  }

  async function runAutomation(suiteIds, options = {}) {
    if (!_currentSetId) {
      showToast('error', translate('testRun.sets.detail.setNotLoaded', 'Set 尚未載入，請重整頁面'));
      return;
    }
    if (!Array.isArray(suiteIds) || suiteIds.length === 0) {
      showToast('error', translate('testRun.sets.detail.automationSuitesEmpty', 'Set 沒有關聯的 automation suite'));
      return;
    }

    const teamId = resolveTeamId();
    if (!teamId) return;

    const single = !!options.single;
    const suiteLines = suiteIds.map((id) => `- ${describeSuite(id)}`).join('\n');
    const singleSuiteName = single ? describeSuite(suiteIds[0]) : '';
    const confirmed = window.confirm(single
      ? (
          translate(
            'testRun.sets.detail.runAutomationSuiteConfirm',
            `即將觸發「${singleSuiteName}」automation suite。\n確認後將送 CIProvider.trigger_run。`,
            { name: singleSuiteName }
          )
        )
      : (
          translate(
            'testRun.sets.detail.runAutomationConfirm',
            `即將觸發 ${suiteIds.length} 個 automation suite。\n${suiteLines}\n確認後將對每個 suite 送 CIProvider.trigger_run。`,
            { count: suiteIds.length, suites: suiteLines }
          )
        )
    );
    if (!confirmed) return;

    const btn = options.button || document.getElementById('setDetailRunAutomationBtn');
    if (btn) btn.disabled = true;
    try {
      // Environment selector (a dropdown button) lives in the set detail
      // automation actions row; the chosen value is on its data-env-value.
      // "" → omit (team default applies server-side).
      const envSelect = document.getElementById('setDetailEnvironmentSelector');
      const environment = envSelect && envSelect.dataset.envValue ? envSelect.dataset.envValue : null;
      const body = single ? { suite_id: suiteIds[0] } : {};
      if (environment) body.environment = environment;

      const response = await window.AuthClient.fetch(
        `/api/teams/${teamId}/test-run-sets/${_currentSetId}/run-automation`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        }
      );
      if (!response.ok) {
        const payload = await response.json().catch(() => ({ detail: null }));
        // Surface the two structured environment errors with clear guidance.
        if (handleEnvironmentError(response.status, payload)) return;
        throw new Error(errorMessageFromPayload(payload, translate('testRun.sets.detail.runAutomationFailed', 'Trigger 失敗')));
      }
      const result = await response.json();
      const triggeredSuiteIds = result && result.triggered_suite_ids ? result.triggered_suite_ids : [];
      const runIds = result && result.run_ids ? result.run_ids : [];
      const successMessage = single
        ? (
            translate(
              'testRun.sets.detail.runAutomationSuiteSuccess',
              `已觸發 ${singleSuiteName} automation suite run`,
              { name: singleSuiteName }
            )
          )
        : translate(
            'testRun.sets.detail.runAutomationSuccess',
            `已觸發 ${triggeredSuiteIds.length} 個 automation suite run（run_ids: ${runIds.join(', ')}）`,
            { count: triggeredSuiteIds.length, runIds: runIds.join(', ') }
          );
      showToast('success', successMessage);
      // Tell set-modal.js to refresh the recent-runs area
      document.dispatchEvent(new CustomEvent('automation:run-triggered', {
        detail: { setId: _currentSetId, suiteIds: triggeredSuiteIds, runIds },
      }));
      if (typeof window.refreshCurrentSetDetail === 'function') {
        await window.refreshCurrentSetDetail();
      }
    } catch (error) {
      const code = (error && error.detail && error.detail.code) || '';
      const msg = (error && error.message) || translate('testRun.sets.detail.runAutomationFailed', 'Trigger 失敗');
      showToast('error', `${code ? `[${code}] ` : ''}${msg}`);
    } finally {
      updateButtonState();
      if (options.button) options.button.disabled = false;
    }
  }

  // Handle the structured 422 environment errors from run-automation:
  //   ENVIRONMENT_REQUIRED   → no environment chosen but the team requires one
  //   ENVIRONMENT_INCOMPLETE → chosen env is missing required vars per script
  // Returns true when the error was handled (caller should stop).
  function handleEnvironmentError(status, payload) {
    if (status !== 422) return false;
    const detail = payload && payload.detail;
    if (!detail || typeof detail !== 'object') return false;
    const code = detail.code;

    if (code === 'ENVIRONMENT_REQUIRED') {
      const msg = translate(
        'testRun.sets.detail.runAutomationEnvRequired',
        'Select an environment before running automation.'
      );
      showToast('error', detail.message ? `${msg} (${detail.message})` : msg);
      const selector = document.getElementById('setDetailEnvironmentSelector');
      if (selector && typeof selector.focus === 'function') selector.focus();
      return true;
    }

    if (code === 'ENVIRONMENT_INCOMPLETE') {
      const intro = translate(
        'testRun.sets.detail.runAutomationEnvIncomplete',
        'The selected environment is missing required variables for some scripts. Open the Script view to configure them.'
      );
      const missing = (detail.missing && typeof detail.missing === 'object') ? detail.missing : {};
      const lines = Object.keys(missing).map((refPath) => {
        const keys = Array.isArray(missing[refPath]) ? missing[refPath].join(', ') : String(missing[refPath]);
        const tmpl = translate(
          'testRun.sets.detail.runAutomationEnvIncompleteScript',
          `${refPath}: missing ${keys}`,
          { ref: refPath, keys }
        );
        // i18n template may not interpolate (depends on helper); fall back to manual.
        return (tmpl && tmpl.indexOf('{ref}') === -1) ? tmpl : `${refPath}: ${keys}`;
      });
      const message = lines.length ? `${intro}\n${lines.join('\n')}` : intro;
      showToast('error', message);
      return true;
    }

    return false;
  }

  function resolveTeamId() {
    if (window.AppUtils && typeof window.AppUtils.getCurrentTeamId === 'function') {
      const teamId = window.AppUtils.getCurrentTeamId();
      if (teamId) return teamId;
    }
    if (window.AppUtils && window.AppUtils.getCurrentTeam) {
      const team = window.AppUtils.getCurrentTeam();
      if (team && team.id) return team.id;
    }
    try {
      const urlTeamId = new URLSearchParams(window.location.search).get('team_id');
      if (urlTeamId) return urlTeamId;
    } catch (_) {}
    if (typeof currentTeamId !== 'undefined' && currentTeamId) {
      return currentTeamId;
    }
    if (typeof window.currentTeamId !== 'undefined' && window.currentTeamId) {
      return window.currentTeamId;
    }
    showToast('error', translate('messages.pleaseSelectTeam', '找不到當前 team'));
    return null;
  }

  function showToast(kind, message) {
    if (window.notify && typeof window.notify[kind] === 'function') {
      window.notify[kind](message);
      return;
    }
    if (window.i18n && window.i18n.t) {
      // best-effort: just show raw message
    }
    if (typeof console !== 'undefined') {
      console[kind === 'error' ? 'error' : 'log'](message);
    }
  }

  function escapeHtml(value) {
    return String(value ?? '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  // Public surface for set-modal.js to call after rendering set detail.
  window.TestRunSetAutomation = { setAutomationSuites, runAllAutomationSuites, runAutomationSuite };
  })();
