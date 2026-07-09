/* 共用釘選 (Pin) 狀態管理：後端持久、per-user，另外併入 team 層級的 app token 共用釘選
   （唯讀，無法在此 UI 取消 — 只能透過 /api/app/teams/{team_id}/pins 管理）。
   透過 /api/pins 讀寫，並在記憶體以 Set 快取每種 entity_type 的釘選 id。
   前端在卡片與精簡列表把釘選項目置頂（釘選群組內依建立日期新→舊排序）。 */
(function (global) {
    'use strict';

    const ENTITY_TYPES = ['test_case_set', 'test_run_set', 'test_run', 'adhoc_run'];

    // entity_type -> Set(id)：個人 + app token 釘選的合併結果（用於置頂顯示）
    const cache = {};
    // entity_type -> Set(id)：僅 app token 釘選的子集（用於停用取消釘選操作）
    const tokenCache = {};
    ENTITY_TYPES.forEach(t => { cache[t] = new Set(); tokenCache[t] = new Set(); });

    function normalizeId(id) {
        // 後端回傳整數 id；統一成 Number 以避免字串/數字比較不一致
        return Number(id);
    }

    async function load(teamId) {
        ENTITY_TYPES.forEach(t => { cache[t].clear(); tokenCache[t].clear(); });
        if (!teamId) return cache;
        try {
            const resp = await window.AuthClient.fetch(`/api/pins?team_id=${teamId}`);
            if (!resp.ok) {
                console.warn('[PinStore] load failed:', resp.status);
                return cache;
            }
            const data = await resp.json();
            const tokenPinned = data.token_pinned || {};
            ENTITY_TYPES.forEach(t => {
                const ids = Array.isArray(data[t]) ? data[t] : [];
                cache[t] = new Set(ids.map(normalizeId));
                const tokenIds = Array.isArray(tokenPinned[t]) ? tokenPinned[t] : [];
                tokenCache[t] = new Set(tokenIds.map(normalizeId));
            });
        } catch (e) {
            console.warn('[PinStore] load error:', e);
        }
        return cache;
    }

    function isPinned(entityType, id) {
        const set = cache[entityType];
        return !!set && set.has(normalizeId(id));
    }

    // true 表示此項目由 app token 釘選（team 共用）；一般取消釘選操作不應對其生效。
    function isTokenPinned(entityType, id) {
        const set = tokenCache[entityType];
        return !!set && set.has(normalizeId(id));
    }

    async function pin(teamId, entityType, id) {
        const resp = await window.AuthClient.fetch('/api/pins', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ team_id: teamId, entity_type: entityType, entity_id: normalizeId(id) })
        });
        if (!resp.ok) throw new Error(`pin failed: ${resp.status}`);
        cache[entityType] && cache[entityType].add(normalizeId(id));
    }

    async function unpin(teamId, entityType, id) {
        if (isTokenPinned(entityType, id)) {
            // App token 團隊共用釘選：不可透過此 UI 取消，只能經 /api/app/teams/{team_id}/pins 管理。
            throw new Error('cannot unpin an app-token-pinned item from this UI');
        }
        const url = `/api/pins/${entityType}/${normalizeId(id)}?team_id=${teamId}`;
        const resp = await window.AuthClient.fetch(url, { method: 'DELETE' });
        if (!resp.ok) throw new Error(`unpin failed: ${resp.status}`);
        cache[entityType] && cache[entityType].delete(normalizeId(id));
    }

    // 回傳新陣列：釘選項目在前（依 createdAtFn 新→舊），其餘維持原順序。
    function sortPinnedFirst(rows, isPinnedFn, createdAtFn) {
        if (!Array.isArray(rows)) return rows;
        const pinned = [];
        const rest = [];
        rows.forEach(r => (isPinnedFn(r) ? pinned : rest).push(r));
        pinned.sort((a, b) => {
            const ta = createdAtFn(a) ? new Date(createdAtFn(a)).getTime() : 0;
            const tb = createdAtFn(b) ? new Date(createdAtFn(b)).getTime() : 0;
            return tb - ta; // 新→舊
        });
        return pinned.concat(rest);
    }

    global.PinStore = { load, isPinned, isTokenPinned, pin, unpin, sortPinnedFirst, ENTITY_TYPES };
})(window);
