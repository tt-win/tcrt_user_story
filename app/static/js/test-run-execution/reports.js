/* Test Run Execution - Reports */

// 在 Charts & Reports 開啟時查詢報告狀態
(function(){
  // 保留掛鉤以後續擴充狀態展示，但目前不顯示或保存 URL
  const modal = document.getElementById('chartsReportsModal');
  if (modal) {
    modal.addEventListener('show.bs.modal', () => {});
  }
})();

// copyReportLink 移除：改由單一按鈕在生成後彈出手動複製視窗

// 生成 HTML 報告並複製連結
async function generateHtmlReport() {
  const btn = document.getElementById('generateHTMLBtn');
  const icon = document.getElementById('generateIcon');
  const text = document.getElementById('generateText');
  if (!btn) return;

  const translate = (key, params, fallback) => {
    if (window.i18n && typeof window.i18n.t === 'function') {
      return window.i18n.t(key, params || {}, fallback);
    }
    return typeof fallback !== 'undefined' ? fallback : key;
  };

  const defaultButtonLabel = translate('testRun.generateHtmlButton', {}, '生成並複製連結');
  const generatingLabel = translate('testRun.generatingHtml', {}, '生成中...');
  const generateFailed = translate('testRun.generateHtmlFailed', {}, '生成失敗');

  // 優先使用頁面內已初始化的 currentTeamId/currentConfigId
  let teamId = (typeof currentTeamId !== 'undefined' && currentTeamId) ? currentTeamId : null;
  let configId = (typeof currentConfigId !== 'undefined' && currentConfigId) ? currentConfigId : null;

  // 後備：從 URL 參數取得
  if (!teamId || !configId) {
    const params = new URLSearchParams(window.location.search);
    teamId = teamId || params.get('team_id') || params.get('teamId') || params.get('team');
    configId = configId || params.get('config_id') || params.get('configId') || params.get('config');
  }

  if (!teamId || !configId) {
    alert(translate('testRun.generateHtmlMissingParams', {}, '無法取得 team_id 或 config_id，請從管理頁進入執行頁面。'));
    return;
  }

  try {
    btn.disabled = true;
    icon.classList.add('fa-spinner', 'fa-spin');
    text.textContent = generatingLabel;

    const resp = await window.AuthClient.fetch(`/api/teams/${encodeURIComponent(teamId)}/test-runs/${encodeURIComponent(configId)}/generate-html`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' }
    });
    const data = await resp.json();
    if (!resp.ok || !data.success) {
      throw new Error(data?.detail || generateFailed);
    }

    const url = data.report_url;
    if (window.AppUtils && typeof AppUtils.showCopyModal === 'function') {
      AppUtils.showCopyModal(url);
    } else {
      const promptLabel = translate('copyModal.prompt', {}, '請手動複製此連結：');
      window.prompt(promptLabel, url);
    }
  } catch (err) {
    const errorMessage = err?.message || err;
    const alertMessage = translate('testRun.generateHtmlError', { error: errorMessage }, `生成 HTML 報告時發生錯誤：${errorMessage}`);
    alert(alertMessage);
  } finally {
    btn.disabled = false;
    icon.classList.remove('fa-spinner', 'fa-spin');
    icon.classList.add('fa-file-alt');
    text.textContent = defaultButtonLabel;
  }
}
function showChartsReportsModal() {
    const modal = new bootstrap.Modal(document.getElementById('chartsReportsModal'));
    modal.show();
    // Modal 顯示後載入圖表
    document.getElementById('chartsReportsModal').addEventListener('shown.bs.modal', function() {
        // 稍微延遲以確保所有元素都已渲染
        setTimeout(() => {
            initializeChartsAndReports();
        }, 200);
    }, { once: true });
}

async function initializeChartsAndReports() {
    try {
        // 顯示載入狀態
        showChartsLoading();
        
        // 收集統計資料
        const statsData = collectTestRunStats();
        
        // 更新基本資訊
        updateReportBasicInfo(statsData);
        
        // 渲染圖表
        await renderTestRunCharts(statsData);
        
        // 隱藏載入狀態
        hideChartsLoading();
        
    } catch (error) {
        console.error('初始化圖表失敗:', error);
        hideChartsLoading();
        showChartsError();
    }
}

function collectTestRunStats() {
    const stats = {
        statusData: {
            passed: 0,
            failed: 0,
            retest: 0,
            notAvailable: 0,
            pending: 0,
            notRequired: 0,
            skip: 0,
            notExecuted: 0
        },
        priorityData: {
            high: 0,
            medium: 0,
            low: 0
        },
        testRunInfo: {
            name: testRunConfig?.name || 'Test Run',
            environment: testRunConfig?.test_environment || '',
            buildNumber: testRunConfig?.build_number || '',
            version: testRunConfig?.test_version || '',
            totalItems: parseInt(document.getElementById('total-count')?.textContent || '0'),
            executedItems: parseInt(document.getElementById('executed-count')?.textContent || '0'),
            executionRate: document.getElementById('execution-rate')?.textContent || '0%',
            passRate: document.getElementById('pass-rate')?.textContent || '0%'
        }
    };
    
    // 從 testRunItems 計算詳細統計
    if (testRunItems && Array.isArray(testRunItems)) {
        testRunItems.forEach(item => {
            // 計算測試結果分布
            switch (item.test_result) {
                case 'Passed':
                    stats.statusData.passed++;
                    break;
                case 'Failed':
                    stats.statusData.failed++;
                    break;
                case 'Retest':
                    stats.statusData.retest++;
                    break;
                case 'Not Available':
                    stats.statusData.notAvailable++;
                    break;
                case 'Pending':
                    stats.statusData.pending++;
                    break;
                case 'Not Required':
                    stats.statusData.notRequired++;
                    break;
                case 'Skip':
                    stats.statusData.skip++;
                    break;
                default:
                    stats.statusData.notExecuted++;
                    break;
            }
            
            // 計算優先級分布
            switch (item.priority) {
                case 'High':
                    stats.priorityData.high++;
                    break;
                case 'Medium':
                    stats.priorityData.medium++;
                    break;
                case 'Low':
                    stats.priorityData.low++;
                    break;
            }
        });
    }
    
    return stats;
}
function updateReportBasicInfo(statsData) {
    // 更新基本資訊
    document.getElementById('reportTestRunName').textContent = statsData.testRunInfo.name;
    document.getElementById('reportEnvironment').textContent = statsData.testRunInfo.environment || '-';
    document.getElementById('reportBuildNumber').textContent = statsData.testRunInfo.buildNumber || '-';
    
    // 更新執行摘要
    document.getElementById('reportTotalItems').textContent = statsData.testRunInfo.totalItems;
    document.getElementById('reportExecutedItems').textContent = statsData.testRunInfo.executedItems;
    document.getElementById('reportExecutionRate').textContent = statsData.testRunInfo.executionRate;
    document.getElementById('reportPassRate').textContent = statsData.testRunInfo.passRate;
    
    // 更新統計卡片
    document.getElementById('chartPassedCount').textContent = statsData.statusData.passed;
    document.getElementById('chartFailedCount').textContent = statsData.statusData.failed;
    document.getElementById('chartRetestCount').textContent = statsData.statusData.retest;
    document.getElementById('chartNotAvailableCount').textContent = statsData.statusData.notAvailable;
    document.getElementById('chartPendingCount').textContent = statsData.statusData.pending;
    document.getElementById('chartNotRequiredCount').textContent = statsData.statusData.notRequired;
}

let testRunCharts = {};

async function renderTestRunCharts(statsData) {
    // 清理舊圖表
    Object.values(testRunCharts).forEach(chart => {
        if (chart) chart.destroy();
    });
    testRunCharts = {};
    
    // 確保 Chart.js 已載入
    if (typeof Chart === 'undefined') {
        throw new Error('Chart.js not loaded');
    }

    // 註冊 DataLabels 插件（如果可用）
    try {
        if (typeof ChartDataLabels !== 'undefined') {
            Chart.register(ChartDataLabels);
        } else {
            console.warn('ChartDataLabels 插件未載入，圖表將不顯示數據標籤');
        }
    } catch (error) {
        console.warn('註冊 ChartDataLabels 插件時出錯:', error);
    }
    
    // 圖表配色
    const colorScheme = {
        passed: '#28a745',
        failed: '#dc3545',
        retest: '#ffc107',
        notAvailable: '#6c757d',
        pending: '#ffca2c',
        notRequired: '#adb5bd',
        skip: '#0d6efd',
        notExecuted: '#dee2e6',
        high: '#dc3545',
        medium: '#ffc107',
        low: '#28a745'
    };
    
    // 1. 測試狀態分布圓餅圖
    const statusCtx = document.getElementById('statusPieChart');
    if (statusCtx) {
        testRunCharts.statusPie = new Chart(statusCtx, {
            type: 'pie',
            data: {
                labels: ['Passed', 'Failed', 'Retest', 'Not Available', 'Pending', 'Not Required', 'Skip', 'Not Executed'],
                datasets: [{
                    data: [
                        statsData.statusData.passed,
                        statsData.statusData.failed,
                        statsData.statusData.retest,
                        statsData.statusData.notAvailable,
                        statsData.statusData.pending,
                        statsData.statusData.notRequired,
                        statsData.statusData.skip,
                        statsData.statusData.notExecuted
                    ],
                    backgroundColor: [
                        colorScheme.passed,
                        colorScheme.failed,
                        colorScheme.retest,
                        colorScheme.notAvailable,
                        colorScheme.pending,
                        colorScheme.notRequired,
                        colorScheme.skip,
                        colorScheme.notExecuted
                    ],
                    borderWidth: 2,
                    borderColor: '#ffffff'
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                animation: {
                    duration: 1500,
                    easing: 'easeInOutQuart'
                },
                plugins: {
                    legend: {
                        position: 'bottom',
                        labels: {
                            padding: 20,
                            usePointStyle: true
                        }
                    },
                    tooltip: {
                        callbacks: {
                            label: function(context) {
                                const total = context.dataset.data.reduce((a, b) => a + b, 0);
                                const percentage = ((context.raw / total) * 100).toFixed(1);
                                return `${context.label}: ${context.raw} (${percentage}%)`;
                            }
                        }
                    },
                    ...(typeof ChartDataLabels !== 'undefined' ? {
                        datalabels: {
                            color: 'white',
                            font: {
                                weight: 'bold',
                                size: 14
                            },
                            formatter: (value, context) => {
                                const total = context.dataset.data.reduce((a, b) => a + b, 0);
                                const percentage = ((value / total) * 100).toFixed(1);
                                return percentage > 5 ? percentage + '%' : '';
                            }
                        }
                    } : {})
                }
            }
        });
    }
    
    // 2. 優先級分布長條圖
    const priorityCtx = document.getElementById('priorityBarChart');
    if (priorityCtx) {
        testRunCharts.priorityBar = new Chart(priorityCtx, {
            type: 'bar',
            data: {
                labels: ['高', '中', '低'],
                datasets: [{
                    label: '測試案例數量',
                    data: [
                        statsData.priorityData.high,
                        statsData.priorityData.medium,
                        statsData.priorityData.low
                    ],
                    backgroundColor: [
                        colorScheme.high,
                        colorScheme.medium,
                        colorScheme.low
                    ],
                    borderColor: [
                        colorScheme.high,
                        colorScheme.medium,
                        colorScheme.low
                    ],
                    borderWidth: 1
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                animation: {
                    duration: 1200,
                    easing: 'easeInOutQuart'
                },
                plugins: {
                    legend: {
                        display: false
                    }
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        ticks: {
                            stepSize: 1
                        }
                    }
                }
            }
        });
    }
}

function showChartsLoading() {
    const loadingElement = document.getElementById('chartsLoadingOverlay');
    if (loadingElement) {
        // 確保載入畫面可以顯示
        loadingElement.style.display = 'flex';
        loadingElement.style.visibility = 'visible';
        loadingElement.classList.remove('d-none');
    } else {
        console.error('找不到載入畫面元素 chartsLoadingOverlay');
    }
}

function hideChartsLoading() {
    const loadingElement = document.getElementById('chartsLoadingOverlay');
    if (loadingElement) {
        // 使用多種方式確保載入畫面被隱藏
        loadingElement.style.display = 'none';
        loadingElement.style.visibility = 'hidden';
        loadingElement.classList.add('d-none');
        // 強制刷新樣式
        loadingElement.offsetHeight;
    } else {
        console.error('找不到載入畫面元素 chartsLoadingOverlay');
    }
}

function showChartsError() {
    const errorElement = document.getElementById('chartsErrorMessage');
    if (errorElement) {
        errorElement.style.display = 'block';
    }
}

// PDF 下載功能
// 將 Chart.js 圖表轉換為靜態圖片以支援 PDF 列印
async function convertChartsToImages() {
    const conversions = [];
    const canvasElements = document.querySelectorAll('#chartsReportsModal canvas');

    // 首先等待所有圖表完全渲染（包括動畫和插件）
    await waitForAllChartsToRender(canvasElements);

    // 使用 Promise.all 確保所有轉換都完成
    const conversionPromises = Array.from(canvasElements).map((canvas, index) => {
        return new Promise(async (resolve) => {
            try {
                // 確認圖表存在且已渲染
                const chart = Chart.getChart(canvas);
                if (chart) {
                    // 確保圖表處於靜止狀態（禁用動畫效果）
                    const originalAnimation = chart.options.animation;
                    chart.options.animation = false;
                    chart.update('none'); // 立即更新，不使用動畫
                    
                    // 等待更新完成
                    await new Promise(resolve => setTimeout(resolve, 200));
                    
                    // 獲取高品質的圖片資料，考慮高DPI顯示
                    const deviceRatio = window.devicePixelRatio || 1;
                    const imageData = canvas.toDataURL('image/png', 1.0);
                    
                    // 驗證圖片數據是否有效
                    if (!imageData || imageData === 'data:,' || imageData.length < 100) {
                        throw new Error(`圖表 ${index + 1} 轉換產生無效圖片數據`);
                    }
                    
                    // 創建 img 元素替換 canvas
                    const img = document.createElement('img');
                    img.src = imageData;
                    img.style.width = '100%';
                    img.style.height = 'auto';
                    img.style.maxWidth = '100%';
                    img.style.display = 'block';
                    img.classList.add('chart-image-replacement');
                    
                    // 等待圖片載入完成
                    await new Promise((imgResolve) => {
                        if (img.complete) {
                            imgResolve();
                        } else {
                            img.onload = imgResolve;
                            img.onerror = imgResolve;
                        }
                    });
                    
                    // 保存原始 canvas 以便後續恢復
                    canvas.style.display = 'none';
                    canvas.dataset.originalDisplay = 'block';
                    canvas.dataset.originalAnimation = JSON.stringify(originalAnimation);
                    canvas.parentNode.insertBefore(img, canvas.nextSibling);
                    
                    const conversionResult = { canvas, img, chart, originalAnimation };
                    conversions.push(conversionResult);
                    resolve(conversionResult);
                } else {
                    console.warn(`Canvas ${index + 1} 沒有對應的 Chart 實例`);
                    resolve(null);
                }
            } catch (error) {
                console.error(`圖表 ${index + 1} 轉換失敗:`, error);
                resolve(null);
            }
        });
    });
    
    // 等待所有轉換完成
    await Promise.all(conversionPromises);
    return conversions;
}

// 等待所有圖表完全渲染的輔助函數
async function waitForAllChartsToRender(canvasElements) {
    const chartPromises = Array.from(canvasElements).map(async (canvas, index) => {
        const chart = Chart.getChart(canvas);
        if (chart) {
            return waitForSingleChartRender(chart, index);
        }
        return Promise.resolve();
    });
    
    await Promise.all(chartPromises);
    
    // 額外等待時間確保插件（如 DataLabels）完全渲染
    await new Promise(resolve => setTimeout(resolve, 800));
}

// 等待單個圖表渲染完成
async function waitForSingleChartRender(chart, index) {
    return new Promise(resolve => {
        // 檢查圖表是否正在動畫中
        if (chart.isAnimating && chart.isAnimating()) {
            // Chart.js 3.x 使用 onAnimationComplete
            const originalOnComplete = chart.options.animation?.onComplete;
            chart.options.animation = chart.options.animation || {};
            chart.options.animation.onComplete = function(context) {
                // 恢復原始回調
                if (originalOnComplete) {
                    originalOnComplete.call(this, context);
                }
                resolve();
            };
            
            // 超時保護機制（3秒）
            setTimeout(() => {
                console.warn(`圖表 ${index + 1} 動畫等待超時，強制繼續`);
                resolve();
            }, 3000);
        } else {
            // 如果沒有動畫，短暫等待確保渲染穩定
            setTimeout(resolve, 300);
        }
    });
}

// PDF 下載狀態管理
function showPDFLoadingState() {
    const button = document.getElementById('downloadPDFBtn');
    const icon = document.getElementById('downloadIcon');
    const text = document.getElementById('downloadText');
    
    if (button && icon && text) {
        button.disabled = true;
        button.classList.add('disabled');
        icon.className = 'fas fa-spinner fa-spin me-2';
        text.textContent = window.i18n ? window.i18n.t('testRun.generatingPDF', {}, '正在生成 PDF...') : '正在生成 PDF...';
    }
}

function hidePDFLoadingState() {
    const button = document.getElementById('downloadPDFBtn');
    const icon = document.getElementById('downloadIcon');
    const text = document.getElementById('downloadText');
    
    if (button && icon && text) {
        button.disabled = false;
        button.classList.remove('disabled');
        icon.className = 'fas fa-download me-2';
        text.textContent = window.i18n ? window.i18n.t('testRun.downloadPDF', {}, '下載 PDF 報告') : '下載 PDF 報告';
    }
}

// 恢復 Canvas 圖表元素
function restoreChartsFromImages(conversions) {
    conversions.forEach(({ canvas, img, chart, originalAnimation }, index) => {
        try {
            // 移除替換的圖片
            if (img && img.parentNode) {
                img.parentNode.removeChild(img);
            }
            
            // 恢復原始 canvas
            canvas.style.display = canvas.dataset.originalDisplay || 'block';
            delete canvas.dataset.originalDisplay;
            
            // 恢復原始動畫設置
            if (chart && originalAnimation !== undefined) {
                chart.options.animation = originalAnimation;
                // 如果需要，重新啟用動畫
                if (originalAnimation) {
                    chart.update(); // 使用預設動畫重新渲染
                }
            }
            
            // 清理 dataset
            if (canvas.dataset.originalAnimation) {
                delete canvas.dataset.originalAnimation;
            }
        } catch (error) {
            console.error('恢復圖表時發生錯誤:', error);
        }
    });
}

async function downloadReportAsPDF() {
    // 顯示載入狀態
    showPDFLoadingState();
    
    try {
        // 檢查必要參數
        if (!currentTeamId || !currentConfigId) {
            throw new Error('缺少必要參數：team_id 或 config_id');
        }
        
        // 呼叫後端 API 生成 PDF
        const response = await window.AuthClient.fetch(`/api/teams/${currentTeamId}/test-runs/${currentConfigId}/generate-pdf`, {
            method: 'GET',
            headers: {
                'Accept': 'application/pdf'
            }
        });
        
        if (!response.ok) {
            if (response.status === 404) {
                throw new Error('找不到指定的 Test Run 配置');
            } else if (response.status === 500) {
                throw new Error('伺服器內部錯誤，請重試或聯繫管理員');
            } else {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }
        }
        
        // 獲取 PDF 內容
        const pdfBlob = await response.blob();
        
        // 創建下載連結並自動下載
        const url = window.URL.createObjectURL(pdfBlob);
        const link = document.createElement('a');
        link.href = url;
        
        // 設定檔案名稱（包含時間戳記）
        const timestamp = new Date().toISOString().slice(0, 19).replace(/[:-]/g, '');
        link.download = `test-run-report-${currentConfigId}-${timestamp}.pdf`;
        
        // 觸發下載
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        
        // 釋放記憶體
        window.URL.revokeObjectURL(url);
        
    } catch (error) {
        console.error('PDF 生成錯誤:', error);
        
        // 使用 i18n 友好的錯誤提示
        const errorMessage = window.i18n ? 
            window.i18n.t('testRun.pdfGenerationFailed', {}, 'PDF 生成失敗，請重試或聯繫管理員') : 
            'PDF 生成失敗，請重試或聯繫管理員';
        
        alert(errorMessage + '\n\n錯誤詳情：' + error.message);
    } finally {
        // 恢復載入狀態
        hidePDFLoadingState();
    }
}
