# UI 元件庫（Jinja macros）

可重用的 Jinja macro，提供跨頁一致的 UI 結構與樣式，避免各頁手刻、重複的 markup。
全部對齊 Bootstrap 5 與 `app/static/css/style.css` 的 design token；**不含 inline `style=`**
（受 `npm run lint:templates` 護欄約束）。

| 元件 | 檔案 | macro | 用途 |
|------|------|-------|------|
| 按鈕 | `button.html` | `button(intent, size, label, label_i18n, icon, type, outline, extra_classes, attrs)` | 統一按鈕與語意色 |
| 對話框 | `modal.html` | `modal(id, title, title_i18n, size, footer, scrollable)`（用 `{% call %}` 注入 body） | 統一 modal 結構 |
| 表格 | `data_table.html` | `data_table(columns, id, extra_classes, striped)` | 統一表格容器（資料常由 JS 填入） |
| 操作列 | `toolbar.html` | `toolbar(title, title_i18n, subtitle)`（用 `{% call %}` 注入操作鈕） | 統一頁面標題＋操作列 |
| 狀態標籤 | `status_badge.html` | `status_badge(text, variant, size, pill, extra_classes)` | 既有狀態徽章 |

## 用法

```jinja
{% from 'components/button.html' import button %}
{% from 'components/modal.html' import modal %}
{% from 'components/toolbar.html' import toolbar %}

{% call toolbar(title='測試案例', title_i18n='testCase.title') %}
  {{ button(intent='primary', label='新增', label_i18n='common.add', icon='bi bi-plus',
            attrs={'data-bs-toggle': 'modal', 'data-bs-target': '#create-tc'}) }}
{% endcall %}

{% call modal(id='create-tc', title='新增測試案例', title_i18n='testCase.create', size='lg') %}
  <form id="create-tc-form"> ... </form>
{% endcall %}
```

## 約定

- 新頁面／新元件**優先使用本元件庫**，勿再手刻 modal/按鈕/表格樣式或新增 inline `style=`。
- macro 輸出契約（class 結構、語意色對映）為穩定介面；調整時需同步本 README。
- 文案請用 `*_i18n` 參數掛 `data-i18n`，交由 client-side i18n 翻譯（見 i18n change）。
