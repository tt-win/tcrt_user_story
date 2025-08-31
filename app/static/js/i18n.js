/**
 * Internationalization (i18n) System for Test Case Repository Web Tool
 * 
 * Features:
 * - Language switching between zh-TW and en-US
 * - Automatic detection of browser language preference
 * - Persistent language selection via localStorage
 * - Dynamic content translation using data-i18n attributes
 * - Support for parameterized messages
 * - Multiple attribute types (text, placeholder, title, etc.)
 */

class I18nSystem {
    constructor() {
        this.currentLanguage = 'zh-TW';
        this.translations = {};
        this.supportedLanguages = ['zh-TW', 'en-US'];
        this.fallbackLanguage = 'zh-TW';
        this.isLoaded = false;
        this.cacheBuster = String(Date.now());
        
        // Initialize the system
        this.init();
    }

    /**
     * Initialize the i18n system
     */
    async init() {
        try {
            // Detect and set initial language
            this.detectLanguage();
            
            // Load translation files
            await this.loadTranslations();
            
            // Mark as loaded
            this.isLoaded = true;
            
            // Apply translations to current page
            this.translatePage();
            
            // Dispatch ready event
            document.dispatchEvent(new CustomEvent('i18nReady', {
                detail: { language: this.currentLanguage }
            }));

        } catch (error) {
            console.error('Failed to initialize i18n:', error);
            this.isLoaded = false;
        }
    }

    /**
     * Detect the appropriate language to use
     */
    detectLanguage() {
        // Check localStorage first
        const storedLanguage = localStorage.getItem('language');
        if (storedLanguage && this.supportedLanguages.includes(storedLanguage)) {
            this.currentLanguage = storedLanguage;
            return;
        }

        // Check browser language
        const browserLanguage = navigator.language || navigator.userLanguage;
        if (browserLanguage) {
            // Try exact match first
            if (this.supportedLanguages.includes(browserLanguage)) {
                this.currentLanguage = browserLanguage;
                return;
            }
            
            // Try language code without region
            const languageCode = browserLanguage.split('-')[0];
            const matchedLanguage = this.supportedLanguages.find(lang => 
                lang.startsWith(languageCode)
            );
            
            if (matchedLanguage) {
                this.currentLanguage = matchedLanguage;
                return;
            }
        }

        // Fall back to default
        this.currentLanguage = this.fallbackLanguage;
    }

    /**
     * Load translation files for all supported languages
     */
    async loadTranslations() {
        const version = localStorage.getItem('i18n_version') || '1.0.0';
        // Load translations for each supported language with cache busting
// Load translations for each supported language with cache busting
this.loadingLanguages = new Set();
// Load translations for each supported language with cache busting
this.loadingLanguages = new Set();
const cachePromises = this.supportedLanguages.map(async (language) => {
            if (this.loadingLanguages.has(language)) return;
            this.loadingLanguages.add(language);
            // Update cache buster for each load to avoid race
            this.cacheBuster = Date.now();
            try {
                const response = await fetch(`/static/locales/${language}.json?v=${this.cacheBuster}`);
                if (!response.ok) {
                    console.warn(`Translation file for ${language} returned status ${response.status}. Attempting fallback.`);
                    throw new Error(`Failed to load ${language}: ${response.status}`);
                }

                // 檢查是否有更新
                const lastModified = response.headers.get('last-modified');
                const cachedModified = localStorage.getItem(`i18n_${language}_modified`);

                if (lastModified && cachedModified !== lastModified) {
                    // 載入新版本
                    const translations = await response.json();
                    this.translations[language] = translations;
                    localStorage.setItem(`i18n_${language}_modified`, lastModified);
                    localStorage.setItem(`i18n_${language}_cache`, JSON.stringify(translations));
                    console.log(`Updated translations for ${language}`);
                } else {
                    // 使用快取版本
                    const cached = localStorage.getItem(`i18n_${language}_cache`);
                    if (cached) {
                        this.translations[language] = JSON.parse(cached);
                        console.log(`Loaded cached translations for ${language}`);
                    } else {
                        // 首次載入
                        const translations = await response.json();
                        this.translations[language] = translations;
                        localStorage.setItem(`i18n_${language}_modified`, lastModified || new Date().toISOString());
                        localStorage.setItem(`i18n_${language}_cache`, JSON.stringify(translations));
                    }
                }
            } catch (error) {
                console.error(`Failed to load translations for ${language}:`, error);
                // 嘗試使用快取版本作為備用
                const cached = localStorage.getItem(`i18n_${language}_cache`);
                if (cached) {
                    this.translations[language] = JSON.parse(cached);
                    console.warn(`Using cached translations for ${language} due to load error`);
                } else {
                    // If current language fails to load, try fallback
                    if (language === this.currentLanguage && language !== this.fallbackLanguage) {
                        console.warn(`Falling back to ${this.fallbackLanguage}`);
                        this.currentLanguage = this.fallbackLanguage;
                        // Load fallback translations if not already loaded
                        if (!this.translations[this.fallbackLanguage]) {
                            try {
                                const resp = await fetch(`/static/locales/${this.fallbackLanguage}.json?v=${this.cacheBuster}`);
                                if (resp.ok) {
                                    this.translations[this.fallbackLanguage] = await resp.json();
                                }
                            } catch (e) {
                                console.error('Failed to load fallback translations:', e);
                            }
                        }
                    }
                }
            }
        });

        await Promise.all(cachePromises);

        // 確保至少有一種語言被載入
        if (Object.keys(this.translations).length === 0) {
            throw new Error('No translation files could be loaded');
        }
    }

    /**
     * Switch to a different language
     * @param {string} language - The language code to switch to
     */
async switchLanguage(language) {
        if (!this.supportedLanguages.includes(language)) {
            console.error(`Unsupported language: ${language}`);
            return false;
        }
 
        if (language === this.currentLanguage) {
            return true; // Already using this language
        }
 
        // Check if translations are loaded
        if (!this.translations[language]) {
            console.warn(`Translations for ${language} not loaded, attempting to load...`);
            try {
                const response = await fetch(`/static/locales/${language}.json?v=${this.cacheBuster}`);
                if (!response.ok) {
                    throw new Error(`Failed to load ${language}`);
                }
                this.translations[language] = await response.json();
            } catch (error) {
                console.error(`Failed to load ${language}:`, error);
                // Restore UI to previous language
                if (this.currentLanguage && this.translations[this.currentLanguage]) {
                    this.translatePage();
                }
                alert(`無法載入語言檔：${language}`);
                return false;
            }
        }
 
        // Switch language
        this.currentLanguage = language;
         
        // Save to localStorage
        localStorage.setItem('language', language);
 
        // Update HTML lang attribute
        document.documentElement.lang = language;
 
        // Retranslate the page
        this.translatePage();
 
        // Dispatch language change event
        document.dispatchEvent(new CustomEvent('languageChanged', {
            detail: { language: language }
        }));
 
        return true;
    }

    /**
     * Get a translation by key path
     * @param {string} keyPath - Dot-separated key path (e.g., "common.save")
     * @param {Object} params - Parameters for string interpolation
     * @param {string} fallbackText - Text to use if translation not found
     * @returns {string} The translated text
     */
    t(keyPath, params = {}, fallbackText = null) {
        if (!this.isLoaded) {
            return fallbackText || keyPath;
        }

        const currentTranslations = this.translations[this.currentLanguage];
        if (!currentTranslations) {
            return fallbackText || keyPath;
        }

        // Navigate through the nested object using the key path
        const keys = keyPath.split('.');
        let value = currentTranslations;
        
        for (const key of keys) {
if (value && typeof value === 'object' && key in value) {
                value = value[key];
            } else {
                // Try fallback language if current language doesn't have the key
                if (this.currentLanguage !== this.fallbackLanguage) {
                    const fallbackTranslations = this.translations[this.fallbackLanguage];
                    if (fallbackTranslations) {
                        let fallbackValue = fallbackTranslations;
                        for (const fallbackKey of keys) {
                            if (fallbackValue && typeof fallbackValue === 'object' && fallbackKey in fallbackValue) {
                                fallbackValue = fallbackValue[fallbackKey];
                            } else {
                                fallbackValue = null;
                                break;
                            }
                        }
                        if (typeof fallbackValue === 'string') {
                            value = fallbackValue;
                            break;
                        }
                    }
                }
                 
                // Return fallback text or key path if no translation found
                return fallbackText || keyPath;
            }
        }

        if (typeof value !== 'string') {
            return fallbackText || keyPath;
        }

        // Perform parameter substitution
        return this.interpolate(value, params);
    }

    /**
     * Interpolate parameters into a string
     * @param {string} text - The text with placeholders like {name}
     * @param {Object} params - Parameters to substitute
     * @returns {string} The interpolated text
     */
    interpolate(text, params) {
        // If the translation contains placeholders but no params provided, warn
        if (text.includes('{') && (!params || Object.keys(params).length === 0)) {
            console.warn(`Missing parameters for translation key: ${keyPath}`);
        }
        return text;

        return text.replace(/\{(\w+)\}/g, (match, key) => {
            return params.hasOwnProperty(key) ? params[key] : match;
        });
    }

    /**
     * Translate all elements on the current page
     */
    translatePage(container = document) {
        if (!this.isLoaded) {
            return;
        }

        // Find all elements with data-i18n attributes
        const root = container instanceof HTMLElement ? container : document;
        const elements = root.querySelectorAll('[data-i18n]');
        
        elements.forEach(element => {
            this.translateElement(element);
        });

        // Also handle other i18n attributes
        this.translateAttributes(root);
    }

    /**
     * Translate a single element
     * @param {HTMLElement} element - The element to translate
     */
    translateElement(element) {
        const key = element.getAttribute('data-i18n');
        if (!key) return;

        // Get parameters from data-i18n-params attribute
        let params = {};
        const paramsAttr = element.getAttribute('data-i18n-params');
        if (paramsAttr) {
            try {
                params = JSON.parse(paramsAttr);
            } catch (error) {
                console.warn('Invalid i18n params JSON:', paramsAttr);
            }
        }

        // Get fallback text from data-i18n-fallback attribute
        const fallbackText = element.getAttribute('data-i18n-fallback');

        // Translate and set the text content
        const translatedText = this.t(key, params, fallbackText);
        element.textContent = translatedText;
    }

    /**
     * Translate elements with attribute-specific data-i18n attributes
     */
translateAttributes(root = document) {
        const attributeTypes = ['placeholder', 'title', 'alt', 'aria-label', 'value'];

attributeTypes.forEach(attrType => {
            const elements = (root instanceof HTMLElement ? root : document).querySelectorAll(`[data-i18n-${attrType}]`);
            
            elements.forEach(element => {
                const key = element.getAttribute(`data-i18n-${attrType}`);
                if (!key) return;

                // Get parameters
                let params = {};
                const paramsAttr = element.getAttribute(`data-i18n-${attrType}-params`);
                if (paramsAttr) {
                    try {
                        params = JSON.parse(paramsAttr);
                    } catch (error) {
                        console.warn(`Invalid i18n ${attrType} params JSON:`, paramsAttr);
                    }
                }

                // Get fallback text
                const fallbackText = element.getAttribute(`data-i18n-${attrType}-fallback`);

                // Translate and set the attribute
                const translatedText = this.t(key, params, fallbackText);
                element.setAttribute(attrType, translatedText);
            });
        });
    }

    /**
     * Get the current language
     * @returns {string} Current language code
     */
    getCurrentLanguage() {
        return this.currentLanguage;
    }

    /**
     * Get list of supported languages
     * @returns {Array<string>} Array of supported language codes
     */
    getSupportedLanguages() {
        return [...this.supportedLanguages];
    }

    /**
     * Check if the i18n system is ready
     * @returns {boolean} True if loaded and ready
     */
    isReady() {
        return this.isLoaded;
    }

    /**
     * Manually trigger a page retranslation (useful for dynamic content)
     */
    retranslate(container) {
        this.translatePage(container);
    }

    /**
     * Add a language switch observer to dynamically added content
     * @param {HTMLElement} container - Container to observe for new content
     */
    observeContainer(container) {
        if (!container || typeof MutationObserver === 'undefined') {
            return;
        }

        const observer = new MutationObserver((mutations, obs) => {
// Handle attribute changes for existing nodes
            mutations.forEach((mutation) => {
                if (mutation.type === 'attributes' && mutation.attributeName.startsWith('data-i18n')) {
                    const element = mutation.target;
                    this.translateElement(element);
                }
            });
            // Existing childList handling remains
            let shouldRetranslate = false;
            mutations.forEach((mutation) => {
                if (mutation.type === 'childList' && mutation.addedNodes.length > 0) {
                    // Check if any added nodes have i18n attributes
                    mutation.addedNodes.forEach((node) => {
                        if (node.nodeType === Node.ELEMENT_NODE) {
                            const element = node;
                            if (element.hasAttribute('data-i18n') || 
                                element.querySelector('[data-i18n]')) {
                                shouldRetranslate = true;
                            }
                        }
                    });
                }
            });
            
            if (shouldRetranslate) {
                this.translatePage();
            }
        });

        observer.observe(container, {
            childList: true,
            subtree: true
        });

        return observer;
    }

    /**
     * 驗證翻譯完整性
     * @returns {Array<string>} 缺少的翻譯鍵列表
     */
    validateTranslations() {
        const missingKeys = [];
        const currentLang = this.translations[this.currentLanguage];
        const fallbackLang = this.translations[this.fallbackLanguage];

        if (!currentLang || !fallbackLang) {
            console.warn('Cannot validate translations: missing language data');
            return missingKeys;
        }

        // 遞歸檢查缺少的鍵
        const checkKeys = (obj, fallbackObj, path = '') => {
            for (const key in fallbackObj) {
                const currentPath = path ? `${path}.${key}` : key;

                if (!(key in obj)) {
                    missingKeys.push({
                        key: currentPath,
                        language: this.currentLanguage,
                        fallback: fallbackObj[key]
                    });
                } else if (typeof obj[key] === 'object' && typeof fallbackObj[key] === 'object') {
                    checkKeys(obj[key], fallbackObj[key], currentPath);
                } else if (typeof obj[key] !== typeof fallbackObj[key]) {
                    console.warn(`Type mismatch for key ${currentPath}: expected ${typeof fallbackObj[key]}, got ${typeof obj[key]}`);
                }
            }
        };

        checkKeys(currentLang, fallbackLang);

        if (missingKeys.length > 0) {
            console.warn(`Found ${missingKeys.length} missing translation keys:`, missingKeys);

            // 在開發環境中顯示更詳細的資訊
            if (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1') {
                console.table(missingKeys);
            }
        }

        return missingKeys;
    }

    /**
     * 修復缺少的翻譯鍵
     * @param {Array} missingKeys - 從 validateTranslations 獲得的結果
     */
fixMissingTranslations(missingKeys) {
        if (!missingKeys || missingKeys.length === 0) return;
 
         const currentLang = this.translations[this.currentLanguage];
         const fallbackLang = this.translations[this.fallbackLanguage];
 
         missingKeys.forEach(({ key }) => {
             const keys = key.split('.');
             let currentObj = currentLang;
             let fallbackObj = fallbackLang;
 
             // 導航到正確的位置，遞迴建立缺失結構
             for (let i = 0; i < keys.length - 1; i++) {
                 const part = keys[i];
                 if (!currentObj[part]) {
                     currentObj[part] = {};
                 }
                 currentObj = currentObj[part];
 
                 if (fallbackObj && fallbackObj[part]) {
                     fallbackObj = fallbackObj[part];
                 } else {
                     fallbackObj = null;
                 }
             }
 
             // 設定備用值
             const lastKey = keys[keys.length - 1];
             if (fallbackObj && fallbackObj[lastKey]) {
                 currentObj[lastKey] = fallbackObj[lastKey];
                 console.log(`Fixed missing translation: ${key}`);
             }
         });
 
         // 更新快取
         localStorage.setItem(`i18n_${this.currentLanguage}_cache`, JSON.stringify(currentLang));
     }
}

// Global debug flag for test environments
window.i18nDebugEnabled = false;

// Create global i18n instance
window.i18n = new I18nSystem();

// 開發者工具 - 僅在開發環境中可用
if ((window.location.hostname === 'localhost' ||
            window.location.hostname === '127.0.0.1') && window.i18nDebugEnabled) {


    window.i18nDebug = {
        /**
         * 顯示當前翻譯狀態
         */
        showStatus() {
            console.group('🌐 i18n System Status');
            console.log('Current Language:', window.i18n.currentLanguage);
            console.log('Supported Languages:', window.i18n.supportedLanguages);
            console.log('Fallback Language:', window.i18n.fallbackLanguage);
            console.log('Is Ready:', window.i18n.isReady());
            console.log('Translations Loaded:', Object.keys(window.i18n.translations));
            console.log('Cache Buster:', window.i18n.cacheBuster);
            console.groupEnd();
        },

        /**
         * 檢查缺少的翻譯鍵
         */
        checkMissingKeys() {
            console.group('🔍 Translation Validation');
            const missingKeys = window.i18n.validateTranslations();
            console.log(`Found ${missingKeys.length} missing keys`);
            if (missingKeys.length > 0) {
                console.table(missingKeys);
            }
            console.groupEnd();
            return missingKeys;
        },

        /**
         * 修復缺少的翻譯鍵
         */
        fixMissingKeys() {
            console.group('🔧 Fixing Missing Translations');
            const missingKeys = window.i18n.validateTranslations();
            if (missingKeys.length > 0) {
                window.i18n.fixMissingTranslations(missingKeys);
                console.log(`Fixed ${missingKeys.length} missing translations`);
                // 重新翻譯頁面
                window.i18n.retranslate(document);
            } else {
                console.log('No missing translations found');
            }
            console.groupEnd();
        },

        /**
         * 強制重新載入翻譯
         */
        forceReload() {
            console.log('🔄 Force reloading translations...');

            // 清除快取
            localStorage.removeItem('language');
            Object.keys(localStorage).forEach(key => {
                if (key.startsWith('i18n_')) {
                    localStorage.removeItem(key);
                }
            });

            // 重新載入頁面
            window.location.reload();
        },

        /**
         * 測試特定翻譯鍵
         */
        testKey(keyPath, params = {}) {
            console.group(`🧪 Testing Translation Key: ${keyPath}`);
            const result = window.i18n.t(keyPath, params);
            console.log('Result:', result);
            console.log('Params:', params);
            console.groupEnd();
            return result;
        },

        /**
         * 顯示所有可用翻譯鍵
         */
        showAllKeys(language = null) {
            const targetLang = language || window.i18n.currentLanguage;
            const translations = window.i18n.translations[targetLang];

            if (!translations) {
                console.error(`No translations found for language: ${targetLang}`);
                return;
            }

            console.group(`📚 All Translation Keys (${targetLang})`);

            const flattenKeys = (obj, prefix = '') => {
                const keys = [];
                for (const key in obj) {
                    const fullKey = prefix ? `${prefix}.${key}` : key;
                    if (typeof obj[key] === 'object') {
                        keys.push(...flattenKeys(obj[key], fullKey));
                    } else {
                        keys.push(fullKey);
                    }
                }
                return keys;
            };

            const allKeys = flattenKeys(translations);
            console.log(`Total keys: ${allKeys.length}`);
            console.log(allKeys.sort());
            console.groupEnd();

            return allKeys;
        },

        /**
         * 監控翻譯效能
         */
        monitorPerformance() {
            const originalTranslate = window.i18n.translatePage;
            let callCount = 0;
            let totalTime = 0;

            window.i18n.translatePage = function(...args) {
                const start = performance.now();
                const result = originalTranslate.apply(this, args);
                const end = performance.now();

                callCount++;
                totalTime += (end - start);

                console.log(`📊 Translation call #${callCount}: ${(end - start).toFixed(2)}ms`);

                if (callCount % 10 === 0) {
                    console.log(`📈 Average translation time: ${(totalTime / callCount).toFixed(2)}ms`);
                }

                return result;
            };

            console.log('🎯 Translation performance monitoring enabled');
        }
    };

    // 在控制台顯示可用指令
    console.log('🌐 i18n Debug Tools Loaded! Available commands:');
    console.log('  window.i18nDebug.showStatus() - Show system status');
    console.log('  window.i18nDebug.checkMissingKeys() - Check missing translations');
    console.log('  window.i18nDebug.fixMissingKeys() - Fix missing translations');
    console.log('  window.i18nDebug.forceReload() - Force reload translations');
    console.log('  window.i18nDebug.testKey(key) - Test specific key');
    console.log('  window.i18nDebug.showAllKeys() - Show all available keys');
    console.log('  window.i18nDebug.monitorPerformance() - Monitor performance');
}

// Export for module usage if needed
if (typeof module !== 'undefined' && module.exports) {
    module.exports = I18nSystem;
}
