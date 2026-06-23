## ADDED Requirements

### Requirement: All user-facing strings resolve through the i18n system

系統 SHALL 確保所有使用者可見字串——同時涵蓋前端（模板與 JS）與後端（API 錯誤與驗證訊息）——透過 i18n 系統解析，使其顯示語言隨使用者選定的語系變動。後端使用者可見訊息 SHALL 以與語系無關的形式（訊息鍵 + 參數）外部化，並在呈現層在地化；不得直接回傳寫死的特定語言字面值。

#### Scenario: Backend error message localized by selected locale
- **WHEN** 使用者在 UI 語系為 `en-US` 時觸發一個後端錯誤（例如登入帳號不存在）
- **THEN** 回應所攜帶的使用者可見訊息以英文呈現給使用者
- **AND** 同一錯誤在語系為 `zh-TW` 時以繁體中文呈現

#### Scenario: Backend message carries a locale-independent key
- **WHEN** 受外部化的後端端點回傳使用者可見錯誤
- **THEN** 回應包含一個與語系無關的訊息鍵（必要時含參數）供呈現層在地化
- **AND** 該訊息不是寫死的單一語言字面值

#### Scenario: Unknown error key falls back gracefully
- **WHEN** 前端收到一個自身字典中不存在的後端訊息鍵
- **THEN** 系統回退顯示後端提供的原始 detail 文字（不顯示空白或鍵名）

#### Scenario: Frontend visible text resolves through i18n
- **WHEN** 使用者切換 UI 語系
- **THEN** 模板文字節點與 JS 提示（alert / confirm / toast）皆隨選定語系更新
- **AND** 不出現殘留於 i18n 系統之外的未翻譯字串

### Requirement: The three locales have identical key sets (CI-enforced)

系統 SHALL 維持 `zh-TW`、`en-US`、`zh-CN` 三個語系檔具有完全相同的葉鍵集合。CI SHALL 以自動化檢查比對三語系的葉鍵集合，任一語系出現缺鍵或多鍵時 SHALL 使檢查失敗並阻擋合併。

#### Scenario: Asymmetric keys fail CI
- **WHEN** 一個 PR 在某語系新增鍵卻未於其他語系補上對應鍵
- **THEN** CI 的語系對稱檢查失敗
- **AND** 失敗輸出列出缺鍵的語系與鍵路徑

#### Scenario: Symmetric keys pass CI
- **WHEN** 三個語系的葉鍵集合完全一致
- **THEN** 語系對稱檢查通過

#### Scenario: Primary locale has no holes
- **WHEN** 對稱檢查執行
- **THEN** 主語系 `zh-TW` 不缺任何於其他語系存在的鍵（不會反向回退成英文）

### Requirement: No untranslated user-facing literal exists outside the i18n system (CI-enforced)

系統 SHALL 不在 i18n 系統之外存在任何使用者可見的 CJK 字面值。CI SHALL 掃描 `app/templates` 與 `app/static/js`，回報未掛 `data-i18n` / `data-i18n-*`（模板）或未經 `i18n.t()`（JS 的 alert/confirm/toast 等可見字串）的 CJK 字面值，並於發現時使檢查失敗。linter SHALL 提供 allowlist 機制，僅供後端字串分批遷移期間暫時豁免明確標註的檔案／行。

#### Scenario: Hardcoded template literal fails CI
- **WHEN** 一個模板新增含 CJK 文字的節點但未掛 `data-i18n`
- **THEN** CJK 字面值掃描失敗並指出檔案與位置

#### Scenario: Hardcoded JS alert literal fails CI
- **WHEN** JS 以 `alert` / `showToast` / `showError` 直接帶入 CJK 字面值且未走 `i18n.t()`
- **THEN** 掃描失敗並指出檔案與位置

#### Scenario: Allowlisted file skipped during migration
- **WHEN** 一個尚未遷移的後端檔案被列入 allowlist
- **THEN** 掃描略過該檔案，不使檢查失敗
- **AND** 該檔案完成遷移並移出 allowlist 後，後續對其新增的硬編字面值會再次被擋下

### Requirement: Terminology is consistent and matches a published glossary

系統 SHALL 維護一份已發布的詞彙表（termbase，例如 `app/static/locales/GLOSSARY.md`）作為標準用語的單一事實來源，至少涵蓋 `測試案例`、`團隊`、`套件`、`測試案例集`、`測試執行`，並為每個語系定義對應譯法。所有語系檔的翻譯值 SHALL 與詞彙表一致；同一概念 SHALL NOT 在同語系內使用多種譯法，且 zh-TW 值內 SHALL NOT 夾雜應被翻譯的英文用語。

#### Scenario: Glossary defines canonical terms per locale
- **WHEN** 檢視詞彙表
- **THEN** 每個受治理概念皆列出標準用語與三語系對應譯法

#### Scenario: Single concept uses one term per locale
- **WHEN** 「set」概念在 zh-TW 出現於多個鍵
- **THEN** 所有相關值使用詞彙表所定的單一標準用語（不再混用 `測試案例集合` / `集合` / `測試案例集`）

#### Scenario: No stray English leaks in zh-TW values
- **WHEN** 巡覽 zh-TW 語系值
- **THEN** 不出現應被翻譯的英文用語（如 `Test Case Set`、`Ad-hoc Run`）
