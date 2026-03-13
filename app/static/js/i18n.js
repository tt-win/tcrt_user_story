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
        this.supportedLanguages = ['en-US', 'zh-TW', 'zh-CN'];
        this.fallbackLanguage = 'en-US';
        this.isLoaded = false;
        this.cacheBuster = String(Date.now());
        this.translationVersion = '2026-03-13-4';
        
        // Initialize the system
        this.init();
    }

     /**
      * Initialize the i18n system
      */
     async init() {
         try {
             this.ensureCacheVersion();

             // Detect and set initial language
             this.detectLanguage();
             // Reflect on <html lang>
             try { document.documentElement.lang = this.currentLanguage; } catch (_) {}
             
             // Load translation files
             await this.loadTranslations();
             
             // Mark as loaded BEFORE translation applied
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
        const resolvedStoredLanguage = this.normalizeSupportedLanguage(storedLanguage);
        if (resolvedStoredLanguage) {
            this.currentLanguage = resolvedStoredLanguage;
            return;
        }

        // Check browser language preferences in order.
        const browserLanguages = this.getBrowserLanguagePreferences();
        for (const browserLanguage of browserLanguages) {
            const matchedLanguage = this.normalizeSupportedLanguage(browserLanguage);
            if (matchedLanguage) {
                this.currentLanguage = matchedLanguage;
                return;
            }
        }

        // Fall back to default
        this.currentLanguage = this.fallbackLanguage;
    }

    getBrowserLanguagePreferences() {
        const candidates = [];

        if (Array.isArray(navigator.languages) && navigator.languages.length > 0) {
            candidates.push(...navigator.languages);
        }

        if (navigator.language) {
            candidates.push(navigator.language);
        }

        if (navigator.userLanguage) {
            candidates.push(navigator.userLanguage);
        }

        return [...new Set(candidates
            .map(language => String(language || '').trim())
            .filter(Boolean))];
    }

    normalizeSupportedLanguage(language) {
        if (!language) {
            return null;
        }

        const normalizedLanguage = String(language).trim();
        if (!normalizedLanguage) {
            return null;
        }

        if (this.supportedLanguages.includes(normalizedLanguage)) {
            return normalizedLanguage;
        }

        const lowerLanguage = normalizedLanguage.toLowerCase().replace(/_/g, '-');

        // Safari often reports Chinese locale via script tags such as zh-Hant-TW / zh-Hans-CN.
        if (
            lowerLanguage.startsWith('zh-hant') ||
            lowerLanguage === 'zh-tw' ||
            lowerLanguage === 'zh-hk' ||
            lowerLanguage === 'zh-mo'
        ) {
            return 'zh-TW';
        }

        if (
            lowerLanguage.startsWith('zh-hans') ||
            lowerLanguage === 'zh-cn' ||
            lowerLanguage === 'zh-sg'
        ) {
            return 'zh-CN';
        }

        const languageCode = lowerLanguage.split('-')[0];
        if (languageCode === 'zh') {
            return 'zh-CN';
        }

        const matchedLanguage = this.supportedLanguages.find(
            supportedLanguage => supportedLanguage.toLowerCase().startsWith(`${languageCode}-`)
        );
        return matchedLanguage || null;
    }

    /**
     * Load translation files for all supported languages
     */
     async loadTranslations() {
         // Load translations for each supported language with cache busting
         this.loadingLanguages = new Set();
         // Set cache buster once for all language loads to prevent race conditions
         this.cacheBuster = Date.now();
         const cachePromises = this.supportedLanguages.map(async (language) => {
             if (this.loadingLanguages.has(language)) return;
             this.loadingLanguages.add(language);
             try {
                 const response = await fetch(`/static/locales/${language}.json?ver=${encodeURIComponent(this.translationVersion)}&t=${this.cacheBuster}`, {
                     cache: 'no-store'
                 });
                 if (!response.ok) {
                     console.warn(`Translation file for ${language} returned status ${response.status}. Attempting fallback.`);
                     throw new Error(`Failed to load ${language}: ${response.status}`);
                 }
                 // 一律以網路回應覆蓋快取，避免 Last-Modified 缺失造成快取不更新
                 const translations = await response.json();
                 this.translations[language] = translations;
                 localStorage.setItem(`i18n_${language}_cache`, JSON.stringify(translations));
                 localStorage.setItem(`i18n_${language}_modified`, new Date().toISOString());
                 console.log(`Loaded translations for ${language} (network)`);
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
                                 const resp = await fetch(`/static/locales/${this.fallbackLanguage}.json?ver=${encodeURIComponent(this.translationVersion)}&t=${this.cacheBuster}`, {
                                     cache: 'no-store'
                                 });
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
                const response = await fetch(`/static/locales/${language}.json?ver=${encodeURIComponent(this.translationVersion)}&t=${this.cacheBuster}`, {
                    cache: 'no-store'
                });
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
                 
                // Return fallback text first, then key path if no fallback provided
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
        if (!text) return text;
        
        // If the translation contains placeholders but no params provided, warn
        if (text.includes('{') && (!params || Object.keys(params).length === 0)) {
            console.warn(`Missing parameters for translation: text contains placeholders but no params provided`);
            return text; // Return original text with placeholders as fallback
        }

        // Perform parameter substitution
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
        const root = container instanceof Element ? container : document;
        const elements = [];

        if (root instanceof Element && root.hasAttribute('data-i18n')) {
            elements.push(root);
        }

        elements.push(...root.querySelectorAll('[data-i18n]'));
        
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

        // Get fallback text from data-i18n-fallback attribute or original DOM text
        const fallbackText = this.getTextFallback(element);

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
            const scope = root instanceof Element ? root : document;
            const elements = [];

            if (scope instanceof Element && scope.hasAttribute(`data-i18n-${attrType}`)) {
                elements.push(scope);
            }

            elements.push(...scope.querySelectorAll(`[data-i18n-${attrType}]`));
            
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

                // Get fallback text from explicit fallback or current DOM attribute
                const fallbackText = this.getAttributeFallback(element, attrType);

                // Translate and set the attribute
                const translatedText = this.t(key, params, fallbackText);
                element.setAttribute(attrType, translatedText);
            });
        });
    }

    ensureCacheVersion() {
        const storedVersion = localStorage.getItem('i18n_version');
        if (storedVersion === this.translationVersion) {
            return;
        }

        this.supportedLanguages.forEach(language => {
            localStorage.removeItem(`i18n_${language}_cache`);
            localStorage.removeItem(`i18n_${language}_modified`);
        });
        localStorage.setItem('i18n_version', this.translationVersion);
    }

    getTextFallback(element) {
        const explicitFallback = element.getAttribute('data-i18n-fallback');
        if (explicitFallback) {
            return explicitFallback;
        }

        const storedOriginal = element.getAttribute('data-i18n-original');
        if (storedOriginal) {
            return storedOriginal;
        }

        const currentText = typeof element.textContent === 'string'
            ? element.textContent.replace(/\s+/g, ' ').trim()
            : '';

        if (!currentText) {
            return null;
        }

        element.setAttribute('data-i18n-original', currentText);
        return currentText;
    }

    getAttributeFallback(element, attrType) {
        const fallbackAttr = `data-i18n-${attrType}-fallback`;
        const explicitFallback = element.getAttribute(fallbackAttr);
        if (explicitFallback) {
            return explicitFallback;
        }

        const originalAttr = `data-i18n-${attrType}-original`;
        const storedOriginal = element.getAttribute(originalAttr);
        if (storedOriginal) {
            return storedOriginal;
        }

        const currentValue = element.getAttribute(attrType);
        if (!currentValue) {
            return null;
        }

        element.setAttribute(originalAttr, currentValue);
        return currentValue;
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
 };

// Export for module usage if needed
if (typeof module !== 'undefined' && module.exports) {
    module.exports = I18nSystem;
}
