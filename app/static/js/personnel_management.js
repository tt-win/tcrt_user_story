// 人員管理模組（僅全域角色）
// - 僅 ADMIN / SUPER_ADMIN 可見
// - 顯示 Lark 名稱與頭像（若已關聯 lark_user_id）
// - 支援使用者 CRUD、重設密碼、Lark 關聯/解除、搜尋/分頁、未存變更警告

(function () {
  const state = {
    inited: false,
    tabInited: false, // 新增：追蹤分頁是否已初始化
    me: null, // { role, user_id }
    page: 1,
    perPage: 20,
    total: 0,
    users: [],
    selected: null, // user obj
    dirty: false,
    larkCache: new Map(), // lark_user_id -> { name, avatar }
  };

  const ROLE_LABELS = {
    viewer: 'Viewer',
    user: 'User',
    admin: 'Admin',
    super_admin: 'Super Admin',
  };

  function hasAuth() {
    const role = (state.me && state.me.role) || '';
    return role === 'admin' || role === 'super_admin';
  }

  async function fetchMe() {
    try {
      const resp = await window.AuthClient.fetch('/api/auth/me');
      if (!resp.ok) throw new Error('HTTP ' + resp.status);
      const json = await resp.json();
      state.me = { role: (json && json.role) || '' };
    } catch (e) {
      console.error('load me failed', e);
      state.me = { role: '' };
    }
  }

  function showPersonnelTabIfAllowed() {
    const li = document.getElementById('tab-personnel-li');
    if (!li) return;
    if (hasAuth()) {
      li.style.display = '';
    } else {
      li.style.display = 'none';
    }
  }

  async function init() {
    if (state.inited) return;
    await fetchMe();
    showPersonnelTabIfAllowed();

    // 預設顯示提示資訊，等待使用者選擇清單項目
    toggleDetailView(false);

    // 僅在切到人員分頁時初始化
    const tabBtn = document.getElementById('tab-personnel');
    if (tabBtn) {
      tabBtn.addEventListener('shown.bs.tab', onTabShown);
    }

    // 若分頁預設已開啟，需立即載入資料
    const pane = document.getElementById('tab-pane-personnel');
    const tabActive = tabBtn && tabBtn.classList.contains('active');
    const paneVisible = pane && (pane.classList.contains('show') || pane.classList.contains('active'));
    if (tabActive || paneVisible) {
      await onTabShown();
    }

    state.inited = true;
  }

  async function onTabShown() {
    if (state.tabInited) return; // 避免重複初始化
    
    // 先套用翻譯到人員分頁容器
    try {
      const pane = document.getElementById('tab-pane-personnel');
      if (pane && window.i18n && window.i18n.isReady()) {
        window.i18n.retranslate(pane);
      }
    } catch (_) {}

    // 綁定事件
    bindFormListeners();
    bindListControls();

    // 載入初始清單
    await loadUsers();
    
    state.tabInited = true; // 標記已初始化
  }

  function bindListControls() {
    const search = document.getElementById('pm-search');
    const prev = document.getElementById('pm-prev');
    const next = document.getElementById('pm-next');
    if (search) {
      let timer = null;
      search.addEventListener('input', () => {
        if (timer) clearTimeout(timer);
        timer = setTimeout(() => { state.page = 1; loadUsers(); }, 300);
      });
    }
    if (prev) prev.addEventListener('click', () => { if (state.page > 1) { state.page--; loadUsers(); } });
    if (next) next.addEventListener('click', () => {
      const maxPage = Math.max(1, Math.ceil(state.total / state.perPage));
      if (state.page < maxPage) { state.page++; loadUsers(); }
    });
  }

  function bindFormListeners() {
    const form = document.getElementById('pm-form');
    const fields = ['pm-username','pm-full-name','pm-email','pm-role','pm-active','pm-lark-id'];
    fields.forEach(id => {
      const el = document.getElementById(id);
      if (!el) return;
      el.addEventListener('input', markDirty);
      el.addEventListener('change', markDirty);
    });

    const btnCreate = document.getElementById('pm-create');
    const btnSave = document.getElementById('pm-save');
    const btnDelete = document.getElementById('pm-delete');
    const btnReset = document.getElementById('pm-reset');
    const btnUnlink = document.getElementById('pm-lark-unlink');

    if (btnCreate) btnCreate.addEventListener('click', onCreate);
    if (btnSave) btnSave.addEventListener('click', onSave);
    if (btnDelete) btnDelete.addEventListener('click', onDelete);
    if (btnReset) btnReset.addEventListener('click', onResetPwd);
    if (btnUnlink) btnUnlink.addEventListener('click', onLarkUnlink);

    // Lark type-to-search
    const larkSearch = document.getElementById('pm-lark-search');
    const larkDropdown = document.getElementById('pm-lark-dropdown');
    if (larkSearch && larkDropdown) {
      let timer = null;
      larkSearch.addEventListener('input', () => {
        const term = larkSearch.value.trim();
        if (timer) clearTimeout(timer);
        timer = setTimeout(async () => {
          if (!term) { hideLarkDropdown(); return; }
          try { const list = await searchLarkUsers(term); showLarkDropdown(list); } catch(_) { hideLarkDropdown(); }
        }, 300);
      });
      // 點擊外部關閉 dropdown
      document.addEventListener('click', (e) => {
        if (!larkSearch.contains(e.target) && !larkDropdown.contains(e.target)) {
          hideLarkDropdown();
        }
      });
    }
  }

  function markDirty() {
    state.dirty = true;
    const hint = document.getElementById('pm-dirty-hint');
    if (hint) hint.style.display = '';
  }

  function clearDirty() {
    state.dirty = false;
    const hint = document.getElementById('pm-dirty-hint');
    if (hint) hint.style.display = 'none';
  }

  async function loadUsers() {
    try {
      const q = (document.getElementById('pm-search')?.value || '').trim();
      const params = new URLSearchParams({ page: String(state.page), per_page: String(state.perPage) });
      if (q) params.set('search', q);
      const url = `/api/users?${params.toString()}`;
      const resp = await window.AuthClient.fetch(url);
      if (!resp.ok) throw new Error('HTTP ' + resp.status);
      const json = await resp.json();
      const rawUsers = json.users || [];
      // 前端顯示需排除 super_admin 角色
      const filteredUsers = rawUsers.filter(u => (u.role || '').toLowerCase() !== 'super_admin');
      const removedCount = rawUsers.length - filteredUsers.length;
      const reportedTotal = typeof json.total === 'number' ? json.total : filteredUsers.length;
      state.users = filteredUsers;
      state.total = Math.max(0, reportedTotal - removedCount);
      if (state.selected && (state.selected.role || '').toLowerCase() === 'super_admin') {
        state.selected = null;
        clearForm();
      }
      updatePageIndicator();
      // 預載 Lark 資料
      await preloadLarkData(state.users);
      renderUserList();
    } catch (e) {
      console.error('load users failed', e);
      toastError(window.i18n ? window.i18n.t('personnel.loadUsersFailed') : '載入使用者清單失敗');
    }
  }

  async function preloadLarkData(users) {
    console.log('PreloadLarkData started with users count:', users.length);
    const larkIds = [...new Set(users.filter(u => u.lark_user_id && u.lark_user_id.trim()).map(u => u.lark_user_id.trim()))];
    console.log('Collected larkIds:', Array.from(larkIds));
    if (larkIds.length === 0) return;
  
    try {
      // 使用 allSettled 確保即使部分 fetch 失敗，也能繼續處理其他，並最終重新渲染
      const results = await Promise.allSettled(larkIds.map(id => fetchLarkPreview(id, false)));
      results.forEach((result, index) => {
        const id = larkIds[index];
        if (result.status === 'fulfilled') {
          console.log('Fetch success for', id, 'data:', result.value);
        } else {
          console.error('Fetch failed for', id, 'reason:', result.reason);
        }
      });
      // 記錄失敗的 ID（可選，用於 debug）
      const failedIds = results.filter(r => r.status === 'rejected').map((_, idx) => larkIds[idx]);
      if (failedIds.length > 0) {
        console.warn(window.i18n ? window.i18n.t('personnel.preloadLarkFailedIds') : '部分 Lark 資料預載失敗，ID:', failedIds);
      }
      console.log('Preload complete, cache size:', state.larkCache.size, 'cache keys:', Array.from(state.larkCache.keys()));
    } catch (e) {
      console.error(window.i18n ? window.i18n.t('personnel.preloadLarkFailed') : '預載 Lark 資料失敗', e);
      // 不中斷流程，僅記錄錯誤
    }
  }

  function updatePageIndicator() {
    const el = document.getElementById('pm-page-indicator');
    if (!el) return;
    const maxPage = Math.max(1, Math.ceil(state.total / state.perPage));
    const params = { page: state.page, maxPage, total: state.total };
    const fallback = window.i18n ? window.i18n.t('personnel.pageIndicator', params) : `${state.page}/${maxPage}（共 ${state.total} 筆）`;
    el.setAttribute('data-i18n', 'personnel.pageIndicator');
    el.setAttribute('data-i18n-params', JSON.stringify(params));
    el.textContent = window.i18n ? window.i18n.t('personnel.pageIndicator', params, fallback) : fallback;
  }

  function renderUserList() {
    console.log('RenderUserList started, users count:', state.users.length, 'cache size:', state.larkCache.size);
    const box = document.getElementById('pm-user-list');
    if (!box) return;
    if (!state.users.length) {
      box.innerHTML = `<div class="list-group-item text-center text-muted">${window.i18n ? window.i18n.t('personnel.noUsers') : '無使用者'}</div>`;
      return;
    }
  
    const html = state.users.map(u => {
      const display = getDisplayName(u);
      const avatar = getAvatarUrl(u);
      console.log(`Rendering user ${u.id}: lark_user_id=${u.lark_user_id}, cache_hit=${!!(u.lark_user_id && state.larkCache.has(u.lark_user_id))}, display_name=${display}, avatar_url=${avatar}`);
      const role = (u.role || '').toUpperCase();
      return `
        <button type="button" class="list-group-item list-group-item-action d-flex align-items-center" data-user-id="${u.id}">
          <img src="${avatar}" onerror="this.src='https://www.gravatar.com/avatar/?d=mp'" class="rounded me-2" style="width:28px;height:28px;object-fit:cover;">
          <div class="flex-grow-1 text-start">
            <div class="fw-semibold">${escapeHtml(display)}</div>
            <div class="text-muted small">${escapeHtml(u.email || '')}</div>
          </div>
          <span class="badge bg-secondary">${escapeHtml(role)}</span>
        </button>`;
    }).join('');
    box.innerHTML = html;
  
    box.querySelectorAll('button[data-user-id]').forEach(btn => {
      btn.addEventListener('click', async (e) => {
        const id = Number(btn.getAttribute('data-user-id'));
        await onSelectUser(id);
      });
    });
  }

  function getDisplayName(u) {
    let larkData = null;
    if (u.lark_user_id && state.larkCache.has(u.lark_user_id)) {
      larkData = state.larkCache.get(u.lark_user_id);
    }
    console.log('getDisplayName for', u.id, 'using lark:', !!larkData, 'name:', larkData ? larkData.name : 'fallback');
    if (u.lark_user_id && state.larkCache.has(u.lark_user_id)) {
      return state.larkCache.get(u.lark_user_id).name || u.full_name || u.username || '';
    }
    return u.full_name || u.username || '';
  }

  function getAvatarUrl(u) {
    let larkData = null;
    if (u.lark_user_id && u.lark_user_id.trim() && state.larkCache.has(u.lark_user_id)) {
      larkData = state.larkCache.get(u.lark_user_id);
    }
    console.log('getAvatarUrl for', u.id, 'using lark:', !!larkData, 'avatar:', larkData ? larkData.avatar : 'fallback');
    if (u.lark_user_id && u.lark_user_id.trim() && state.larkCache.has(u.lark_user_id)) {
      const avatar = state.larkCache.get(u.lark_user_id).avatar;
      return avatar && avatar.trim() ? avatar : 'https://www.gravatar.com/avatar/?d=mp';
    }
    return 'https://www.gravatar.com/avatar/?d=mp';
  }

  async function onSelectUser(userId) {
    if (state.dirty && !confirm(window.i18n ? window.i18n.t('personnel.unsavedConfirm') : '有未儲存的變更，確定要切換嗎？')) return;
    clearDirty();

    const u = state.users.find(x => x.id === userId);
    if (!u) return;

    state.selected = u;
    // 若有 lark id，補抓預覽（快取）
    if (u.lark_user_id && !state.larkCache.has(u.lark_user_id)) {
      await fetchLarkPreview(u.lark_user_id);
    }

    fillForm(u);
    applyRoleRestrictions(u);
  }

  function fillForm(u) {
    toggleDetailView(true);
    setVal('pm-username', u.username || '');
    setVal('pm-full-name', u.full_name || '');
    setVal('pm-email', u.email || '');
    setChecked('pm-active', !!u.is_active);
    // 角色選項
    buildRoleOptions(u.role);
    // 主要團隊（目前後端未提供，僅顯示空）
    setVal('pm-primary-team', u.primary_team_id != null ? String(u.primary_team_id) : '');
    // Lark：同步隱藏值與搜尋框顯示
    setVal('pm-lark-id', u.lark_user_id || '');
    const larkSearch = document.getElementById('pm-lark-search');
    if (larkSearch) {
      if (!u.lark_user_id) {
        larkSearch.value = '';
      } else {
        // 如果快取有名稱，顯示名稱；否則先用 ID 佔位
        let text = u.lark_user_id;
        if (state.larkCache.has(u.lark_user_id)) {
          const d = state.larkCache.get(u.lark_user_id);
          text = d.name || u.lark_user_id;
        }
        larkSearch.value = text;
      }
    }
    hideLarkDropdown();
    // 僅在已選擇且有資料時顯示預覽框
    updateLarkPreviewBox(u.lark_user_id);
  }

  function toggleDetailView(showForm) {
    const form = document.getElementById('pm-form');
    const prompt = document.getElementById('pm-select-user-prompt');
    if (form) form.style.display = showForm ? '' : 'none';
    if (prompt) prompt.style.display = showForm ? 'none' : 'block';
  }

  function buildRoleOptions(selectedRole = null) {
    const sel = document.getElementById('pm-role');
    if (!sel) return;

    const meRole = (state.me && state.me.role) || '';
    const normalizedSelected = selectedRole ? String(selectedRole).toLowerCase() : '';

    const allowed = [];
    if (meRole === 'super_admin') {
      allowed.push('viewer', 'user', 'admin');
    } else if (meRole === 'admin') {
      allowed.push('viewer', 'user');
    } else {
      allowed.push('viewer');
    }

    const seen = new Set();
    const options = [];
    allowed.forEach((role) => {
      const value = role.toLowerCase();
      if (seen.has(value)) return;
      seen.add(value);
      options.push({ value, label: ROLE_LABELS[value] || value, locked: false });
    });

    if (normalizedSelected && !seen.has(normalizedSelected)) {
      seen.add(normalizedSelected);
      options.push({ value: normalizedSelected, label: ROLE_LABELS[normalizedSelected] || normalizedSelected, locked: true });
    }

    sel.innerHTML = options
      .map((opt) => `<option value="${opt.value}"${opt.locked ? ' data-locked="true"' : ''}>${opt.label}</option>`)
      .join('');

    if (normalizedSelected) {
      sel.value = normalizedSelected;
    }
  }

  function applyRoleRestrictions(targetUser) {
    const meRole = (state.me && state.me.role) || '';
    const targetRole = targetUser ? targetUser.role : '';
    buildRoleOptions(targetRole);
    const saveBtn = document.getElementById('pm-save');
    const delBtn = document.getElementById('pm-delete');
    const resetBtn = document.getElementById('pm-reset');
    const roleSel = document.getElementById('pm-role');
    const usernameInput = document.getElementById('pm-username');

    // 預設可操作
    enableEl(saveBtn, true);
    enableEl(delBtn, true);
    enableEl(resetBtn, true);
    enableEl(roleSel, true);
    enableEl(usernameInput, false); // username 一律不可修改

    const tRole = (targetUser.role || '').toLowerCase();

    if (meRole === 'admin') {
      if (tRole === 'admin' || tRole === 'super_admin') {
        // admin 不得修改高級角色的核心設定，但可編輯非關鍵欄位（姓名、Email、Lark關聯）
        enableEl(delBtn, false);  // 不可刪除
        enableEl(resetBtn, false); // 不可重設密碼
        enableEl(roleSel, false);  // 不可改角色
        // saveBtn 保持啟用，可編輯非關鍵欄位
      } else {
        // 僅能 viewer <-> user 範圍
      }
    } else if (meRole === 'super_admin') {
      if (tRole === 'super_admin') {
        // super_admin 不可修改另一個 super_admin 的核心設定
        enableEl(delBtn, false);  // 不可刪除
        enableEl(resetBtn, false); // 不可重設密碼
        enableEl(roleSel, false);  // 不可改角色
        // saveBtn 保持啟用，可編輯非關鍵欄位
      } else {
        // super_admin 可將他人設為 viewer/user/admin
      }
    } else {
      // 其他角色不可見此分頁，但若出現則全部禁用
      enableEl(saveBtn, false);
      enableEl(delBtn, false);
      enableEl(resetBtn, false);
      enableEl(roleSel, false);
    }
    
    console.log('Role restrictions applied:', {
      meRole, targetRole: tRole,
      saveDisabled: saveBtn?.disabled,
      deleteDisabled: delBtn?.disabled,
      resetDisabled: resetBtn?.disabled,
      roleSelectDisabled: roleSel?.disabled
    });
  }

  async function onCreate(e) {
    e.preventDefault();
    // 準備一個用於建立新使用者的空白表單
    state.selected = null;
    clearDirty();
    clearForm({ keepVisible: true });
    // 將焦點設定到 username 輸入框
    const usernameInput = document.getElementById('pm-username');
    if(usernameInput) {
        usernameInput.readOnly = false; // 確保 username 可以輸入
        usernameInput.focus();
    }
  }

  async function onSave(e) {
    e.preventDefault();
    if (!hasAuth()) {
      toastError(window.i18n ? window.i18n.t('personnel.noPermission') : '權限不足');
      return;
    }

    if (state.selected) {
      // 更新現有使用者
      try {
        const body = collectForm(state.selected);
        const resp = await window.AuthClient.fetch(`/api/users/${state.selected.id}`, {
          method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body)
        });
        if (!resp.ok) throw await respError(resp);
        toastSuccess(window.i18n ? window.i18n.t('personnel.saved') : '已儲存');
        clearDirty();
        await loadUsers();
      } catch (e) {
        console.error('Save user error:', e);
        toastError((window.i18n ? window.i18n.t('personnel.saveFailedPrefix') : '儲存失敗：') + (e?.message || e));
      }
    } else {
      // 建立新使用者
      const username = val('pm-username').trim();
      if (!username) {
        toastError(window.i18n ? window.i18n.t('personnel.usernameRequired') : '請填寫使用者名稱');
        return;
      }
      try {
        const body = collectForm(null /* new */);
        const resp = await window.AuthClient.fetch('/api/users', {
          method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body)
        });
        if (!resp.ok) throw await respError(resp);
        toastSuccess(window.i18n ? window.i18n.t('personnel.userCreated') : '使用者建立成功');
        clearDirty();
        clearForm(); // 清空表單
        await loadUsers();
      } catch (e) {
        console.error('Create user error:', e);
        toastError((window.i18n ? window.i18n.t('personnel.createFailedPrefix') : '建立失敗：') + (e?.message || e));
      }
    }
  }

  async function onDelete(e) {
    e.preventDefault();
    if (!hasAuth() || !state.selected) return;
    if (!confirm(window.i18n ? window.i18n.t('personnel.deleteConfirm') : '確定要停用/刪除此使用者？')) return;
    try {
      const resp = await window.AuthClient.fetch(`/api/users/${state.selected.id}`, { method: 'DELETE' });
      if (!resp.ok) throw await respError(resp);
      toastSuccess(window.i18n ? window.i18n.t('personnel.deleted') : '已停用/刪除');
      state.selected = null;
      clearForm();
      clearDirty();
      await loadUsers();
    } catch (e) {
      toastError((window.i18n ? window.i18n.t('personnel.deleteFailedPrefix') : '刪除失敗：') + (e?.message || e));
    }
  }

  async function onResetPwd(e) {
    e.preventDefault();
    if (!hasAuth() || !state.selected) return;
    if (!confirm(window.i18n ? window.i18n.t('personnel.resetPwdConfirm') : '確定要重設密碼？')) return;
    try {
      const url = `/api/users/${state.selected.id}/reset-password?generate_new=true`;
      const resp = await window.AuthClient.fetch(url, { method: 'POST' });
      const json = await resp.json().catch(() => ({}));
      if (!resp.ok) throw await respError(resp, json);
      const newPwd = json?.new_password || '';
      toastSuccess((window.i18n ? window.i18n.t('personnel.resetPwdSuccess') : '密碼已重設') + (newPwd ? `：${newPwd}` : ''));
      // 可選：自動複製
      if (newPwd && navigator.clipboard) {
        try { await navigator.clipboard.writeText(newPwd); } catch(_) {}
      }
    } catch (e) {
      toastError((window.i18n ? window.i18n.t('personnel.resetPwdFailedPrefix') : '重設密碼失敗：') + (e?.message || e));
    }
  }

  function collectForm(currentUser) {
    const body = {};
    const username = val('pm-username').trim();
    const fullName = val('pm-full-name').trim();
    const email = val('pm-email').trim();
    const role = val('pm-role');
    const isActive = checked('pm-active');
    const larkId = val('pm-lark-id').trim();

    // 新增使用者時的處理
    if (!currentUser) {
      body.username = username; // 新增時必填
      body.full_name = fullName || null;
      body.email = email || null;
      body.role = role || 'user';
      body.is_active = isActive;
      body.lark_user_id = larkId || null;
      return body;
    }

    // 更新使用者時的處理
    if (fullName !== (currentUser.full_name || '')) body.full_name = fullName || null;
    if (email !== (currentUser.email || '')) body.email = email || null;
    if (role && role !== (currentUser.role || '').toLowerCase()) body.role = role;
    if (isActive !== !!currentUser.is_active) body.is_active = isActive;
    
    // 重要：始終包含 lark_user_id，即使是空值，以確保能正確清除連結
    // 不論是否有變化，都包含此字段，以便後端可以正確設置為 null
    body.lark_user_id = larkId || null;
    
    return body;
  }

  async function onLarkPreview() {
    const larkId = val('pm-lark-id').trim();
    if (!larkId) { updateLarkPreviewBox(null); return; }
    await fetchLarkPreview(larkId, true);
  }

  function onLarkUnlink() {
    setVal('pm-lark-id', '');
    const larkSearch = document.getElementById('pm-lark-search');
    if (larkSearch) larkSearch.value = '';
    hideLarkDropdown();
    updateLarkPreviewBox(null); // 解除後隱藏預覽框
    markDirty();
    
    // 提示使用者需要儲存變更
    if (window.AppUtils && AppUtils.showWarning) {
      AppUtils.showWarning('已解除 Lark 連結，請點擊儲存按鈕以保存變更');
    } else {
      console.log('已解除 Lark 連結，請點擊儲存按鈕以保存變更');
    }
  }

  async function fetchLarkPreview(larkId, showToast) {
      const normalizedLarkId = String(larkId ?? '').trim();
      if (!normalizedLarkId) {
        console.warn('fetchLarkPreview called without larkId');
        return;
      }
      console.log('Fetching Lark for', normalizedLarkId);
      try {
        const resp = await window.AuthClient.fetch(`/api/lark/users/${encodeURIComponent(normalizedLarkId)}`);
        if (!resp.ok) throw new Error('HTTP ' + resp.status);
        const json = await resp.json();
        console.log('Received avatar from API: ' + json.avatar);
        state.larkCache.set(normalizedLarkId, { name: json?.name || '', avatar: json?.avatar || '' });
        console.log('Fetched Lark for', normalizedLarkId, 'name:', json.name, 'avatar:', json.avatar);
        // 更新搜尋框顯示值為名稱
        const larkSearch = document.getElementById('pm-lark-search');
        if (larkSearch && larkSearch.value === normalizedLarkId) {
          larkSearch.value = json?.name || normalizedLarkId;
        }
        const currentHiddenLarkId = val('pm-lark-id').trim();
        if (normalizedLarkId && currentHiddenLarkId === normalizedLarkId) {
          updateLarkPreviewBox(normalizedLarkId);
        }
        if (showToast) toastSuccess(window.i18n ? window.i18n.t('personnel.larkLoaded') : '已載入 Lark 資訊');
      } catch (e) {
        console.error('Fetch error for', normalizedLarkId, e);
        state.larkCache.delete(normalizedLarkId);
        const currentHiddenLarkId = val('pm-lark-id').trim();
        if (normalizedLarkId && currentHiddenLarkId === normalizedLarkId) {
          updateLarkPreviewBox(null);
        }
        if (showToast) toastError(window.i18n ? window.i18n.t('personnel.larkLoadFailed') : '無法取得 Lark 使用者資訊');
      }
    }

  function updateLarkPreviewBox(larkId) {
    const box = document.getElementById('pm-lark-preview-box');
    const img = document.getElementById('pm-lark-avatar');
    const nameEl = document.getElementById('pm-lark-name');
    const notConfiguredDiv = document.getElementById('pm-lark-not-configured');
    
    console.log('updateLarkPreviewBox called with:', larkId, 'cache has:', larkId ? state.larkCache.has(larkId) : false);
    
    if (!box || !img || !nameEl || !notConfiguredDiv) {
      console.error('Preview box elements not found');
      return;
    }
    
    // 隱藏所有元素
    box.style.display = 'none';
    notConfiguredDiv.style.display = 'none';
    
    // 如果沒有 larkId，顯示未配置消息
    if (!larkId || !larkId.trim()) {
      notConfiguredDiv.style.display = 'block';
      img.src = 'https://www.gravatar.com/avatar/?d=mp';
      img.style.display = 'block'; // 重置顯示狀態
      nameEl.textContent = '';
      return;
    }
    
    // 如果沒有快取資料，也顯示未配置消息
    if (!state.larkCache.has(larkId)) {
      notConfiguredDiv.style.display = 'block';
      img.src = 'https://www.gravatar.com/avatar/?d=mp';
      img.style.display = 'block'; // 重置顯示狀態
      nameEl.textContent = '';
      return;
    }
    
    const data = state.larkCache.get(larkId);
    console.log('Lark data:', data);
    
    // 檢查是否有有用的資料（名稱和頭像）
    const hasName = data.name && data.name.trim();
    const hasAvatar = data.avatar && data.avatar.trim();
    
    // 總是顯示預覽框，如果有連結
    console.log('Showing preview box');
    const avatarUrl = hasAvatar ? data.avatar : 'https://www.gravatar.com/avatar/?d=mp';
    img.src = avatarUrl;
    img.style.display = 'block'; // 總是顯示圖片，使用 Gravatar 作為 fallback
    img.onerror = function() { this.src = 'https://www.gravatar.com/avatar/?d=mp'; }; // 額外確保 onerror fallback
    nameEl.textContent = hasName ? data.name : '';
    box.style.display = 'flex'; // 使用 flex 顯示，以正確顯示對齊
    // 隱藏未配置消息
    notConfiguredDiv.style.display = 'none';
  }

  function clearForm(options = {}) {
    buildRoleOptions(); // 填充角色下拉選單
    const usernameInput = document.getElementById('pm-username');
    if (usernameInput) {
      usernameInput.disabled = false;
      usernameInput.readOnly = false;
    }
    setVal('pm-username','');
    setVal('pm-full-name','');
    setVal('pm-email','');
    setVal('pm-role','');
    setChecked('pm-active', true);
    setVal('pm-lark-id','');
    const larkSearch = document.getElementById('pm-lark-search');
    if (larkSearch) larkSearch.value = '';
    hideLarkDropdown();
    setVal('pm-primary-team','');
    updateLarkPreviewBox(null);
    toggleDetailView(!!options.keepVisible);
  }

  async function searchLarkUsers(term){
    const params = new URLSearchParams({ search: term, per_page: '20' });
    const resp = await window.AuthClient.fetch(`/api/lark/users?${params.toString()}`);
    if (!resp.ok) throw new Error('HTTP '+resp.status);
    const json = await resp.json();
    return json?.users || [];
  }

  function showLarkDropdown(list){
    const dropdown = document.getElementById('pm-lark-dropdown');
    if (!dropdown) return;
    if (!list.length) {
      hideLarkDropdown(); return;
    }
    dropdown.innerHTML = list.map(u => {
      const label = u.email ? `${escapeHtml(u.name || '')} (${escapeHtml(u.email)})` : `${escapeHtml(u.name || '')}`;
      return `<div class="dropdown-item" data-id="${u.id}" data-name="${escapeHtml(u.name || '')}" style="cursor:pointer;">${label}</div>`;
    }).join('');
    dropdown.style.display = 'block';
    
    // 綁定點擊事件
    dropdown.querySelectorAll('.dropdown-item').forEach(item => {
      item.addEventListener('click', async () => {
        const id = item.getAttribute('data-id');
        const name = item.getAttribute('data-name');
        const larkSearch = document.getElementById('pm-lark-search');
        if (larkSearch) larkSearch.value = name;
        setVal('pm-lark-id', id);
        hideLarkDropdown();
        await fetchLarkPreview(id, false);
        markDirty();
      });
    });
  }

  function hideLarkDropdown(){
    const dropdown = document.getElementById('pm-lark-dropdown');
    if (dropdown) {
      dropdown.style.display = 'none';
      dropdown.innerHTML = '';
    }
  }

  // Helpers
  function val(id){ const el = document.getElementById(id); return el ? el.value : ''; }
  function setVal(id,v){ const el = document.getElementById(id); if (el) el.value = v; }
  function checked(id){ const el = document.getElementById(id); return !!(el && el.checked); }
  function setChecked(id, c){ const el = document.getElementById(id); if (el) el.checked = !!c; }
  function enableEl(el, on){ if (el) el.disabled = !on; }
  function escapeHtml(s){ if (s==null) return ''; return String(s).replace(/[&<>"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;','\'':'&#039;'}[m])); }
  async function respError(resp, json){
    try{ json = json || await resp.json(); }catch(_){}
    const msg = json?.detail || json?.message || resp.statusText || ('HTTP '+resp.status);
    return new Error(msg);
  }
  function toastSuccess(msg){ if (window.AppUtils && AppUtils.showSuccess) AppUtils.showSuccess(msg); else console.log('SUCCESS:', msg); }
  function toastError(msg){ if (window.AppUtils && AppUtils.showError) AppUtils.showError(msg); else console.error('ERROR:', msg); }

  // 初始化：在頁面載入以及開啟同步 Modal 前就準備好
  document.addEventListener('DOMContentLoaded', init);
  // 若同步 Modal 開啟時才載入使用者權限，也可保險再次檢查
  const syncBtn = document.getElementById('syncOrgBtn');
  if (syncBtn) syncBtn.addEventListener('click', async ()=>{ await fetchMe(); showPersonnelTabIfAllowed(); });
})();
