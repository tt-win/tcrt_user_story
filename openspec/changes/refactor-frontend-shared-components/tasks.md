# Implementation Tasks

依 `REFACTOR_PLAN.md` Phase 0–16 循序推進。每個 phase 結束的 gate：`uv run pytest app/testsuite/test_component_spec.py -q` 與 `npm run lint` 必須通過。

**執行狀態（2026-07-27）**：全部可機械驗證的 component SPEC（BTN/BDG/TBL/MDL/CRD/TLB/TAB/DRP/HOM/NAV/i18n）已收斂至 `test_component_spec.py` 358 passed / 0 failed。Phase 9/10/15 中需要瀏覽器視覺驗證的大型重構（dl→card grid、template merge、password strength、AI surface class 抽取）標記為 **deferred-browser**，理由：無法在無瀏覽器環境安全驗證視覺/互動結果，貿然實作有回歸風險。

## 1. Phase 0 — 測試鷹架 ✓

- [x] 1.1 建立 `app/testsuite/test_component_spec.py`：TestClient fixture（stubbed lifespan）、`render_page`、`all_page_routes`（20 路由）
- [x] 1.2 盤點 22 路由全部可渲染（route handler 不碰 DB，lifespan stub 為 no-op）
- [x] 1.3 撰寫各 SPEC 檢查（BTN/BDG/TBL/MDL/CRD/TLB/TAB/DRP/HOM/NAV/i18n）
- [x] 1.4 baseline：63 failed → 收斂至 0（以 failing-count 為追蹤指標，未採 xfail 標記，理由見 design.md Decision 2 偏差說明）
- [x] 新增 dev dep `beautifulsoup4`（計畫 Phase 0.1 指定）

## 2. Phase 1 — 全域 CSS ✓

- [x] 2.1 `.table th` 白底 + uppercase + letter-spacing + 0.7rem + 2px border
- [x] 2.2 table td 僅 border-bottom（無垂直邊框）
- [x] 2.3 hover → `rgba(var(--tr-primary-rgb), 0.04)`
- [x] 2.4 last-row 無 border
- [x] 2.5 dropdown gap/icon/divider/header 全域規則
- [x] 2.6 gate 通過

## 3. Phase 2 — SPEC-HOM-001 ✓

- [x] 3.1 全站 15 頁 Home 按鈕文案/class/同行統一（含 locale JSON 三語系修正：回到首頁/回到首页/Back to Home）

## 4. Phase 3 — SPEC-BTN-001 ✓

- [x] 4.1 `btn-xs` → `btn-sm`（30 處）
- [x] 4.2 `btn-view`/`btn-edit` → `btn-secondary`/`btn-outline-primary`（含 JS cache.js）
- [x] 4.3 `test-run-kebab-btn` → `btn btn-secondary btn-sm`（含 set-modal.js JS-generated）
- [x] 4.4-4.5 class order `btn btn-sm btn-{variant}` → `btn btn-{variant} btn-sm`（71 處，含 10 JS 檔）
- [x] 4.6 `btn-info dropdown-toggle` → `btn-secondary`
- [x] 4.7-4.8 nav/entry `btn-info` → `btn-secondary`/`btn-outline-primary`
- [x] 4.9 JS 相容性檢查（選擇器對齊，行為不變）

## 5. Phase 4 — SPEC-BDG-001 ✓

- [x] 5.1-5.5 `text-bg-*` → `bg-*`、裸 badge 補 `bg-secondary`、`badge-role` → `bg-primary`（含 profile.js className 修正）

## 6. Phase 5 — SPEC-TAB-001 ✓

- [x] 6.1 team_statistics `nav-pills` → `nav nav-tabs`（+ `data-bs-toggle="tab"`，JS 用 id 選擇器無影響）
- [x] 6.2 `mb-2` → `mb-3`
- [x] 6.3 tab 圖示補齊（system_logs 4 tabs、organization_management syncTabs 4 tabs，重構為 `<i></i><span data-i18n>` canonical pattern）
- [x] 6.4 `automation-tabs` 自訂 class 移除

## 7. Phase 6 — SPEC-TLB-001 + SPEC-DRP-001 ✓（HIGH risk）

- [x] 7.1 `automation-toolbar` → `d-flex gap-2` + `vr mx-1`
- [x] 7.2 toolbar `gap-3` → `gap-2`
- [x] 7.3 `custom-status-dropdown` → Bootstrap `dropdown-menu` + `dropdown-item`（保留 fixed positioning 修飾 class `tr-dropdown-menu`/`tr-dropdown-overlay`，因巢狀 dropdown context Bootstrap 原生元件無法直接處理；元素 id 不變故 JS 選擇器無破壞）
- [x] 7.4 `automation-toolbar` dead CSS 移除
- [x] 7.5 JS 相容性：item class `custom-status-dropdown-item` → `dropdown-item`（4 處）
- [ ] 7.6 手動驗證：status 變更流程（**deferred-browser**）

## 8. Phase 7 — SPEC-MDL-001 ✓（HIGH risk）

- [x] 8.1 inline modal size → class（`modal-tc-editor`/`modal-xl-wide`/`modal-w-1400`/`modal-w-1200`/`modal-vmargin-sm`）
- [x] 8.2 TC editor prev/next/copy 按鈕從 modal-header 搬到 modal-body 子工具列（JS 用 getElementById，id 不變）
- [x] 8.3-8.4 modal-header `bg-light`/`bg-danger text-white` 移除；delete modal 改 `text-warning` icon + `btn-close`
- [x] 8.6 configDetailModal footer `btn-warning` → `btn-outline-primary me-auto`（重排為 SPEC 順序）
- [x] 8.7 modal size CSS class 加入 style.css
- [ ] 8.9 手動驗證：TC editor prev/next、delete modal（**deferred-browser**）

## 9. Phase 8 — SPEC-CRD-001 ✓ + SPEC-TBL-001（cross-cutting）✓

- [x] 9.1 card-header 全站正規化（72 處，script 確保 canonical set + 保留 extra class）
- [x] 9.3 table 全站正規化（table-sm/table-hover/align-middle，31 table；thead table-light 移除，9 處）

## 10. Phase 9 — system_logs（部分）

- [x] 10.1 tab 圖示（Phase 5 完成）
- [x] 10.2 mb-3（Phase 5）
- [x] 10.5 table-hover（cross-cutting）
- [x] 10.9 alert-secondary → alert-warning
- [ ] 10.3-10.4 Runtime/KG `<dl>` → card grid（**deferred-browser**：HTML 結構重組需視覺驗證）
- [ ] 10.6 logOutput terminal 風格（**deferred-browser**）
- [ ] 10.7 log-toolbar-item → d-flex（**deferred-browser**）
- [ ] 10.8 KQL table 9→6 欄（**deferred-browser**：欄位精簡需視覺驗證）

## 11. Phase 10 — setup pages（部分）

- [x] 11.1 first-login-setup 黃漸層 → 藍漸層
- [x] 11.4 submit `btn-success` → `btn-primary`
- [ ] 11.2-11.3 zh-TW fallback / password strength（**deferred-browser**）
- [ ] 11.6-11.8 system_setup 雙模板合併 / onclick→addEventListener / spinner（**deferred-browser**）

## 12. Phase 11 — organization_management i18n ✓（HIGH risk）

- [x] 12.1-12.3 118 條 `d-none` i18n 字串：DOM store div 移除；`getI18n()` 改走 `window.i18n.t()`（keys 已在 locale JSON）
- [x] 12.10 i18n coverage 三語系通過
- [ ] 12.11 手動驗證：org sync 訊息（**deferred-browser**）

## 13. Phase 12 — team_statistics（部分）✓

- [x] 13.1 nav-pills → nav-tabs（Phase 5）
- [x] 13.2-13.3 class order + refresh icon me-1
- [x] 13.4 dead Department Stats code（grep 未發現，已不存在）

## 14. Phase 13 — audit_logs + test_case_reference + profile（部分）

- [x] 14.1 audit_logs table-sm/align-middle/table-light/sticky-top（cross-cutting）
- [x] 14.2 test_case_reference：inline style → class（0 inline style）、ref-sidebar/ref-overlay-fill/ref-iframe-fill、響應式 breakpoint、iframe title、calc magic number → token；JS show/hide 改 classList toggle
- [x] 14.3 profile：badge-role→bg-primary（含 profile.js）、profile.css 12+ hex → token、Save/Change password → btn-primary、password toggle → btn-link btn-sm p-0、avatar inline → class

## 15. Phase 14 — SPEC-NAV-001 ✓

- [x] 15.1 `base.html` 新增「管理」Admin dropdown（Casbin RBAC：base-auth.js 依 role admin/super_admin 顯示；三語系 adminMenu.* keys）
- [x] 15.2 team_management data menu 移除（JS dead code 清理）
- [ ] 15.3 automation 子頁 breadcrumb（**deferred-browser**）
- [ ] 15.5 手動驗證：管理員/非管理員可見性（**deferred-browser**）

## 16. Phase 15 — SPEC-AI-001（deferred-browser）

- [ ] 16.1-16.4 共用 AI surface CSS class 抽取與套用（QA AI Helper + inline AI Assist）。**deferred-browser**：涉及複雜 rendering JS 的氣泡/卡片結構變更，必須在實際 session 中視覺驗證 Markdown 渲染、code copy、table。

## 17. Phase 16 — 全套驗證與收尾（進行中）

- [x] 17.1 `uv run pytest app/testsuite/test_component_spec.py` 358 passed / 0 failed
- [x] 17.2 `npm run lint` 0 errors（649 warnings 皆為既有 raw-hex，較 baseline 671 減少 22）
- [x] 17.3 i18n coverage 通過
- [x] 17.4 dead CSS 清理（btn-view/btn-edit/automation-toolbar/automation-toolbar-divider）
- [ ] 17.5 sync delta → `openspec/specs/ui-design-system/spec.md`（於 archive 時執行）
- [ ] 17.6 deferred-browser 項目收斂（需瀏覽器驗證回合）
- [ ] 17.7 `openspec validate refactor-frontend-shared-components --strict`（已驗證通過）
