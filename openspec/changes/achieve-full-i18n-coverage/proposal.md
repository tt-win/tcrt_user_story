## Why

本專案宣稱支援三語（zh-TW 主、en-US、zh-CN），但翻譯覆蓋率與用語一致性都有結構性缺口，使用者實際看到的是「中英混雜、且常常無視 UI 語言設定」的介面：

- **後端字串完全繞過 i18n（最大缺口）**：`app/api` 與 `app/services` 內大量 `HTTPException(detail="…")` 與驗證訊息直接寫死繁體中文（例如 `app/api/auth.py:153` `detail="帳號不存在"`、`app/api/llm_context.py:176` `detail="無權限存取此團隊資料"`）。這些訊息會原封不動回傳前端並顯示給使用者，無論 UI 切到哪一種語言都是中文。光是 `detail=` 形態的中文字面值就有數百處，集中在 `auth.py` / `llm_context.py` / `test_case_sections.py` / `qa_ai_helper.py`，是覆蓋率的主要破口。
- **前端硬編字串**：約 1,069 行模板含 CJK 文字但沒有 `data-i18n`（`team_management.html`、`team_statistics.html`、`test_case_management.html` 為大宗），部分頁面整頁未接線（`system_setup_standalone.html`、`first_login_setup.html`）。JS 端另有 40 處 `alert/confirm` 與 118 處 `showToast/showError` 直接帶中文字面值、未走 `i18n.t()`（例如 `usm_import.js:82`、`test-case-drag-drop.js:267`）。
- **語系鍵不對稱**：以 zh-TW 為基準，en-US 缺 78 鍵、zh-CN 缺 124 鍵（整個 `adhoc.*` 命名空間缺失）；連主語系 zh-TW 自己也缺 `testCase.editTestCaseSet`、`adhoc.status`，導致主語系反而回退成英文。
- **用語漂移、且沒有詞彙表（glossary）**：同一概念多種譯法——「set」在 zh-TW 混用 `測試案例集合` / `集合` / `測試案例集`；「test case」多為 `測試案例` 但 `adhoc.*` 出現裸 `案例`、另有一處 `測試用例`；zh-TW 值內夾雜英文（`Test Case Set`、`Ad-hoc Run`）；`suite`（套件）與 `set` 概念被混為一談。

缺口會持續惡化：目前沒有任何 CI 護欄阻止新的硬編字串或不對稱鍵被合併進來。本變更要把覆蓋率推到 100%、用語鎖定到單一詞彙表，並以 CI linter 防止回歸。

## What Changes

- **新增 i18n 覆蓋率 linter 並接上 CI**（P0，護欄優先）：
  - (a) 比對三個語系檔的「葉鍵集合」，任一語系缺鍵／多鍵即 fail（複用 `app/static/js/i18n.js` `validateTranslations()` 的遞迴葉鍵比對邏輯）。
  - (b) 掃描 `app/templates` 與 `app/static/js`，凡 `data-i18n` / `i18n.t()` 之外出現的使用者可見 CJK 字面值即 fail。
  - linter 對 PR 設為 gate，先止血、阻止新增缺口。
- **後端使用者可見字串外部化**（P0，主缺口）：將 `HTTPException.detail` 與驗證訊息改為走訊息鍵（message key）目錄——回傳「錯誤碼 + 參數」由前端翻譯，或導入 server-side gettext（擇一，見 `design.md`）。先處理 `auth.py` / `llm_context.py` / `test_case_sections.py` / `qa_ai_helper.py`（數百處，為最大宗）。
- **抽出前端硬編文字**（P1）：模板文字節點（約 1,069 處）改掛 `data-i18n`、JS 的 `alert/toast`（約 158 處）改走 `i18n.t()`；優先處理整頁未接線者（`system_setup_standalone.html`、`first_login_setup.html`）與高流量檔（`user_story_map.js`、`test-case-management/modal.js`）。
- **補齊缺鍵並修主語系破洞**（P1）：補 en-US 78 鍵、zh-CN 124 鍵，補回 zh-TW 自身缺鍵；發布詞彙表 `app/static/locales/GLOSSARY.md` 鎖定 `測試案例` / `團隊` / `套件` / `測試案例集` / `測試執行` 等標準用語與對應翻譯。
- **既有值一次性正規化**（P2）：將既有翻譯值對齊詞彙表，之後由 linter 持續強制。

非目標（Non-Goals）：

- 不新增現有三語以外的 UI 語言。
- 不改變前端 i18n runtime 機制（維持 `data-i18n` + `i18n.t()` + `MutationObserver`，不重寫 `i18n.js` 的載入／套用流程）。
- 不變更後端任何業務邏輯或 API 行為；外部化僅改變「訊息如何被在地化呈現」，不改變狀態碼語意與既有 API 契約以外的行為。
- 不追求文案重寫（rewording）；正規化僅統一用語，不重撰句子。

## Capabilities

### New Capabilities
- `i18n-coverage`: 定義「全應用程式國際化覆蓋」的可觀察品質門檻——所有使用者可見字串（前端與後端）皆透過 i18n 解析、三語系鍵集合一致（CI 強制）、i18n 系統外不存在使用者可見 CJK 字面值（CI 強制）、並有已發布詞彙表定義標準用語且翻譯值需相符。

### Modified Capabilities
<!-- 無既有 capability 的需求被變更；本變更僅新增 i18n 覆蓋率治理需求。 -->

## Impact

- **後端**：`app/api` 與 `app/services` 內 `HTTPException.detail` 與驗證訊息由寫死 CJK 改為訊息鍵（message-key catalog）外部化——擇定「回傳錯誤碼 + 參數、由前端以 i18n 翻譯」為主要方案（細節見 `design.md`）。需新增一份後端訊息鍵目錄與對應的前端 `errors.*` 命名空間鍵。Migration note：採分批遷移（auth.py → llm_context.py → test_case_sections.py → qa_ai_helper.py → 其餘），遷移期間 linter 對「已遷移檔案」開啟 fail、對未遷移檔案以 allowlist 暫時豁免，避免一次性大爆炸；既有 API 狀態碼與路由契約不變，前端對未知錯誤鍵需回退顯示原始 detail，確保非破壞。
- **前端**：
  - `app/templates/*.html`：硬編文字節點抽出為 `data-i18n` / `data-i18n-*`（優先 `system_setup_standalone.html`、`first_login_setup.html`、`team_management.html`、`team_statistics.html`、`test_case_management.html`）。
  - `app/static/js/**`：`alert/confirm/showToast/showError` 等改走 `i18n.t('key', params, fallback)`（優先 `user_story_map.js`、`test-case-management/modal.js`、`usm_import.js`、`test-case-drag-drop.js`）。
  - `app/static/locales/{zh-TW,en-US,zh-CN}.json`：補齊缺鍵（en-US +78、zh-CN +124、zh-TW 自身破洞）、新增後端錯誤訊息所需 `errors.*` 鍵、並依詞彙表正規化既有值。
  - `app/static/locales/GLOSSARY.md`：新增詞彙表／termbase（單一事實來源）。
- **建置/CI**：新增 i18n 覆蓋率 linter（語系鍵對稱檢查 + CJK 字面值掃描），接入既有 CI 與 PR 流程作為 gate；linter 需提供 allowlist 機制以支援後端字串分批遷移。
- **相容性**：前端 runtime 機制不變；補鍵與正規化屬非破壞性（僅新增／修正鍵值）。後端外部化採前端翻譯 + 未知鍵回退原始 detail，舊前端或未遷移路徑在最壞情況下仍顯示既有中文訊息，不致出現空白或錯誤；CI gate 僅作用於新／已遷移程式碼，不阻擋既有未遷移區塊。
