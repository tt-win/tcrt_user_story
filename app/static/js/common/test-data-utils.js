/* 共用 Test Data 工具：依 category 解析 / 序列化 / 產生複製選項 / 格式轉換。
   credential 以 JSON 內嵌於 value；其他 category value 為原始字串。 */
(function (global) {
    'use strict';

    const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

    // ===== credential：value = JSON {username, password} =====
    function parseCredential(value) {
        if (!value) return { username: '', password: '' };
        try {
            const parsed = JSON.parse(value);
            if (parsed && typeof parsed === 'object') {
                return {
                    username: String(parsed.username || ''),
                    password: String(parsed.password || '')
                };
            }
        } catch (_) { /* 退回：舊字串 */ }
        return { username: String(value), password: '' };
    }

    function serializeCredential(username, password) {
        return JSON.stringify({
            username: username || '',
            password: password || ''
        });
    }

    // ===== email =====
    function splitEmail(value) {
        const v = value || '';
        if (!v.includes('@')) return { username: v, domain: '', full: v };
        const at = v.lastIndexOf('@');
        return { username: v.substring(0, at), domain: v.substring(at + 1), full: v };
    }

    function isValidEmail(value) {
        return EMAIL_RE.test(value || '');
    }

    // ===== date =====
    function parseDate(value) {
        if (!value) return null;
        // 先試 epoch（秒 9-10 位、毫秒 13 位）
        const s = String(value).trim();
        if (/^\d{9,10}$/.test(s)) {
            const d = new Date(parseInt(s, 10) * 1000);
            if (!isNaN(d.getTime())) return d;
        }
        if (/^\d{13}$/.test(s)) {
            const d = new Date(parseInt(s, 10));
            if (!isNaN(d.getTime())) return d;
        }
        // 試 Date 內建 parser
        const d = new Date(s);
        if (!isNaN(d.getTime())) return d;
        // 試 YYYY/MM/DD 或 YYYY-MM-DD
        const m = s.match(/^(\d{4})[\/\-](\d{1,2})[\/\-](\d{1,2})(?:[ T](\d{1,2}):(\d{1,2})(?::(\d{1,2}))?)?/);
        if (m) {
            const d2 = new Date(
                parseInt(m[1], 10),
                parseInt(m[2], 10) - 1,
                parseInt(m[3], 10),
                m[4] ? parseInt(m[4], 10) : 0,
                m[5] ? parseInt(m[5], 10) : 0,
                m[6] ? parseInt(m[6], 10) : 0
            );
            if (!isNaN(d2.getTime())) return d2;
        }
        return null;
    }

    const pad2 = (n) => String(n).padStart(2, '0');

    function formatDate(value, fmt) {
        const d = parseDate(value);
        if (!d) return value || '';
        const y = d.getFullYear();
        const mo = pad2(d.getMonth() + 1);
        const da = pad2(d.getDate());
        const h = pad2(d.getHours());
        const mi = pad2(d.getMinutes());
        const sc = pad2(d.getSeconds());
        switch (fmt) {
            case 'slash':    return `${y}/${mo}/${da}`;
            case 'dash':     return `${y}-${mo}-${da}`;
            case 'datetime': return `${y}-${mo}-${da} ${h}:${mi}:${sc}`;
            case 'iso':      return d.toISOString();
            case 'epoch':    return String(Math.floor(d.getTime() / 1000));
            case 'epoch_ms': return String(d.getTime());
            default:         return value || '';
        }
    }

    // ===== JSON =====
    function tryPrettyJson(value) {
        if (!value) return '';
        try {
            return JSON.stringify(JSON.parse(value), null, 2);
        } catch (_) {
            return value;
        }
    }

    function isValidJson(value) {
        if (!value) return true; // 空字串視為合法（使用者尚未填）
        try { JSON.parse(value); return true; } catch (_) { return false; }
    }

    function _escHtml(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;');
    }

    // 輕量 JSON 高亮（不依賴外部 lib）
    function highlightJson(value) {
        const pretty = tryPrettyJson(value);
        const escaped = _escHtml(pretty);
        return escaped.replace(
            /("(?:\\.|[^"\\])*")(\s*:)?|(\b-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?\b)|(\btrue\b|\bfalse\b|\bnull\b)/g,
            function (match, str, colon, num, bool) {
                if (str !== undefined) {
                    if (colon) return `<span class="td-json-key">${str}</span>${colon}`;
                    return `<span class="td-json-string">${str}</span>`;
                }
                if (num !== undefined) return `<span class="td-json-number">${num}</span>`;
                if (bool !== undefined) return `<span class="td-json-bool">${bool}</span>`;
                return match;
            }
        );
    }

    // ===== 複製選項：null 表示單一值直接複製 =====
    function getCopyOptions(category, value) {
        switch (category) {
            case 'credential': {
                const c = parseCredential(value);
                return [
                    { key: 'username', labelKey: 'testRun.copyCredentialUsername', fallback: '帳號', value: c.username },
                    { key: 'password', labelKey: 'testRun.copyCredentialPassword', fallback: '密碼', value: c.password }
                ];
            }
            case 'email': {
                const p = splitEmail(value);
                return [
                    { key: 'full',     labelKey: 'testRun.copyEmailFull',     fallback: '完整 Email', value: p.full },
                    { key: 'username', labelKey: 'testRun.copyEmailUsername', fallback: 'Username',   value: p.username },
                    { key: 'domain',   labelKey: 'testRun.copyEmailDomain',   fallback: 'Domain',     value: p.domain }
                ];
            }
            case 'date': {
                return [
                    { key: 'slash',    labelKey: 'testRun.copyDateSlash',    fallback: 'YYYY/MM/DD',        value: formatDate(value, 'slash') },
                    { key: 'dash',     labelKey: 'testRun.copyDateDash',     fallback: 'YYYY-MM-DD',        value: formatDate(value, 'dash') },
                    { key: 'datetime', labelKey: 'testRun.copyDateDatetime', fallback: 'YYYY-MM-DD HH:mm:ss', value: formatDate(value, 'datetime') },
                    { key: 'iso',      labelKey: 'testRun.copyDateIso',      fallback: 'ISO 8601',          value: formatDate(value, 'iso') },
                    { key: 'epoch',    labelKey: 'testRun.copyDateEpoch',    fallback: 'Epoch (秒)',         value: formatDate(value, 'epoch') },
                    { key: 'epoch_ms', labelKey: 'testRun.copyDateEpochMs',  fallback: 'Epoch (毫秒)',       value: formatDate(value, 'epoch_ms') }
                ];
            }
            default:
                return null;
        }
    }

    // 顯示用：credential 顯示 username + 遮罩密碼；其他 category 回傳原值
    function getDisplayValue(category, value) {
        if (category === 'credential') {
            const c = parseCredential(value);
            const masked = c.password ? '•'.repeat(Math.min(c.password.length, 10)) : '';
            return c.username + (masked ? ` / ${masked}` : '');
        }
        return value || '';
    }

    global.TestDataUtils = {
        parseCredential,
        serializeCredential,
        splitEmail,
        isValidEmail,
        parseDate,
        formatDate,
        tryPrettyJson,
        isValidJson,
        highlightJson,
        getCopyOptions,
        getDisplayValue
    };
})(window);
