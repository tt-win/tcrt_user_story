/* 共用 Compact Table：可排序表格，取代卡片格線的精簡列表視圖。
   呼叫端負責提供已跳脫（escapeHtml）過的 render() 內容；本檔案只負責排序與渲染。 */
(function (global) {
    'use strict';

    function getSortState(storageKey) {
        if (!storageKey) return { field: null, dir: 'asc' };
        try {
            const raw = window.localStorage.getItem(storageKey);
            if (!raw) return { field: null, dir: 'asc' };
            const parsed = JSON.parse(raw);
            return {
                field: parsed && parsed.field ? parsed.field : null,
                dir: parsed && parsed.dir === 'desc' ? 'desc' : 'asc'
            };
        } catch (_e) {
            return { field: null, dir: 'asc' };
        }
    }

    function persistSortState(storageKey, state) {
        if (!storageKey) return;
        try {
            window.localStorage.setItem(storageKey, JSON.stringify(state));
        } catch (_e) {
            /* localStorage may be disabled; non-fatal */
        }
    }

    function compareValues(a, b) {
        if (a == null && b == null) return 0;
        if (a == null) return -1;
        if (b == null) return 1;
        if (a < b) return -1;
        if (a > b) return 1;
        return 0;
    }

    // options: { storageKey, columns: [{key, label, sortable, thClass, tdClass, stopRowClick, render(row), sortValue(row)}],
    //            rows, rowAttrs(row) -> string, emptyHtml }
    function renderCompactTable(container, options) {
        if (!container) return;
        const {
            storageKey = null,
            columns = [],
            rows = [],
            rowAttrs = null,
            emptyHtml = '',
            pin = null   // { isPinned(row), pinSortValue(row) } — pinned rows always float to top
        } = options || {};

        if (!rows.length) {
            container.innerHTML = emptyHtml;
            return;
        }

        const sortState = getSortState(storageKey);
        let sortedRows = rows;
        if (sortState.field) {
            const col = columns.find(c => c.key === sortState.field && c.sortable);
            if (col && typeof col.sortValue === 'function') {
                const dirMul = sortState.dir === 'desc' ? -1 : 1;
                sortedRows = rows.slice().sort((r1, r2) => dirMul * compareValues(col.sortValue(r1), col.sortValue(r2)));
            }
        }

        // Pinned rows always on top (by pinSortValue desc = newest created first),
        // regardless of the active column sort; the rest keep the active-sort order.
        if (pin && typeof pin.isPinned === 'function') {
            const pinned = [];
            const rest = [];
            sortedRows.forEach(r => (pin.isPinned(r) ? pinned : rest).push(r));
            if (pinned.length) {
                const pinVal = typeof pin.pinSortValue === 'function' ? pin.pinSortValue : () => 0;
                pinned.sort((a, b) => compareValues(pinVal(b), pinVal(a)));
                sortedRows = pinned.concat(rest);
            }
        }

        const theadHtml = `<tr>${columns.map(col => {
            const isActive = sortState.field === col.key;
            const arrow = isActive
                ? ` <span class="compact-table-sort-indicator">${sortState.dir === 'desc' ? '▼' : '▲'}</span>`
                : '';
            const classes = ['compact-table-th'];
            if (col.sortable) classes.push('sortable');
            if (isActive) classes.push('sorted');
            if (col.thClass) classes.push(col.thClass);
            const dataAttr = col.sortable ? ` data-sort-key="${col.key}"` : '';
            return `<th class="${classes.join(' ')}"${dataAttr}>${col.label}${arrow}</th>`;
        }).join('')}</tr>`;

        const tbodyHtml = sortedRows.map(row => {
            const attrs = typeof rowAttrs === 'function' ? (rowAttrs(row) || '') : '';
            const cells = columns.map(col => {
                const tdClass = col.tdClass ? ` class="${col.tdClass}"` : '';
                const stopClick = col.stopRowClick ? ' onclick="event.stopPropagation()"' : '';
                return `<td${tdClass}${stopClick}>${col.render(row)}</td>`;
            }).join('');
            return `<tr${attrs}>${cells}</tr>`;
        }).join('');

        container.innerHTML = `
            <div class="table-responsive compact-table-wrapper">
                <table class="compact-table">
                    <thead>${theadHtml}</thead>
                    <tbody>${tbodyHtml}</tbody>
                </table>
            </div>
        `;

        container.querySelectorAll('th.sortable').forEach(th => {
            th.addEventListener('click', () => {
                const field = th.getAttribute('data-sort-key');
                const next = {
                    field,
                    dir: (sortState.field === field && sortState.dir === 'asc') ? 'desc' : 'asc'
                };
                persistSortState(storageKey, next);
                renderCompactTable(container, options);
            });
        });

        // .table-responsive's overflow-x:auto forces overflow-y:auto too (CSS spec), which
        // clips dropdown-menus that would otherwise overflow below the table. Popper's
        // 'fixed' strategy positions the menu relative to the viewport instead, escaping it.
        if (window.bootstrap && window.bootstrap.Dropdown) {
            container.querySelectorAll('[data-bs-toggle="dropdown"]').forEach(toggleEl => {
                new window.bootstrap.Dropdown(toggleEl, {
                    popperConfig: (defaultConfig) => Object.assign({}, defaultConfig, { strategy: 'fixed' })
                });
            });
        }

        if (window.i18n && typeof window.i18n.isReady === 'function' && window.i18n.isReady()) {
            window.i18n.retranslate(container);
        }
    }

    global.renderCompactTable = renderCompactTable;
})(window);
