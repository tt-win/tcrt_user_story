# Design — achieve-full-i18n-coverage

## Context

現行 i18n 為**純前端 runtime**：`app/static/js/i18n.js` 的 `I18nSystem` 於開機時 fetch `/static/locales/<lang>.json`，`translatePage()` 對 `[data-i18n]` 設 `textContent`、對 `[data-i18n-*]` 設屬性，動態 JS 走 `i18n.t(key, params, fallback)`，`MutationObserver` 重譯後續注入的 DOM。Jinja 模板以原始語言渲染、再於瀏覽器端被 `data-i18n` 改寫。後端**無任何 i18n**（無 gettext/Babel），因此 `HTTPException.detail` 等字串以何種語言寫死，使用者就看到何種語言。

本設計處理三件事：(1) 後端使用者可見字串的外部化方案；(2) CI linter 設計；(3) 詞彙表（termbase）與既有值正規化的推行方式。

## Goals / Non-Goals

- Goals：後端字串可在地化；三語系鍵對稱且無 i18n 系統外的 CJK 字面值，並由 CI 強制；用語鎖定到單一詞彙表。
- Non-Goals：不新增第四語言；不重寫前端 runtime 機制（維持 `data-i18n` + `i18n.t()`）；不改後端業務邏輯與既有 API 契約；不做文案重寫。

## Decision 1 — 後端字串外部化：訊息鍵 + 前端翻譯（採用），不導入 server-side gettext

### 選項比較

- **方案 A（採用）— 訊息鍵 + 參數，前端以既有 i18n 翻譯**
  後端回傳與語系無關的「錯誤鍵 + 參數」，前端統一錯誤處理層以 `i18n.t(key, params, fallback)` 在地化。錯誤鍵對應前端 `errors.*` 命名空間，與既有三語系檔同源。
  - 優點：**重用既有前端 runtime 與三語系檔**，不引入新 i18n 技術棧（無 Babel/gettext/.po）；翻譯資源單一事實來源（locales JSON）；語系切換在前端即時生效，無需後端感知 `Accept-Language`；與既有 `i18n.t()` 流程一致。
  - 缺點：非瀏覽器消費者（純 API 客戶端）需自行翻譯或仰賴回退 detail；需要前端建立統一錯誤處理層。
- **方案 B — server-side gettext / Babel（.po/.mo）**
  後端依 `Accept-Language` 解析語系並回傳已在地化字串。
  - 優點：API 回應自帶在地化，對非瀏覽器消費者友善。
  - 缺點：引入第二套 i18n 技術棧與資源格式（.po/.mo 與 locales JSON 並存，雙重維護與雙重事實來源）；後端需處理語系協商；偏離本專案「前端 runtime」既有模式，違反非目標中「不改 runtime 機制」的精神面。

### 採用理由

選 **方案 A**。本專案翻譯資源已集中於三語系 JSON、且前端已有成熟的 `i18n.t()` 與 `MutationObserver` 流程；方案 A 能把後端缺口「導回」既有單一管道，避免雙技術棧。對非瀏覽器客戶端的弱點以「回退原始 detail」緩解（見下）。

### 形態與相容性

- 後端回應形態：`detail` 改為攜帶 `{ code: "<error.key>", params: {...} }`（或等效結構），保留人類可讀的 `message`/原始 detail 作為回退文字。**狀態碼語意不變**，既有路由契約不變。
- 後端維護一份**訊息鍵目錄（message-key catalog）**，與前端 `errors.*` 鍵一一對應，命名規則於 task 2.2 拍板。
- 前端新增**統一錯誤處理層**：解析回應的 `code` + `params`，以 `i18n.t(code, params, fallbackDetail)` 呈現；**未知鍵回退顯示後端原始 detail**（保證舊前端、未遷移路徑、或純 API 客戶端最壞情況仍可讀，不出現空白或鍵名）。

### 遷移策略（避免大爆炸）

分批遷移，順序 `auth.py → llm_context.py → test_case_sections.py → qa_ai_helper.py → app/api / app/services 其餘`。遷移期間：

- linter 的 CJK 掃描對**已遷移檔案**開啟 fail、對**未遷移檔案**以 allowlist 暫時豁免；每完成一檔即將其移出 allowlist。
- 因前端有「未知鍵回退原始 detail」，遷移中途的混合狀態仍可正常顯示，達成非破壞。

## Decision 2 — i18n 覆蓋率 linter

單一腳本（置於 `scripts/` 或 `tools/`），CI 與本機共用，兩項檢查：

1. **語系鍵對稱**：載入三語系 JSON，遞迴蒐集**葉鍵集合**並兩兩比對。比對語意**複用 `app/static/js/i18n.js` 的 `validateTranslations()`**——該函式以遞迴 `checkKeys()` 走訪 fallback 物件、回報缺鍵與型別不符；linter 將其「單向缺鍵」邏輯擴充為「三語系互為基準」的對稱檢查（任一方缺鍵／多鍵皆 fail），輸出缺鍵語系與鍵路徑。
2. **CJK 字面值掃描**：
   - 模板（`app/templates/*.html`）：解析文字節點與屬性，回報含 CJK 但未掛 `data-i18n` / `data-i18n-*` 者。
   - JS（`app/static/js/**`）：回報 `alert/confirm/showToast/showError` 等使用者可見呼叫中、未經 `i18n.t()` 的 CJK 字面值。

設計要點：

- **Allowlist**：檔案／行豁免清單，支援後端字串分批遷移；目標是最終清空，僅保留明確標註的「非使用者可見」例外。
- **輸出**：可讀違規清單（檔案 + 位置 + 類別）、非零退出碼。
- **CI gate**：接入既有 CI 對 PR 設為阻擋；本機執行方式記錄於 `README` 或 CI 設定。
- **誤報控管**：掃描聚焦「使用者可見」面（模板文字節點、特定 JS 呼叫的字串引數），避免把註解、log、內部識別字誤判為違規。

## Decision 3 — 詞彙表（termbase）與正規化推行

- **單一事實來源**：`app/static/locales/GLOSSARY.md`，至少鎖定 `測試案例`、`團隊`、`套件`、`測試案例集`、`測試執行`，逐語系列出對應譯法。明確區隔 `suite`（套件）與 `set`（測試案例集），終結兩者混用。
- **一次性正規化**：對既有值掃描並對齊詞彙表——統一 zh-TW「set」用語、修裸 `案例`／`測試用例` → `測試案例`、清除 zh-TW 值內英文殘留（`Test Case Set`、`Ad-hoc Run`）、釐清 suite/set 鍵歸屬；en-US / zh-CN 比照對齊。
- **持續強制**：正規化後由 linter（對稱檢查 + CJK 掃描）守住；詞彙表層級的逐詞校驗以人工審查與詞彙表對照為主（自動詞彙比對可作為後續增強，本變更不要求）。

## Risks / Trade-offs

- **純 API 客戶端在地化弱化**（方案 A 固有）：以回退原始 detail 緩解；若未來需求升高，可在不破壞 locales 單一來源前提下，另加 server-side 翻譯層。
- **CJK linter 誤報**：以「聚焦可見面 + allowlist」控管；初期可能需調整掃描規則。
- **遷移期混合狀態**：以「未知鍵回退原始 detail」確保任何中間狀態皆可讀。

## Migration / Rollout

1. 先上 linter（對稱檢查 + CJK 掃描）並設 allowlist 涵蓋現況 → 止血、阻止新增缺口。
2. 後端字串分批外部化，逐檔移出 allowlist。
3. 前端硬編抽出 + 補鍵 + 發布詞彙表。
4. 既有值一次性正規化。
5. 清空 allowlist，linter 全面 gate。

每階段皆非破壞：補鍵與正規化僅新增／修正鍵值；後端外部化以回退保底；CI gate 僅作用於新／已遷移程式碼。
