/**
 * DateTimeFormatter - A module for handling date/time formatting using browser locale
 * Uses native Intl.DateTimeFormat API (ICU-based standard)
 * Separates UI language from locale formatting (date/time/numbers)
 */

class DateTimeFormatter {
    constructor() {
        this.browserLocale = this.detectBrowserLocale();
        this.formatterCache = new Map();
    }

    /**
     * Detect the user's preferred locale from browser settings
     * @returns {string} Browser locale (e.g., 'en-US', 'zh-TW', 'ja-JP')
     */
    detectBrowserLocale() {
        // Use navigator.languages for ordered preference list
        if (navigator.languages && navigator.languages.length > 0) {
            return navigator.languages[0];
        }
        
        // Fallback to navigator.language
        if (navigator.language) {
            return navigator.language;
        }
        
        // Final fallback
        return 'en-US';
    }

    /**
     * Get or create a cached formatter instance
     * @param {string} cacheKey - Unique key for this formatter configuration
     * @param {string} locale - Locale string
     * @param {Object} options - Intl.DateTimeFormat options
     * @returns {Intl.DateTimeFormat} Formatter instance
     */
    getFormatter(cacheKey, locale, options) {
        if (!this.formatterCache.has(cacheKey)) {
            this.formatterCache.set(cacheKey, new Intl.DateTimeFormat(locale, options));
        }
        return this.formatterCache.get(cacheKey);
    }

    /**
     * Format a date using browser locale preferences
     * @param {Date|string} date - Date object or date string
     * @param {string} style - Format style: 'date', 'time', 'datetime', 'short', 'medium', 'long', 'full'
     * @returns {string} Formatted date string
     */
    format(date, style = 'datetime') {
        if (!date) return '';

        // Convert string to Date if necessary
        const dateObj = date instanceof Date ? date : new Date(date);
        
        // Check for invalid date
        if (isNaN(dateObj.getTime())) {
            console.warn('Invalid date provided to DateTimeFormatter:', date);
            return '';
        }

        const locale = this.browserLocale;
        const options = this.getOptionsForStyle(style);
        const cacheKey = `${locale}-${style}`;
        
        const formatter = this.getFormatter(cacheKey, locale, options);
        return formatter.format(dateObj);
    }

    /**
     * Get Intl.DateTimeFormat options based on style
     * @param {string} style - Format style
     * @returns {Object} Options object for Intl.DateTimeFormat
     */
    getOptionsForStyle(style) {
        const styleMap = {
            // Legacy format styles (for backward compatibility)
            // 使用 'short' 來符合各地區標準的簡短日期格式
            // en-US: 8/22/2024, zh-TW: 2024/8/22, de-DE: 22.8.24 等
            'date': {
                dateStyle: 'short'
            },
            'time': {
                timeStyle: 'short'
            },
            'datetime': {
                dateStyle: 'short',
                timeStyle: 'short'
            },
            
            // Standard Intl styles
            'short': {
                dateStyle: 'short',
                timeStyle: 'short'
            },
            'medium': {
                dateStyle: 'medium',
                timeStyle: 'medium'
            },
            'long': {
                dateStyle: 'long',
                timeStyle: 'long'
            },
            'full': {
                dateStyle: 'full',
                timeStyle: 'full'
            },
            
            // Date-only styles
            'date-short': {
                dateStyle: 'short'
            },
            'date-medium': {
                dateStyle: 'medium'
            },
            'date-long': {
                dateStyle: 'long'
            },
            'date-full': {
                dateStyle: 'full'
            },
            
            // Time-only styles
            'time-short': {
                timeStyle: 'short'
            },
            'time-medium': {
                timeStyle: 'medium'
            },
            'time-long': {
                timeStyle: 'long'
            }
        };

        return styleMap[style] || styleMap['datetime'];
    }

    /**
     * Format a relative time (e.g., "2 hours ago", "in 3 days")
     * @param {Date|string} date - Date object or date string
     * @returns {string} Relative time string
     */
    formatRelative(date) {
        if (!date) return '';

        const dateObj = date instanceof Date ? date : new Date(date);
        if (isNaN(dateObj.getTime())) return '';

        const now = new Date();
        const diffMs = dateObj.getTime() - now.getTime();
        const diffMinutes = Math.round(diffMs / (1000 * 60));

        // Use Intl.RelativeTimeFormat for proper localization
        const rtf = new Intl.RelativeTimeFormat(this.browserLocale, { numeric: 'auto' });

        if (Math.abs(diffMinutes) < 1) {
            return rtf.format(0, 'minute'); // "now" or equivalent
        } else if (Math.abs(diffMinutes) < 60) {
            return rtf.format(diffMinutes, 'minute');
        } else if (Math.abs(diffMinutes) < 1440) { // 24 hours
            return rtf.format(Math.round(diffMinutes / 60), 'hour');
        } else if (Math.abs(diffMinutes) < 43200) { // 30 days
            return rtf.format(Math.round(diffMinutes / 1440), 'day');
        } else if (Math.abs(diffMinutes) < 525600) { // 365 days
            return rtf.format(Math.round(diffMinutes / 43200), 'month');
        } else {
            return rtf.format(Math.round(diffMinutes / 525600), 'year');
        }
    }

    /**
     * Get the current browser locale
     * @returns {string} Current browser locale
     */
    getBrowserLocale() {
        return this.browserLocale;
    }

    /**
     * Refresh the browser locale (useful if user changes system settings)
     */
    refreshBrowserLocale() {
        this.browserLocale = this.detectBrowserLocale();
        this.formatterCache.clear(); // Clear cache to use new locale
    }
}

// Create a global instance
const dateTimeFormatter = new DateTimeFormatter();

// Export for use in other modules
window.DateTimeFormatter = dateTimeFormatter;

// Log the detected locale for debugging
console.log('DateTimeFormatter initialized with browser locale:', dateTimeFormatter.getBrowserLocale());