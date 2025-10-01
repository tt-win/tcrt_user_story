/**
 * 加密工具函式
 *
 * 提供前端密碼加密功能，用於 Challenge-Response 認證機制
 */

class CryptoUtils {
    /**
     * 使用 PBKDF2 對密碼進行雜湊
     *
     * @param {string} password - 明文密碼
     * @param {string} salt - 鹽值
     * @param {number} iterations - 迭代次數 (預設 100000)
     * @returns {Promise<ArrayBuffer>} - 雜湊值的 ArrayBuffer
     */
    static async hashPasswordPBKDF2(password, salt, iterations = 100000) {
        const encoder = new TextEncoder();

        // 將密碼轉換為 key material
        const keyMaterial = await window.crypto.subtle.importKey(
            'raw',
            encoder.encode(password),
            'PBKDF2',
            false,
            ['deriveBits']
        );

        // 使用 PBKDF2 派生密鑰
        const derivedBits = await window.crypto.subtle.deriveBits(
            {
                name: 'PBKDF2',
                salt: encoder.encode(salt),
                iterations: iterations,
                hash: 'SHA-256'
            },
            keyMaterial,
            256  // 輸出 256 bits
        );

        return derivedBits;
    }

    /**
     * 使用 HMAC-SHA256 計算雜湊
     *
     * @param {string} message - 訊息
     * @param {ArrayBuffer} keyBuffer - 密鑰 (ArrayBuffer)
     * @returns {Promise<string>} - 十六進位字串格式的 HMAC 值
     */
    static async hmacSHA256(message, keyBuffer) {
        const encoder = new TextEncoder();

        // 匯入密鑰
        const cryptoKey = await window.crypto.subtle.importKey(
            'raw',
            keyBuffer,
            { name: 'HMAC', hash: 'SHA-256' },
            false,
            ['sign']
        );

        // 計算 HMAC
        const signature = await window.crypto.subtle.sign(
            'HMAC',
            cryptoKey,
            encoder.encode(message)
        );

        return this.arrayBufferToHex(signature);
    }

    /**
     * 計算 Challenge-Response
     *
     * 流程：
     * 1. 使用 PBKDF2 對密碼進行雜湊
     * 2. 使用 HMAC-SHA256(challenge, password_hash) 計算 response
     *
     * @param {string} password - 明文密碼
     * @param {string} salt - 鹽值 (通常是 username)
     * @param {string} challenge - 伺服器提供的 challenge
     * @param {number} iterations - PBKDF2 迭代次數
     * @returns {Promise<string>} - 十六進位字串格式的 response
     */
    static async calculateChallengeResponse(password, salt, challenge, iterations = 100000) {
        // 步驟 1: 使用 PBKDF2 雜湊密碼
        const passwordHashBuffer = await this.hashPasswordPBKDF2(password, salt, iterations);

        // 步驟 2: 使用 HMAC-SHA256 計算 response
        const response = await this.hmacSHA256(challenge, passwordHashBuffer);

        return response;
    }

    /**
     * ArrayBuffer 轉十六進位字串
     *
     * @param {ArrayBuffer} buffer
     * @returns {string}
     */
    static arrayBufferToHex(buffer) {
        return Array.from(new Uint8Array(buffer))
            .map(b => b.toString(16).padStart(2, '0'))
            .join('');
    }

    /**
     * 十六進位字串轉 ArrayBuffer
     *
     * @param {string} hex
     * @returns {ArrayBuffer}
     */
    static hexToArrayBuffer(hex) {
        const bytes = new Uint8Array(hex.length / 2);
        for (let i = 0; i < hex.length; i += 2) {
            bytes[i / 2] = parseInt(hex.substr(i, 2), 16);
        }
        return bytes.buffer;
    }

    /**
     * 測試 Web Crypto API 是否可用
     *
     * @returns {boolean}
     */
    static isWebCryptoAvailable() {
        return !!(window.crypto && window.crypto.subtle);
    }
}

// 匯出供其他模組使用
if (typeof window !== 'undefined') {
    window.CryptoUtils = CryptoUtils;
}

if (typeof module !== 'undefined' && module.exports) {
    module.exports = CryptoUtils;
}
