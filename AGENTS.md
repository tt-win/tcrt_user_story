# TCRT Project Agent Supplement

最後整理日期：2026-07-27

本檔是 `tcrt_user_story` 的專案層補充。先遵守全域 `AGENTS.md` / `CLAUDE.md` / `QWEN.md` / `GEMINI.md` / Copilot 類指令；本檔只記錄這個 repo 的特殊約束。若有衝突，資料安全、秘密保護、破壞性動作核准與使用者最新指示優先。

---

## 專案輪廓

- TCRT 是測試案例、Test Run、User Story Map、Automation Hub、QA AI Helper 與 Jira/Lark/LLM 整合的 FastAPI 系統。
- 後端主要是 Python 3.10+、FastAPI、Pydantic 2、SQLAlchemy 2 async、Alembic、Casbin、pytest；套件管理以 `uv` 與 `uv.lock` 為準。
- 前端是 Jinja2 模板、Bootstrap 5 CDN、原生 JS/CSS 與 `app/static/locales/` i18n；`package.json` 只提供 stylelint / template guard，不是前端 build pipeline。
- 資料庫支援 SQLite、本機/容器 MySQL 8、PostgreSQL 16。不要寫只在單一引擎可用的 SQL，除非該路徑明確限定引擎並有測試。

## 重要入口

- App 啟動：`app/main.py`
- Router 組裝：`app/api/__init__.py`
- API：`app/api/`
- 服務層：`app/services/`
- ORM / schema：`app/models/`
- 顯式 DB access boundary：`app/db_access/`
- Audit 模組：`app/audit/`
- 模板與元件：`app/templates/`、`app/templates/components/`
- 靜態資產與三語系：`app/static/js/`、`app/static/css/`、`app/static/locales/`
- 測試：`app/testsuite/`
- OpenSpec：`openspec/project.md`、`openspec/specs/`、`openspec/changes/`
- 對外 automation skill：`tools/skills/tcrt-automation-pomify/`
- 共用元件規範視覺參考：`mock.html`（project root）

## 變更流程補充

- 行為、API contract、schema、權限、安全、跨模組流程、使用者可見 UX 的變更，先檢查 `openspec/project.md` 與相關 `openspec/specs/`；若需要新契約，先建立或更新 `openspec/changes/<change>/` 工件再實作。
- 純文字修正、小型內部重構或只補 agent 文件時，不必硬開 OpenSpec change，但仍要確認沒有打破現有 spec 描述。
- 修改 Automation Hub、QA AI Helper、Test Run、i18n、DB boundary 等共享行為時，先找既有測試與 spec；不要只靠頁面手測。
- 如果同一規則同時存在於 `docs/`、`manual/`、`openspec/`、`tools/skills/`，修改行為時要同步更新相關文件，不要只更新程式碼。

## 資料庫與資料安全

- 本專案有三組 Alembic migration：
  - main：`alembic.ini` + `alembic/`
  - audit：`alembic_audit.ini` + `alembic_audit/`
  - usm：`alembic_usm.ini` + `alembic_usm/`
- 新增/修改 schema 必須放到正確 migration 目錄，並檢查 `database_init.py`、bootstrap、測試 fixture 與跨引擎相容性。
- Web runtime 優先使用 async session 與 `app/db_access/` boundary；同步 DB engine 只應用於 migration/bootstrap 等明確場景，`ALLOW_SYNC_DB_RUNTIME` 不可當成一般 runtime 解法。
- 不要隨意讀取、改寫或提交本機 `*.db`、`*.sqlite3`、`generated_report/`、`attachments/`、`keys/`、`config.yaml`、`.env*`。需要碰真實或疑似真實資料時，先說明風險與回滾方案。
- `AUTOMATION_PROVIDER_ENCRYPTION_KEY`、Jira/Lark/OpenRouter/GitHub/Jenkins/Allure credentials 都只能走 env/config；不要硬編碼、輸出或寫進測試 snapshot。

---

## 前端與 i18n

- 新頁面或改版**必須**沿用 `app/templates/base.html` 的 block、`app/templates/components/` 元件、以及下方「共用元件規範」的 canonical class 結構。
- HTML 留在 `app/templates/`，JS/CSS 放在 `app/static/js/`、`app/static/css/`；**禁止**在模板中新增 inline `style=`（受 `scripts/check-inline-styles.mjs` 護欄約束）。
- CSS **必須**使用 design token（`var(--tr-*)` 或 `var(--color-*)`）；`:root` 以外的 raw hex 會被 stylelint 攔截。
- 所有使用者可見新文案同步更新 `app/static/locales/en-US.json`、`zh-CN.json`、`zh-TW.json`。
- 動態 DOM 要使用既有 i18n lifecycle：`data-i18n`、`data-i18n-placeholder`、`data-i18n-title`、`data-i18n-params`，必要時呼叫 `window.i18n.retranslate(...)`，並注意 `i18nReady` / `languageChanged`。
- **禁止**在 DOM 中用 `d-none` div 隱藏 i18n 字串（`organization_management.html` 的 anti-pattern）；i18n 文字只能在 locale JSON 定義。

---

## 共用元件規範 (Mandatory Component Specifications)

以下規範是**強制條款**，不是建議。違反任一規則會被 component spec test 或 lint 攔截，阻止 merge。
Canonical 參考渲染在 `mock.html`。重構計劃見 `REFACTOR_PLAN.md`。

### SPEC-BTN-001 · Button System

| Rule | Detail |
|------|--------|
| Class order | `btn btn-{variant} btn-sm` — variant before size, always. **Never** `btn btn-sm btn-{variant}`. |
| Icon placement | Icon before text with `me-1`: `<i class="fas fa-plus me-1"></i> 新增` |
| Semantic mapping | `btn-primary`=create/save · `btn-secondary`=cancel/back · `btn-success`=confirm/apply · `btn-danger`=delete · `btn-info`=auxiliary/info only · `btn-warning`=caution action |
| Forbidden classes | `btn-xs`, `btn-view`, `btn-edit`, `test-run-kebab-btn` — remove on sight, replace with standard variant. |
| Forbidden inline overrides | `style="border:none;background:none"` on buttons — use `btn-link btn-sm p-0` instead. |
| Toolbar buttons | Always `btn-sm`. Modal body buttons may use standard `btn` (no size class). |
| `btn-info` semantics | Used ONLY for genuinely informational/auxiliary actions. Dropdown triggers use `btn-secondary`. |

### SPEC-BDG-001 · Badge

| Rule | Detail |
|------|--------|
| Color convention | Use `bg-{semantic}`. **Never** Bootstrap 5.3 `text-bg-*` (not adopted project-wide). |
| Test status mapping | `bg-success`=Passed · `bg-danger`=Failed · `bg-secondary`=Pending · `bg-warning`=Blocked · `bg-info`=Retest |
| Count badges | `bg-secondary`, `font-size: 0.65rem`, `padding: 0.125rem 0.35rem`. |
| Bare badges forbidden | `<span class="badge">` without `bg-*` is invalid. Always add a background. |
| Multi-class combos forbidden | No `bg-info-subtle text-info-emphasis border border-info-subtle`. Use `bg-info`. |
| Tags (TCG) | Use `tcg-tag` class (monospace, bordered pill), NOT `badge`. |
| Custom badge classes | `badge-role` and similar page-specific badge classes are removed. Use `bg-primary` or `bg-secondary`. |

### SPEC-TBL-001 · Table

| Rule | Detail |
|------|--------|
| Standard classes | `table table-sm table-hover align-middle mb-0` — all four, always. |
| Header style | White background (no `table-light`). Uppercase, `letter-spacing: 0.04em`, `font-size: 0.7rem`, bottom border `2px solid var(--tr-border)`. |
| Vertical borders | None. Only horizontal `border-bottom: 1px solid var(--tr-border-light)` between rows. |
| Hover | `rgba(74, 144, 226, 0.04)` (primary at 4% opacity). Not `var(--tr-bg-sidebar)`. |
| Sticky header | Add `sticky-top` to `<thead>` when table height exceeds viewport (automation tables, audit logs). |
| `table-sm` mandatory | All tables include `table-sm`. No full-padding tables. |
| `table-hover` mandatory | All data tables include `table-hover`. |
| Last row | No bottom border on the last `<tr>` (`border-bottom: none`). |
| Tags in cells | Use `tcg-tag` class, not `badge`. |

### SPEC-MDL-001 · Modal

| Rule | Detail |
|------|--------|
| Sizing | Use Bootstrap classes only: `modal-sm` / default / `modal-lg` / `modal-xl` + optional `modal-dialog-scrollable`. |
| Inline size override forbidden | `style="width:1400px;height:90vh"` on `.modal-dialog` is banned. Use `modal-xl` or a custom CSS class in `style.css`. |
| Header structure | `<h5 class="modal-title">` (optional icon with `text-primary me-2` or `text-warning me-2`) + `<button class="btn-close">`. Nothing else in the header. |
| Header background | No `bg-light`, `bg-danger`, or `text-white` on `.modal-header`. Header uses default (white) background. |
| Navigation buttons in header forbidden | Prev/next/copy buttons go in a sub-toolbar inside `modal-body`, never in `modal-header`. |
| Footer button order | Left→right: `btn-secondary` (cancel) → `btn-primary` or `btn-danger` (confirm/delete). |
| Footer third button | Left-aligned with `me-auto`: `btn-outline-danger me-auto` (clear/reset) or `btn-outline-primary me-auto` (edit). |
| Footer `bg-light` forbidden | Modal-footer uses default background. |

### SPEC-CRD-001 · Card

| Rule | Detail |
|------|--------|
| Header classes | `card-header bg-light d-flex align-items-center justify-content-between flex-wrap gap-2` |
| Header title | `<h6 class="mb-0">` — no `fw-bold` (inherited from card-header). |
| Body padding | `0.75rem` (enforced by style.css). Do not override with `p-0`, `p-2`, or `p-4` unless the card contains a table/chart that needs edge-flush content (add a comment explaining why). |

### SPEC-TLB-001 · Page Toolbar

| Rule | Detail |
|------|--------|
| Wrapper | `<div class="d-flex gap-2 align-items-center">` — always. |
| Spacing | `gap-2` only. Never `gap-3` or custom margin-based spacing. |
| Custom toolbar classes forbidden | `automation-toolbar`, `automation-toolbar-divider` — replace with standard `d-flex gap-2` + `<div class="vr mx-1">`. |
| Button order (left→right) | Page primary action (`btn-primary`) → auxiliary dropdown (`btn-secondary dropdown-toggle`) → refresh (`btn-secondary`) → home (`btn-secondary`). |

### SPEC-TAB-001 · Tab Navigation

| Rule | Detail |
|------|--------|
| Tab style | `nav nav-tabs` only. **Never** `nav-pills` (not even for sub-tabs within the same page). |
| Spacing | `mb-3` on the `<ul>`. Never `mb-2`. |
| Icons | Every tab button has an icon: `<i class="fas fa-{icon} me-1"></i>`. No tab without an icon. |
| Custom tab classes | Remove `automation-tabs` and similar. Standard `nav nav-tabs` + global CSS only. |
| Pane classes | First: `tab-pane fade show active`. Others: `tab-pane fade`. |

### SPEC-DRP-001 · Dropdown

| Rule | Detail |
|------|--------|
| Trigger class | `btn btn-secondary btn-sm dropdown-toggle` — always for toolbar dropdowns. Never `btn-info`. |
| Custom dropdowns forbidden | `custom-status-dropdown`, `custom-status-dropdown-overlay` — replace with Bootstrap `dropdown` component. |
| Menu gap | `margin-top: 5px` on `.dropdown-menu` (enforced by global CSS). |
| Icon alignment | Dropdown item icons get `me-2`; global CSS enforces `i { width:16px; text-align:center }` within `.dropdown-item`. |
| Kebab buttons | Use `btn btn-secondary btn-sm` + `<i class="fas fa-ellipsis-v">`. Remove `test-run-kebab-btn`. |

### SPEC-HOM-001 · Home Button

| Rule | Detail |
|------|--------|
| Label | `回到首頁` — always. Never `首頁` or `Home`. |
| Class | `btn btn-secondary btn-sm` — always (variant before size). |
| Structure | `<a href="/" class="btn btn-secondary btn-sm"><i class="fas fa-home me-1"></i> 回到首頁</a>` |
| Single line | Icon and text on the same line. No line breaks. |

### SPEC-AI-001 · AI Assistant Surfaces

| Rule | Detail |
|------|--------|
| FAB | 52px circle, `linear-gradient(135deg, var(--tr-primary), var(--tr-primary-dark))`, white icon, `box-shadow: 0 4px 14px rgba(primary-rgb,.45)`. |
| Panel header | Same gradient, white text, 28×28 icon buttons with `rgba(255,255,255,.18)` hover. |
| User bubble | `background: var(--tr-primary); color: #fff; border-radius: 14px 14px 5px 14px`. |
| AI bubble | `background: #fff; border: 1px solid var(--tr-border-light); border-radius: 14px 14px 14px 5px; box-shadow: var(--tr-shadow-sm)`. |
| Tool activity | `<details>` accordion, `background: var(--tr-bg-sidebar)`, `border-radius: 10px`. |
| Confirm card | Left border `3-4px solid` (primary or warning), `border-radius: 10px`. |
| Composer | Textarea `border-radius: 10px` + circular send button 38px. |
| Assistant buttons | Use `tcrt-assistant-btn-*` series (not Bootstrap `.btn`) inside AI panels — intentionally different radius/padding. |
| All AI surfaces | QA AI Helper, inline AI Assist modal, and global assistant widget share the same bubble/card/tool-activity styles. |

---

## 入口結構規則

### SPEC-NAV-001 · Navigation Consolidation

以下是目前允許的結構性變更方針（逐步實施中，見 `REFACTOR_PLAN.md`）：

1. **移除 team_management 的 data menu dropdown。** `team_management.html` 的 `btn-info dropdown`（含 audit-logs / team-statistics / system-links 連結）移除。這些連結改由 header 的「管理」dropdown 統一入口。
2. **在 `base.html` header 新增 Admin dropdown。** 一個 `btn btn-secondary btn-sm dropdown-toggle` 標籤為 `管理`，加在 `page_actions` block 中，所有已認證頁面可見。內容分兩區：組織（團隊管理、組織設定）、系統（稽核日誌、系統日誌、統計分析）。Dropdown 遵循 Casbin RBAC。
3. **Automation 子頁面：保持路由，統一 breadcrumb。** `/automation-provider-settings` 和 `/automation-webhook-config` 維持獨立路由。頁首改用 breadcrumb（`Automation Hub › Provider Settings`）取代「Back to Hub」按鈕。
4. **Home 按鈕統一。** 依 SPEC-HOM-001 統一全站文案與 class。

---

## 頁面設計品質規範

除了共用元件 SPEC 外，以下頁面有不合理的設計或編排問題，需在重構中一併修正。
所有修正**不改變頁面功能**，只改善視覺品質與 SaaS 慣例一致性。

### system_logs.html — 系統日誌（4 tab 頁面）

| 問題 | 修正 |
|------|------|
| 4 個 tab 按鈕全缺圖示 | 全部加上 `fas fa-*` 圖示（Logs=terminal, Runtime=cog, KG=project-diagram, KQL=search） |
| `<ul>` 用 `mb-2` | 改為 `mb-3` |
| Runtime Settings tab 用裸 `<dl>` definition list | 改為 card-based key-value grid（每組設定一個小 card，label + value 水平排列，不用 `<dl>`） |
| Knowledge Graph tab 同樣用 `<dl>` | 同上，改為 card-based 佈局 |
| 3 個 inner table 缺 `table-hover` | 全部加上 `table-hover` |
| KQL table 有 9 欄太密集 | 精簡為 6 欄（時間、來源、操作、狀態、查詢摘要、耗時），其餘欄位改為 row expansion |
| Log output `#logOutput` 無 card-body 包裹 | 加 card-body，並用 terminal 風格的深色或淺灰背景 + monospace |
| Filter toolbar 用 `log-toolbar-item` 自訂 class | 改用標準 `d-flex gap-2 flex-wrap` + Bootstrap form-control/form-select |

### first_login_setup.html — 首次登入設定

| 問題 | 修正 |
|------|------|
| Header 漸層用黃色 warning 色 (`--tr-warning` → `#FACC15`) | 改用與 system_setup 一致的藍色漸層 `linear-gradient(135deg, var(--tr-primary), var(--tr-primary-dark))` |
| 全頁 fallback 文案是英文 | 全部改為 zh-TW fallback |
| 無密碼強度即時驗證 | 加入與 profile.html 一致的 real-time strength indicator（green check 動態切換） |
| Submit 按鈕用 `btn-success` | 改為 `btn-primary`（設定密碼是 primary action） |
| Back to login 用 `text-muted` 文字連結 | 改為 `btn btn-secondary btn-sm` |

### system_setup.html + system_setup_standalone.html — 系統初始化

| 問題 | 修正 |
|------|------|
| 兩份近乎相同的模板 | 合併為單一 template，以 `bootstrap` flag 控制是否載入完整 framework |
| `onclick="togglePassword()"` inline JS | 改用 `addEventListener` |
| 無 loading state 的 submit 按鈕 | 加上 disabled + spinner |
| 安全注意事項在 submit 按鈕下方 | 移至表單欄位上方或 inline |

### audit_logs.html — 稽核日誌

| 問題 | 修正 |
|------|------|
| 缺 `table-sm` + `align-middle` | 加上 |
| `<thead>` 用 `table-light` | 移除（SPEC-TBL-001 改為白底） |
| Home 按鈕文案 `首頁` | 改為 `回到首頁` |
| 無 sticky header（9 欄表格超出 viewport） | 加 `sticky-top` |
| Filter sidebar 固定 320px 太寬 | 改為 collapsible top filter bar（chip/tag 風格）或縮窄至 240px |
| 無載入計數指示 | 在 footer 加 "顯示 X / Y 筆" |

### organization_management.html — 組織管理

| 問題 | 修正 |
|------|------|
| **118 個 i18n 字串隱藏在 `d-none` div 中**（L733-854） | 全部移至 locale JSON，JS 改用 `window.i18n.t()` |
| 多處 inline `style="display:none"` | 改用 `d-none` class |
| MCP Token table 缺 `table-hover` | 加上 |
| `text-bg-secondary` badge（L269） | 改為 `bg-secondary` |
| Org sync 按鈕缺 `btn-sm`（L247-255） | 加上 |
| Lark search dropdown 用 inline style 定位 | 改用 CSS class + Bootstrap dropdown |
| 副標題列出了所有功能（像目錄） | 簡化為「組織與系統設定」 |

### team_statistics.html — 團隊統計

| 問題 | 修正 |
|------|------|
| 7 個主 tab + 7 個 QA AI 子 pill = 14 個導覽區塊 | QA AI Agent 分析拆為獨立路由 `/qa-ai-analytics` 或獨立子頁面 |
| 子 tab 用 `nav nav-pills` | 改為 `nav nav-tabs`（SPEC-TAB-001） |
| 工具列 3 個按鈕 class 順序錯（`btn btn-sm btn-secondary`） | 改為 `btn btn-secondary btn-sm` |
| Refresh 按鈕 icon 缺 `me-1` | 加上 |
| 已註解掉的「Department Stats」tab 死碼 | 移除 |
| KPI card-body 用 `py-2` 覆蓋 padding | 加註釋或改用 CSS class |

### test_case_reference.html — 參考測試案例

| 問題 | 修正 |
|------|------|
| 全頁大量 inline `style` | 全部改用 CSS class |
| 左面板固定 `width: 400px` | 改用 `col-4` / CSS flex 比例 |
| `calc(100vh - 160px)` magic number | 改用 `calc(100vh - var(--header-height) - var(--footer-height))` |
| iframe 缺 `title` 屬性 | 加上無障礙 title |
| 無 responsive breakpoint | 加 `@media (max-width: 768px)` 改為單欄堆疊 |
| `body.popup-minimal` class 由 JS 注入 | 改為 template 層級控制 |

### profile.html — 個人資料

| 問題 | 修正 |
|------|------|
| `badge-role` 自訂 class（L47） | 改為 `badge bg-primary` |
| profile.css 有 12+ 處 hardcoded hex | 全部改用 `var(--tr-*)` token |
| Save profile 用 `btn-success` | 改為 `btn-primary` |
| Change password 用 `btn-warning` | 改為 `btn-primary` |
| Password toggle 用 `btn-secondary` | 改為 `btn-link btn-sm p-0` |
| Avatar img 有 inline style | 改用 CSS class |

---

## 重構工作流程

1. **一個 SPEC 一個 branch。** 每個 branch 處理一個 SPEC 的一部分（或一個頁面的多項修正），保持 diff 可審查、可回滾。
2. **先讀現況。** 修改模板前，先讀當前版本的結構與行為。
3. **保留 Jinja logic。** `{% %}` / `{{ }}` / `{% if %}` / `{% for %}` 必須原樣保留。只改 HTML/CSS class 結構。
4. **保留 data attributes。** JS 依賴的所有 `data-*` 屬性（`data-i18n`、`data-bs-toggle`、`data-field`、`data-role` 等）必須原樣保留。
5. **每頁改完跑測試：**
   ```bash
   uv run pytest app/testsuite/test_component_spec.py -k "<page_name>" -q
   npm run lint
   ```
6. **Commit message 格式。** `refactor(spec-{ID}): <description>`

---

## 前端測試需求

每個重構後的模板必須有對應的 component spec test，驗證 rendered HTML 符合 canonical 結構：

```python
# app/testsuite/test_component_spec.py
# Example: verify table classes
def test_audit_logs_table_has_canonical_classes():
    """SPEC-TBL-001: audit_logs table must use standard classes."""
    html = render_template("audit_logs.html")
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", class_="table")
    classes = table.get("class", [])
    assert "table-sm" in classes
    assert "table-hover" in classes
    assert "align-middle" in classes
```

| SPEC | 測試驗證項目 |
|------|------------|
| SPEC-BTN-001 | 任何 rendered template 中不含 `btn-xs`, `btn-view`, `btn-edit` |
| SPEC-BDG-001 | 任何 rendered template 中不含 `text-bg-*`、裸 `badge` 無 `bg-*`、`badge-role` |
| SPEC-TBL-001 | 所有 `<table class="table">` 有 `table-sm table-hover align-middle`；`<thead>` 無 `table-light` |
| SPEC-MDL-001 | `.modal-dialog` 無 `style=`；`.modal-header` 無 `bg-light`/`bg-danger` |
| SPEC-CRD-001 | 所有 `.card-header` 有 `bg-light d-flex align-items-center justify-content-between` |
| SPEC-TLB-001 | 任何 template 中不含 `automation-toolbar` class |
| SPEC-TAB-001 | 任何 template 中不含 `nav-pills`；所有 `nav nav-tabs` 有 `mb-3` |
| SPEC-DRP-001 | 任何 template 中不含 `custom-status-dropdown`；不含 `btn-info dropdown-toggle` |
| SPEC-HOM-001 | 所有 home link 文案為 `回到首頁`；class 順序為 `btn btn-secondary btn-sm` |
| SPEC-NAV-001 | `base.html` render 出 Admin dropdown；`team_management.html` 無 data menu |

### Lint gates（繼承自 v1）

```bash
npm run lint          # stylelint + inline-style checker
npm run lint:css      # CSS only
npm run lint:templates # inline style only
```

---

## Automation Hub 特別約束

- Provider credentials 與 environment variables 可能被 AES-256-GCM 加密保存；不要繞過 service 或直接明文落檔。
- script 掃描、`script_format` 推斷、include/exclude glob、`tcrt-automation.yml`、Suite CI job 命名、webhook、Allure/Jenkins/GitHub provider 行為，都要對照 `openspec/specs/automation-hub-*`。
- script 與 manual test case 的關聯以 marker-derived link 為主要真相來源：Python `@pytest.mark.tcrt(...)`，JS/TS `// tcrt:`；`created_by="marker-sync"`、`ai-suggest:<id>`、`PRIMARY` / `COVERS` / `REFERENCES` 行為不可任意改。
- 任何 marker grammar、掃描分類、命名規則或 template set 改動，必須同步更新 `tools/skills/tcrt-automation-pomify/`，尤其 `SKILL.md`、`references/tcrt-format-rules.md`、`references/framework-detection.md` 與相關 templates。

## QA AI Helper 與整合

- QA AI Helper 跨 API、service、planner、prompt、runtime、metrics 與 team analytics；修改前先查 `app/services/qa_ai_helper*`、`app/services/test_case_helper/` 與對應 tests。
- OpenRouter/LLM 設定只能透過現有 config/env 路徑。缺少必要設定時應 fail fast 或回報待設定，不要塞不安全預設值。
- Jira/Lark/MCP 相關改動要檢查權限、audit、team scope 與 token/machine auth 測試。

---

## 驗證指令

- 後端目標測試優先：`uv run pytest app/testsuite/<target> -q`
- 後端全套：`uv run pytest app/testsuite -q`
- 前端 component spec：`uv run pytest app/testsuite/test_component_spec.py -q`
- Ruff：`uv run ruff check app scripts database_init.py`
- 前端 lint：`npm run lint`
- i18n coverage：`node scripts/check-i18n-coverage.mjs`
- 修改 JS 時至少跑對應 `node --check app/static/js/<file>.js`
- OpenSpec 變更完成前跑 `openspec validate <change> --strict`
- DB/bootstrap 相關變更需用 disposable DB 或測試 fixture 驗證；不要拿本機真實 DB 當唯一驗證。

---

## 不要踩的坑

- 不要引入第二套 package manager 或前端 bundler。
- 不要把 Jinja 頁面改成需要 build 才能跑的前端架構。
- 不要直接繞過 `app/db_access/` 在任意服務中新增裸 session/query pattern。
- 不要把 Automation Hub 的人工 link write API 加回來；現況已收斂到 marker-derived 與 AI suggestion acceptance 流程。
- 不要清理 `.opencode/`、`.antigravitycli/`、`.playwright-mcp/`、`.serena/`、`.spectra/`、`.tmp/` 等本機工具狀態，除非任務明確要求。
- 不要在 DOM 中用 `d-none` div 隱藏 i18n 字串 — i18n 文字只能在 locale JSON 定義。
- 不要在 `:root` 以外使用 raw hex — 一律用 `var(--tr-*)` / `var(--color-*)` token。
- 不要在模板中使用 inline `style=` — 受 `scripts/check-inline-styles.mjs` 護欄約束。
- 不要使用 `text-bg-*`（Bootstrap 5.3 新語法）— 全站統一用 `bg-*`。

---

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

When the user types `/graphify`, use the installed graphify skill or instructions before doing anything else.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- Dirty graphify-out/ files are expected after hooks or incremental updates; dirty graph files are not a reason to skip graphify. Only skip graphify if the task is about stale or incorrect graph output, or the user explicitly says not to use it.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).
