(function (global) {
  'use strict';

  const DB_NAME = 'tr_cache';
  const DB_VERSION = 1;
  const STORE_EXEC = 'exec_tc';
  const STORE_TCG = 'tcg';
  const EXEC_LRU_MAX = 5000; // per requirement

  const TRCache = {
    _dbPromise: null,
    debug: false,

    async _openDB() {
      if (this._dbPromise) return this._dbPromise;
      this._dbPromise = new Promise((resolve, reject) => {
        if (!('indexedDB' in global)) {
          console.error('[TRCache] indexedDB not supported');
          reject(new Error('indexedDB not supported'));
          return;
        }
        const req = indexedDB.open(DB_NAME, DB_VERSION);
        req.onupgradeneeded = (e) => {
          const db = e.target.result;
          if (!db.objectStoreNames.contains(STORE_EXEC)) {
            const s = db.createObjectStore(STORE_EXEC, { keyPath: 'key' });
            s.createIndex('ts', 'ts');
            s.createIndex('lastAccess', 'lastAccess');
          }
          if (!db.objectStoreNames.contains(STORE_TCG)) {
            const s2 = db.createObjectStore(STORE_TCG, { keyPath: 'key' });
            s2.createIndex('ts', 'ts');
            s2.createIndex('lastAccess', 'lastAccess');
          }
          if (TRCache.debug) console.debug('[TRCache] onupgradeneeded');
        };
        req.onsuccess = () => { if (TRCache.debug) console.debug('[TRCache] DB opened'); resolve(req.result); };
        req.onerror = () => { console.error('[TRCache] DB open error:', req.error); reject(req.error); };
      });
      return this._dbPromise;
    },

    _gzip(str, level = 5) {
      // returns Uint8Array
      return global.pako ? global.pako.gzip(str, { level }) : new TextEncoder().encode(str);
    },
    _gunzip(bytes) {
      // accepts Uint8Array, returns string
      if (global.pako) {
        const out = global.pako.ungzip(bytes);
        return new TextDecoder().decode(out);
      }
      return new TextDecoder().decode(bytes);
    },

    _execKey(teamId, number) { return `${teamId || 'unknown'}:${number}`; },

    async _put(store, record) {
      const db = await this._openDB();
      return new Promise((resolve, reject) => {
        const tx = db.transaction(store, 'readwrite');
        tx.oncomplete = () => { if (TRCache.debug) console.debug('[TRCache] put complete', store, record.key); resolve(true); };
        tx.onerror = () => { console.error('[TRCache] put tx error:', tx.error); reject(tx.error); };
        const req = tx.objectStore(store).put(record);
        req.onerror = () => { console.error('[TRCache] put req error:', req.error); };
      });
    },

    async _get(store, key) {
      const db = await this._openDB();
      return new Promise((resolve, reject) => {
        const tx = db.transaction(store, 'readonly');
        tx.onerror = () => { console.error('[TRCache] get tx error:', tx.error); reject(tx.error); };
        const req = tx.objectStore(store).get(key);
        req.onsuccess = () => { if (TRCache.debug) console.debug('[TRCache] get ok', store, key, !!req.result); resolve(req.result || null); };
        req.onerror = () => { console.error('[TRCache] get req error:', req.error); reject(req.error); };
      });
    },

    async _delete(store, key) {
      const db = await this._openDB();
      return new Promise((resolve, reject) => {
        const tx = db.transaction(store, 'readwrite');
        tx.oncomplete = () => resolve(true);
        tx.onerror = () => reject(tx.error);
        tx.objectStore(store).delete(key);
      });
    },

    async _count(store) {
      const db = await this._openDB();
      return new Promise((resolve, reject) => {
        const tx = db.transaction(store, 'readonly');
        tx.onerror = () => reject(tx.error);
        const req = tx.objectStore(store).count();
        req.onsuccess = () => resolve(req.result || 0);
        req.onerror = () => reject(req.error);
      });
    },

    async _lruEvict(store, max) {
      try {
        const db = await this._openDB();
        const total = await this._count(store);
        if (total <= max) return;
        const toDelete = total - max;
        await new Promise((resolve, reject) => {
          const tx = db.transaction(store, 'readwrite');
          const idx = tx.objectStore(store).index('lastAccess');
          let removed = 0;
          idx.openCursor().onsuccess = (e) => {
            const cursor = e.target.result;
            if (!cursor) return;
            cursor.delete();
            removed++;
            if (removed >= toDelete) { resolve(true); return; }
            cursor.continue();
          };
          tx.oncomplete = () => resolve(true);
          tx.onerror = () => reject(tx.error);
        });
      } catch (_) { /* ignore */ }
    },

    // Public API
    async getExecDetail(teamId, testCaseNumber, ttlMs) {
      const key = this._execKey(teamId, testCaseNumber);
      const rec = await this._get(STORE_EXEC, key);
      if (!rec) return null;
      const now = Date.now();
      if (ttlMs && rec.ts && (now - rec.ts) > ttlMs) return null;
      // update lastAccess asynchronously
      rec.lastAccess = now;
      this._put(STORE_EXEC, rec).catch(()=>{});
      try {
        const blob = rec.data;
        const bytes = blob instanceof Blob ? new Uint8Array(await blob.arrayBuffer()) : new Uint8Array(blob);
        const jsonStr = this._gunzip(bytes);
        return { ts: rec.ts, data: JSON.parse(jsonStr) };
      } catch (_) {
        return null;
      }
    },

    async setExecDetail(teamId, testCaseNumber, obj) {
      try {
        const key = this._execKey(teamId, testCaseNumber);
        const jsonStr = JSON.stringify(obj);
        const gz = this._gzip(jsonStr, 5);
        const rec = { key, ts: Date.now(), lastAccess: Date.now(), data: new Blob([gz], { type: 'application/octet-stream' }), size: gz.length };
        if (TRCache.debug) console.debug('[TRCache] setExecDetail', key, 'size', rec.size);
        await this._put(STORE_EXEC, rec);
        await this._lruEvict(STORE_EXEC, EXEC_LRU_MAX);
      } catch (_) { /* ignore */ }
    },

    async getTCG(ttlMs) {
      const rec = await this._get(STORE_TCG, 'tcg');
      if (!rec) return null;
      const now = Date.now();
      if (ttlMs && rec.ts && (now - rec.ts) > ttlMs) return null;
      // update lastAccess asynchronously
      rec.lastAccess = now;
      this._put(STORE_TCG, rec).catch(()=>{});
      try {
        const blob = rec.data;
        const bytes = blob instanceof Blob ? new Uint8Array(await blob.arrayBuffer()) : new Uint8Array(blob);
        const jsonStr = this._gunzip(bytes);
        return { ts: rec.ts, data: JSON.parse(jsonStr) };
      } catch (_) { return null; }
    },

    async setTCG(list) {
      try {
        const jsonStr = JSON.stringify(list || []);
        const gz = this._gzip(jsonStr, 5);
        const rec = { key: 'tcg', ts: Date.now(), lastAccess: Date.now(), data: new Blob([gz], { type: 'application/octet-stream' }), size: gz.length };
        if (TRCache.debug) console.debug('[TRCache] setTCG size', rec.size);
        await this._put(STORE_TCG, rec);
      } catch (_) { /* ignore */ }
    },

    async selfTest() {
      try {
        TRCache.debug = true;
        await TRCache.setExecDetail('selftest', 'DEMO', { ok: true, at: Date.now() });
        const d = await TRCache.getExecDetail('selftest', 'DEMO', 60*60*1000);
        console.log('[TRCache] selfTest result:', d);
        return d;
      } catch (e) { console.error('[TRCache] selfTest error', e); return null; }
    }

    async clearTeam(teamId) {
      try {
        const db = await this._openDB();
        await new Promise((resolve, reject) => {
          const tx = db.transaction(STORE_EXEC, 'readwrite');
          const s = tx.objectStore(STORE_EXEC);
          s.openCursor().onsuccess = (e) => {
            const cursor = e.target.result;
            if (!cursor) return;
            if (String(cursor.key).startsWith(`${teamId || 'unknown'}:`)) cursor.delete();
            cursor.continue();
          };
          tx.oncomplete = () => resolve(true);
          tx.onerror = () => reject(tx.error);
        });
      } catch (_) { /* ignore */ }
    },

    async clearAll() {
      try {
        const db = await this._openDB();
        await Promise.all([
          new Promise((res, rej)=>{ const tx=db.transaction(STORE_EXEC,'readwrite'); tx.objectStore(STORE_EXEC).clear(); tx.oncomplete=()=>res(true); tx.onerror=()=>rej(tx.error);} ),
          new Promise((res, rej)=>{ const tx=db.transaction(STORE_TCG,'readwrite'); tx.objectStore(STORE_TCG).clear(); tx.oncomplete=()=>res(true); tx.onerror=()=>rej(tx.error);} )
        ]);
      } catch (_) { /* ignore */ }
    }
  };

  global.TRCache = TRCache;
})(window);
