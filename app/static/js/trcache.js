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
    enableErrorLogging: true, // 啟用詳細錯誤日志記錄
    _sessionId: null, // 會話唯一標識符，避免快取衝突

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

    _execKey(teamId, number) {
      const validTeamId = this._getValidTeamId(teamId);
      const key = `${validTeamId}:${number}`;
      if (this.debug) {
        console.debug('[TRCache] 產生key:', key, { originalTeamId: teamId, validTeamId });
      }
      return key;
    },

    _getValidTeamId(teamId) {
      // 1. 使用有效的teamId
      if (teamId && teamId !== 'null' && teamId !== 'undefined' && teamId !== '') {
        return String(teamId);
      }

      // 2. 嘗試從AppUtils獲取
      try {
        if (typeof AppUtils !== 'undefined' && AppUtils.getCurrentTeam) {
          const team = AppUtils.getCurrentTeam();
          if (team && team.id) {
            if (this.debug || this.enableErrorLogging) {
              console.log('[TRCache] 使用AppUtils獲取teamId:', team.id);
            }
            return String(team.id);
          }
        }
      } catch (e) {
        if (this.enableErrorLogging) {
          console.warn('[TRCache] AppUtils獲取teamId失敗:', e);
        }
      }

      // 3. 嘗試從URL參數獲取
      try {
        const params = new URLSearchParams(window.location.search);
        const urlTeamId = params.get('team_id') || params.get('teamId') || params.get('team');
        if (urlTeamId) {
          if (this.debug || this.enableErrorLogging) {
            console.log('[TRCache] 使用URL參數獲取teamId:', urlTeamId);
          }
          return String(urlTeamId);
        }
      } catch (e) {
        if (this.enableErrorLogging) {
          console.warn('[TRCache] URL參數獲取teamId失敗:', e);
        }
      }

      // 4. 最後使用會話唯一ID，避免與其他會話衝突
      if (!this._sessionId) {
        this._sessionId = `session_${Date.now()}_${Math.random().toString(36).substring(2, 11)}`;
        if (this.enableErrorLogging) {
          console.warn('[TRCache] teamId無效，使用會話ID避免衝突:', this._sessionId, '原始teamId:', teamId);
        }
      }
      return this._sessionId;
    },

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
        // 輸入驗證
        if (!testCaseNumber) {
          if (this.enableErrorLogging) {
            console.error('[TRCache] setExecDetail: testCaseNumber為空', { teamId, testCaseNumber, obj });
          }
          return false;
        }
        if (!obj || typeof obj !== 'object') {
          if (this.enableErrorLogging) {
            console.error('[TRCache] setExecDetail: 無效的數據對象', { teamId, testCaseNumber, obj });
          }
          return false;
        }

        const key = this._execKey(teamId, testCaseNumber);
        const jsonStr = JSON.stringify(obj);

        // 檢查JSON序列化結果
        if (!jsonStr || jsonStr === 'null' || jsonStr === 'undefined') {
          if (this.enableErrorLogging) {
            console.error('[TRCache] setExecDetail: JSON序列化失敗', { key, obj });
          }
          return false;
        }

        const gz = this._gzip(jsonStr, 5);
        const rec = {
          key,
          ts: Date.now(),
          lastAccess: Date.now(),
          data: new Blob([gz], { type: 'application/octet-stream' }),
          size: gz.length
        };

        if (TRCache.debug) console.debug('[TRCache] setExecDetail', key, 'size', rec.size);

        const success = await this._put(STORE_EXEC, rec);
        if (success) {
          await this._lruEvict(STORE_EXEC, EXEC_LRU_MAX);
          if (this.debug) {
            console.log('[TRCache] setExecDetail成功:', key);
          }
          return true;
        } else {
          if (this.enableErrorLogging) {
            console.error('[TRCache] setExecDetail: _put失敗', key);
          }
          return false;
        }
      } catch (error) {
        if (this.enableErrorLogging) {
          console.error('[TRCache] setExecDetail發生未預期錯誤:', error, { teamId, testCaseNumber, obj });
        }
        return false;
      }
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
        if (!Array.isArray(list) && list !== null && list !== undefined) {
          if (this.enableErrorLogging) {
            console.error('[TRCache] setTCG: 無效的列表數據', list);
          }
          return false;
        }

        const jsonStr = JSON.stringify(list || []);
        if (!jsonStr) {
          if (this.enableErrorLogging) {
            console.error('[TRCache] setTCG: JSON序列化失敗', list);
          }
          return false;
        }

        const gz = this._gzip(jsonStr, 5);
        const rec = {
          key: 'tcg',
          ts: Date.now(),
          lastAccess: Date.now(),
          data: new Blob([gz], { type: 'application/octet-stream' }),
          size: gz.length
        };

        if (TRCache.debug) console.debug('[TRCache] setTCG size', rec.size);

        const success = await this._put(STORE_TCG, rec);
        if (success) {
          if (this.debug) {
            console.log('[TRCache] setTCG成功，大小:', rec.size);
          }
          return true;
        } else {
          if (this.enableErrorLogging) {
            console.error('[TRCache] setTCG: _put失敗');
          }
          return false;
        }
      } catch (error) {
        if (this.enableErrorLogging) {
          console.error('[TRCache] setTCG發生未預期錯誤:', error, list);
        }
        return false;
      }
    },

    async selfTest() {
      try {
        const originalDebug = TRCache.debug;
        const originalErrorLogging = TRCache.enableErrorLogging;
        TRCache.debug = true;
        TRCache.enableErrorLogging = true;

        console.log('[TRCache] 開始自我測試...');

        // 測試基本寫入讀取
        const testData = { ok: true, at: Date.now(), test: '中文測試數據' };
        console.log('[TRCache] 測試數據:', testData);

        const writeSuccess = await TRCache.setExecDetail('selftest', 'DEMO', testData);
        console.log('[TRCache] 寫入結果:', writeSuccess);

        const readResult = await TRCache.getExecDetail('selftest', 'DEMO', 60*60*1000);
        console.log('[TRCache] 讀取結果:', readResult);

        // 測試TCG功能
        const testTcgData = [{id: 1, name: 'test'}, {id: 2, name: '測試'}];
        const tcgWriteSuccess = await TRCache.setTCG(testTcgData);
        console.log('[TRCache] TCG寫入結果:', tcgWriteSuccess);

        const tcgRead = await TRCache.getTCG(60*60*1000);
        console.log('[TRCache] TCG讀取結果:', tcgRead);

        // 測試衝突場景：不同的teamId是否獲得不同的key
        const key1 = TRCache._execKey(null, 'TEST');
        const key2 = TRCache._execKey(undefined, 'TEST');
        const key3 = TRCache._execKey('', 'TEST');
        const key4 = TRCache._execKey('1', 'TEST');
        console.log('[TRCache] Key衝突測試:');
        console.log('  null -> ', key1);
        console.log('  undefined -> ', key2);
        console.log('  empty -> ', key3);
        console.log('  "1" -> ', key4);
        console.log('  會話ID:', TRCache._sessionId);

        // 恢復原始設定
        TRCache.debug = originalDebug;
        TRCache.enableErrorLogging = originalErrorLogging;

        const success = writeSuccess && readResult && tcgWriteSuccess && tcgRead;
        console.log('[TRCache] 自我測試結果:', success ? '成功' : '失敗');

        return { success, execTest: readResult, tcgTest: tcgRead, keys: { key1, key2, key3, key4 } };
      } catch (e) {
        console.error('[TRCache] selfTest error', e);
        return { success: false, error: e.message };
      }
    },

    // 啟用/禁用詳細日志
    enableLogging(enable = true) {
      this.enableErrorLogging = enable;
      console.log('[TRCache] 錯誤日志', enable ? '已啟用' : '已禁用');
    },

    // 啟用/禁用調試模式
    enableDebug(enable = true) {
      this.debug = enable;
      console.log('[TRCache] 調試模式', enable ? '已啟用' : '已禁用');
    },

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

  // 暴露全域方法
  global.TRCache = TRCache;

  // 快速設定函數（方便控制台調試）
  global.TRCacheDebug = {
    enable: () => TRCache.enableDebug(true),
    disable: () => TRCache.enableDebug(false),
    enableLogging: () => TRCache.enableLogging(true),
    disableLogging: () => TRCache.enableLogging(false),
    selfTest: () => TRCache.selfTest(),
    clearAll: () => TRCache.clearAll(),
    showSession: () => console.log('Session ID:', TRCache._sessionId),
    testKeys: () => {
      console.log('Key 測試:');
      console.log('null:', TRCache._execKey(null, 'TEST'));
      console.log('undefined:', TRCache._execKey(undefined, 'TEST'));
      console.log('"1":', TRCache._execKey('1', 'TEST'));
      console.log('"2":', TRCache._execKey('2', 'TEST'));
    }
  };

  // 初始化時顯示版本信息
  if (TRCache.enableErrorLogging) {
    console.log('[TRCache] 已載入，版本: v2.0 (修復key衝突)', '\n調試指令: TRCacheDebug.selfTest()');
  }
})(window);
