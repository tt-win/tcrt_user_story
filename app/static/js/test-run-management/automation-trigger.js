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

  function getSuiteSummary(suiteId) {
    const normalizedId = Number(suiteId);
    return (_currentSuiteSummaries || []).find((suite) => Number(suite.id) === normalizedId) || null;
  }

  function describeSuite(suiteId) {
    const suite = getSuiteSummary(suiteId);
    if (!suite) return `Suite #${suiteId}`;
    const scriptCount = typeof suite.script_count === 'number' ? ` (${suite.script_count} scripts)` : '';
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
      showToast('error', 'Automation suite 不在目前 Set 中');
      return;
    }
    await runAutomation([normalizedId], { single: true, button });
  }

  async function runAutomation(suiteIds, options = {}) {
    if (!_currentSetId) {
      showToast('error', 'Set 尚未載入，請重整頁面');
      return;
    }
    if (!Array.isArray(suiteIds) || suiteIds.length === 0) {
      showToast('error', 'Set 沒有關聯的 automation suite');
      return;
    }

    const teamId = resolveTeamId();
    if (!teamId) return;

    const single = !!options.single;
    const suiteLines = suiteIds.map((id) => `- ${describeSuite(id)}`).join('\n');
    const singleSuiteName = single ? describeSuite(suiteIds[0]) : '';
    const confirmed = window.confirm(single
      ? (
          window.i18n?.t('testRun.sets.detail.runAutomationSuiteConfirm', { name: singleSuiteName })
          || `即將觸發「${singleSuiteName}」automation suite。\n確認後將送 CIProvider.trigger_run。`
        )
      : (
          `即將觸發 ${suiteIds.length} 個 automation suite。\n${suiteLines}\n` +
          '確認後將對每個 suite 送 CIProvider.trigger_run。'
        )
    );
    if (!confirmed) return;

    const btn = options.button || document.getElementById('setDetailRunAutomationBtn');
    if (btn) btn.disabled = true;
    try {
      const response = await window.AuthClient.fetch(
        `/api/teams/${teamId}/test-run-sets/${_currentSetId}/run-automation`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(single ? { suite_id: suiteIds[0] } : {}),
        }
      );
      if (!response.ok) {
        const payload = await response.json().catch(() => ({ detail: null }));
        throw new Error(errorMessageFromPayload(payload, 'Trigger 失敗'));
      }
      const result = await response.json();
      const triggeredSuiteIds = result && result.triggered_suite_ids ? result.triggered_suite_ids : [];
      const runIds = result && result.run_ids ? result.run_ids : [];
      const successMessage = single
        ? (
            window.i18n?.t('testRun.sets.detail.runAutomationSuiteSuccess', { name: singleSuiteName })
            || `已觸發 ${singleSuiteName} automation suite run`
          )
        : `已觸發 ${triggeredSuiteIds.length} 個 automation suite run（run_ids: ${runIds.join(', ')}）`;
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
      const msg = (error && error.message) || 'Trigger 失敗';
      showToast('error', `${code ? `[${code}] ` : ''}${msg}`);
    } finally {
      updateButtonState();
      if (options.button) options.button.disabled = false;
    }
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
    showToast('error', '找不到當前 team');
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
