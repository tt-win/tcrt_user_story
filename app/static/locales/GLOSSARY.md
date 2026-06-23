# TCRT i18n 詞彙表（termbase）

**單一事實來源**：本表鎖定核心領域用語在三語系的標準譯法。新增/修改文案時務必對齊本表；
既有值的正規化（統一散落用語）以本表為準。`scripts/check-i18n-coverage.mjs` 守住鍵對稱與
未翻譯 CJK，**逐詞用語**則以本表 + 人工審查把關。

## 核心術語

| 概念 | en-US | zh-TW（繁・標準） | zh-CN（简・标准） | 備註 |
|------|-------|------------------|------------------|------|
| test case | Test Case | **測試案例** | **测试用例** | 勿用裸「案例」；繁體勿用「測試用例」 |
| test case set | Test Case Set | **測試案例集** | **测试用例集** | 勿用「集合」「測試案例集合」 |
| suite | Suite | **套件** | **套件** | 與「測試案例集」**不同概念**，勿混用 |
| team | Team | **團隊** | **团队** | 勿用「小組」 |
| test run | Test Run | **測試執行** | **测试执行** | run 作名詞時用此；勿用裸「執行」 |
| test run set | Test Run Set | **測試執行集** | **测试执行集** | |
| section | Section | **區段** | **区段** | |
| ad-hoc run | Ad-hoc Run | **臨時執行** | **临时执行** | zh 值內勿殘留英文「Ad-hoc Run」 |
| automation | Automation | **自動化** | **自动化** | |

## suite vs set（務必區分）

- **suite（套件）**：Automation Hub 的自動化腳本套件（CI job 對應單位）。
- **set（測試案例集 / 測試執行集）**：測試案例或執行的集合。

兩者在英文與中文皆為不同詞，鍵命名與譯文不得互換。

## 正規化待辦（既有值，供 group 5 normalization）

- zh-TW「set」散見 `集合` / `測試案例集合` → 統一為 **測試案例集**。
- zh-TW「test case」裸 `案例` / 殘留 `測試用例` → **測試案例**。
- 清除 zh-TW 值內英文殘留（`Test Case`、`Test Case Set`、`Ad-hoc Run`）。
- **`adhoc.status` 結構不一致**：zh-TW 為狀態值物件 `{active,completed,archived,draft}`，
  en-US/zh-CN 為標籤字串 `"Status"/"状态"`（同鍵不同義）。程式無直接引用；
  normalization 時須釐清語意後統一結構（建議：狀態值移至 `adhoc.statusValues.*`，
  `adhoc.status` 一律為「狀態」標籤）。

## 維護

- 改文案 → 對照本表；新增概念 → 先在此登錄標準譯法再落地三語系。
- 詞彙表變更需同步 reviewer；`check-i18n-coverage.mjs` 確保三語系鍵不漏。
