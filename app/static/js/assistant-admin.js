/**
 * Super Admin assistant prompt / skills editor.
 */
(function () {
  'use strict';

  const state = {
    promptVersion: null,
    skills: [],
    editingId: null,
    isNew: false,
    isBuiltin: false,
  };

  function t(key, fallback) {
    try {
      if (window.i18n && typeof window.i18n.t === 'function') {
        const v = window.i18n.t(key);
        if (v && v !== key) return v;
      }
    } catch (_) {}
    return fallback;
  }

  function authFetch(url, options) {
    if (window.AuthClient && typeof window.AuthClient.fetch === 'function') {
      return window.AuthClient.fetch(url, options);
    }
    return fetch(url, options);
  }

  function formatApiError(data, resp) {
    if (!data) return resp ? resp.status + ' ' + resp.statusText : 'unknown error';
    const d = data.detail;
    if (d == null) return data.message || JSON.stringify(data);
    if (typeof d === 'string') return d;
    if (Array.isArray(d)) {
      return d
        .map(function (item) {
          if (typeof item === 'string') return item;
          const loc = (item.loc || []).filter(function (x) {
            return x !== 'body';
          });
          return (loc.length ? loc.join('.') + ': ' : '') + (item.msg || JSON.stringify(item));
        })
        .join('; ');
    }
    if (typeof d === 'object') {
      return d.message || d.code || JSON.stringify(d);
    }
    return String(d);
  }

  function setBanner(msg, isError) {
    const el = document.getElementById('aaSkillBanner');
    if (!el) return;
    el.textContent = msg || '';
    el.classList.toggle('d-none', !msg);
    el.classList.toggle('alert-danger', !!isError);
    el.classList.toggle('alert-success', !isError && !!msg);
    el.classList.toggle('alert-secondary', false);
  }

  function setPromptStatus(msg, isError) {
    const el = document.getElementById('aaPromptStatus');
    if (!el) return;
    el.textContent = msg || '';
    el.classList.toggle('text-danger', !!isError);
    el.classList.toggle('text-success', !isError && !!msg);
  }

  function normalizeSkillId(raw) {
    return String(raw || '')
      .trim()
      .toLowerCase()
      .replace(/_/g, '-')
      .replace(/\s+/g, '-')
      .replace(/[^a-z0-9-]/g, '')
      .replace(/-+/g, '-')
      .replace(/^-+|-+$/g, '');
  }

  async function requireSuperAdmin() {
    try {
      const resp = await authFetch('/api/auth/me');
      if (!resp.ok) throw new Error('auth ' + resp.status);
      const me = await resp.json();
      const role = String(me.role || (me.user && me.user.role) || '').toLowerCase();
      if (role !== 'super_admin') {
        document.getElementById('aaUnauthorized')?.classList.remove('d-none');
        return false;
      }
      document.getElementById('aaMain')?.classList.remove('d-none');
      return true;
    } catch (e) {
      console.error('[assistant-admin] auth failed', e);
      document.getElementById('aaUnauthorized')?.classList.remove('d-none');
      return false;
    }
  }

  async function loadPrompt() {
    try {
      const resp = await authFetch('/api/admin/assistant/system-prompt');
      if (!resp.ok) {
        const data = await resp.json().catch(function () {
          return {};
        });
        throw new Error(formatApiError(data, resp));
      }
      const data = await resp.json();
      state.promptVersion = data.version;
      document.getElementById('aaPromptEditor').value = data.content || '';
      document.getElementById('aaPromptVersion').textContent = 'v' + data.version;
      document.getElementById('aaPromptMeta').textContent =
        (data.updated_by || '') +
        ' · ' +
        (data.updated_at || '') +
        ' · ' +
        (data.content_length || 0) +
        ' chars';
      setPromptStatus('', false);
    } catch (e) {
      console.error('[assistant-admin] loadPrompt', e);
      setPromptStatus(t('assistantAdmin.loadFailed', 'Load failed') + ': ' + e.message, true);
    }
  }

  async function savePrompt() {
    const content = document.getElementById('aaPromptEditor').value;
    try {
      const resp = await authFetch('/api/admin/assistant/system-prompt', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: content, expected_version: state.promptVersion }),
      });
      const data = await resp.json().catch(function () {
        return {};
      });
      if (!resp.ok) {
        setPromptStatus(t('assistantAdmin.saveFailed', 'Save failed') + ': ' + formatApiError(data, resp), true);
        if (resp.status === 409) await loadPrompt();
        return;
      }
      state.promptVersion = data.version;
      document.getElementById('aaPromptVersion').textContent = 'v' + data.version;
      setPromptStatus(t('assistantAdmin.saved', 'Saved') + ' v' + data.version, false);
    } catch (e) {
      console.error('[assistant-admin] savePrompt', e);
      setPromptStatus(t('assistantAdmin.saveFailed', 'Save failed') + ': ' + e.message, true);
    }
  }

  async function restoreOverwrite() {
    if (
      !window.confirm(
        t(
          'assistantAdmin.confirmOverwrite',
          'Overwrite system prompt and all builtin skill bodies from factory? is_enabled flags are kept. Custom skills are not deleted.'
        )
      )
    ) {
      return;
    }
    try {
      const resp = await authFetch('/api/admin/assistant/restore', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode: 'overwrite-builtins', confirm: true }),
      });
      const data = await resp.json().catch(function () {
        return {};
      });
      if (!resp.ok) {
        setPromptStatus(formatApiError(data, resp), true);
        return;
      }
      setPromptStatus(t('assistantAdmin.restored', 'Restored') + ': ' + JSON.stringify(data), false);
      await loadPrompt();
      await loadSkills();
    } catch (e) {
      setPromptStatus(String(e.message || e), true);
    }
  }

  async function seedMissing() {
    try {
      const resp = await authFetch('/api/admin/assistant/restore', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode: 'missing-only' }),
      });
      const data = await resp.json().catch(function () {
        return {};
      });
      if (!resp.ok) {
        setBanner(formatApiError(data, resp), true);
        return;
      }
      setBanner(t('assistantAdmin.seeded', 'Seed complete') + ': ' + JSON.stringify(data), false);
      await loadSkills();
      await loadPrompt();
    } catch (e) {
      setBanner(String(e.message || e), true);
    }
  }

  function showEditor(show) {
    const card = document.getElementById('aaSkillEditorCard');
    if (!card) return;
    card.classList.toggle('d-none', !show);
    if (show) {
      try {
        card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      } catch (_) {
        card.scrollIntoView();
      }
      const focusEl = state.isNew
        ? document.getElementById('aaSkillId')
        : document.getElementById('aaSkillName');
      if (focusEl) {
        setTimeout(function () {
          focusEl.focus();
        }, 50);
      }
    }
  }

  function fillEditor(s, isNew) {
    state.isNew = !!isNew;
    state.editingId = isNew ? null : s.skill_id;
    state.isBuiltin = !isNew && !!s.is_builtin;
    const idInput = document.getElementById('aaSkillId');
    idInput.value = s.skill_id || '';
    idInput.disabled = !isNew;
    document.getElementById('aaSkillName').value = s.name || '';
    document.getElementById('aaSkillDesc').value = s.description || '';
    document.getElementById('aaSkillBody').value = s.body || '';
    document.getElementById('aaSkillTriggers').value = (s.triggers || []).join(', ');
    document.getElementById('aaSkillSort').value = s.sort_order != null ? s.sort_order : 0;
    document.getElementById('aaSkillEnabled').checked = s.is_enabled !== false;
    document.getElementById('aaSkillReset').classList.toggle('d-none', isNew || !s.is_builtin);
    document.getElementById('aaSkillDelete').classList.toggle('d-none', isNew || !!s.is_builtin);
    document.getElementById('aaSkillEditorTitle').textContent = isNew
      ? t('assistantAdmin.newSkill', 'New skill')
      : t('assistantAdmin.editSkill', 'Edit skill') + ': ' + (s.skill_id || '');
    showEditor(true);
  }

  async function loadSkills() {
    const tbody = document.getElementById('aaSkillsBody');
    if (!tbody) return;
    tbody.innerHTML = '';
    try {
      const resp = await authFetch('/api/admin/assistant/skills');
      if (!resp.ok) {
        const data = await resp.json().catch(function () {
          return {};
        });
        throw new Error(formatApiError(data, resp));
      }
      const data = await resp.json();
      state.skills = data.skills || [];
      if (!state.skills.length) {
        const tr = document.createElement('tr');
        const td = document.createElement('td');
        td.colSpan = 5;
        td.className = 'text-muted';
        td.textContent = t('assistantAdmin.noSkills', 'No skills yet. Use seed or create one.');
        tr.appendChild(td);
        tbody.appendChild(tr);
        return;
      }
      state.skills.forEach(function (s) {
        const tr = document.createElement('tr');
        tr.dataset.skillId = s.skill_id;

        const tdId = document.createElement('td');
        const code = document.createElement('code');
        code.textContent = s.skill_id;
        tdId.appendChild(code);

        const tdName = document.createElement('td');
        tdName.textContent = s.name || '';

        const tdEnabled = document.createElement('td');
        const toggle = document.createElement('input');
        toggle.type = 'checkbox';
        toggle.className = 'form-check-input';
        toggle.checked = !!s.is_enabled;
        toggle.title = t('assistantAdmin.toggleEnabled', 'Enable / disable');
        toggle.addEventListener('change', function () {
          toggleSkillEnabled(s.skill_id, toggle.checked, toggle);
        });
        tdEnabled.appendChild(toggle);

        const tdBuiltin = document.createElement('td');
        tdBuiltin.textContent = s.is_builtin
          ? t('assistantAdmin.builtin', 'builtin')
          : t('assistantAdmin.custom', 'custom');

        const tdActions = document.createElement('td');
        tdActions.className = 'text-end';
        const editBtn = document.createElement('button');
        editBtn.type = 'button';
        editBtn.className = 'btn btn-secondary btn-sm';
        editBtn.textContent = t('common.edit', 'Edit');
        editBtn.addEventListener('click', function () {
          openSkill(s.skill_id);
        });
        tdActions.appendChild(editBtn);

        tr.appendChild(tdId);
        tr.appendChild(tdName);
        tr.appendChild(tdEnabled);
        tr.appendChild(tdBuiltin);
        tr.appendChild(tdActions);
        tbody.appendChild(tr);
      });
      setBanner('', false);
    } catch (e) {
      console.error('[assistant-admin] loadSkills', e);
      setBanner(t('assistantAdmin.loadFailed', 'Load failed') + ': ' + e.message, true);
    }
  }

  async function openSkill(skillId) {
    try {
      setBanner(t('assistantAdmin.loading', 'Loading…'), false);
      const resp = await authFetch('/api/admin/assistant/skills/' + encodeURIComponent(skillId));
      const data = await resp.json().catch(function () {
        return {};
      });
      if (!resp.ok) {
        throw new Error(formatApiError(data, resp));
      }
      fillEditor(data, false);
      setBanner('', false);
    } catch (e) {
      console.error('[assistant-admin] openSkill', e);
      setBanner(t('assistantAdmin.openFailed', 'Open failed') + ': ' + e.message, true);
    }
  }

  function openNew() {
    fillEditor(
      {
        skill_id: '',
        name: '',
        description: '',
        body: '',
        triggers: [],
        sort_order: 0,
        is_enabled: true,
        is_builtin: false,
      },
      true
    );
    setBanner(t('assistantAdmin.fillNewSkill', 'Fill skill_id, name, description and body, then save.'), false);
  }

  function parseTriggers(raw) {
    return String(raw || '')
      .split(',')
      .map(function (s) {
        return s.trim();
      })
      .filter(Boolean);
  }

  function readEditorPayload() {
    let skillId = document.getElementById('aaSkillId').value;
    if (state.isNew) {
      skillId = normalizeSkillId(skillId);
      document.getElementById('aaSkillId').value = skillId;
    }
    return {
      skill_id: skillId,
      name: document.getElementById('aaSkillName').value,
      description: document.getElementById('aaSkillDesc').value,
      body: document.getElementById('aaSkillBody').value,
      triggers: parseTriggers(document.getElementById('aaSkillTriggers').value),
      is_enabled: !!document.getElementById('aaSkillEnabled').checked,
      sort_order: Number(document.getElementById('aaSkillSort').value || 0),
    };
  }

  async function saveSkill() {
    const payload = readEditorPayload();
    if (state.isNew && !payload.skill_id) {
      setBanner(t('assistantAdmin.skillIdRequired', 'skill_id is required (lowercase slug).'), true);
      return;
    }
    if (!payload.name.trim() || !payload.description.trim() || !payload.body.trim()) {
      setBanner(
        t('assistantAdmin.fieldsRequired', 'name, description and body are required.'),
        true
      );
      return;
    }
    try {
      setBanner(t('assistantAdmin.saving', 'Saving…'), false);
      let resp;
      if (state.isNew) {
        resp = await authFetch('/api/admin/assistant/skills', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
      } else {
        resp = await authFetch(
          '/api/admin/assistant/skills/' + encodeURIComponent(state.editingId || payload.skill_id),
          {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              name: payload.name,
              description: payload.description,
              body: payload.body,
              triggers: payload.triggers,
              is_enabled: payload.is_enabled,
              sort_order: payload.sort_order,
            }),
          }
        );
      }
      const data = await resp.json().catch(function () {
        return {};
      });
      if (!resp.ok) {
        setBanner(t('assistantAdmin.saveFailed', 'Save failed') + ': ' + formatApiError(data, resp), true);
        return;
      }
      state.isNew = false;
      state.editingId = data.skill_id;
      state.isBuiltin = !!data.is_builtin;
      document.getElementById('aaSkillId').disabled = true;
      document.getElementById('aaSkillId').value = data.skill_id;
      setBanner(t('assistantAdmin.saved', 'Saved') + ': ' + data.skill_id, false);
      await loadSkills();
    } catch (e) {
      console.error('[assistant-admin] saveSkill', e);
      setBanner(t('assistantAdmin.saveFailed', 'Save failed') + ': ' + e.message, true);
    }
  }

  async function toggleSkillEnabled(skillId, enabled, checkboxEl) {
    try {
      setBanner(t('assistantAdmin.saving', 'Saving…'), false);
      const resp = await authFetch('/api/admin/assistant/skills/' + encodeURIComponent(skillId), {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ is_enabled: enabled }),
      });
      const data = await resp.json().catch(function () {
        return {};
      });
      if (!resp.ok) {
        if (checkboxEl) checkboxEl.checked = !enabled;
        setBanner(t('assistantAdmin.saveFailed', 'Save failed') + ': ' + formatApiError(data, resp), true);
        return;
      }
      if (state.editingId === skillId) {
        document.getElementById('aaSkillEnabled').checked = enabled;
      }
      setBanner(
        (enabled
          ? t('assistantAdmin.enabled', 'Enabled')
          : t('assistantAdmin.disabled', 'Disabled')) +
          ': ' +
          skillId,
        false
      );
    } catch (e) {
      if (checkboxEl) checkboxEl.checked = !enabled;
      console.error('[assistant-admin] toggleSkillEnabled', e);
      setBanner(t('assistantAdmin.saveFailed', 'Save failed') + ': ' + e.message, true);
    }
  }

  async function deleteSkill() {
    if (!state.editingId || state.isBuiltin) return;
    if (!window.confirm(t('assistantAdmin.confirmDelete', 'Delete skill') + ' ' + state.editingId + '?')) {
      return;
    }
    try {
      const resp = await authFetch(
        '/api/admin/assistant/skills/' + encodeURIComponent(state.editingId),
        { method: 'DELETE' }
      );
      const data = await resp.json().catch(function () {
        return {};
      });
      if (!resp.ok) {
        setBanner(formatApiError(data, resp), true);
        return;
      }
      showEditor(false);
      setBanner(t('assistantAdmin.deleted', 'Deleted') + ': ' + state.editingId, false);
      state.editingId = null;
      await loadSkills();
    } catch (e) {
      setBanner(String(e.message || e), true);
    }
  }

  async function resetSkill() {
    if (!state.editingId || !state.isBuiltin) return;
    if (
      !window.confirm(
        t('assistantAdmin.confirmReset', 'Reset body from factory? is_enabled is kept.') +
          ' (' +
          state.editingId +
          ')'
      )
    ) {
      return;
    }
    try {
      const resp = await authFetch(
        '/api/admin/assistant/skills/' + encodeURIComponent(state.editingId) + '/reset',
        { method: 'POST' }
      );
      const data = await resp.json().catch(function () {
        return {};
      });
      if (!resp.ok) {
        setBanner(formatApiError(data, resp), true);
        return;
      }
      fillEditor(data, false);
      setBanner(t('assistantAdmin.resetDone', 'Reset to factory'), false);
    } catch (e) {
      setBanner(String(e.message || e), true);
    }
  }

  document.addEventListener('DOMContentLoaded', async function () {
    const ok = await requireSuperAdmin();
    if (!ok) return;
    document.getElementById('aaPromptReload')?.addEventListener('click', loadPrompt);
    document.getElementById('aaPromptSave')?.addEventListener('click', savePrompt);
    document.getElementById('aaPromptRestore')?.addEventListener('click', restoreOverwrite);
    document.getElementById('aaSkillsReload')?.addEventListener('click', loadSkills);
    document.getElementById('aaSkillNew')?.addEventListener('click', openNew);
    document.getElementById('aaSeedMissing')?.addEventListener('click', seedMissing);
    document.getElementById('aaSkillSave')?.addEventListener('click', saveSkill);
    document.getElementById('aaSkillDelete')?.addEventListener('click', deleteSkill);
    document.getElementById('aaSkillReset')?.addEventListener('click', resetSkill);
    document.getElementById('aaSkillCancel')?.addEventListener('click', function () {
      showEditor(false);
      setBanner('', false);
    });
    document.getElementById('aaSkillId')?.addEventListener('blur', function (ev) {
      if (state.isNew) ev.target.value = normalizeSkillId(ev.target.value);
    });
    await loadPrompt();
    await loadSkills();
  });
})();
