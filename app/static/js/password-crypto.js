/**
 * 密碼加密工具
 * 使用 Web Crypto API 對密碼進行加密，確保傳輸安全
 */
class PasswordCrypto {
    /**
     * 生成 RSA 金鑰對（前端暫存使用）
     * 注意：實際應該由後端提供公鑰
     */
    static async generateKeyPair() {
        return await window.crypto.subtle.generateKey(
            {
                name: "RSA-OAEP",
                modulusLength: 2048,
                publicExponent: new Uint8Array([1, 0, 1]),
                hash: "SHA-256",
            },
            true,
            ["encrypt", "decrypt"]
        );
    }

    /**
     * 從後端獲取公鑰
     */
    static async getPublicKey() {
        try {
            const response = await fetch('/api/auth/public-key');
            if (!response.ok) {
                throw new Error('無法獲取公鑰');
            }
            const data = await response.json();

            // 將 base64 編碼的公鑰轉換為 CryptoKey
            const publicKeyData = this.base64ToArrayBuffer(data.public_key);

            return await window.crypto.subtle.importKey(
                "spki",
                publicKeyData,
                {
                    name: "RSA-OAEP",
                    hash: "SHA-256",
                },
                true,
                ["encrypt"]
            );
        } catch (error) {
            console.error('獲取公鑰失敗:', error);
            throw error;
        }
    }

    /**
     * 使用公鑰加密密碼
     * @param {string} password - 明文密碼
     * @param {CryptoKey} publicKey - RSA 公鑰
     * @returns {string} Base64 編碼的加密密碼
     */
    static async encryptPassword(password, publicKey) {
        try {
            const encoder = new TextEncoder();
            const data = encoder.encode(password);

            const encrypted = await window.crypto.subtle.encrypt(
                {
                    name: "RSA-OAEP"
                },
                publicKey,
                data
            );

            // 轉換為 base64
            return this.arrayBufferToBase64(encrypted);
        } catch (error) {
            console.error('加密密碼失敗:', error);
            throw error;
        }
    }

    /**
     * 將 ArrayBuffer 轉換為 Base64 字串
     */
    static arrayBufferToBase64(buffer) {
        const bytes = new Uint8Array(buffer);
        let binary = '';
        for (let i = 0; i < bytes.byteLength; i++) {
            binary += String.fromCharCode(bytes[i]);
        }
        return window.btoa(binary);
    }

    /**
     * 將 Base64 字串轉換為 ArrayBuffer
     */
    static base64ToArrayBuffer(base64) {
        const binary = window.atob(base64);
        const bytes = new Uint8Array(binary.length);
        for (let i = 0; i < binary.length; i++) {
            bytes[i] = binary.charCodeAt(i);
        }
        return bytes.buffer;
    }

    /**
     * 檢查瀏覽器是否支援 Web Crypto API
     */
    static isSupported() {
        const hasWebCrypto = !!(window.crypto && window.crypto.subtle);
        const isSecureContext = window.isSecureContext;

        console.log('[PasswordCrypto] 支援檢查:');
        console.log('  - window.crypto 存在?', !!window.crypto);
        console.log('  - window.crypto.subtle 存在?', !!(window.crypto && window.crypto.subtle));
        console.log('  - 安全上下文 (HTTPS/localhost)?', isSecureContext);

        if (hasWebCrypto && !isSecureContext) {
            console.warn('[PasswordCrypto] Web Crypto API 存在但不在安全上下文中');
        }

        return hasWebCrypto;
    }

    /**
     * 加密密碼變更請求
     * @param {string} currentPassword - 目前密碼
     * @param {string} newPassword - 新密碼
     * @returns {object} 包含加密密碼的物件
     */
    static async encryptPasswordChangeRequest(currentPassword, newPassword) {
        console.log('[PasswordCrypto] 開始加密密碼變更請求');

        if (!this.isSupported()) {
            console.warn('[PasswordCrypto] 瀏覽器不支援 Web Crypto API，密碼將以明文傳送');
            return {
                current_password: currentPassword,
                new_password: newPassword,
                encrypted: false
            };
        }

        try {
            console.log('[PasswordCrypto] 獲取公鑰...');
            const publicKey = await this.getPublicKey();
            console.log('[PasswordCrypto] 公鑰獲取成功');

            console.log('[PasswordCrypto] 加密目前密碼...');
            const encryptedCurrent = await this.encryptPassword(currentPassword, publicKey);
            console.log('[PasswordCrypto] 目前密碼加密成功，長度:', encryptedCurrent.length);

            console.log('[PasswordCrypto] 加密新密碼...');
            const encryptedNew = await this.encryptPassword(newPassword, publicKey);
            console.log('[PasswordCrypto] 新密碼加密成功，長度:', encryptedNew.length);

            console.log('[PasswordCrypto] 密碼加密完成');
            return {
                current_password: encryptedCurrent,
                new_password: encryptedNew,
                encrypted: true
            };
        } catch (error) {
            console.error('[PasswordCrypto] 加密失敗，回退到明文傳送:', error);
            console.error('[PasswordCrypto] 錯誤堆疊:', error.stack);
            // 如果加密失敗，回退到明文（但應該警告使用者）
            return {
                current_password: currentPassword,
                new_password: newPassword,
                encrypted: false
            };
        }
    }
}

// 將 PasswordCrypto 暴露到全域
window.PasswordCrypto = PasswordCrypto;
