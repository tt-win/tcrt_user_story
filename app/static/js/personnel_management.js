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

    // 僅在切到人員分頁時初始化
    const tabBtn = document.getElementById('tab-personnel');
    if (tabBtn) {
      tabBtn.addEventListener('shown.bs.tab', onTabShown);
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

    console.log('Binding buttons:', { btnCreate, btnSave, btnDelete, btnReset, btnUnlink }); // 除錯

    if (btnCreate) {
      btnCreate.addEventListener('click', onCreate);
      console.log('Create button bound');
    } else {
      console.error('Create button not found!');
    }
    if (btnSave) {
      btnSave.addEventListener('click', onSave);
      console.log('Save button bound');
    } else {
      console.error('Save button not found!');
    }
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
      state.users = json.users || [];
      state.total = json.total || 0;
      renderUserList();
      updatePageIndicator();
    } catch (e) {
      console.error('load users failed', e);
      toastError('載入使用者清單失敗');
    }
  }

  function updatePageIndicator() {
    const el = document.getElementById('pm-page-indicator');
    if (!el) return;
    const maxPage = Math.max(1, Math.ceil(state.total / state.perPage));
    el.textContent = `${state.page}/${maxPage}（共 ${state.total} 筆）`;
  }

  function renderUserList() {
    const box = document.getElementById('pm-user-list');
    if (!box) return;
    if (!state.users.length) {
      box.innerHTML = '<div class="list-group-item text-center text-muted">無使用者</div>';
      return;
    }

    const html = state.users.map(u => {
      const display = getDisplayName(u);
      const avatar = getAvatarUrl(u);
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
    if (u.lark_user_id && state.larkCache.has(u.lark_user_id)) {
      return state.larkCache.get(u.lark_user_id).name || u.full_name || u.username || '';
    }
    return u.full_name || u.username || '';
  }

  function getAvatarUrl(u) {
    if (u.lark_user_id && state.larkCache.has(u.lark_user_id)) {
      return state.larkCache.get(u.lark_user_id).avatar || 'https://www.gravatar.com/avatar/?d=mp';
    }
    return 'https://www.gravatar.com/avatar/?d=mp';
  }

  async function onSelectUser(userId) {
    if (state.dirty && !confirm('有未儲存的變更，確定要切換嗎？')) return;
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
    setVal('pm-username', u.username || '');
    setVal('pm-full-name', u.full_name || '');
    setVal('pm-email', u.email || '');
    setChecked('pm-active', !!u.is_active);
    // 角色選項
    buildRoleOptions();
    setVal('pm-role', (u.role || '').toLowerCase());
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

  function buildRoleOptions() {
    const sel = document.getElementById('pm-role');
    if (!sel) return;
    const meRole = (state.me && state.me.role) || '';
    const options = [];
    if (meRole === 'super_admin') {
      options.push(['viewer','viewer'], ['user','user'], ['admin','admin']);
    } else if (meRole === 'admin') {
      options.push(['viewer','viewer'], ['user','user']);
    } else {
      options.push(['viewer','viewer']);
    }
    sel.innerHTML = options.map(([v,l]) => `<option value="${v}">${l}</option>`).join('');
  }

  function applyRoleRestrictions(targetUser) {
    const meRole = (state.me && state.me.role) || '';
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
        buildRoleOptions();
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
        buildRoleOptions();
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
    console.log('onCreate called'); // 除錯用
    if (!hasAuth()) {
      toastError('權限不足');
      return;
    }
    
    // 驗證必填欄位
    const username = val('pm-username').trim();
    if (!username) {
      toastError('請填寫使用者名稱');
      return;
    }
    
    try {
      const body = collectForm(null /* new */);
      console.log('Create user body:', body); // 除錯用
      // 後端會自動生成密碼（若未提供）
      const resp = await window.AuthClient.fetch('/api/users', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body)
      });
      if (!resp.ok) throw await respError(resp);
      toastSuccess('使用者建立成功');
      clearDirty();
      clearForm(); // 清空表單
      await loadUsers();
    } catch (e) {
      console.error('Create user error:', e);
      toastError('建立失敗：' + (e?.message || e));
    }
  }

  async function onSave(e) {
    e.preventDefault();
    console.log('onSave called, state.selected:', state.selected); // 除錯用
    if (!hasAuth()) {
      toastError('權限不足');
      return;
    }
    if (!state.selected) {
      toastError('請先選擇要編輯的使用者');
      return;
    }
    try {
      const body = collectForm(state.selected);
      console.log('Save user body:', body); // 除錯用
      const resp = await window.AuthClient.fetch(`/api/users/${state.selected.id}`, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body)
      });
      if (!resp.ok) throw await respError(resp);
      toastSuccess('已儲存');
      clearDirty();
      await loadUsers();
    } catch (e) {
      console.error('Save user error:', e);
      toastError('儲存失敗：' + (e?.message || e));
    }
  }

  async function onDelete(e) {
    e.preventDefault();
    if (!hasAuth() || !state.selected) return;
    if (!confirm('確定要停用/刪除此使用者？')) return;
    try {
      const resp = await window.AuthClient.fetch(`/api/users/${state.selected.id}`, { method: 'DELETE' });
      if (!resp.ok) throw await respError(resp);
      toastSuccess('已停用/刪除');
      state.selected = null;
      clearForm();
      clearDirty();
      await loadUsers();
    } catch (e) {
      toastError('刪除失敗：' + (e?.message || e));
    }
  }

  async function onResetPwd(e) {
    e.preventDefault();
    if (!hasAuth() || !state.selected) return;
    if (!confirm('確定要重設密碼？')) return;
    try {
      const url = `/api/users/${state.selected.id}/reset-password?generate_new=true`;
      const resp = await window.AuthClient.fetch(url, { method: 'POST' });
      const json = await resp.json().catch(() => ({}));
      if (!resp.ok) throw await respError(resp, json);
      const newPwd = json?.new_password || '';
      toastSuccess('密碼已重設' + (newPwd ? `：${newPwd}` : ''));
      // 可選：自動複製
      if (newPwd && navigator.clipboard) {
        try { await navigator.clipboard.writeText(newPwd); } catch(_) {}
      }
    } catch (e) {
      toastError('重設密碼失敗：' + (e?.message || e));
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

    // 更新使用者時的處理（僅包含有變更的欄位）
    if (fullName !== (currentUser.full_name || '')) body.full_name = fullName || null;
    if (email !== (currentUser.email || '')) body.email = email || null;
    if (role && role !== (currentUser.role || '').toLowerCase()) body.role = role;
    if (isActive !== !!currentUser.is_active) body.is_active = isActive;
    if (larkId !== (currentUser.lark_user_id || '')) body.lark_user_id = larkId || null;
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
  }

  async function fetchLarkPreview(larkId, showToast) {
    try {
      const resp = await window.AuthClient.fetch(`/api/lark/users/${encodeURIComponent(larkId)}`);
      if (!resp.ok) throw new Error('HTTP ' + resp.status);
      const json = await resp.json();
      state.larkCache.set(larkId, { name: json?.name || '', avatar: json?.avatar || '' });
      // 更新搜尋框顯示值為名稱
      const larkSearch = document.getElementById('pm-lark-search');
      if (larkSearch && larkSearch.value === larkId) {
        larkSearch.value = json?.name || larkId;
      }
      updateLarkPreviewBox(larkId);
      if (showToast) toastSuccess('已載入 Lark 資訊');
    } catch (e) {
      state.larkCache.delete(larkId);
      updateLarkPreviewBox(null);
      if (showToast) toastError('無法取得 Lark 使用者資訊');
    }
  }

  function updateLarkPreviewBox(larkId) {
    const box = document.getElementById('pm-lark-preview-box');
    const img = document.getElementById('pm-lark-avatar');
    const nameEl = document.getElementById('pm-lark-name');
    
    console.log('updateLarkPreviewBox called with:', larkId, 'cache has:', larkId ? state.larkCache.has(larkId) : false);
    
    if (!box || !img || !nameEl) {
      console.error('Preview box elements not found');
      return;
    }
    
    // 無條件隱藏預覽框：無 larkId 或無快取資料
    if (!larkId || !state.larkCache.has(larkId)) {
      console.log('Hiding preview box: no larkId or no cache data');
      box.style.display = 'none';
      img.src = '';
      nameEl.textContent = '';
      return;
    }
    
    const data = state.larkCache.get(larkId);
    console.log('Lark data:', data);
    
    // 無條件隱藏預覽框：沒有有用的資料（名稱和頭像都是空的）
    const hasName = data.name && data.name.trim();
    const hasAvatar = data.avatar && data.avatar.trim();
    
    if (!hasName && !hasAvatar) {
      console.log('Hiding preview box: no useful data');
      box.style.display = 'none';
      img.src = '';
      nameEl.textContent = '';
      return;
    }
    
    // 有有用資料才顯示
    console.log('Showing preview box');
    img.src = data.avatar || 'https://www.gravatar.com/avatar/?d=mp';
    nameEl.textContent = data.name || '';
    box.style.display = 'block';
  }

  function clearForm() {
    console.log('Clearing form');
    setVal('pm-username','');
    setVal('pm-full-name','');
    setVal('pm-email','');
    setVal('pm-role','');
    setChecked('pm-active', false);
    setVal('pm-lark-id','');
    const larkSearch = document.getElementById('pm-lark-search');
    if (larkSearch) larkSearch.value = '';
    hideLarkDropdown();
    setVal('pm-primary-team','');
    updateLarkPreviewBox(null);
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
