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
    _monitoringEnabled: false, // 監控狀態旗標

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

      // 加入頁面路徑作為附加區別信息，進一步避免衝突
      const pagePath = window.location.pathname.replace(/\//g, '_');
      const key = `${validTeamId}:${pagePath}:${number}`;

      if (this.debug) {
        console.debug('[TRCache] 產生key:', key, {
          originalTeamId: teamId,
          validTeamId,
          pagePath,
          fullUrl: window.location.href
        });
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

      // 4. 最後使用會話唯一ID + 時間戳，確保絕對唯一
      if (!this._sessionId) {
        // 加入頁面標題和時間戳作為額外區別信息
        const pageHash = btoa(document.title + window.location.href).substring(0, 10);
        this._sessionId = `session_${Date.now()}_${pageHash}_${Math.random().toString(36).substring(2, 11)}`;
        if (this.enableErrorLogging) {
          console.warn('[TRCache] teamId無效，使用增強會話ID避免衝突:', this._sessionId, '原始teamId:', teamId);
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

    // 衝突檢測和解決
    async detectConflicts(teamIds) {
      console.log('[TRCache] 檢測團隊衝突:', teamIds);
      const keyMap = new Map();
      const conflicts = [];

      for (const teamId of teamIds) {
        const key = this._execKey(teamId, 'CONFLICT_TEST');
        if (keyMap.has(key)) {
          conflicts.push({
            key,
            conflictingTeams: [keyMap.get(key), teamId]
          });
        } else {
          keyMap.set(key, teamId);
        }
      }

      if (conflicts.length > 0) {
        console.error('[TRCache] 發現衝突:', conflicts);
        console.log('建議解決方案: 清除快取或使用更具體的teamId');
      } else {
        console.log('[TRCache] 未發現衝突');
      }

      return conflicts;
    },

    // 強制更新會話ID（解決衝突時使用）
    regenerateSession() {
      const oldSessionId = this._sessionId;
      this._sessionId = null; // 清除舊的
      const newSessionId = this._getValidTeamId(null); // 重新生成
      console.log('[TRCache] 會話ID更新:', { old: oldSessionId, new: newSessionId });
      return newSessionId;
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

    // 詳細的團隊信息調試
    diagnoseTeam: () => {
      console.log('=== 團隊診斷信息 ===');
      console.log('1. AppUtils 狀態:');
      try {
        if (typeof AppUtils !== 'undefined') {
          const currentTeam = AppUtils.getCurrentTeam();
          console.log('   AppUtils.getCurrentTeam():', currentTeam);
          console.log('   團隊ID:', currentTeam?.id);
          console.log('   團隊名稱:', currentTeam?.name);
        } else {
          console.log('   AppUtils 未定義');
        }
      } catch (e) {
        console.error('   AppUtils 錯誤:', e);
      }

      console.log('2. URL 參數:');
      try {
        const params = new URLSearchParams(window.location.search);
        console.log('   team_id:', params.get('team_id'));
        console.log('   teamId:', params.get('teamId'));
        console.log('   team:', params.get('team'));
        console.log('   完整URL:', window.location.href);
      } catch (e) {
        console.error('   URL 解析錯誤:', e);
      }

      console.log('3. 會話信息:');
      console.log('   會話ID:', TRCache._sessionId);
      console.log('   頁面標題:', document.title);
      console.log('   載入時間:', new Date().toISOString());
    },

    // 測試特定團隊ID的key生成
    testTeamKeys: (...teamIds) => {
      console.log('=== 團隊Key測試 ===');
      const keyMap = new Map();
      const duplicates = [];

      teamIds.forEach(teamId => {
        const key = TRCache._execKey(teamId, 'TEST');
        const validTeamId = TRCache._getValidTeamId(teamId);
        console.log(`團隊ID: ${teamId} (${typeof teamId}) -> 有效ID: ${validTeamId} -> Key: ${key}`);

        // 檢查重複
        if (keyMap.has(key)) {
          duplicates.push({ key, teams: [keyMap.get(key), teamId] });
        } else {
          keyMap.set(key, teamId);
        }
      });

      if (duplicates.length > 0) {
        console.error('⚠️  發現重複key:', duplicates);
      } else {
        console.log('✅ 所有key都是唯一的');
      }

      return { keyMap: Object.fromEntries(keyMap), duplicates };
    },

    // 檢查兩個特定團隊的衝突
    checkTeamConflict: (teamId1, teamId2) => {
      console.log(`=== 檢查團隊 ${teamId1} 和 ${teamId2} 的衝突 ===`);
      const key1 = TRCache._execKey(teamId1, 'TEST');
      const key2 = TRCache._execKey(teamId2, 'TEST');
      const valid1 = TRCache._getValidTeamId(teamId1);
      const valid2 = TRCache._getValidTeamId(teamId2);

      console.log(`團隊1: ${teamId1} -> ${valid1} -> ${key1}`);
      console.log(`團隊2: ${teamId2} -> ${valid2} -> ${key2}`);

      if (key1 === key2) {
        console.error('⚠️  衝突！相同key:', key1);
        console.log('解決建議: TRCacheDebug.regenerateSession()');
        return { conflict: true, key: key1, teams: [teamId1, teamId2] };
      } else {
        console.log('✅ 無衝突');
        return { conflict: false, keys: [key1, key2] };
      }
    },

    // 重新生成會話ID（解決衝突）
    regenerateSession: () => {
      return TRCache.regenerateSession();
    },

    // 監控cache操作
    monitorCache: (enable = true) => {
      if (enable && !TRCache._monitoringEnabled) {
        const originalSetExec = TRCache.setExecDetail;
        TRCache.setExecDetail = function(teamId, testCaseNumber, obj) {
          const key = TRCache._execKey(teamId, testCaseNumber);
          const validTeamId = TRCache._getValidTeamId(teamId);
          console.log(`%c[Cache Monitor] 寫入`, 'color: #4CAF50; font-weight: bold', {
            原始TeamId: teamId,
            有效TeamId: validTeamId,
            測試案例: testCaseNumber,
            快取Key: key,
            數據大小: JSON.stringify(obj).length + ' bytes'
          });
          return originalSetExec.call(this, teamId, testCaseNumber, obj);
        };

        const originalGetExec = TRCache.getExecDetail;
        TRCache.getExecDetail = function(teamId, testCaseNumber, ttl) {
          const key = TRCache._execKey(teamId, testCaseNumber);
          const validTeamId = TRCache._getValidTeamId(teamId);
          console.log(`%c[Cache Monitor] 讀取`, 'color: #2196F3; font-weight: bold', {
            原始TeamId: teamId,
            有效TeamId: validTeamId,
            測試案例: testCaseNumber,
            快取Key: key,
            TTL: ttl ? (ttl/1000/60).toFixed(1) + '分鐘' : '無限制'
          });
          return originalGetExec.call(this, teamId, testCaseNumber, ttl);
        };

        const originalSetTCG = TRCache.setTCG;
        TRCache.setTCG = function(list) {
          console.log(`%c[Cache Monitor] TCG寫入`, 'color: #FF9800; font-weight: bold', {
            項目數量: Array.isArray(list) ? list.length : 0,
            數據大小: JSON.stringify(list || []).length + ' bytes'
          });
          return originalSetTCG.call(this, list);
        };

        TRCache._monitoringEnabled = true;
        console.log('%c[Cache Monitor] 已啟用cache操作監控', 'color: #4CAF50; font-weight: bold; background: #E8F5E8; padding: 4px 8px; border-radius: 4px');
      } else if (enable && TRCache._monitoringEnabled) {
        console.log('[Cache Monitor] 監控已經啟用');
      } else {
        console.log('[Cache Monitor] 監控功能需要重新載入頁面來停用');
      }
    },

    // 基本key測試
    testKeys: () => {
      console.log('Key 測試:');
      console.log('null:', TRCache._execKey(null, 'TEST'));
      console.log('undefined:', TRCache._execKey(undefined, 'TEST'));
      console.log('"1":', TRCache._execKey('1', 'TEST'));
      console.log('"2":', TRCache._execKey('2', 'TEST'));
      console.log('1 (數字):', TRCache._execKey(1, 'TEST'));
      console.log('2 (數字):', TRCache._execKey(2, 'TEST'));
    },

    // 列出所有快取key
    listCacheKeys: async () => {
      try {
        const db = await TRCache._openDB();
        const execKeys = [];
        const tcgKeys = [];

        // 獲取exec快取keys
        await new Promise((resolve) => {
          const tx = db.transaction(['exec_tc'], 'readonly');
          const store = tx.objectStore('exec_tc');
          store.openCursor().onsuccess = (event) => {
            const cursor = event.target.result;
            if (cursor) {
              execKeys.push(cursor.key);
              cursor.continue();
            } else {
              resolve();
            }
          };
        });

        // 獲取TCG快取keys
        await new Promise((resolve) => {
          const tx = db.transaction(['tcg'], 'readonly');
          const store = tx.objectStore('tcg');
          store.openCursor().onsuccess = (event) => {
            const cursor = event.target.result;
            if (cursor) {
              tcgKeys.push(cursor.key);
              cursor.continue();
            } else {
              resolve();
            }
          };
        });

        console.log('=== 快取Key列表 ===');
        console.log('執行快取Keys:', execKeys);
        console.log('TCG快取Keys:', tcgKeys);
        return { execKeys, tcgKeys };
      } catch (e) {
        console.error('列出快取Keys失敗:', e);
      }
    }
  };

  // 初始化時顯示版本信息和啟用監控
  if (TRCache.enableErrorLogging) {
    console.log('[TRCache] 已載入，版本: v2.3 (預設監控)', '\n調試指令: TRCacheDebug.diagnoseTeam()\n衝突檢查: TRCacheDebug.checkTeamConflict(teamId1, teamId2)');

    // 預設啟用快取操作監控
    setTimeout(() => {
      TRCacheDebug.monitorCache(true);
    }, 100);
  }
})(window);
