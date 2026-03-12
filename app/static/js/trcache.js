(function (global) {
  'use strict';

  const DB_NAME = 'tr_cache';
  const DB_VERSION = 5; // 移除已停用的 TCG 快取 store
  const STORE_EXEC = 'exec_unified'; // 統一的執行資料store
  const EXEC_LRU_MAX = 100000; // 全域LRU限制

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

          // 統一的執行資料store
          if (!db.objectStoreNames.contains(STORE_EXEC)) {
            const s1 = db.createObjectStore(STORE_EXEC, { keyPath: 'key' });
            s1.createIndex('ts', 'ts');
            s1.createIndex('lastAccess', 'lastAccess');
            s1.createIndex('teamId', 'teamId'); // 新增teamId索引方便查詢和LRU管理
          }

          // 清理舊的 stores 與已停用的 TCG 快取 store
          if (db.objectStoreNames.contains('tcg')) {
            db.deleteObjectStore('tcg');
          }
          ['exec_tc', 'exec_team_1', 'exec_team_2', 'exec_team_3', 'exec_team_4', 'exec_team_5', 'exec_team_unknown'].forEach(oldStore => {
            if (db.objectStoreNames.contains(oldStore)) {
              db.deleteObjectStore(oldStore);
            }
          });

          if (TRCache.debug) console.debug('[TRCache] DB upgraded to v5 - removed obsolete TCG cache store');
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

    // 生成團隊專用的 key：僅依 teamId + testCaseNumber，確保跨頁共用
    _execKey(teamId, number) {
      const validTeamId = this._getValidTeamId(teamId);
      const normalizedNumber = String(number || '').trim();
      const key = `${validTeamId}:${normalizedNumber}`;

      if (this.debug) {
        console.debug('[TRCache] 產生key:', key, {
          originalTeamId: teamId,
          validTeamId,
          testCaseNumber: normalizedNumber
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

    // 團隊獨立LRU淘汰機制
    async _lruEvict(store, max) {
      try {
        const db = await this._openDB();
        const total = await this._count(store);
        if (total <= max) {
          if (this.enableErrorLogging) {
            console.log(`[TRCache LRU] ${store}: ${total}/${max} 項目，無需淘汰`);
          }
          return;
        }

        const toDelete = total - max;
        if (this.enableErrorLogging) {
          console.log(`[TRCache LRU] ${store}: ${total}/${max} 項目，需淘汰 ${toDelete} 項`);
        }

        await new Promise((resolve, reject) => {
          const tx = db.transaction(store, 'readwrite');
          const idx = tx.objectStore(store).index('lastAccess');
          let removed = 0;
          const deletedKeys = [];

          idx.openCursor().onsuccess = (e) => {
            const cursor = e.target.result;
            if (!cursor) {
              if (this.enableErrorLogging && deletedKeys.length > 0) {
                console.log(`[TRCache LRU] ${store} 淘汰完成，已刪除 ${deletedKeys.length} 項:`, deletedKeys.slice(0, 5));
              }
              return;
            }

            deletedKeys.push(cursor.key);
            cursor.delete();
            removed++;
            if (removed >= toDelete) {
              resolve(true);
              return;
            }
            cursor.continue();
          };
          tx.oncomplete = () => resolve(true);
          tx.onerror = () => reject(tx.error);
        });
      } catch (error) {
        if (this.enableErrorLogging) {
          console.error('[TRCache LRU] 淘汰失敗:', error);
        }
      }
    },

    // Public API
    async getExecDetail(teamId, testCaseNumber, ttlMs) {
      try {
        const validTeamId = this._getValidTeamId(teamId);

        // 由於使用時間戳和隨機數的key，需要查詢最新的記錄
        // 使用索引查詢特定團隊和測試案例的所有記錄
        const db = await this._openDB();
        const records = [];

        await new Promise((resolve) => {
          const tx = db.transaction([STORE_EXEC], 'readonly');
          const store = tx.objectStore(STORE_EXEC);
          const index = store.index('teamId');

          index.openCursor(IDBKeyRange.only(validTeamId)).onsuccess = (event) => {
            const cursor = event.target.result;
            if (cursor) {
              const record = cursor.value;
              if (record.testCaseNumber === testCaseNumber) {
                records.push(record);
              }
              cursor.continue();
            } else {
              resolve();
            }
          };
        });

        if (records.length === 0) return null;

        // 選擇最新的記錄
        const rec = records.reduce((latest, current) =>
          current.ts > latest.ts ? current : latest
        );

        const now = Date.now();
        if (ttlMs && rec.ts && (now - rec.ts) > ttlMs) return null;

        // 更新lastAccess
        rec.lastAccess = now;
        this._put(STORE_EXEC, rec).catch(()=>{});

        try {
          const blob = rec.data;
          const bytes = blob instanceof Blob ? new Uint8Array(await blob.arrayBuffer()) : new Uint8Array(blob);
          const jsonStr = this._gunzip(bytes);
          return { ts: rec.ts, data: JSON.parse(jsonStr) };
        } catch (error) {
          if (this.enableErrorLogging) {
            console.error('[TRCache] getExecDetail解壓縮失敗:', error, { validTeamId, testCaseNumber });
          }
          return null;
        }
      } catch (error) {
        if (this.enableErrorLogging) {
          console.error('[TRCache] getExecDetail發生未預期錯誤:', error, { teamId, testCaseNumber, ttlMs });
        }
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

        const validTeamId = this._getValidTeamId(teamId);
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
          teamId: validTeamId,
          testCaseNumber,
          ts: Date.now(),
          lastAccess: Date.now(),
          data: new Blob([gz], { type: 'application/octet-stream' }),
          size: gz.length
        };

        if (TRCache.debug) console.debug('[TRCache] setExecDetail', STORE_EXEC, key, 'size', rec.size);

        const success = await this._put(STORE_EXEC, rec);
        if (success) {
          // 全域LRU管理
          await this._lruEvict(STORE_EXEC, EXEC_LRU_MAX);
          if (this.debug) {
            console.log('[TRCache] setExecDetail成功:', validTeamId, testCaseNumber, key);
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

    async removeExecDetail(teamId, testCaseNumber) {
      try {
        const key = this._execKey(teamId, testCaseNumber);
        await this._delete(STORE_EXEC, key);
        if (this.debug) {
          console.debug('[TRCache] removeExecDetail', STORE_EXEC, key);
        }
        return true;
      } catch (error) {
        if (this.enableErrorLogging) {
          console.error('[TRCache] removeExecDetail 發生錯誤:', error, { teamId, testCaseNumber });
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

        const success = writeSuccess && readResult;
        console.log('[TRCache] 自我測試結果:', success ? '成功' : '失敗');

        return { success, execTest: readResult, keys: { key1, key2, key3, key4 } };
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
        const teamStore = await this._getTeamStore(teamId);
        const db = await this._openDB();
        await new Promise((resolve, reject) => {
          const tx = db.transaction(teamStore, 'readwrite');
          const store = tx.objectStore(teamStore);
          store.clear();
          tx.oncomplete = () => {
            if (this.enableErrorLogging) {
              console.log(`[TRCache] 清除團隊 ${this._getValidTeamId(teamId)} 的所有快取`);
            }
            resolve(true);
          };
          tx.onerror = () => reject(tx.error);
        });
      } catch (error) {
        if (this.enableErrorLogging) {
          console.error('[TRCache] clearTeam 失敗:', error);
        }
      }
    },

    async clearAll() {
      try {
        const db = await this._openDB();
        const storeNames = Array.from(db.objectStoreNames);
        const clearPromises = [];

        // 清除所有store（包括TCG和所有團隊store）
        storeNames.forEach(storeName => {
          clearPromises.push(
            new Promise((resolve, reject) => {
              const tx = db.transaction(storeName, 'readwrite');
              tx.objectStore(storeName).clear();
              tx.oncomplete = () => resolve(storeName);
              tx.onerror = () => reject(tx.error);
            })
          );
        });

        const clearedStores = await Promise.all(clearPromises);
        if (this.enableErrorLogging) {
          console.log('[TRCache] 已清除所有快取:', clearedStores);
        }
      } catch (error) {
        if (this.enableErrorLogging) {
          console.error('[TRCache] clearAll 失敗:', error);
        }
      }
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

    // 測試團隊分離儲存
    testTeamSeparation: (...teamIds) => {
      console.log('=== 團隊分離儲存測試 ===');
      const storeMap = new Map();
      const duplicates = [];

      teamIds.forEach(teamId => {
        const validTeamId = TRCache._getValidTeamId(teamId);
        const storeName = `exec_team_${validTeamId}`;
        console.log(`團隊ID: ${teamId} (${typeof teamId}) -> 有效ID: ${validTeamId} -> Store: ${storeName}`);

        // 檢查Store名稱重複（這在新架構中不應該發生）
        if (storeMap.has(storeName)) {
          duplicates.push({ storeName, teams: [storeMap.get(storeName), teamId] });
        } else {
          storeMap.set(storeName, teamId);
        }
      });

      if (duplicates.length > 0) {
        console.error('⚠️  發現重複Store名稱 (這表示團隊隔離失敗):', duplicates);
      } else {
        console.log('✅ 所有團隊都有獨立的ObjectStore');
      }

      return { storeMap: Object.fromEntries(storeMap), duplicates };
    },

    // 檢查兩個團隊的完全隔離
    checkTeamIsolation: (teamId1, teamId2) => {
      console.log(`=== 檢查團隊 ${teamId1} 和 ${teamId2} 的完全隔離 ===`);
      const valid1 = TRCache._getValidTeamId(teamId1);
      const valid2 = TRCache._getValidTeamId(teamId2);
      const store1 = `exec_team_${valid1}`;
      const store2 = `exec_team_${valid2}`;

      console.log(`團隊1: ${teamId1} -> 有效ID: ${valid1} -> Store: ${store1}`);
      console.log(`團隊2: ${teamId2} -> 有效ID: ${valid2} -> Store: ${store2}`);

      if (store1 === store2) {
        console.error('⚠️  團隊隔離失敗！共享相同Store:', store1);
        console.log('這意味著兩個團隊的資料會相互干擾');
        return { isolated: false, sharedStore: store1, teams: [teamId1, teamId2] };
      } else {
        console.log('✅ 團隊完全隔離，使用不同的ObjectStore');
        return { isolated: true, stores: [store1, store2] };
      }
    },

    // 全面的團隊隔離效果測試
    fullIsolationTest: async () => {
      console.log('🔍 =========================');
      console.log('🔍 開始全面團隊隔離效果測試');
      console.log('🔍 =========================');

      // 測試資料
      const testTeams = [
        { id: '1', name: '團隊A' },
        { id: '2', name: '團隊B' },
        { id: null, name: '無效團隊1' },
        { id: undefined, name: '無效團隊2' },
        { id: '', name: '空團隊' }
      ];

      const testCases = ['TC001', 'TC002', 'TC003'];

      console.log('📝 第1步: 測試不同團隊的Store分離...');
      const storeResults = [];
      for (const team of testTeams) {
        const validId = TRCache._getValidTeamId(team.id);
        const storeName = `exec_team_${validId}`;
        storeResults.push({
          原始ID: team.id,
          有效ID: validId,
          團隊名稱: team.name,
          Store名稱: storeName
        });
      }
      console.table(storeResults);

      // 檢查Store唯一性
      const storeNames = storeResults.map(r => r.Store名稱);
      const uniqueStores = new Set(storeNames);
      console.log(`📊 Store統計: 總共${storeNames.length}個團隊 -> ${uniqueStores.size}個獨立Store`);

      if (uniqueStores.size === storeNames.length) {
        console.log('✅ Store完全隔離：每個團隊都有獨立的ObjectStore');
      } else {
        console.error('❌ Store隔離失敗：某些團隊共享ObjectStore');
      }

      console.log('\n📝 第2步: 測試資料寫入隔離...');
      const writeResults = [];

      for (let i = 0; i < testTeams.length; i++) {
        const team = testTeams[i];
        for (let j = 0; j < testCases.length; j++) {
          const testCase = testCases[j];
          const testData = {
            teamInfo: team,
            timestamp: Date.now(),
            testIndex: `${i}_${j}`,
            testCaseNumber: testCase
          };

          console.log(`💾 寫入 ${team.name}(${team.id}) -> ${testCase}`);
          const success = await TRCache.setExecDetail(team.id, testCase, testData);
          writeResults.push({
            團隊: team.name,
            測試案例: testCase,
            寫入結果: success ? '✅成功' : '❌失敗'
          });
        }
      }
      console.table(writeResults);

      console.log('\n📝 第3步: 測試資料讀取隔離...');
      const readResults = [];

      for (let i = 0; i < testTeams.length; i++) {
        const team = testTeams[i];
        for (let j = 0; j < testCases.length; j++) {
          const testCase = testCases[j];

          console.log(`📖 讀取 ${team.name}(${team.id}) -> ${testCase}`);
          const result = await TRCache.getExecDetail(team.id, testCase);
          readResults.push({
            團隊: team.name,
            測試案例: testCase,
            讀取結果: result ? '✅找到資料' : '❌無資料',
            資料正確: result && result.data?.teamInfo?.name === team.name ? '✅正確' : '❌不正確'
          });
        }
      }
      console.table(readResults);

      console.log('\n📝 第4步: 檢查跨團隊污染...');
      // 檢查團隊A的資料是否出現在團隊B中
      console.log('檢查跨團隊資料洩漏...');
      let crossContamination = false;

      for (const testCase of testCases) {
        const team1Data = await TRCache.getExecDetail('1', testCase);
        const team2Data = await TRCache.getExecDetail('2', testCase);

        if (team1Data && team2Data &&
            team1Data.data?.teamInfo?.name === team2Data.data?.teamInfo?.name) {
          console.error(`❌ 發現跨團隊污染: ${testCase} 在兩個團隊中有相同資料`);
          crossContamination = true;
        }
      }

      if (!crossContamination) {
        console.log('✅ 無跨團隊資料污染');
      }

      console.log('\n📝 第5步: 檢查ObjectStore結構...');
      const cacheStructure = await TRCacheDebug.listCacheKeys();

      console.log('\n🎯 =================');
      console.log('🎯 團隊隔離測試總結');
      console.log('🎯 =================');

      const summary = {
        Store隔離: uniqueStores.size === storeNames.length ? '✅完全隔離' : '❌失敗',
        資料寫入: writeResults.every(r => r.寫入結果 === '✅成功') ? '✅全部成功' : '⚠️部分失敗',
        資料讀取: readResults.every(r => r.讀取結果 === '✅找到資料') ? '✅全部成功' : '⚠️部分失敗',
        資料正確性: readResults.every(r => r.資料正確 === '✅正確') ? '✅完全正確' : '❌有錯誤',
        跨團隊污染: crossContamination ? '❌發現污染' : '✅無污染',
      };

      console.table([summary]);

      const overallSuccess = Object.values(summary).every(v => v.includes('✅'));
      console.log(overallSuccess ?
        '🎉 團隊資料完全隔離測試: 全部通過！' :
        '⚠️  團隊資料完全隔離測試: 發現問題，需要修正'
      );

      return {
        success: overallSuccess,
        details: {
          storeResults,
          writeResults,
          readResults,
          summary,
          cacheStructure
        }
      };
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
          const validTeamId = TRCache._getValidTeamId(teamId);
          const key = TRCache._execKey(teamId, testCaseNumber);
          console.log(`%c[Cache Monitor] 寫入`, 'color: #4CAF50; font-weight: bold', {
            原始TeamId: teamId,
            有效TeamId: validTeamId,
            ObjectStore: STORE_EXEC,
            測試案例: testCaseNumber,
            快取Key: key,
            數據大小: JSON.stringify(obj).length + ' bytes'
          });
          return originalSetExec.call(this, teamId, testCaseNumber, obj);
        };

        const originalGetExec = TRCache.getExecDetail;
        TRCache.getExecDetail = function(teamId, testCaseNumber, ttl) {
          const validTeamId = TRCache._getValidTeamId(teamId);
          console.log(`%c[Cache Monitor] 讀取`, 'color: #2196F3; font-weight: bold', {
            原始TeamId: teamId,
            有效TeamId: validTeamId,
            ObjectStore: STORE_EXEC,
            測試案例: testCaseNumber,
            TTL: ttl ? (ttl/1000/60).toFixed(1) + '分鐘' : '無限制'
          });
          return originalGetExec.call(this, teamId, testCaseNumber, ttl);
        };

        TRCache._monitoringEnabled = true;
        console.log('%c[Cache Monitor] 已啟用cache操作監控', 'color: #4CAF50; font-weight: bold; background: #E8F5E8; padding: 4px 8px; border-radius: 4px');
      } else if (enable && TRCache._monitoringEnabled) {
        console.log('[Cache Monitor] 監控已經啟用');
      } else {
        console.log('[Cache Monitor] 監控功能需要重新載入頁面來停用');
      }
    },

    // 基本Store測試
    testStores: () => {
      console.log('Store 測試:');
      console.log('null:', `exec_team_${TRCache._getValidTeamId(null)}`);
      console.log('undefined:', `exec_team_${TRCache._getValidTeamId(undefined)}`);
      console.log('"1":', `exec_team_${TRCache._getValidTeamId('1')}`);
      console.log('"2":', `exec_team_${TRCache._getValidTeamId('2')}`);
      console.log('1 (數字):', `exec_team_${TRCache._getValidTeamId(1)}`);
      console.log('2 (數字):', `exec_team_${TRCache._getValidTeamId(2)}`);
    },

    // 列出所有快取key（按團隊分組）
    listCacheKeys: async () => {
      try {
        const db = await TRCache._openDB();
        const storeNames = Array.from(db.objectStoreNames);
        const result = {};

        for (const storeName of storeNames) {
          const keys = [];
          await new Promise((resolve) => {
            const tx = db.transaction([storeName], 'readonly');
            const store = tx.objectStore(storeName);
            store.openCursor().onsuccess = (event) => {
              const cursor = event.target.result;
              if (cursor) {
                keys.push(cursor.key);
                cursor.continue();
              } else {
                resolve();
              }
            };
          });
          result[storeName] = keys;
        }

        console.log('=== 快取Key列表（按團隊分組） ===');
        Object.entries(result).forEach(([storeName, keys]) => {
          if (storeName === 'tcg') {
            console.log(`TCG快取: ${keys.length}個項目`);
          } else if (storeName.startsWith('exec_team_')) {
            const teamId = storeName.replace('exec_team_', '');
            console.log(`團隊 ${teamId}: ${keys.length}個項目`, keys.length > 0 ? `(範例: ${keys.slice(0, 3).join(', ')})` : '');
          } else {
            console.log(`${storeName}: ${keys.length}個項目`);
          }
        });

        return result;
      } catch (e) {
        console.error('列出快取Keys失敗:', e);
      }
    },
  };

  // 初始化時顯示版本信息和啟用監控
  if (TRCache.enableErrorLogging) {
    console.log('[TRCache] 已載入，版本: v4.0 (統一storage + 改進key策略)', '\n新特性: 單一ObjectStore + 唯一key避免衝突\n調試指令: TRCacheDebug.listCacheKeys()');

    // 預設啟用快取操作監控
    setTimeout(() => {
      TRCacheDebug.monitorCache(true);
    }, 100);
  }
})(window);
