// 全域應用程式物件
const AppUtils = {
    // 當前選中的團隊
    currentTeam: null,

    // 設定當前團隊
    setCurrentTeam: function(team) {
        this.currentTeam = team;
        localStorage.setItem('currentTeam', JSON.stringify(team));
        this.triggerTeamChangeEvent();
    },

    // 獲取當前團隊
    getCurrentTeam: function() {
        if (!this.currentTeam) {
            const stored = localStorage.getItem('currentTeam');
            if (stored) {
                this.currentTeam = JSON.parse(stored);
            }
        }
        return this.currentTeam;
    },

    // 獲取當前團隊 ID
    getCurrentTeamId: function() {
        const team = this.getCurrentTeam();
        return team ? team.id.toString() : null;
    },

    // 清除當前團隊
    clearCurrentTeam: function() {
        this.currentTeam = null;
        localStorage.removeItem('currentTeam');
        this.triggerTeamClearEvent();
    },

    // 觸發團隊變更事件
    triggerTeamChangeEvent: function() {
        const event = new CustomEvent('teamChanged', { 
            detail: { team: this.currentTeam } 
        });
        window.dispatchEvent(event);
    },

    // 觸發團隊清除事件
    triggerTeamClearEvent: function() {
        const event = new CustomEvent('teamCleared');
        window.dispatchEvent(event);
    },

    // 顯示成功訊息
    showSuccess: function(message) {
        this.showMessage(message, 'success');
    },

    // 顯示錯誤訊息
    showError: function(message) {
        this.showMessage(message, 'danger');
    },

    // 顯示資訊訊息
    showInfo: function(message) {
        this.showMessage(message, 'info');
    },

    // 顯示警告訊息
    showWarning: function(message) {
        this.showMessage(message, 'warning');
    },

    // 顯示確認對話框
    showConfirm: function(message) {
        return new Promise((resolve) => {
            const confirmed = window.confirm(message);
            resolve(confirmed);
        });
    },

    // 通用訊息顯示函數
    showMessage: function(message, type = 'info') {
        const container = document.getElementById('flash-messages');
        if (!container) return;

        const alertId = 'alert-' + Date.now();
        const alertHtml = `
            <div class="alert alert-${type} alert-dismissible fade show" role="alert" id="${alertId}">
                ${message}
                <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
            </div>
        `;

        container.insertAdjacentHTML('beforeend', alertHtml);

        // 3 秒後自動移除訊息
        setTimeout(() => {
            const alertElement = document.getElementById(alertId);
            if (alertElement) {
                const bsAlert = bootstrap.Alert.getOrCreateInstance(alertElement);
                bsAlert.close();
            }
        }, 3000);
    },

    // 格式化日期 - 使用瀏覽器的 locale 設定，不依賴介面語言
    formatDate: function(dateString, format = 'datetime') {
        if (!dateString) return '';
        
        // 使用新的 DateTimeFormatter 模組，它會自動使用瀏覽器的 locale 設定
        if (window.DateTimeFormatter) {
            return window.DateTimeFormatter.format(dateString, format);
        }
        
        // 備用方案：如果 DateTimeFormatter 尚未載入，使用瀏覽器預設 locale
        let date;
        // Handle UTC time strings without timezone identifier (support both 'T' and ' ' separators)
        if (typeof dateString === 'string' && dateString.match(/^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(\.\d+)?$/) && !dateString.endsWith('Z')) {
            const isoString = dateString.includes('T') ? dateString + 'Z' : dateString.replace(' ', 'T') + 'Z';
            date = new Date(isoString);
        } else {
            date = new Date(dateString);
        }
        if (isNaN(date.getTime())) return '';
        
        // 使用瀏覽器的預設 locale 而非硬編碼的 'zh-TW'
        const browserLocale = navigator.language || navigator.userLanguage || 'en-US';
        
        // 使用地區標準格式，讓各地區顯示符合當地慣例的格式
        if (format === 'date') {
            return date.toLocaleDateString(browserLocale);
        } else if (format === 'datetime') {
            return date.toLocaleString(browserLocale);
        } else if (format === 'datetime-tz') {
            // 顯示包含時區資訊的日期時間格式
            return date.toLocaleString(browserLocale, {
                year: 'numeric',
                month: 'numeric', 
                day: 'numeric',
                hour: 'numeric',
                minute: '2-digit',
                timeZoneName: 'short'
            });
        } else if (format === 'time') {
            return date.toLocaleTimeString(browserLocale);
        }

        return date.toLocaleString(browserLocale);
    },

    // 格式化相對時間 (e.g., "2 hours ago", "in 3 days")
    formatRelativeTime: function(dateString) {
        if (window.DateTimeFormatter) {
            return window.DateTimeFormatter.formatRelative(dateString);
        }
        
        // 簡單備用方案
        return this.formatDate(dateString, 'datetime');
    },

    // 獲取瀏覽器的 locale 設定
    getBrowserLocale: function() {
        if (window.DateTimeFormatter) {
            return window.DateTimeFormatter.getBrowserLocale();
        }
        return navigator.language || navigator.userLanguage || 'en-US';
    },

    // 團隊變更回調函數 (可由外部設定)
    onTeamChange: null,

    // 顯示團隊名稱標籤
    showTeamNameBadge: function() {
        const team = this.getCurrentTeam();
        const badge = document.getElementById('team-name-badge');
        const text = document.getElementById('team-name-text');

        if (team && badge && text) {
            text.textContent = team.name;
            badge.classList.remove('d-none');
        } else if (badge) {
            badge.classList.add('d-none');
        }
    },

    // 更新團隊名稱標籤
    updateTeamNameBadge: function() {
        const team = this.getCurrentTeam();
        if (team) {
            this.showTeamNameBadge();
        } else {
            this.hideTeamNameBadge();
        }
    },

    // 隱藏團隊名稱標籤
    hideTeamNameBadge: function() {
        const badge = document.getElementById('team-name-badge');
        if (badge) {
            badge.classList.add('d-none');
        }
    },

    // 顯示手動複製連結對話框（統一介面）
    showCopyModal: function(text, options = {}) {
        const translate = (key) => (window.i18n && typeof window.i18n.t === 'function') ? window.i18n.t(key) : null;
        const title = options.title || translate('copyModal.title') || '手動複製連結';
        const instruction = options.instruction || translate('copyModal.instruction') || '請使用 Ctrl/Cmd + C 進行複製';
        const selectLabel = options.selectLabel || translate('copyModal.select') || '選取';
        const closeLabel = options.closeLabel || translate('common.close') || '關閉';
        const urlLabel = options.urlLabel || translate('copyModal.url') || 'URL';

        try {
            const existing = document.getElementById('copyModal');
            if (existing && existing.closest('.modal')) {
                const inst = bootstrap.Modal.getInstance(existing.closest('.modal'));
                if (inst) inst.hide();
                existing.closest('.modal').remove();
            }
        } catch (_) {}

        const wrapper = document.createElement('div');
        wrapper.innerHTML = `
            <div class="modal fade" id="copyModal" tabindex="-1" aria-hidden="true">
              <div class="modal-dialog modal-dialog-centered">
                <div class="modal-content">
                  <div class="modal-header">
                    <h5 class="modal-title">${title}</h5>
                    <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
                  </div>
                  <div class="modal-body">
                    <div class="mb-2">
                      <label class="form-label">${urlLabel}</label>
                      <input id="copyModalInput" type="text" class="form-control" readonly value="${text || ''}">
                    </div>
                    <small class="text-muted">${instruction}</small>
                  </div>
                  <div class="modal-footer">
                    <button type="button" class="btn btn-outline-secondary" data-bs-dismiss="modal">${closeLabel}</button>
                    <button type="button" class="btn btn-primary" id="copySelectBtn">${selectLabel}</button>
                  </div>
                </div>
              </div>
            </div>`;
        document.body.appendChild(wrapper);
        const modalEl = wrapper.querySelector('#copyModal');
        const modal = new bootstrap.Modal(modalEl);
        const inputEl = wrapper.querySelector('#copyModalInput');
        const selectBtn = wrapper.querySelector('#copySelectBtn');

        const selectAll = () => {
            try {
                inputEl.focus();
                inputEl.select();
                inputEl.setSelectionRange(0, (inputEl.value || '').length);
            } catch (_) {}
        };

        modalEl.addEventListener('shown.bs.modal', selectAll);
        selectBtn.addEventListener('click', selectAll);
        modalEl.addEventListener('hidden.bs.modal', () => {
            // 移除包裹節點避免殘留
            wrapper.remove();
        });

        modal.show();
    }
};

// 全域翻譯監視器 - 處理動態內容的翻譯
class TranslationObserver {
    constructor() {
        this.observer = null;
        this.debounceTimer = null;
        this.init();
    }

    init() {
        // 監視 DOM 變化
        this.observer = new MutationObserver((mutations) => {
            let needsTranslation = false;

            mutations.forEach((mutation) => {
                if (mutation.type === 'childList') {
                    mutation.addedNodes.forEach((node) => {
                        if (node.nodeType === Node.ELEMENT_NODE) {
                            const element = node;
                            if (element.hasAttribute && (
                                element.hasAttribute('data-i18n') ||
                                element.querySelector && element.querySelector('[data-i18n]')
                            )) {
                                needsTranslation = true;
                            }
                        }
                    });
                } else if (mutation.type === 'attributes') {
                    if (mutation.attributeName && mutation.attributeName.startsWith('data-i18n')) {
                        needsTranslation = true;
                    }
                }
            });

            if (needsTranslation) {
                this.scheduleRetranslation();
            }
        });

        // 開始監視
        if (document.body) {
            this.observer.observe(document.body, {
                childList: true,
                subtree: true,
                attributes: true,
                attributeFilter: ['data-i18n', 'data-i18n-params', 'data-i18n-placeholder']
            });
        }
    }

    scheduleRetranslation() {
        // 防抖處理，避免頻繁重新翻譯
        if (this.debounceTimer) {
            clearTimeout(this.debounceTimer);
        }

        this.debounceTimer = setTimeout(() => {
            if (window.i18n && window.i18n.isReady()) {
                console.log('Retranslating page due to dynamic content changes');
                window.i18n.retranslate(document);
            }
        }, 100);
    }

    disconnect() {
        if (this.observer) {
            this.observer.disconnect();
        }
        if (this.debounceTimer) {
            clearTimeout(this.debounceTimer);
        }
    }
}

// 全域翻譯監視器實例
let translationObserver = null;

// 應用程式初始化
document.addEventListener('DOMContentLoaded', function() {
    // 載入儲存的團隊選擇
    AppUtils.getCurrentTeam();

    // 顯示團隊名稱標籤
    AppUtils.updateTeamNameBadge();
    // 背景驗證當前團隊是否仍存在，避免顯示過期的徽章
    (async () => {
        try {
            const team = AppUtils.getCurrentTeam();
            if (!team || !team.id) {
                AppUtils.hideTeamNameBadge();
                return;
            }
            const resp = await window.AuthClient.fetch(`/api/teams/${team.id}`);
            if (!resp.ok) {
                // 團隊不存在或取得失敗，清除並隱藏徽章
                AppUtils.clearCurrentTeam();
                AppUtils.hideTeamNameBadge();
            } else {
                // 團隊仍存在，確保徽章內容正確
                AppUtils.updateTeamNameBadge();
            }
        } catch (e) {
            // 網路或其他錯誤時，不干擾頁面；若沒有選擇團隊則維持隱藏
            const team = AppUtils.getCurrentTeam();
            if (!team || !team.id) AppUtils.hideTeamNameBadge();
        }
    })();

    // 初始化翻譯監視器
    if (!translationObserver) {
        translationObserver = new TranslationObserver();
    }
});

// 監聽 i18n 準備完成事件
document.addEventListener('i18nReady', function() {
    // 確保初始翻譯完成
    if (window.i18n) {
        window.i18n.retranslate(document);
    }
});

// 監聽語言變更事件
document.addEventListener('languageChanged', function() {
    // 語言變更後重新翻譯
    if (window.i18n) {
        setTimeout(() => window.i18n.retranslate(document), 50);
    }
});

// 全域函數 (向後兼容)
function selectTeamGlobally(teamId) {
    // 這個函數會在需要時被其他頁面使用
    AppUtils.setCurrentTeam({ id: teamId });
}

// 全域刷新當前頁面資料的函數
function refreshCurrentPageData() {
    // 觸發頁面資料刷新事件
    const event = new CustomEvent('refreshPageData');
    window.dispatchEvent(event);
}

// ----------------------------------------------
// 隱藏模式：Konami Code（上上下下左右左右BA）
// 偵測到後顯示一個 Bootstrap Modal（先佈署外觀，功能後續再設計）
// ----------------------------------------------
(function setupHiddenMode() {
    // 定義序列（最後兩個按鍵接受 A/a 與 B/b）
    const KONAMI_SEQUENCE = [
        'ArrowUp','ArrowUp','ArrowDown','ArrowDown',
        'ArrowLeft','ArrowRight','ArrowLeft','ArrowRight',
        'b','a'
    ];

    let buffer = [];

    function normalizeKey(e) {
        const k = e.key;
        // 僅接受方向鍵與 a/b，忽略其他組合鍵
        if (k.startsWith('Arrow')) return k;
        if (k === 'a' || k === 'A') return 'a';
        if (k === 'b' || k === 'B') return 'b';
        return null;
    }

async function showHiddenModeModal() {
    try {
        const userInfo = await window.AuthClient.getUserInfo();
        if (!userInfo || userInfo.role !== 'super_admin') {
            showMorse404Modal();
            return;
        }
    } catch (e) {
        console.warn('無法獲取用戶角色，顯示 404 modal:', e);
        showMorse404Modal();
        return;
    }

    // 如已存在同名 modal，先移除避免重覆
    try {
        const existing = document.getElementById('hiddenModeModal');
        if (existing && existing.closest('.modal')) {
            const inst = bootstrap.Modal.getInstance(existing.closest('.modal'));
            if (inst) inst.hide();
            existing.closest('.modal').remove();
        }
    } catch (_) {}

    const wrapper = document.createElement('div');
    wrapper.innerHTML = `
        <div class="modal fade" id="hiddenModeModal" tabindex="-1" aria-hidden="true">
          <div class="modal-dialog modal-dialog-centered" style="max-width: 1000px; width: 1000px;">
            <div class="modal-content" style="height: 700px; display: flex; flex-direction: column;">
              <div class="modal-header">
                <h5 class="modal-title">隱藏模式</h5>
                <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
              </div>
              <div class="modal-body" style="flex: 1 1 auto; overflow: auto;">
                <!-- Tabs -->
                <ul class="nav nav-tabs" id="hiddenModeTabs" role="tablist">
                  <li class="nav-item" role="presentation">
                    <button class="nav-link active" id="sys-tab" data-bs-toggle="tab" data-bs-target="#sys-pane" type="button" role="tab" aria-controls="sys-pane" aria-selected="true">系統監控</button>
                  </li>
                  <li class="nav-item" role="presentation">
                    <button class="nav-link" id="stats-tab" data-bs-toggle="tab" data-bs-target="#stats-pane" type="button" role="tab" aria-controls="stats-pane" aria-selected="false">數據統計</button>
                  </li>
                </ul>
                <div class="tab-content pt-3">
                  <!-- 系統監控 -->
                  <div class="tab-pane fade show active" id="sys-pane" role="tabpanel" aria-labelledby="sys-tab">
                    <div class="border rounded p-2">
                      <div class="d-flex justify-content-between align-items-center mb-2">
                        <div class="fw-semibold">伺服器資源監控</div>
                        <div>
                          <span id="hm-last-updated" class="text-muted small">—</span>
                        </div>
                      </div>
                      <div id="hm-metrics" class="small">
                        <div class="text-muted">讀取中…</div>
                      </div>
                    </div>
                  </div>

                  <!-- 數據統計 -->
                  <div class="tab-pane fade" id="stats-pane" role="tabpanel" aria-labelledby="stats-tab">
                    <div class="d-flex justify-content-between align-items-center mb-2">
                      <div class="fw-semibold">過去 30 天</div>
                      <div class="text-muted small" id="stats-last-updated">—</div>
                    </div>
                    <div class="mb-3">
                      <div class="small text-muted mb-1">各 Team 每日新增 Test Case</div>
                      <canvas id="hm-chart-tc-daily" height="140"></canvas>
                    </div>
                    <div>
                      <div class="small text-muted mb-1">每日 Test Run 操作次數</div>
                      <canvas id="hm-chart-tr-daily" height="140"></canvas>
                    </div>
                  </div>
                </div>
              </div>
              <div class="modal-footer">
                <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">關閉</button>
              </div>
            </div>
          </div>
        </div>`;

        document.body.appendChild(wrapper);
        const modalEl = wrapper.querySelector('#hiddenModeModal');
        const modal = new bootstrap.Modal(modalEl, { backdrop: true });

        let timer = null;
        let abortCtrl = null;

        // Chart instances
        let tcDailyChart = null;
        let trDailyChart = null;

        function fmtBytes(bytes) {
            if (bytes == null) return '—';
            const units = ['B','KB','MB','GB','TB'];
            let u = 0; let val = Number(bytes);
            while (val >= 1024 && u < units.length - 1) { val /= 1024; u++; }
            return `${val.toFixed(val >= 10 ? 0 : 1)} ${units[u]}`;
        }

        function fmtPct(p) { return (p == null) ? '—' : `${Number(p).toFixed(1)}%`; }
        function fmtUptime(s) {
            if (s == null) return '—';
            s = Math.floor(s);
            const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
            return `${h}h ${m}m ${sec}s`;
        }

        async function fetchMetrics() {
            try {
                if (abortCtrl) abortCtrl.abort();
                abortCtrl = new AbortController();
                const resp = await window.AuthClient.fetch('/api/admin/system_metrics', { signal: abortCtrl.signal });
                if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
                const data = await resp.json();
                renderMetrics(data);
            } catch (e) {
                const box = modalEl.querySelector('#hm-metrics');
                if (box) box.innerHTML = `<div class="text-danger">讀取失敗：${e?.message || e}</div>`;
            } finally {
                modalEl.querySelector('#hm-last-updated').textContent = new Date().toLocaleTimeString();
            }
        }

        function renderMetrics(data) {
            const load = data?.load || {};
            const cpu = data?.cpu || {};
            const mem = data?.memory || {};
            const box = modalEl.querySelector('#hm-metrics');
            if (!box) return;
            box.innerHTML = `
              <div class="row g-2">
                <div class="col-6">
                  <div class="text-muted">Uptime</div>
                  <div>${(function(){
                    const s = Math.floor(data?.uptime_seconds || 0);
                    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
                    return `${h}h ${m}m ${sec}s`;
                  })()}</div>
                </div>
                <div class="col-6">
                  <div class="text-muted">CPU</div>
                  <div>${(cpu.percent == null) ? '—' : `${Number(cpu.percent).toFixed(1)}%`}</div>
                </div>
                <div class="col-6">
                  <div class="text-muted">Load Avg (1/5/15)</div>
                  <div>${[load['1m'], load['5m'], load['15m']].map(v => (v==null? '—' : Number(v).toFixed(2))).join(' / ')}</div>
                </div>
                <div class="col-6">
                  <div class="text-muted">Process RSS</div>
                  <div>${fmtBytes(mem.process_rss)}</div>
                </div>
                <div class="col-6">
                  <div class="text-muted">Memory Used</div>
                  <div>${fmtBytes(mem.used)} (${(mem.percent == null) ? '—' : `${Number(mem.percent).toFixed(1)}%`})</div>
                </div>
                <div class="col-6">
                  <div class="text-muted">Memory Avail / Total</div>
                  <div>${fmtBytes(mem.available)} / ${fmtBytes(mem.total)}</div>
                </div>
              </div>
            `;
        }

        async function ensureChartJs() {
            if (window.Chart) return;
            await new Promise((resolve, reject) => {
                const s = document.createElement('script');
                s.src = 'https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js';
                s.onload = resolve; s.onerror = reject;
                document.head.appendChild(s);
            });
        }

        function groupByDayAndTeam(rows) {
            const labelsSet = new Set();
            const teamsSet = new Set();
            rows.forEach(r => { labelsSet.add(r.day); if (r.team_name) teamsSet.add(r.team_name); });
            const labels = Array.from(labelsSet).sort();
            const teams = Array.from(teamsSet);
            const datasets = teams.map((t, idx) => {
                const color = `hsl(${(idx*67)%360} 70% 50%)`;
                const data = labels.map(d => {
                    const found = rows.find(r => r.team_name===t && r.day===d);
                    return found ? found.count : 0;
                });
                return { label: t, data, borderColor: color, backgroundColor: color, tension: 0.2 };
            });
            return { labels, datasets };
        }

        const chartHiddenState = {
            tc: new Set(),
            tr: new Set()
        };


        async function loadStats(days = 30) {
            try {
                await ensureChartJs();
                const [tcResp, trResp] = await Promise.all([
                    window.AuthClient.fetch(`/api/admin/stats/test_cases_created_daily?days=${days}`),
                    window.AuthClient.fetch(`/api/admin/stats/test_run_actions_daily?days=${days}`)
                ]);
        
                if (!tcResp.ok) {
                    throw new Error(`Test Cases API: ${tcResp.status} ${tcResp.statusText}`);
                }
                if (!trResp.ok) {
                    throw new Error(`Test Run Actions API: ${trResp.status} ${trResp.statusText}`);
                }
        
                let tcJson, trJson;
                try {
                    tcJson = await tcResp.json();
                    trJson = await trResp.json();
                } catch (jsonErr) {
                    throw new Error('JSON 解析失敗：伺服器返回非 JSON 格式');
                }
        
                const tcCtx = modalEl.querySelector('#hm-chart-tc-daily');
                const trCtx = modalEl.querySelector('#hm-chart-tr-daily');
                if (tcDailyChart) { tcDailyChart.destroy(); }
                if (trDailyChart) { trDailyChart.destroy(); }
        
                // 檢查返回格式是否符合期望
                if (!tcJson.dates || !tcJson.counts || !trJson.dates || !trJson.counts) {
                    throw new Error('API 返回數據格式不正確');
                }
        
                // 為圖表準備數據：使用 dates 作為 labels，counts 作為單一數據集
                const tcLabels = tcJson.dates;
                const tcData = tcJson.counts;
                const trLabels = trJson.dates;
                const trData = trJson.counts;
        
                // 簡化圖表：單一數據集
                const tcDataset = [{
                    label: '每日新增 Test Cases',
                    data: tcData,
                    borderColor: 'hsl(200, 70%, 50%)',
                    backgroundColor: 'hsl(200, 70%, 50%)',
                    tension: 0.2
                }];
                const trDataset = [{
                    label: '每日 Test Run 動作',
                    data: trData,
                    borderColor: 'hsl(120, 70%, 50%)',
                    backgroundColor: 'hsl(120, 70%, 50%)',
                    tension: 0.2
                }];
        
                tcDailyChart = new Chart(tcCtx, {
                    type: 'line',
                    data: { labels: tcLabels, datasets: tcDataset },
                    options: {
                        responsive: true,
                        interaction: { intersect: false, mode: 'nearest' },
                        plugins: {
                            legend: { display: false },
                            tooltip: {
                                callbacks: {
                                    title: (items) => items?.[0]?.label || '',
                                    label: (item) => `${item.dataset.label}: ${item.formattedValue}`
                                }
                            }
                        },
                        scales: {
                            y: {
                                beginAtZero: true,
                                ticks: { precision: 0 }
                            }
                        }
                    }
                });
        
                trDailyChart = new Chart(trCtx, {
                    type: 'line',
                    data: { labels: trLabels, datasets: trDataset },
                    options: {
                        responsive: true,
                        interaction: { intersect: false, mode: 'nearest' },
                        plugins: {
                            legend: { display: false },
                            tooltip: {
                                callbacks: {
                                    title: (items) => items?.[0]?.label || '',
                                    label: (item) => `${item.dataset.label}: ${item.formattedValue}`
                                }
                            }
                        },
                        scales: {
                            y: {
                                beginAtZero: true,
                                ticks: { precision: 0 }
                            }
                        }
                    }
                });
        
                const statsStamp = modalEl.querySelector('#stats-last-updated');
                if (statsStamp) statsStamp.textContent = new Date().toLocaleTimeString();
        
                // 清除任何先前錯誤訊息
                const errorDiv = modalEl.querySelector('#stats-error');
                if (errorDiv) errorDiv.remove();
        
            } catch (e) {
                console.error('loadStats error', e);
                
                // 顯示友好錯誤訊息
                const statsPane = modalEl.querySelector('#stats-pane');
                if (statsPane) {
                    let errorDiv = statsPane.querySelector('#stats-error');
                    if (!errorDiv) {
                        errorDiv = document.createElement('div');
                        errorDiv.id = 'stats-error';
                        errorDiv.className = 'alert alert-warning';
                        statsPane.insertBefore(errorDiv, statsPane.firstChild);
                    }
                    errorDiv.innerHTML = `
                        <i class="fas fa-exclamation-triangle me-2"></i>
                        無法載入統計數據：${e.message || '未知錯誤'}
                    `;
                }
        
                const statsStamp = modalEl.querySelector('#stats-last-updated');
                if (statsStamp) statsStamp.textContent = '載入失敗';
            }
        }

        function start() {
            fetchMetrics();
            timer = setInterval(fetchMetrics, 2000);
            // 延遲載入統計，避免阻塞 modal 開啟
            setTimeout(() => loadStats(30), 200);
        }
        function stop() {
            if (timer) { clearInterval(timer); timer = null; }
            if (abortCtrl) { abortCtrl.abort(); abortCtrl = null; }
            if (tcDailyChart) { tcDailyChart.destroy(); tcDailyChart = null; }
            if (trDailyChart) { trDailyChart.destroy(); trDailyChart = null; }
        }

        modalEl.addEventListener('shown.bs.modal', start);
        modalEl.addEventListener('hidden.bs.modal', () => {
            stop();
            // 關閉後移除節點，保持整潔
            wrapper.remove();
        });

        modal.show();
    }

    function onKeydown(e) {
        // 避免在輸入框影響使用者輸入
        const tag = (e.target && e.target.tagName) ? e.target.tagName.toLowerCase() : '';
        if (tag === 'input' || tag === 'textarea' || tag === 'select' || e.isComposing) {
            return; 
        }

        const key = normalizeKey(e);
        if (!key) return;

        buffer.push(key);
        // 只保留最近 N 個
        if (buffer.length > KONAMI_SEQUENCE.length) {
            buffer.shift();
        }

        // 檢查是否完全匹配
        const matched = KONAMI_SEQUENCE.every((k, idx) => buffer[idx] === k);
        if (matched) {
            // 重置並顯示 modal
            buffer = [];
            showHiddenModeModal();
        }
    }

    // 404 Morse Code Modal 函數
    function showMorse404Modal() {
        // 如已存在同名 modal，先移除避免重覆
        try {
            const existing = document.getElementById('morse404Modal');
            if (existing && existing.closest('.modal')) {
                const inst = bootstrap.Modal.getInstance(existing.closest('.modal'));
                if (inst) inst.hide();
                existing.closest('.modal').remove();
            }
        } catch (_) {}

        const wrapper = document.createElement('div');
        wrapper.innerHTML = `
            <div class="modal fade" id="morse404Modal" tabindex="-1" aria-hidden="true">
              <div class="modal-dialog modal-dialog-centered">
                <div class="modal-content">
                  <div class="modal-header">
                    <h5 class="modal-title">404 - 存取被拒</h5>
                    <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
                  </div>
                  <div class="modal-body text-center">
                    <p class="mb-4">您無權限存取此隱藏模式。</p>
                    <div id="morse-animation" class="mb-3" style="font-size: 2rem; font-family: monospace; line-height: 2;">
                      <!-- 動畫將在這裡顯示 -->
                    </div>
                    <p class="text-muted small">摩斯電碼：404 Not Found</p>
                  </div>
                  <div class="modal-footer">
                    <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">關閉</button>
                  </div>
                </div>
              </div>
            </div>`;

        document.body.appendChild(wrapper);
        const modalEl = wrapper.querySelector('#morse404Modal');
        const modal = new bootstrap.Modal(modalEl);
        const animationEl = modalEl.querySelector('#morse-animation');

        // 摩斯碼序列：404 Not Found
        // 4: ....- 0: ----- 4: ....-   N: -. O: ---   F: ..-. O: --- U: ..- N: -. D: -..
        const morseSequence = [
            { code: '....-', letter: '4' },
            { code: '-----', letter: '0' },
            { code: '....-', letter: '4' },
            { code: '-.', letter: 'N' },
            { code: '---', letter: 'O' },
            { code: '..-.', letter: 'F' },
            { code: '---', letter: 'O' },
            { code: '..-', letter: 'U' },
            { code: '-.', letter: 'N' },
            { code: '-..', letter: 'D' }
        ];

        let currentIndex = 0;
        let currentCharIndex = 0;
        let intervalId = null;

        function playMorse() {
            if (currentIndex >= morseSequence.length) {
                // 循環重播
                currentIndex = 0;
                currentCharIndex = 0;
                animationEl.textContent = '';
                return;
            }

            const current = morseSequence[currentIndex];
            if (currentCharIndex < current.code.length) {
                const symbol = current.code[currentCharIndex];
                const display = symbol === '.' ? '·' : '—';
                animationEl.textContent = `${current.letter}: ${display}`;
                
                // 閃爍動畫：dit 短閃，dah 長閃
                const flashDuration = symbol === '.' ? 200 : 600;
                animationEl.style.color = '#000';
                setTimeout(() => {
                    animationEl.style.color = '#ff0000';
                    setTimeout(() => {
                        animationEl.style.color = '#000';
                        currentCharIndex++;
                        if (currentCharIndex >= current.code.length) {
                            currentCharIndex = 0;
                            currentIndex++;
                            setTimeout(() => {
                                animationEl.textContent += ' '; // 字母間空格
                            }, 400);
                        }
                    }, flashDuration);
                }, 100);
            }
        }

        function startAnimation() {
            playMorse();
            intervalId = setInterval(playMorse, 1000); // 每個符號間隔
        }

        function stopAnimation() {
            if (intervalId) {
                clearInterval(intervalId);
                intervalId = null;
            }
            animationEl.textContent = '';
        }

        modalEl.addEventListener('shown.bs.modal', startAnimation);
        modalEl.addEventListener('hidden.bs.modal', () => {
            stopAnimation();
            wrapper.remove();
        });

        modal.show();
    }

    document.addEventListener('keydown', onKeydown, { passive: true });
})();
