/* TCRT canonical Markdown adapter: CommonMark 0.31.2 plus four GFM extensions. */
(function installTCRTMarkdown(global) {
    'use strict';
    if (!global || typeof global !== 'object') return;
    if (global.TCRTMarkdown && typeof global.TCRTMarkdown.render === 'function') return;

    const VERSION = Object.freeze({
        commonmark: '0.31.2', gfm: '0.29', parser: 'commonmark@0.31.2', sanitizer: 'dompurify@3.4.12',
    });
    const GFM_EXTENSIONS = Object.freeze(['tables', 'task-list-items', 'strikethrough', 'autolink-literals']);
    const SAFE_TAGS = Object.freeze([
        'p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'ul', 'ol', 'li', 'blockquote', 'pre', 'code',
        'em', 'strong', 'del', 'a', 'br', 'hr', 'table', 'thead', 'tbody', 'tr', 'th', 'td', 'img', 'input',
    ]);
    const SAFE_ATTRIBUTES = Object.freeze([
        'href', 'target', 'rel', 'src', 'alt', 'type', 'checked', 'disabled',
    ]);
    const SANITIZE_CONFIG = Object.freeze({
        ALLOWED_TAGS: SAFE_TAGS, ALLOWED_ATTR: SAFE_ATTRIBUTES, ALLOW_ARIA_ATTR: false, ALLOW_DATA_ATTR: false,
        FORBID_ATTR: ['style'],
        FORBID_TAGS: ['base', 'form', 'iframe', 'math', 'object', 'script', 'style', 'svg', 'template'],
        KEEP_CONTENT: true, RETURN_TRUSTED_TYPE: false,
    });
    const REASONS = Object.freeze({
        PENDING: 'renderer-pending', ASSET: 'asset-unavailable', PARSER: 'parser-unavailable',
        SANITIZER: 'sanitizer-unavailable', RENDER: 'renderer-error',
    });
    const CONTROL_CHARACTERS = /[\u0000-\u001f\u007f]/;
    const SCHEME = /^[a-z][a-z0-9+.-]*:/i;
    const UNSAFE_SCHEME = /^(?:javascript|data|blob|file):/i;
    const UNSAFE_EMBEDDED_SCHEME = /(?:javascript|data|blob|file):/i;
    const MAIL_LOCAL = /^[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+$/;
    const MAIL_LABEL = '[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?';
    const MAIL_DOMAIN = new RegExp('^(?:' + MAIL_LABEL + '\\.)+' + MAIL_LABEL + '$');

    let parser = null;
    let sanitizer = null;
    let state = 'pending';
    let unavailableReason = REASONS.PENDING;
    const recordedReasons = new Set();
    const sourceText = (value) => {
        if (value == null) return '';
        try { return String(value); } catch (_) { return ''; }
    };
    const escapeHtml = (value) => sourceText(value).replace(/[&<>"']/g, (character) => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    })[character]);
    const escapeAttribute = escapeHtml;

    function recordUnavailable(reason) {
        if (recordedReasons.has(reason)) return;
        recordedReasons.add(reason);
        if (global.console && typeof global.console.warn === 'function') {
            global.console.warn('[TCRTMarkdown] ' + reason);
        }
    }
    function fallback(value, reason) {
        return { html: '<pre>' + escapeHtml(sourceText(value)) + '</pre>', status: 'fallback', reason };
    }
    function urlConstructor() {
        if (typeof global.URL === 'function') return global.URL;
        if (typeof URL === 'function') return URL;
        return null;
    }
    function baseUrl() {
        const URLCtor = urlConstructor();
        const candidate = global.document && typeof global.document.baseURI === 'string'
            ? global.document.baseURI
            : global.location && typeof global.location.href === 'string' ? global.location.href : null;
        if (!URLCtor || !candidate) return null;
        try { return new URLCtor(candidate); } catch (_) { return null; }
    }
    function encodeUrl(value) {
        try {
            const encoder = typeof global.encodeURI === 'function' ? global.encodeURI : encodeURI;
            return encoder(value);
        } catch (_) { return null; }
    }
    function urlSchemeProbe(value) {
        // Decode HTML entities, but do not decode percent escapes: a percent-encoded
        // scheme-looking destination remains a relative literal and is URI-encoded.
        return value.replace(/&colon;/gi, ':').replace(/&#(?:x([0-9a-f]+)|([0-9]+));/gi, (_, hex, decimal) => {
            const codePoint = Number.parseInt(hex || decimal, hex ? 16 : 10);
            return Number.isFinite(codePoint) && codePoint >= 0 && codePoint <= 0x10ffff
                ? String.fromCodePoint(codePoint) : _;
        });
    }
    function safeMailto(value) {
        if (!/^mailto:/i.test(value)) return null;
        const body = value.slice(7);
        if (!body || CONTROL_CHARACTERS.test(body) || /[<>\s?#/\\]/.test(body)) return null;
        if (/%(?:0[0-9a-f]|1[0-9a-f]|7f|2f|5c|3f|23)/i.test(body)) return null;
        if (UNSAFE_EMBEDDED_SCHEME.test(body)) return null;
        let decoded;
        try {
            const decoder = typeof global.decodeURIComponent === 'function' ? global.decodeURIComponent : decodeURIComponent;
            decoded = decoder(body);
        } catch (_) {
            return null;
        }
        if (CONTROL_CHARACTERS.test(decoded) || /[/?#\\]/.test(decoded)) return null;
        const parts = body.split('@');
        if (parts.length !== 2) return null;
        const [local, domain] = parts;
        if (!MAIL_LOCAL.test(local) || !local || local.startsWith('.') || local.endsWith('.') || local.includes('..')) return null;
        if (!MAIL_DOMAIN.test(domain)) return null;
        return { value: 'mailto:' + body, external: false };
    }
    function normalizeUrl(rawValue, kind) {
        if (typeof rawValue !== 'string') return null;
        const value = rawValue.trim();
        if (!value || CONTROL_CHARACTERS.test(value) || value.includes('\\')) return null;
        if (value.startsWith('//')) return null;
        const probe = urlSchemeProbe(value);
        if (CONTROL_CHARACTERS.test(probe) || UNSAFE_SCHEME.test(probe)) return null;
        if (/^mailto:/i.test(probe) && !/^mailto:/i.test(value)) return null;
        const mailto = safeMailto(value);
        if (mailto) return kind === 'image' ? null : mailto;
        if (/^mailto:/i.test(value) || UNSAFE_SCHEME.test(value)) return null;
        if (!SCHEME.test(value)) {
            const encoded = encodeUrl(value);
            return encoded && !CONTROL_CHARACTERS.test(encoded) ? { value: encoded, external: false } : null;
        }
        if (!/^https?:\/\//i.test(value)) return null;
        const URLCtor = urlConstructor();
        const encoded = encodeUrl(value);
        if (!URLCtor || !encoded) return null;
        let parsed;
        try { parsed = new URLCtor(encoded); } catch (_) { return null; }
        if (parsed.username || parsed.password) return null;
        if (!/^https?:$/i.test(parsed.protocol)) return null;
        if (kind === 'image' && parsed.protocol.toLowerCase() !== 'https:') return null;
        const origin = baseUrl();
        return { value: parsed.href, external: !origin || parsed.origin !== origin.origin };
    }

    function nodeInlineText(node) {
        let result = '';
        for (let child = node && node.firstChild; child; child = child.next) {
            if (child.type === 'text' || child.type === 'code') result += sourceText(child.literal);
            else if (child.type === 'softbreak' || child.type === 'linebreak') result += '\n';
            else result += nodeInlineText(child);
        }
        return result;
    }
    function gfmMarker(kind, index) {
        return 'TCRTMD' + kind + 'MARKER' + index + 'END';
    }
    function isEscaped(value, index) {
        let slashCount = 0;
        for (let cursor = index - 1; cursor >= 0 && value[cursor] === '\\'; cursor -= 1) slashCount += 1;
        return slashCount % 2 === 1;
    }
    function splitTableRow(line) {
        let value = sourceText(line).trim();
        if (value.startsWith('|')) value = value.slice(1);
        if (value.endsWith('|') && !isEscaped(value, value.length - 1)) value = value.slice(0, -1);
        const cells = [];
        let cell = '';
        let codeTickLength = 0;
        let linkLabelDepth = 0;
        let linkDestinationDepth = 0;
        let linkDestinationPending = false;
        for (let index = 0; index < value.length;) {
            const character = value[index];
            if (character === '\\') {
                cell += character;
                if (index + 1 < value.length) cell += value[index + 1];
                index += index + 2 <= value.length ? 2 : 1;
                continue;
            }
            if (character === '`') {
                let end = index + 1;
                while (value[end] === '`') end += 1;
                const tickLength = end - index;
                if (codeTickLength === 0) codeTickLength = tickLength;
                else if (codeTickLength === tickLength) codeTickLength = 0;
                cell += value.slice(index, end);
                index = end;
                continue;
            }
            if (codeTickLength === 0) {
                if (character === '[') {
                    linkLabelDepth += 1;
                    linkDestinationPending = false;
                } else if (character === ']' && linkLabelDepth > 0) {
                    linkLabelDepth -= 1;
                    linkDestinationPending = linkLabelDepth === 0;
                } else if (character === '(' && linkDestinationPending) {
                    linkDestinationDepth = 1;
                    linkDestinationPending = false;
                } else if (character === '(' && linkDestinationDepth > 0) {
                    linkDestinationDepth += 1;
                } else if (character === ')' && linkDestinationDepth > 0) {
                    linkDestinationDepth -= 1;
                } else if (linkDestinationPending) {
                    linkDestinationPending = false;
                }
            }
            if (character === '|' && codeTickLength === 0 && linkLabelDepth === 0 && linkDestinationDepth === 0) {
                cells.push(cell.trim());
                cell = '';
            } else {
                cell += character;
            }
            index += 1;
        }
        cells.push(cell.trim());
        return cells;
    }
    function blockQuoteContext(line) {
        let content = sourceText(line);
        let prefix = '';
        let depth = 0;
        let marker;
        while ((marker = /^( {0,3}>[ \t]?)/.exec(content))) {
            prefix += marker[1];
            content = content.slice(marker[1].length);
            depth += 1;
        }
        return { content, prefix, depth };
    }
    function parseGfmTable(lines, index) {
        const header = blockQuoteContext(lines[index]);
        const delimiter = blockQuoteContext(lines[index + 1]);
        const headerLine = header.content;
        const delimiterLine = delimiter.content;
        if (header.depth !== delimiter.depth || /^(?: {4}|\t)/.test(headerLine) || !headerLine || !delimiterLine || !headerLine.includes('|') || !delimiterLine.includes('|')) return null;
        const headers = splitTableRow(headerLine);
        const delimiters = splitTableRow(delimiterLine);
        if (!headers.length || headers.length !== delimiters.length || delimiters.some((cell) => !/^:?-+:?$/.test(cell))) return null;
        const rows = [];
        let end = index + 1;
        for (let cursor = index + 2; cursor < lines.length; cursor += 1) {
            const row = blockQuoteContext(lines[cursor]);
            if (row.depth !== header.depth || row.content.trim() === '' || !row.content.includes('|')) break;
            const cells = splitTableRow(row.content);
            while (cells.length < headers.length) cells.push('');
            rows.push(cells.slice(0, headers.length));
            end = cursor;
        }
        return { headers, rows, end, prefix: header.prefix, indentation: /^([ \t]*)/.exec(headerLine)[1] };
    }
    function canStartGfmTable(lines, index) {
        if (index === 0) return true;
        const current = blockQuoteContext(lines[index]);
        const previous = blockQuoteContext(lines[index - 1]);
        if (current.depth !== previous.depth || previous.content.trim() === '') return true;
        return /^(?: {0,3}#{1,6}(?:[ \t]|$)| {0,3}(?:`{3,}|~{3,})[ \t]*$)$/.test(previous.content);
    }
    function replaceTaskMarker(line, tasksByLine, outputLine) {
        const match = /^((?: {0,3}>[ \t]?)*[ \t]*(?:[-+*]|\d{1,9}[.)])[ \t]+)\[([ xX])\]([ \t]+|$)/.exec(line);
        if (!match) return line;
        const marker = gfmMarker('TASK', tasksByLine.size);
        tasksByLine.set(outputLine, { checked: match[2].toLowerCase() === 'x', prefixLength: marker.length + match[3].length });
        return match[1] + marker + match[3] + line.slice(match[0].length);
    }
    function prepareGfmSource(value) {
        const source = sourceText(value);
        const lines = source.split('\n');
        const tablesByLine = new Map();
        const tasksByLine = new Map();
        const output = [];
        let fence = null;
        for (let index = 0; index < lines.length; index += 1) {
            const line = lines[index];
            const context = blockQuoteContext(line);
            const fenceMarker = /^( {0,3})(`{3,}|~{3,})/.exec(context.content);
            if (fence) {
                output.push(line);
                if (
                    context.depth === fence.depth
                    && new RegExp('^ {0,3}' + fence.char + '{' + fence.length + ',}\\s*$').test(context.content)
                ) fence = null;
                continue;
            }
            if (fenceMarker) {
                fence = { char: fenceMarker[2][0], length: fenceMarker[2].length, depth: context.depth };
                output.push(line);
                continue;
            }
            const table = canStartGfmTable(lines, index) ? parseGfmTable(lines, index) : null;
            if (table) {
                const marker = gfmMarker('TABLE', tablesByLine.size);
                tablesByLine.set(output.length + 1, { headers: table.headers, rows: table.rows });
                output.push(table.prefix + table.indentation + marker, '');
                index = table.end;
                continue;
            }
            if (/^(?: {4}|\t)/.test(context.content)) {
                output.push(line);
                continue;
            }
            output.push(replaceTaskMarker(
                line.replace(/^([ \t]{0,3})(\[\^[^\]\n]+]:)/, '$1\\$2'),
                tasksByLine,
                output.length + 1,
            ));
        }
        return { source: output.join('\n'), tablesByLine, tasksByLine };
    }
    function bindGfmNodes(document, prepared) {
        const tableNodes = new WeakMap();
        const taskNodes = new WeakMap();
        if (!document || typeof document.walker !== 'function') return { tableNodes, taskNodes };
        const walker = document.walker();
        let event;
        while ((event = walker.next())) {
            const node = event.node;
            if (!event.entering || !node || node.type !== 'paragraph' || !node.sourcepos) continue;
            const start = node.sourcepos[0] && node.sourcepos[0][0];
            if (!Number.isInteger(start)) continue;
            const table = prepared.tablesByLine.get(start);
            if (table) tableNodes.set(node, table);
            const task = prepared.tasksByLine.get(start);
            if (task && node.parent && node.parent.type === 'item') taskNodes.set(node.parent, task);
        }
        return { tableNodes, taskNodes };
    }

    function createRenderer(commonmarkApi, gfm) {
        const renderer = new commonmarkApi.HtmlRenderer({ safe: false, softbreak: '\n' });
        renderer.attrs = () => [];
        const tableNodes = gfm && gfm.tableNodes instanceof WeakMap ? gfm.tableNodes : new WeakMap();
        const taskNodes = gfm && gfm.taskNodes instanceof WeakMap ? gfm.taskNodes : new WeakMap();
        renderer._taskStack = [];
        renderer._tableParagraph = null;
        renderer._imageDepth = 0;
        renderer._linkStack = [];
        renderer._linkLiteralDepth = 0;
        renderer._strikeDepth = 0;
        let sourceRawHtml = null;
        const sourceRawHtmlLiteral = (node) => {
            const literal = sourceText(node && node.literal);
            if (node && typeof node === 'object') {
                sourceRawHtml ||= new WeakMap();
                sourceRawHtml.set(node, { origin: 'source-raw-html', literal });
            }
            return literal;
        };

        const renderInline = (value) => {
            const document = new commonmarkApi.Parser().parse(sourceText(value));
            const fragment = createRenderer(commonmarkApi).render(document);
            return fragment.replace(/^<p>/, '').replace(/<\/p>\n$/, '');
        };
        const renderTable = (table) => {
            const cell = (tag, value) => '<' + tag + '>' + renderInline(value) + '</' + tag + '>\n';
            let html = '<table>\n<thead>\n<tr>\n';
            table.headers.forEach((header) => { html += cell('th', header); });
            html += '</tr>\n</thead>\n';
            if (table.rows.length) {
                html += '<tbody>\n';
                for (const row of table.rows) {
                    html += '<tr>\n';
                    row.forEach((value) => { html += cell('td', value); });
                    html += '</tr>\n';
                }
                html += '</tbody>\n';
            }
            return html + '</table>\n';
        };
        const taskInfo = (node) => taskNodes.get(node) || null;
        const currentTask = () => renderer._taskStack.length ? renderer._taskStack[renderer._taskStack.length - 1] : null;
        const writeCheckbox = (task) => {
            renderer.lit('<input type="checkbox"' + (task.checked ? ' checked' : '') + ' disabled> ');
            task.prefixRemaining = task.prefixLength;
        };
        const hasStrikeClosing = (node) => {
            for (let sibling = node && node.next; sibling; sibling = sibling.next) {
                if (sibling.type === 'text' && /~~/.test(sourceText(sibling.literal))) return true;
            }
            return false;
        };
        const renderText = (value) => {
            let text = sourceText(value);
            const task = currentTask();
            if (task && task.prefixRemaining > 0) {
                const remove = Math.min(task.prefixRemaining, text.length);
                text = text.slice(remove);
                task.prefixRemaining -= remove;
            }
            if (!text) return;
            if (renderer._linkStack.length > 0) {
                renderer.lit(escapeHtml(text));
                return;
            }
            const pattern = /~~([^~\n]+?)~~|(?:https?:\/\/|www\.)[^\s<>]+|[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+/gi;
            let cursor = 0;
            let match;
            while ((match = pattern.exec(text))) {
                const literal = match[0];
                let destination = literal;
                let consumedLength = destination.length;
                if (/^(?:https?:\/\/|www\.)/i.test(literal)) {
                    while (/[.,!?;:)]$/.test(destination)) destination = destination.slice(0, -1);
                    consumedLength = destination.length;
                }
                if (!destination) continue;
                renderer.lit(escapeHtml(text.slice(cursor, match.index)));
                if (literal.startsWith('~~') && literal.endsWith('~~')) {
                    renderer.lit('<del>' + renderInline(literal.slice(2, -2)) + '</del>');
                } else {
                    const emailLiteral = literal.includes('@') && !/^(?:https?:\/\/|www\.)/i.test(literal);
                    const href = emailLiteral ? 'mailto:' + destination
                        : /^www\./i.test(destination) ? 'https://' + destination : destination;
                    const normalized = normalizeUrl(href, 'link');
                    if (!normalized) { renderer.lit(escapeHtml(literal)); consumedLength = literal.length; }
                    else {
                        const label = escapeHtml(destination);
                        const external = normalized.external && /^https?:/i.test(normalized.value);
                        const target = external ? ' target="_blank" rel="noopener noreferrer"' : '';
                        renderer.lit('<a href="' + escapeAttribute(normalized.value) + '"' + target + '>' + label + '</a>');
                    }
                }
                cursor = match.index + consumedLength;
            }
            renderer.lit(escapeHtml(text.slice(cursor)));
        };

        renderer.text = function text(node) {
            if (this._tableParagraph || this._imageDepth > 0 || this._linkLiteralDepth > 0) return;
            const value = sourceText(node && node.literal);
            if (this._strikeDepth > 0 && value.endsWith('~~')) {
                renderText(value.slice(0, -2));
                this.lit('</del>');
                this._strikeDepth -= 1;
                return;
            }
            if (value.startsWith('~~') && (value === '~~' || !value.endsWith('~~')) && hasStrikeClosing(node)) {
                this.lit('<del>');
                this._strikeDepth += 1;
                renderText(value.slice(2));
                return;
            }
            renderText(value);
        };
        renderer.softbreak = function softbreak() {
            if (!this._tableParagraph && this._imageDepth === 0 && this._linkLiteralDepth === 0) this.lit('\n');
        };
        renderer.linebreak = function linebreak() {
            if (!this._tableParagraph && this._imageDepth === 0 && this._linkLiteralDepth === 0) { this.lit('<br />'); this.cr(); }
        };
        renderer.html_inline = function htmlInline(node) {
            if (!this._tableParagraph && this._imageDepth === 0 && this._linkLiteralDepth === 0) this.lit(escapeHtml(sourceRawHtmlLiteral(node)));
        };
        renderer.html_block = function htmlBlock(node) {
            if (!this._tableParagraph && this._imageDepth === 0 && this._linkLiteralDepth === 0) { this.cr(); this.lit(escapeHtml(sourceRawHtmlLiteral(node))); this.cr(); }
        };
        renderer.link = function link(node, entering) {
            if (this._tableParagraph || this._imageDepth > 0) return;
            if (entering) {
                const label = nodeInlineText(node);
                const literalFootnote = /^\^/.test(label);
                const normalized = literalFootnote ? null : normalizeUrl(node && node.destination, 'link');
                this._linkStack.push({ normalized, literalFootnote });
                if (literalFootnote) { this._linkLiteralDepth += 1; this.lit('[' + escapeHtml(label) + ']'); }
                else if (normalized) {
                    const external = normalized.external && /^https?:/i.test(normalized.value);
                    const target = external ? ' target="_blank" rel="noopener noreferrer"' : '';
                    this.lit('<a href="' + escapeAttribute(normalized.value) + '"' + target + '>');
                }
            } else {
                const state = this._linkStack.pop() || {};
                if (state.literalFootnote) this._linkLiteralDepth = Math.max(0, this._linkLiteralDepth - 1);
                else if (state.normalized) this.lit('</a>');
            }
        };
        renderer.image = function image(node, entering) {
            if (this._tableParagraph) return;
            if (entering) {
                const normalized = normalizeUrl(node && node.destination, 'image');
                this._imageDepth += 1;
                this._imageStack = this._imageStack || [];
                this._imageStack.push(normalized);
                if (normalized) {
                    const alt = escapeAttribute(nodeInlineText(node));
                    this.lit('<img src="' + escapeAttribute(normalized.value) + '" alt="' + alt + '">');
                }
            } else {
                this._imageDepth = Math.max(0, this._imageDepth - 1);
                this._imageStack.pop();
            }
        };
        renderer.code = function code(node) {
            if (!this._tableParagraph) this.lit('<code>' + escapeHtml(node && node.literal) + '</code>');
        };
        renderer.code_block = function codeBlock(node) {
            if (!this._tableParagraph) { this.cr(); this.lit('<pre><code>' + escapeHtml(node && node.literal) + '</code></pre>'); this.cr(); }
        };
        renderer.heading = function heading(node, entering) {
            const depth = Math.min(6, Math.max(1, Number(node && node.level) || 1));
            if (entering) { this.cr(); this.tag('h' + depth); } else { this.tag('/h' + depth); this.cr(); }
        };
        renderer.list = function list(node, entering) {
            const tag = node && node.listType === 'ordered' ? 'ol' : 'ul';
            if (entering) { this.cr(); this.tag(tag); this.cr(); } else { this.cr(); this.tag('/' + tag); this.cr(); }
        };
        renderer.item = function item(node, entering) {
            if (entering) {
                const task = taskInfo(node);
                task && (task.prefixRemaining = 0);
                this._taskStack.push(task);
                this.tag('li');
                if (task && node.parent && node.parent.listTight) writeCheckbox(task);
            } else {
                this.tag('/li'); this.cr(); this._taskStack.pop();
            }
        };
        renderer.paragraph = function paragraph(node, entering) {
            if (this._tableParagraph === node) { if (!entering) this._tableParagraph = null; return; }
            const table = entering ? tableNodes.get(node) : null;
            if (table) { this._tableParagraph = node; this.cr(); this.lit(renderTable(table)); return; }
            const list = node && node.parent && node.parent.parent;
            const tight = list && list.type === 'list' && list.listTight;
            const task = currentTask();
            if (tight) return;
            if (entering) { this.cr(); this.tag('p'); if (task) writeCheckbox(task); }
            else { this.tag('/p'); this.cr(); }
        };
        return renderer;
    }

    function configureSanitizer(instance) {
        if (!instance || typeof instance.sanitize !== 'function' || typeof instance.addHook !== 'function') {
            const error = new Error('sanitizer API unavailable'); error.code = REASONS.SANITIZER; throw error;
        }
        if (typeof instance.removeAllHooks === 'function') instance.removeAllHooks();
        instance.addHook('uponSanitizeAttribute', (node, data) => {
            const tag = node && node.nodeName ? String(node.nodeName).toLowerCase() : '';
            const name = data && data.attrName ? String(data.attrName).toLowerCase() : '';
            const value = data && data.attrValue != null ? String(data.attrValue) : '';
            if (name === 'href' && tag === 'a' && !normalizeUrl(value, 'link')) data.keepAttr = false;
            if (name === 'src' && tag === 'img' && !normalizeUrl(value, 'image')) data.keepAttr = false;
            if (name === 'target' && tag === 'a' && value !== '_blank') data.keepAttr = false;
            if (name === 'rel' && tag === 'a' && value !== 'noopener noreferrer') data.keepAttr = false;
            if (name === 'type' && tag === 'input' && value.toLowerCase() !== 'checkbox') data.keepAttr = false;
            if ((name === 'checked' || name === 'disabled') && tag !== 'input') data.keepAttr = false;
        });
        return instance;
    }
    function sanitizerInstance(module) {
        const candidate = module && module.default ? module.default : module;
        if (candidate && typeof candidate.sanitize === 'function') return candidate;
        if (typeof candidate === 'function') {
            try { const instance = candidate(global); if (instance && typeof instance.sanitize === 'function') return instance; } catch (_) { /* handled below */ }
        }
        return null;
    }
    function parserInstance(module) {
        const candidate = module && module.default ? module.default : module;
        return candidate && typeof candidate.Parser === 'function' && typeof candidate.HtmlRenderer === 'function'
            ? candidate : null;
    }
    function clearCommonmarkGlobal() {
        try { delete global.commonmark; } catch (_) { global.commonmark = undefined; }
    }
    async function loadDependencies() {
        clearCommonmarkGlobal();
        try {
            const [commonmarkModule, purifyModule] = await Promise.all([
                import('/static/vendor/commonmark/commonmark.esm.mjs'),
                import('/static/vendor/dompurify/purify.es.mjs'),
            ]);
            const commonmarkApi = parserInstance(commonmarkModule);
            if (!commonmarkApi) { const error = new Error('parser API unavailable'); error.code = REASONS.PARSER; throw error; }
            const purify = sanitizerInstance(purifyModule);
            if (!purify) { const error = new Error('sanitizer API unavailable'); error.code = REASONS.SANITIZER; throw error; }
            parser = commonmarkApi; sanitizer = configureSanitizer(purify); state = 'ready'; unavailableReason = '';
            return { status: 'ok' };
        } catch (error) {
            state = 'unavailable'; unavailableReason = error && error.code ? error.code : REASONS.ASSET;
            recordUnavailable(unavailableReason); return { status: 'fallback', reason: unavailableReason };
        } finally {
            clearCommonmarkGlobal();
        }
    }
    function render(source, _options) {
        // Surface context is accepted but cannot alter parser/sanitizer policy.
        const text = sourceText(source);
        if (state !== 'ready' || !parser || !sanitizer) return fallback(text, state === 'pending' ? REASONS.PENDING : unavailableReason);
        let html;
        try {
            const prepared = prepareGfmSource(text);
            const document = new parser.Parser().parse(prepared.source);
            html = createRenderer(parser, bindGfmNodes(document, prepared)).render(document);
            if (typeof html !== 'string') throw new Error('renderer returned non-string output');
        } catch (error) {
            recordUnavailable(REASONS.RENDER);
            return fallback(text, REASONS.RENDER);
        }
        try {
            const clean = sanitizer.sanitize(html, SANITIZE_CONFIG);
            if (clean == null) throw new Error('sanitizer returned no output');
            return { html: String(clean), status: 'ok' };
        } catch (error) {
            recordUnavailable(REASONS.SANITIZER);
            return fallback(text, REASONS.SANITIZER);
        }
    }
    const adapter = {
        dialect: 'CommonMark 0.31.2 + GFM 0.29 tables/task-list-items/strikethrough/autolink-literals',
        extensions: GFM_EXTENSIONS,
        policy: Object.freeze({
            allowedAttributes: SAFE_ATTRIBUTES,
            allowedTags: SAFE_TAGS,
            breaks: false,
            headingIds: false,
            rawHtml: 'escape',
            rawHtmlProvenance: 'ast-node-type',
        }),
        ready: loadDependencies(), render, versions: VERSION,
    };
    global.TCRTMarkdown = Object.freeze(adapter);
}(typeof window !== 'undefined' ? window : typeof globalThis !== 'undefined' ? globalThis : this));
