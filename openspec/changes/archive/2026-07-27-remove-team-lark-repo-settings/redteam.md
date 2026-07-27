# 紅隊審查紀錄

對本 change 的 proposal / design / tasks 進行對抗式自審。每一輪的目標是**證明計畫是錯的**：找出會讓實作失敗、產生回歸、或讓 reviewer 被誤導的假設。每項發現都必須以實際掃描 repo 的證據支持，不接受「感覺可能有問題」。

---

## Round 1（2026-07-27）

攻擊面：計畫中所有「未經驗證就當成事實」的假設。

### F1 ⚠️ 高 — `TeamCreate` 沒有 `extra="forbid"`，D7 測試案例 2 的預期是錯的

design D7 案例 2 寫「`POST /api/teams` 額外帶 `lark_config` → 422」。實際上 `extra="forbid"` 只設在 `Team`（`app/models/team.py:80` 的 `model_config`），`TeamCreate`（:128）與 `TeamUpdate`（:137）**都沒有 `model_config`**，Pydantic 2 預設是 `extra="ignore"`。照原計畫寫測試會直接紅燈。

**處置**：不替 `TeamCreate`／`TeamUpdate` 補 `extra="forbid"`——那是本次需求之外的契約收緊，會讓任何送出額外欄位的既有 client 由 200 變 422。改為修正測試預期：帶 `lark_config` 的請求 SHALL 回 201、該欄位被忽略、且 DB 中 `wiki_token` 仍為 `""`（證明不會被偷偷寫入）。已更新 design D7 與 tasks 6.1。

### F2 ⚠️ 中 — 回滾缺口的嚴重度被低估：不是「該 team 無法列出」，是整個列表 500

`get_teams()`（`app/api/teams.py:146`）以 list comprehension 對所有 team 呼叫 `team_db_to_model()`。revert 後只要**任何一筆** team 的 `wiki_token` 是空字串，`LarkRepoConfig` validator 就會拋 `ValidationError`，整個 `GET /api/teams` 回 500——不是只有那一筆消失，而是所有人都看不到任何 team，`/team-management` 與首頁同時失效。

**處置**：design「Migration Plan」段落改寫為正確嚴重度；`rollback.md` 從「建議」升級為**必要交付物**（tasks 7.3 保留），內容必須包含可直接執行的修復 SQL。

### F3 ⚠️ 中 — 只 override `get_current_user` 不足以通過 `require_admin()`

`require_admin()` → `require_role()` → `permission_service.check_user_role(current_user.id, ...)`（`app/auth/dependencies.py:151-167`），是**用 user id 查 DB**，不看注入物件的 `role` 屬性。既有 HTTP 測試（如 `test_pins_api.py`）只 override `get_current_user`，因為它們打的是非 admin-only 端點。`POST /api/teams` 是 `require_admin()`，照抄該 pattern 會拿到 403。

**處置**：design D7 補上測試前置條件——monkeypatch `app.auth.permission_service.permission_service.check_user_role` 回 `True`（或在測試 DB 插入真實 admin user 列）。已寫入 tasks 6.1。

### F4 ⚠️ 中 — `teams.py` 模組級 `settings` import 會變成未使用，但有同名遮蔽陷阱

`app/api/teams.py:31` 有模組級 `from app.config import settings`，唯二使用者是要被刪的兩支 validate 端點（:192、:215）。刪除後該 import 未使用 → `ruff` F401 擋 CI。陷阱在於同一檔案還有兩個同名符號：`team_db_to_model()` 內的區域變數 `settings = TeamSettings(...)`（:76、:86），以及 `delete_team()` 內的函式級 `from app.config import settings`（:439-441）。粗暴地全域搜尋刪除會誤傷。

**處置**：tasks 1.5 明列「只刪模組級 import，保留 :86 的區域變數與 :439 的函式級 import」。

### F5 低 — i18n gate 是「三語系 key 對稱 + 可見字面量 baseline」

`scripts/check-i18n-coverage.mjs` 檢查 locale key symmetry 與模板/JS 中的高信心可見字面量，既有債務以 baseline 計數放行、只有**增加**才失敗。含意有二：刪 key 必須三個檔案同步（否則 symmetry 失敗）；改寫文案時若在 HTML/JS 留下裸中文字面量，baseline 會上升而擋 CI。

**處置**：tasks 5.1／5.2 已要求三語系同步；新增註記「不得引入新的 raw CJK 字面量」。

### F6 低 — `is_lark_configured` 現況在兩個端點的算法本來就不一致

`app/api/app_read.py:106` 是 `bool(team.wiki_token)`，`app/api/mcp.py:326` 是 `bool(team.wiki_token and team.test_case_table_id)`。凍結為 `false` 會順帶消除這個既有不一致，但 diff 上看起來像是「兩個不同的東西被改成同一個常數」。

**處置**：design D3 補一句說明，避免 reviewer 誤判為筆誤或漏改。

### F7 ℹ️ 三個潛在破壞面掃描後確認為零

- **Audit**：`app/api/teams.py` 全檔無任何 audit 呼叫，team CRUD 不產生 audit event → 無 audit schema 影響。
- **權限設定**：`config/permissions/*.yaml` 無任何 `validate` 相關條目 → 刪端點不需同步權限設定。
- **OpenAPI 快照測試**：`app/testsuite` 僅 `test_system_runtime_settings_api.py`、`test_system_log_api.py` 提到 openapi，皆與 teams 無關 → 刪端點不會撞快照。

### F8 ℹ️ 同類死碼但明確劃在範圍外

`teams.last_sync_at` 在 app 程式碼中**沒有任何寫入者**（寫 `last_sync_at` 的是 `lark_departments`／`lark_users`／`test_run_configs`），是 Lark 同步時代的遺留欄位；`Team`／`TeamResponse` 兩個 pydantic model 全 repo 無使用者。兩者都不是本次的「team settings Lark 依賴」，不動，於 design Non-Goals 記錄，避免後續 reviewer 反覆提問。

### F9 中 — proposal 對「舊 team 上傳路由」的描述會誤導

proposal 原文讓人以為空 token guard 之後 Lark 上傳路徑就封閉了。實際上 D6 刻意保留舊 team 的 token，因此 `attachments.py` 那 6 支上傳路由對**舊 team** 仍然會真的去打 Lark API（只是沒有 UI 入口，且 Lark 端表格早已無人維護）。

**處置**：proposal 與 design D4 明講此後果，並在後續 `purge-dead-lark-runtime-code` change 中處理。

### Round 1 結論

9 項發現，其中 F1／F3 會直接讓實作階段紅燈，F2 低估了回滾風險，F4 會擋 CI。全部已回寫 design / tasks / proposal。**核心方案（保留欄位、寫空字串、凍結 flag）未被推翻**：沒有任何一項發現指向「必須改用 migration」或「必須 drop 欄位」。

---

## Round 2（2026-07-27）

攻擊面：Round 1 修訂後的計畫，改攻「已修訂處是否引入新問題」與「Round 1 沒碰到的執行面」。

### F10 低 — 空字串寫入 `NOT NULL` 在三引擎的行為未實測

D1 的前提是「`''` 對 SQLite／MySQL 8／PostgreSQL 16 的 `VARCHAR NOT NULL` 皆合法」。這在標準 SQL 下成立（`NOT NULL` 拒絕的是 NULL，不是空字串），MySQL strict mode 也不拒絕空字串。但本專案的驗證任務（tasks 8.4）只跑一次性 SQLite。

**處置**：tasks 8.4 補一條——若本機 MySQL 容器可用則同步跑一次建立 team；若不可用，須在驗證報告的「待驗證」明確列出，不得默認為已驗證。（判定：低風險，不阻擋。）

### F11 中 — 測試 6.1 案例 5（PUT 不清空 token）在移除 `TeamUpdate.lark_config` 後，證明力來自「沒有程式碼會寫」而非「有防護」

案例 5 想證明「編輯 team 不會清掉 cold data」。但移除 `lark_config` 分支後，`update_team()` 根本沒有任何路徑會碰這兩個欄位——測試通過只代表當下沒人寫，不代表未來不會有人加回去。這仍然值得測（它是回歸網），但**不能**在驗證報告裡宣稱為「資料受到保護」。

**處置**：design D7 案例 5 補註「這是回歸網，不是防護機制」；若未來真需要防護，正解是資料庫層或 service 層的明確保護，不在本次範圍。

### F12 中 — `showValidationMessage()` 的移除範圍需要在 tasks 明確化

`app/static/js/team-management/main.js:537` 的 `showValidationMessage()` 只被 `validateLarkConnection()` 內的 4 個呼叫點使用（:395、:426、:429、:435），且函式本體操作的是 `#larkValidationResult`——該 DOM 節點隨 tasks 3.1 一併刪除。若只刪 `validateLarkConnection()` 而留下 `showValidationMessage()`，會留下一個操作不存在節點的孤兒函式。

**處置**：tasks 3.3 已含此項，補上明確的行號與判定依據。

### F13 低 — `team.subtitle` / `createFirstTeamHint` / `createFirstConfigHint` 改寫後的新文案未定稿

三處保留 key 但改寫文案的任務只寫「改為不含 Lark 的敘述」，沒有定稿字串。實作者可能寫出三語系語氣不一致的文案，或在 HTML 內留下與 JSON 不同步的 fallback 文字（這些位置的 `data-i18n` 元素內文本身就是中文 fallback）。

**處置**：tasks 5.2 補上三語系定稿字串，並要求 HTML/JS 內的 fallback 文字同步改寫（否則 i18n 未載入時仍會閃現舊的 Lark 字樣）。

### Round 2 結論

4 項發現，皆為執行面精確化，無一推翻 Round 1 的修訂。**沒有發現新的高風險項**。

---

## Round 3（2026-07-27）

攻擊面：假設前兩輪都被正確修訂，改攻「這個 change 本身該不該存在／範圍切法是否站得住」與「驗收條件是否可證偽」。

### F14 — 範圍切法質疑：把死碼清理切出去，是否讓本 change 的驗收無法閉環？

**攻擊**：本 change 宣稱「移除 team settings 的 Lark 依賴」，但落地後 `app/api/attachments.py` 仍有 6 支會讀 `team.wiki_token` 的路由、`test_result_cleanup_service` 仍有 Lark 分支。外部觀察者無法說「Lark 依賴已移除」。

**回應（範圍維持不變）**：本 change 的驗收條件是**使用者可觀察的行為**——建立/編輯 team 不需要 Lark 欄位、頁面上沒有 Lark 設定、API 不接受也不回傳 Lark 欄位、既有資料不受影響。這四點在本 change 內完全閉環且可測（tasks 6.1 六個案例 + 8.4）。殘留的後端路由屬於「移除前就已無人使用」的既有債務，其存廢不影響上述任何一條驗收。合併處理會讓 diff 從 ~15 檔擴大到 ~25 檔且跨越三個子系統，違反最小變更原則。**在 proposal 明確命名後續 change（`purge-dead-lark-runtime-code`）即為閉環承諾。**

### F15 — 決策質疑：`is_lark_configured` 凍結為 `false`，是否反而比移除欄位更糟？

**攻擊**：凍結成常數的欄位是「殭屍契約」——它永遠存在、永遠無意義，client 讀到它還是得猜。不如一次移除乾淨。

**回應（決策維持不變，但補強）**：兩害相權，殭屍欄位的成本是「client 多讀一個永遠為 false 的欄位」，移除欄位的成本是「做嚴格 schema 驗證的 client 直接壞掉，且我們無法枚舉所有 client」。前者可逆、後者不可逆。此外 design Open Question 1（`tcrt-app` skill 是否依賴）在**實作前**（tasks 0.1）就會有答案：若掃描確認無人依賴，可以在同一個 change 內升級為直接移除欄位——決策點已前置，不會卡住。

**處置**：design D3 補上這個「依 0.1 掃描結果可升級為直接移除」的條件分支，讓決策可證偽而非一廂情願。

### F16 — 驗收質疑：tasks 8.4 的「一次性 disposable DB 實測」是否可證偽？

**攻擊**：8.4 只列了四個檢查點，但沒說明如何構造「legacy token team」。若實作者用新程式碼建立 team（必然是空字串）再宣稱「legacy team 可正常列出」，等於什麼都沒驗到。

**處置**：tasks 8.4 明確要求 legacy team 必須以**直接 SQL INSERT 或 ORM 繞過 API** 的方式構造，帶入符合舊 validator 規則的真實格式 token（≥10 字、`tbl` 開頭），才能證明讀取路徑對舊資料相容。

### Round 3 結論

3 項發現：2 項是對既有決策的挑戰，經回應後**維持原決策**並補強其可證偽性；1 項（F16）是實質的驗收漏洞，已修補。

---

## Round 4（2026-07-27）

攻擊面：前三輪都聚焦在 team 設定本身。這一輪改問「**還有誰在讀 `GET /api/teams` 的回應**」——即前三輪都預設「只有 `team-management/main.js`」這個假設本身。

### F17 ℹ️ AI 助手有 `list_teams` 工具直接代理 `GET /api/teams/`——已確認不受影響

`app/services/assistant/tools_misc.py:42-49` 定義了 `list_teams` 工具，`path_template="/api/teams/"`，也就是助手在對話中列出 team 時走的正是本次要改的端點。這是前三輪完全沒有涵蓋的消費者。

實際檢查後**確認無影響**：該工具設有 `projection=("id", "name", "description", "test_case_count")`，回應在送進 LLM 之前就被投影過濾，`lark_config` 與 `is_lark_configured` 都不在投影清單內。移除欄位對助手是 no-op；`test_case_count` 等仍在投影中的欄位本次不動。

**附帶結論**：助手路徑因為有投影，所以**沒有**外洩 `wiki_token`；但 HTTP API 本身（任何已登入且可存取該 team 的使用者直接呼叫 `GET /api/teams/`）目前確實會拿到明文 `wiki_token`。proposal 中「消除明文外洩」的說法成立，範圍限於 HTTP API 直接呼叫者。

**處置**：無需修改計畫。記錄於此，避免後續 reviewer 重複提出同一疑問。

### F18 低 — 三處文案改寫在 tasks 中有兩個來源

任務 3.2／4.2／4.3 與 5.2 都描述了同一批文案的改寫，但只有 5.2 有定稿字串。兩處描述容易在實作時各改一半。

**處置**：3.2／4.2／4.3 改為「套用 5.2 的定稿字串」，定稿字串只留 5.2 一個來源。

### F19 ℹ️ `rollback.md` 提前到設計階段完成

F2 把 `rollback.md` 從建議升級為必要交付物後，把它留在實作任務清單裡意味著「回滾方案要等實作時才確定」——但它的內容完全由設計決定，沒有任何依賴實作的部分。

**處置**：於設計階段直接寫完 `rollback.md`（含備份要求與三引擎通用的修復 SQL），tasks 7.3 標記為已完成。

### Round 4 結論

3 項發現：F17 是前三輪的盲區（新的消費者），檢查後確認無影響；F18／F19 為文件一致性修補。**沒有發現需要改變核心方案的問題。**

---

## 收斂判定

四輪審查共 19 項發現：

- **會讓實作直接失敗**：F1（測試預期錯誤）、F3（測試授權方式錯誤）、F4（ruff F401）——皆已修正。
- **低估風險**：F2（回滾缺口是全域 500）——已改寫並產出 `rollback.md`。
- **會誤導 reviewer**：F6、F9、F11、F13、F16、F18——皆已補述或修補。
- **對核心決策的挑戰**：F14（範圍切法）、F15（凍結欄位 vs 移除欄位）——經回應後維持原決策，且 F15 已前置為 tasks 0.1 的可驗證決策點。
- **掃描後確認無影響**：F7（audit／權限設定／openapi 快照）、F8（同類死碼）、F10（三引擎空字串）、F17（助手 `list_teams` 工具）。

Round 4 未再產生任何需要改變方案的發現，且最後一輪的發現全部落在「文件一致性」層級。**判定審查收斂，計畫可進入實作。**

實作階段仍有兩個必須在動手第一步解決的未決項（已寫入 tasks 0.1 與 design Open Questions）：`tcrt-app` skill 是否依賴 `is_lark_configured`；以及若無依賴，是否把「凍結為 false」升級為「直接移除欄位」。
