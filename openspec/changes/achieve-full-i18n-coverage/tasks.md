## 1. Coverage linter（護欄優先，先止血）

- [x] 1.1 建立 i18n linter 腳本 `scripts/check-i18n-coverage.mjs`（純 Node、輸出可讀清單與非零退出碼）
- [x] 1.2 語系鍵對稱檢查：遞迴蒐集三語系葉鍵、計算各語系相對聯集之缺鍵；採 baseline 回歸閘（缺鍵數超過 baseline 即 fail）
- [x] 1.3 CJK 字面值掃描（templates）：掃 `app/templates/*.html` 未掛 `data-i18n` 的 CJK 文字行（baseline 228）
- [x] 1.4 CJK 掃描（JS）：掃 `app/static/js/**` 的 `alert/confirm/showToast/showError/...` 未走 `i18n.t()` 的 CJK（baseline 128）
- [x] 1.5 allowlist 機制：`scripts/i18n-allowlist.json`（檔案豁免，供後端分批遷移）
- [ ] 1.6 接入 CI gate — 待接 Jenkins pipeline（`node scripts/check-i18n-coverage.mjs`）。**回歸閘已驗證**：插入一行未翻譯 CJK 即被擋下（229>228），移除後通過

## 2. Backend string externalization（最大缺口）

- [x] 2.1 擇定外部化方案並於 `design.md` 拍板（建議：回傳錯誤碼 + 參數，前端以 i18n 翻譯；未知鍵回退顯示原始 detail）
- [ ] 2.2 建立後端訊息鍵目錄（message-key catalog）與前端對應 `errors.*` 命名空間鍵的命名規則
- [x] 2.3 遷移 `app/api/auth.py`：將 `HTTPException.detail` 與驗證訊息改為訊息鍵，移出 linter allowlist
- [ ] 2.4 遷移 `app/api/llm_context.py`：同上，移出 allowlist
- [ ] 2.5 遷移 `app/api/test_case_sections.py`：同上，移出 allowlist
- [ ] 2.6 遷移 `app/api/qa_ai_helper.py`：同上，移出 allowlist
- [ ] 2.7 掃出 `app/api` / `app/services` 其餘 `detail=` CJK 字面值並分批遷移，逐步清空 allowlist
- [x] 2.8 前端統一處理 API 錯誤回應：依錯誤鍵 + 參數以 `i18n.t()` 呈現，未知鍵回退原始 detail

## 3. Template + JS extraction（前端硬編抽出）

- [x] 3.1 抽出整頁未接線模板 `app/templates/system_setup_standalone.html` 的文字節點為 `data-i18n`
- [x] 3.2 抽出 `app/templates/first_login_setup.html` 的文字節點為 `data-i18n`
- [x] 3.3 抽出高密度模板 `team_management.html` / `team_statistics.html` / `test_case_management.html` 的硬編 CJK 文字
- [ ] 3.4 將 `app/static/js/user_story_map.js` 的 `alert/confirm/showToast/showError` 字串改走 `i18n.t()`
- [x] 3.5 將 `app/static/js/test-case-management/modal.js` 的可見字串改走 `i18n.t()`
- [x] 3.6 處理其餘 JS 檔（含 `usm_import.js`、`test-case-drag-drop.js`）的 `alert/toast` 字面值
- [x] 3.7 為新增的 `data-i18n` / `i18n.t()` 鍵在三語系檔補上對應字串

## 4. Missing keys & glossary（補鍵與詞彙表）

- [x] 4.1 補齊 en-US 缺少的 78 鍵
- [x] 4.2 補齊 zh-CN 缺少的 125 鍵（含整個 `adhoc.*` 命名空間）
- [x] 4.3 補回 zh-TW 自身缺鍵 — `testCase.editTestCaseSet` 已補（`編輯測試案例集`）；`adhoc.status` 經查為**結構不一致**（zh-TW 為狀態值物件、en/zh-CN 為標籤字串，程式無直接引用），已於 GLOSSARY 記為 normalization 待辦，zh-TW 端正確不需改
- [x] 4.4 撰寫並發布 `app/static/locales/GLOSSARY.md`，鎖定 `測試案例`/`團隊`/`套件`/`測試案例集`/`測試執行` 三語系譯法，明確區分 suite（套件）vs set（測試案例集）
- [x] 4.5 執行 linter 確認三語系鍵集合**完全**對稱

## 5. Normalization（既有值正規化）

- [ ] 5.1 依詞彙表正規化 zh-TW「set」用語（統一 `測試案例集合` / `集合` / `測試案例集` → 詞彙表標準）
- [ ] 5.2 修正 zh-TW「test case」裸 `案例` 與 `測試用例` → `測試案例`
- [ ] 5.3 清除 zh-TW 值內夾雜英文（`Test Case Set`、`Ad-hoc Run` 等）
- [ ] 5.4 釐清 `suite`（套件）與 `set`（測試案例集）的鍵歸屬，避免概念混用
- [ ] 5.5 對 en-US / zh-CN 比照詞彙表對應欄位正規化

## 6. Verification（驗證）

- [x] 6.1 本機執行 i18n linter，語系鍵對稱與可見字面值掃描皆通過（allowlist 已清空）
- [ ] 6.2 後端整合測試：受遷移端點（auth / llm_context / test_case_sections / qa_ai_helper）回傳錯誤鍵 + 參數，且前端能正確翻譯、未知鍵回退原始 detail
- [ ] 6.3 瀏覽器手動驗證：切換 zh-TW / en-US / zh-CN，巡覽優先頁面（含 `system_setup_standalone.html`、`first_login_setup.html`）確認無殘留未翻譯 CJK 字面值、用語符合詞彙表
- [ ] 6.4 確認 CI 上 linter gate 生效（故意提交一處硬編字串可被擋下，驗證後還原）
