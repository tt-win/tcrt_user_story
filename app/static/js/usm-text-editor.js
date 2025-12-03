/**
 * USM 文字編輯器
 * 使用 Monaco Editor 提供語法高亮的文字編輯功能
 */

(function () {
    let editor = null;
    let currentMapId = null;
    let editorReady = false;

    /**
     * 獲取當前地圖 ID
     */
    function getCurrentMapId() {
        // 優先使用全局變數（由主要的 user_story_map.js 設定）
        if (window.userStoryMapFlow && window.userStoryMapFlow.getCurrentMapId) {
            return window.userStoryMapFlow.getCurrentMapId();
        }
        
        // 備用：從 URL 解析
        const pathParts = window.location.pathname.split('/').filter(p => p);
        const teamIdIndex = pathParts.indexOf('user-story-map') + 1;
        return pathParts[teamIdIndex + 1] ? parseInt(pathParts[teamIdIndex + 1]) : null;
    }

    /**
     * 初始化 Monaco Editor
     */
    function initMonacoEditor() {
        require.config({ 
            paths: { 
                'vs': 'https://cdn.jsdelivr.net/npm/monaco-editor@0.45.0/min/vs' 
            } 
        });

        require(['vs/editor/editor.main'], function () {
            // 註冊 USM 語言
            monaco.languages.register({ id: 'usm' });

            // 設定語法高亮
            monaco.languages.setMonarchTokensProvider('usm', {
                tokenizer: {
                    root: [
                        // 註解
                        [/#.*$/, 'comment'],
                        
                        // Node ID ([@id])
                        [/\[@[\w\-_]+\]/, 'keyword'],
                        
                        // 節點類型 (root:, feature:, story:)
                        [/\b(root|feature|story):\s/, 'type'],
                        
                        // 屬性名稱
                        [/\b(desc|comment|jira|product|team|team_tags|related|as_a|i_want|so_that):\s/, 'attribute.name'],
                        
                        // 多行標記
                        [/\|/, 'string'],
                        
                        // 字串
                        [/"([^"\\]|\\.)*$/, 'string.invalid'],
                        [/"/, 'string', '@string'],
                    ],
                    
                    string: [
                        [/[^\\"]+/, 'string'],
                        [/\\./, 'string.escape'],
                        [/"/, 'string', '@pop']
                    ],
                }
            });

            // 設定主題顏色
            monaco.editor.defineTheme('usm-theme', {
                base: 'vs',
                inherit: true,
                rules: [
                    { token: 'comment', foreground: '6a737d', fontStyle: 'italic' },
                    { token: 'keyword', foreground: 'd73a49', fontStyle: 'bold' },
                    { token: 'type', foreground: '6f42c1', fontStyle: 'bold' },
                    { token: 'attribute.name', foreground: '005cc5' },
                    { token: 'string', foreground: '22863a' },
                ],
                colors: {
                    'editor.background': '#ffffff',
                    'editor.foreground': '#24292e',
                    'editor.lineHighlightBackground': '#f6f8fa',
                    'editorLineNumber.foreground': '#959da5',
                }
            });

            // 建立編輯器
            const container = document.getElementById('usmTextEditor');
            if (!container) {
                console.error('找不到 usmTextEditor 容器');
                return;
            }

            editor = monaco.editor.create(container, {
                value: '# USM 文字格式\n# 請先選擇或建立一個地圖，然後匯出為文字進行編輯\n\n',
                language: 'usm',
                theme: 'usm-theme',
                automaticLayout: true,
                minimap: { enabled: true },
                lineNumbers: 'on',
                scrollBeyondLastLine: false,
                wordWrap: 'on',
                fontSize: 14,
                tabSize: 2,
                insertSpaces: true,
                formatOnPaste: true,
                formatOnType: true,
            });

            editorReady = true;
            console.log('Monaco Editor 初始化完成');
            
            // 如果已經在文字模式，立即匯出
            const textPane = document.getElementById('text-pane');
            const mapId = getCurrentMapId();
            if (textPane && textPane.classList.contains('active') && mapId) {
                console.log('編輯器初始化完成且已在文字模式，立即匯出');
                exportToText();
            }
        });
    }

    /**
     * 匯出當前地圖為文字格式
     */
    async function exportToText() {
        const mapId = getCurrentMapId();
        console.log('exportToText - 當前 mapId:', mapId);
        
        if (!mapId) {
            showMessage('請先選擇一個地圖', 'warning');
            return;
        }

        try {
            const response = await fetch(`/api/user-story-maps/${mapId}/export-text`, {
                method: 'GET',
                headers: {
                    'Content-Type': 'application/json',
                },
            });

            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.detail || '匯出失敗');
            }

            const data = await response.json();
            
            if (editor) {
                editor.setValue(data.text);
                showMessage(`成功匯出 ${data.nodes_count} 個節點`, 'success');
            }
        } catch (error) {
            console.error('匯出文字失敗:', error);
            showMessage(`匯出失敗: ${error.message}`, 'error');
        }
    }

    /**
     * 從文字匯入（不取代現有節點）
     */
    async function importFromText() {
        const mapId = getCurrentMapId();
        
        if (!mapId) {
            showMessage('請先選擇一個地圖', 'warning');
            return;
        }

        if (!editor) {
            showMessage('編輯器尚未初始化', 'error');
            return;
        }

        const text = editor.getValue();
        if (!text.trim()) {
            showMessage('請輸入 USM 文字內容', 'warning');
            return;
        }

        if (!confirm('確定要從文字匯入節點嗎？這會新增節點到現有地圖中。')) {
            return;
        }

        try {
            const response = await fetch(`/api/user-story-maps/${mapId}/import-text`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    text: text,
                    replace_existing: false,
                }),
            });

            const data = await response.json();

            if (!response.ok) {
                if (data.errors && data.errors.length > 0) {
                    const errorMsg = data.errors.join('\n');
                    showMessage(`解析錯誤:\n${errorMsg}`, 'error');
                } else {
                    throw new Error(data.detail || data.message || '匯入失敗');
                }
                return;
            }

            showMessage(data.message || `成功匯入 ${data.nodes_count} 個節點`, 'success');
            
            // 切換回視覺化模式並重新載入地圖
            setTimeout(() => {
                const visualTab = document.getElementById('visual-tab');
                if (visualTab) {
                    visualTab.click();
                }
                if (window.userStoryMapFlow && window.userStoryMapFlow.loadMap) {
                    window.userStoryMapFlow.loadMap(mapId);
                }
            }, 1000);

        } catch (error) {
            console.error('匯入文字失敗:', error);
            showMessage(`匯入失敗: ${error.message}`, 'error');
        }
    }

    /**
     * 從文字匯入（取代所有現有節點）
     */
    async function importReplaceAll() {
        const mapId = getCurrentMapId();
        
        if (!mapId) {
            showMessage('請先選擇一個地圖', 'warning');
            return;
        }

        if (!editor) {
            showMessage('編輯器尚未初始化', 'error');
            return;
        }

        const text = editor.getValue();
        if (!text.trim()) {
            showMessage('請輸入 USM 文字內容', 'warning');
            return;
        }

        if (!confirm('⚠️ 警告：這將會刪除現有的所有節點並以文字內容取代。\n\n確定要繼續嗎？')) {
            return;
        }

        try {
            const response = await fetch(`/api/user-story-maps/${mapId}/import-text`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    text: text,
                    replace_existing: true,
                }),
            });

            const data = await response.json();

            if (!response.ok) {
                if (data.errors && data.errors.length > 0) {
                    const errorMsg = data.errors.join('\n');
                    showMessage(`解析錯誤:\n${errorMsg}`, 'error');
                } else {
                    throw new Error(data.detail || data.message || '匯入失敗');
                }
                return;
            }

            showMessage(data.message || `成功取代並匯入 ${data.nodes_count} 個節點`, 'success');
            
            // 切換回視覺化模式並重新載入地圖
            setTimeout(() => {
                const visualTab = document.getElementById('visual-tab');
                if (visualTab) {
                    visualTab.click();
                }
                if (window.userStoryMapFlow && window.userStoryMapFlow.loadMap) {
                    window.userStoryMapFlow.loadMap(mapId);
                }
            }, 1000);

        } catch (error) {
            console.error('匯入取代失敗:', error);
            showMessage(`匯入失敗: ${error.message}`, 'error');
        }
    }

    /**
     * 下載文字檔案
     */
    function downloadText() {
        if (!editor) {
            showMessage('編輯器尚未初始化', 'error');
            return;
        }

        const mapId = getCurrentMapId();
        const text = editor.getValue();
        const blob = new Blob([text], { type: 'text/plain;charset=utf-8' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `usm_map_${mapId || 'export'}_${new Date().getTime()}.usm`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
        
        showMessage('文字檔案已下載', 'success');
    }

    /**
     * 顯示訊息
     */
    function showMessage(message, type = 'info') {
        if (window.showMessage) {
            window.showMessage(message, type);
        } else {
            console.log(`[${type}] ${message}`);
            alert(message);
        }
    }

    /**
     * 初始化事件監聽器
     */
    function initEventListeners() {
        // 匯出按鈕
        const exportBtn = document.getElementById('exportToTextBtn');
        if (exportBtn) {
            exportBtn.addEventListener('click', exportToText);
        }

        // 匯入按鈕
        const importBtn = document.getElementById('importFromTextBtn');
        if (importBtn) {
            importBtn.addEventListener('click', importFromText);
        }

        // 取代全部按鈕
        const replaceBtn = document.getElementById('importReplaceBtn');
        if (replaceBtn) {
            replaceBtn.addEventListener('click', importReplaceAll);
        }

        // 下載按鈕
        const downloadBtn = document.getElementById('downloadTextBtn');
        if (downloadBtn) {
            downloadBtn.addEventListener('click', downloadText);
        }

        // 當切換到文字模式時，自動匯出
        const textTab = document.getElementById('text-tab');
        if (textTab) {
            textTab.addEventListener('shown.bs.tab', function () {
                const mapId = getCurrentMapId();
                console.log('切換到文字模式，mapId:', mapId, 'editorReady:', editorReady, 'editor:', !!editor);
                if (mapId) {
                    // 如果編輯器還沒準備好，等待一下
                    if (!editorReady || !editor) {
                        console.log('編輯器尚未準備好，等待...');
                        let attempts = 0;
                        const maxAttempts = 10;
                        const checkEditor = setInterval(() => {
                            attempts++;
                            console.log(`檢查編輯器... 第 ${attempts} 次`);
                            if (editorReady && editor) {
                                console.log('編輯器已準備好，開始匯出');
                                clearInterval(checkEditor);
                                exportToText();
                            } else if (attempts >= maxAttempts) {
                                console.error('編輯器初始化逾時');
                                clearInterval(checkEditor);
                                showMessage('編輯器初始化逾時，請重新整理頁面', 'error');
                            }
                        }, 500);
                    } else {
                        console.log('編輯器已準備好，立即匯出');
                        exportToText();
                    }
                }
            });
        }
    }

    /**
     * 初始化
     */
    function init() {
        // 等待 DOM 載入完成
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', () => {
                initMonacoEditor();
                initEventListeners();
            });
        } else {
            initMonacoEditor();
            initEventListeners();
        }
    }

    // 執行初始化
    init();

    // 匯出到 window 供除錯使用
    window.usmTextEditor = {
        getEditor: () => editor,
        exportToText,
        importFromText,
        importReplaceAll,
        downloadText,
    };
})();
