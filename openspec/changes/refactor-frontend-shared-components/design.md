## Context

`ui-design-system` 已落地 design token 層、stylelint 護欄與 Jinja macro 元件庫，但頁面層級的元件發散仍由人工把關——`AGENTS.md` 的 SPEC-BTN/BDG/TBL/MDL/CRD/TLB/TAB/DRP/HOM/NAV/AI 在 18 個頁面上普遍違反，且**沒有任何自動化測試攔截**。`REFACTOR_PLAN.md` 把收斂工作拆成 Phase 0–16 的漸進計畫。本設計說明如何把該計畫執行完，並把 SPEC 從文件變成會 fail 的測試。

既有專案前置事實：
- 後端 FastAPI app 已可在測試中以 `starlette.testclient.TestClient` 啟動。
- `app/testsuite/` 已有完整 pytest 基礎建設與 fixtures。
- `app/templates/base.html` 是全站 layout 母板，所有頁面繼承它。
- 18 個頁面路由散落在 `app/api/` 各 router；需逐一盤點可用路由（部分頁面需登入/團隊 scope）。

## Goals / Non-Goals

**Goals:**
- 建立 `test_component_spec.py` 機械護欄，以 rendered HTML 為真相逐 SPEC 檢查。
- 依 `REFACTOR_PLAN.md` Phase 0–16 逐頁掃到全綠（`uv run pytest app/testsuite -q` + `npm run lint`）。
- 全程不改後端、API contract、schema、權限、JS 行為；JS 僅更新選擇器／類別參考。

**Non-Goals:**
- 不做視覺改版、不導入前端 build pipeline、不引進第二套 package manager。
- 不重寫 macro 元件庫（已由前一個 change 建立）；本變更在頁面層套用既有規範。
- 不改變 Jinja 邏輯（`{% %}`/`{{ }}`）與 JS 依賴的 `data-*` 屬性。

## Decisions

### Decision 1：測試以 rendered HTML 為真相，不做純字串掃描
`test_component_spec.py` 透過 `TestClient` 實際 GET 每個頁面路由，再用 BeautifulSoup 解析。這比 regex 掃描模板原始碼更接近使用者實際看到的結果，也能捕捉 Jinja 迴圈／條件產生的違規。代價是需要能渲染每個頁面——需盤點哪些路由可匿名、哪些需 fixture 注入 auth/團隊 scope。**無法在測試中渲染的頁面**改用模板原始碼掃描作為 fallback，並在測試中標註原因。

### Decision 2：xfail 基線 → 逐 phase 移除
Phase 0 建立測試時，對當前已違反的檢查標記 `pytest.mark.xfail(strict=True)`，建立可量化的追蹤基線。每完成一個 phase，**該 phase 修掉的違規對應的 xfail 必須同步移除**（Phase 16 確認零 xfail 殘留）。這讓進度可被 `pytest -rx` 直接觀察。

### Decision 3：JS 相容性以 grep 前置檢查 + 選擇器對齊為原則
每個動到 HTML class 的 phase，先 `rg` 對應 JS 檔案對舊 class／屬性的選擇器參考，**只更新選擇器與類別字串，不改事件處理或 API 呼叫**。HIGH risk 項目（Phase 6 custom-status-dropdown、Phase 7 modal 按鈕搬移、Phase 11 i18n DOM→JSON）額外需求：列出受影響 JS 函式清單，並在該 phase 的 task 中標註手動驗證步驟。

### Decision 4：i18n 字串只進 locale JSON，不進 DOM
Phase 11 的 118 條 `d-none` i18n 字串遷移到 `app/static/locales/{en-US,zh-CN,zh-TW}.json`，JS 改用 `window.i18n.t()` 讀取。這對齊 `AGENTS.md` 明令禁止的 anti-pattern（`organization_management.html` 的 `d-none` div 隱藏 i18n 字串）。三語系須同步更新，並以 `node scripts/check-i18n-coverage.mjs` 驗證無缺漏。

### Decision 5：modal 尺寸 inline style → 具名 CSS class
Phase 7 把 `style="width:1400px;height:90vh"` 這類 inline modal 尺寸改為具名 class（如 `modal-tc-editor`）定義在 `style.css`。這對齊 SPEC-MDL-001「inline size override forbidden」與全域「模板禁 inline style」護欄。class 命名採語意而非尺寸（`modal-tc-editor` 而非 `modal-1400`）。

### Decision 6：Admin dropdown RBAC 由 Jinja 條件控制
Phase 14 在 `base.html` 新增「管理」dropdown，連結到組織設定／稽核日誌／系統日誌／統計分析等頁面。可見性由既有 Casbin RBAC 的 Jinja 條件（與各頁面現行使用的相同 `current_user` / 權限旗標）控制，**不新增任何後端權限邏輯**。

## Risks / Trade-offs

| Risk | Severity | Mitigation |
|------|----------|------------|
| 某些頁面路由在測試中無法渲染（需複雜 auth/團隊 scope fixture） | Medium | Phase 0 先盤點可渲染路由清單；無法渲染者改用模板原始碼掃描 fallback 並標註。 |
| Phase 6 `custom-status-dropdown` 是完整自訂實作，改 Bootstrap dropdown 可能破壞狀態變更流程 | **High** | 實作前完整讀現有 JS；保留所有 `data-*` 屬性與事件；手動驗證狀態變更流程；phase 完成後跑 `test_run_management` 相關測試。 |
| Phase 7 把 modal-header 按鈕搬到 modal-body，JS 選擇器需同步更新 | **High** | 實作前 `rg` 所有相關按鈕 id/class；搬移後逐一驗證 prev/next/copy 流程；保留按鈕 id 不變。 |
| Phase 11 遷移 118 條 i18n 字串，JS 改 `window.i18n.t()` | **High** | 逐鍵比對遷移；三語系同步；`check-i18n-coverage.mjs` 驗證；手動觸發 org sync 流程確認訊息正確。 |
| Phase 14 RBAC 條件錯誤導致非管理員看到管理連結 | Medium | 沿用各頁面現行 Jinja 權限旗標，不新算權限；手動以非管理員帳號驗證。 |
| Phase 10 合併 system_setup 雙模板可能破壞 standalone 模式 | Medium | 以 `bootstrap` flag 條件載入；兩種模式各手動驗證一次。 |
| 全站 18 頁大規模 class 改動引入回歸 | Medium | 每 phase 結束跑 `uv run pytest app/testsuite -q` + `npm run lint` 作為 gate；HIGH risk phase 額外手動驗證。 |

**Trade-off**：以「測試為真相」而非「模板原始碼掃描」會增加 Phase 0 的 fixture 建置成本，但能捕捉 Jinja 動態產生的違規，長期維護性更高。接受這個成本。
