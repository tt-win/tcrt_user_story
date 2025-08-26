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
            
            console.log(`i18n initialized with language: ${this.currentLanguage}`);
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
        const loadPromises = this.supportedLanguages.map(async (language) => {
            try {
                const response = await fetch(`/static/locales/${language}.json?v=${this.cacheBuster}`);
                if (!response.ok) {
                    throw new Error(`Failed to load ${language}: ${response.status}`);
                }
                const translations = await response.json();
                this.translations[language] = translations;
                console.log(`Loaded translations for ${language}`);
            } catch (error) {
                console.error(`Failed to load translations for ${language}:`, error);
                // If current language fails to load, try fallback
                if (language === this.currentLanguage && language !== this.fallbackLanguage) {
                    console.warn(`Falling back to ${this.fallbackLanguage}`);
                    this.currentLanguage = this.fallbackLanguage;
                }
            }
        });

        await Promise.all(loadPromises);
        
        // Ensure at least one language is loaded
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
                const response = await fetch(`/static/locales/${language}.json`);
                if (!response.ok) {
                    throw new Error(`Failed to load ${language}`);
                }
                this.translations[language] = await response.json();
            } catch (error) {
                console.error(`Failed to load ${language}:`, error);
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
        
        console.log(`Language switched to: ${language}`);
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
                        if (fallbackValue && typeof fallbackValue === 'string') {
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
        if (!params || Object.keys(params).length === 0) {
            return text;
        }

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
        const attributeTypes = ['placeholder', 'title', 'alt', 'aria-label'];
        
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

        const observer = new MutationObserver((mutations) => {
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
}

// Create global i18n instance
window.i18n = new I18nSystem();

// Export for module usage if needed
if (typeof module !== 'undefined' && module.exports) {
    module.exports = I18nSystem;
}
