## Why

`ui-design-system` 已建立 design token 層、stylelint 護欄與 Jinja macro 元件庫，但**頁面層級的視覺與結構發散尚未收斂**：`AGENTS.md` 列出的 SPEC-BTN/BDG/TBL/MDL/CRD/TLB/TAB/DRP/HOM/NAV/AI 在 18 個頁面上仍普遍違反——`btn-xs`/`btn-view`/`btn-edit`/`test-run-kebab-btn` 等非標準類別、`text-bg-*` 與裸 badge、`nav-pills`、`automation-toolbar`、custom dropdown、modal-header 上不該有的導覽按鈕、inline `style=` 覆寫 modal 尺寸、118 條 i18n 字串藏在 `d-none` div 等反模式，目前**完全沒有自動化測試攔截**。本變更補上 `test_component_spec.py` 機械護欄，並依 `REFACTOR_PLAN.md` Phase 0–16 逐頁掃到符合 SPEC，使 spec 從「文件」變成「會 fail 的測試」。

## What Changes

**Phase 0｜測試鷹架**
- 新增 `app/testsuite/test_component_spec.py`：以 TestClient + BeautifulSoup 渲染全部頁面路由，逐 SPEC 機械檢查 rendered HTML（按鈕類別、badge、table、modal、card、tab、toolbar、dropdown、home button、nav）。
- 對當前已違反的檢查標記 `xfail` 作為追蹤基線，後續 phase 修正後逐一移除。

**Phase 1–8｜逐 SPEC 全站清掃（純呈現層）**
- Phase 1：`style.css` 全域 table header/border/hover 與 dropdown gap/icon 對齊（零模板更動）。
- Phase 2：SPEC-HOM-001 全站 15 頁 Home 按鈕統一為 `回到首頁` + `btn btn-secondary btn-sm`。
- Phase 3：SPEC-BTN-001 移除 `btn-xs`/`btn-view`/`btn-edit`/`test-run-kebab-btn`，修正 `btn btn-sm btn-{variant}` → `btn btn-{variant} btn-sm` 類別順序，`btn-info` dropdown 觸發 → `btn-secondary`。
- Phase 4：SPEC-BDG-001 `text-bg-*` → `bg-*`、裸 badge 補 `bg-*`、多類別組合簡化、`badge-role` → `badge bg-primary`。
- Phase 5：SPEC-TAB-001 `nav-pills` → `nav nav-tabs`、`mb-2` → `mb-3`、tab 按鈕補圖示、移除 `automation-tabs`。
- Phase 6：SPEC-TLB-001 `automation-toolbar` → `d-flex gap-2` + `<div class="vr mx-1">`；SPEC-DRP-001 `custom-status-dropdown` → Bootstrap dropdown。
- Phase 7：SPEC-MDL-001 modal-dialog inline `style=` → CSS class；modal-header 導覽按鈕搬到 modal-body 子工具列；移除 modal-header/footer 的 `bg-light`/`bg-danger`；修正 footer 按鈕順序。
- Phase 8：SPEC-CRD-001 card-header 統一為 `bg-light d-flex align-items-center justify-content-between flex-wrap gap-2`。

**Phase 9–13｜頁面品質修正（仍純呈現層，不變功能）**
- Phase 9：system_logs 重設計（tab 圖示、`<dl>` → card grid、log output terminal 風格、KQL 表精簡為 6 欄）。
- Phase 10：first_login_setup 黃色漸層 → 藍色、即時密碼強度驗證、`btn-success` → `btn-primary`；合併 system_setup 雙模板、inline `onclick` → addEventListener、submit 加 spinner。
- Phase 11：organization_management 把 118 條 `d-none` i18n 字串遷移到 locale JSON、JS 改用 `window.i18n.t()`；inline `style="display:none"` → `d-none`；MCP Token 表加 `table-hover`。
- Phase 12：team_statistics `nav-pills` → `nav nav-tabs`、工具列按鈕類別順序、移除死碼。
- Phase 13：audit_logs（`table-sm`/`align-middle`/移除 `table-light`/`sticky-top`/計數）、test_case_reference（inline style → class、響應式）、profile（`badge-role` → `bg-primary`、profile.css 12+ hex → token、按鈕語意）。

**Phase 14–15｜入口與 AI 表面**
- Phase 14：SPEC-NAV-001 在 `base.html` header 新增「管理」dropdown（Casbin RBAC），移除 team_management 的 `btn-info` data menu；automation 子頁改 breadcrumb。
- Phase 15：SPEC-AI-001 抽出共用 AI 表面 CSS（`.ai-bubble-user`/`.ai-bubble-assistant`/`.ai-tool-activity`/`.ai-confirm-card`），QA AI Helper 與 inline AI Assist 改用共用類別。

**Phase 16｜驗證收尾**
- 全套 `uv run pytest app/testsuite -q` 100% green（無 `xfail` 殘留）、`npm run lint` 零違規、i18n coverage 通過、清理 dead CSS、同步更新 `openspec/specs/ui-design-system/spec.md`。

**非目標（Non-Goals）**
- 不變更任何後端行為、API contract、schema、權限邏輯（`app/api/`/`app/auth/`/`app/models/`/`app/services/`/`app/audit/`/`app/db_access/`/`alembic*` 全程唯讀）。
- 不改變任何 JS 行為或 API 呼叫；JS 僅允許更新選擇器／類別參考以對齊新 HTML 結構。
- 不做視覺改版；保留既有 TCRT/TestRail 外觀，僅做一致性收斂。
- 不導入前端 build pipeline、不引進第二套 package manager。
- 不改變 Jinja 邏輯（`{% %}`/`{{ }}`）與 JS 依賴的 `data-*` 屬性。

## Capabilities

### New Capabilities
<!-- 無新增 capability；本變更擴充既有 ui-design-system。 -->

### Modified Capabilities
- `ui-design-system`: 在既有按鈕視覺系統、token、macro 元件庫之上，新增「全頁面元件規格強制（component-spec enforcement across all pages）」需求——以 `test_component_spec.py` 機械檢查 rendered HTML，使 SPEC-BTN/BDG/TBL/MDL/CRD/TLB/TAB/DRP/HOM/NAV/AI 從文件變成會 fail 的測試；並補上 modal 結構規範（無 inline size、header 結構、footer 按鈕順序）、card-header 標準類別、tab 圖示、toolbar 標準排版、dropdown 標準觸發、home 按鈕全站統一、入口 Admin dropdown 整併、AI 表面共用樣式等頁面層級需求。

## Impact

- **前端模板（`app/templates/`）**：全部 18 個頁面模板與 `base.html` 依各 phase 修正類別順序、移除非標準類別、搬移 modal 按鈕、補 tab 圖示。Jinja 邏輯與 `data-*` 屬性原樣保留。
- **前端 CSS（`app/static/css/`）**：`style.css` 全域 table/dropdown 規則；新增 `modal-tc-editor` 等取代 inline size 的 class；`first-login-setup.css`/`profile.css`/`test-case-reference.css` 等 token 化與響應式；`automation-hub.css` 移除 `automation-toolbar` 死碼。
- **前端 JS（`app/static/js/`）**：選擇器與類別參考對齊新 HTML（如 modal-header 按鈕搬到 modal-body、`custom-status-dropdown` 改 Bootstrap dropdown、`nav-pills` 改 `nav-tabs`、org_management i18n 改 `window.i18n.t()`）。行為與 API 呼叫不變。
- **i18n（`app/static/locales/`）**：`en-US.json`/`zh-CN.json`/`zh-TW.json` 新增 organization_management 遷出的 118 條字串與 first_login_setup zh-TW fallback。
- **測試（`app/testsuite/`）**：新增 `test_component_spec.py`；既有測試不受影響。
- **OpenSpec**：`openspec/specs/ui-design-system/spec.md` 同步新增頁面層級需求。
- **無資料庫／migration／API contract／權限變更**；風險侷限於前端呈現層與 JS 選擇器相容性。Phase 6（custom-status-dropdown）、Phase 7（modal 按鈕搬移）、Phase 11（118 條 i18n 遷移）為計畫標註的 HIGH risk，需逐項 JS 相容性檢查與手動驗證。
