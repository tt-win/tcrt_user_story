# 紅隊審查紀錄

延續 `remove-team-lark-repo-settings` 的作法：對抗式自審，每項發現需以實際掃描證據支持。本 change 的攻擊重點與前一個不同——刪程式碼的風險不在設計，而在「你確定它真的沒人用嗎」。

---

## Round 1（2026-07-27）

攻擊面：每一項「這是死碼」的宣稱。

### F1 ✅ 證實 — `test_runs.py` 的 8 支路由確實是壞的，不只是沒人用

不接受「靜態 grep 看不到 `table_id` 欄位」這種間接推論，直接在 runtime 檢查：

```
TestRunConfig.__table__.columns → [id, team_id, name, description, test_version,
  test_environment, build_number, related_tp_tickets_json, tp_tickets_search,
  test_case_set_ids_json, notifications_enabled, notify_chat_ids_json,
  notify_chat_names_snapshot, notify_chats_search, status, start_date, end_date,
  total_test_cases, executed_cases, passed_cases, failed_cases, created_at,
  updated_at, last_sync_at]
hasattr(TestRunConfig, 'table_id') → False
```

8 支路由全部走 `config.table_id`，因此對**任何** team 都是 `AttributeError` → 500。移除它們不可能造成回歸。

### F2 ⚠️ 中 — `app/models/__init__.py` 若有 re-export，刪 `models/test_run.py` 會炸掉整個 app

這是刪模組最典型的地雷。實際檢查：`app/models/__init__.py` 是**空檔**，沒有任何 re-export。精確 grep（排除 `test_run_config` / `test_run_set` / `test_run_item` 等同前綴模組）確認 `app/models/test_run.py` 的唯一 importer 就是 `app/api/test_runs.py`，`TestRunFieldMapping` 與 `TestRunFilter` 全 repo 無其他使用者。

**處置**：可安全刪除；驗證步驟保留「app 可正常 import」作為最後保險。

### F3 低 — OpenAPI 快照測試可能因路由消失而失敗

`test_system_runtime_settings_api.py:117` 與 `test_system_log_api.py:173` 都會抓 `/openapi.json`。實際檢查後確認兩者都是 `test_openapi_excludes_*`——斷言**特定系統端點不在** paths 中，不是路由總表快照。移除其他路徑不影響。

### F4 ⚠️ 中 — 下載代理不是死碼，且有 spec 明文保護

原本可能被順手當成「Lark 相關就一起砍」的目標。實際上：

- `openspec/specs/async-runtime-performance/spec.md:30` 明文規定其上游狀態碼映射（401→401、404→404、其他→502、逾時 30 秒→504、連線錯誤→502）與 Content-Disposition 傳遞規則。
- `app/testsuite/test_attachment_proxy_contract.py` 以 monkeypatch `get_lark_client_for_team` 的方式鎖住這些映射。
- 前端 3 處使用該端點。

**處置**：明確列為保留（design D3、tasks 2.2），且 `get_lark_client_for_team()` 必須一起留下。這也是本 change 不兌現前一個 change「一併封閉 Lark 出口」說法的原因——那句話把「清死碼」和「關閉服務既有資料的活路徑」混為一談了，本 change 只做前者，並在 spec 中寫下後者的前置條件。

### F5 低 — 刪路由後的未使用 import 會擋 CI

`teams.py` 已經踩過一次同名 `settings` 遮蔽。`test_run_items.py` 有完全相同的結構：模組級 `from app.config import settings`（:20）只被要刪的 helper 使用，另有函式級 re-import（:1605）供 Jira 摘要使用。

**處置**：刪除模組級 import、保留函式級；以 ruff 逐檔驗證（實作時確認 HEAD 上該檔為 All checks passed，故任何錯誤都是本次造成）。

### Round 1 結論

5 項發現：F1／F2／F3 證實了刪除的安全性，F4 攔下一個會造成實質回歸的過度刪除，F5 是已知模式的重演。核心方案不變。

---

## Round 2（2026-07-27，實作後）

攻擊面：實作結果本身——「你刪完之後，剩下的東西還對嗎」。

### F6 ✅ Route table 實測

以 `app.main` 實際載入後列舉 route table，`/api/teams/{team_id}/test-runs/` 下只剩：

```
/api/teams/{team_id}/test-runs/{config_id}/generate-html
/api/teams/{team_id}/test-runs/{config_id}/report
```

`/api/attachments/` 下只剩 `.../attachments/download`。`/api/teams/{team_id}/testcases/.../attachments` 那批仍在——那是 `test_cases.py` 的本機附件路徑，不是被刪的 Lark 路由，兩者名稱相近但不同檔案。

### F7 ✅ 剩餘 Lark 出站路徑盤點

`rg "LarkClient\(|wiki_token|set_wiki_token" app/api app/services`（排除 `lark_*` 模組）的完整結果只有三處：

1. `attachments.py`（下載代理回退，含空 token guard）— 刻意保留
2. `test_result_cleanup_service.py`（legacy 附件解除關聯，含空 token guard）— 刻意保留
3. `lark_users.py`（組織層人員查詢，只用全域 app_id/secret，與 team token 無關）— 不在範圍

沒有任何非預期殘留。

### F8 低 — `test_runs.py` 的 docstring 若不改會誤導

原 docstring 寫「直接操作 Lark 多維表格」。檔案現在只剩報告端點，docstring 必須同步改寫，否則下一個讀者會以為還有 Lark 路徑。`attachments.py` 同理。

**處置**：兩個檔案的 docstring 都已改寫並指向新 capability。

### Round 2 結論

3 項發現皆為實測確認，無新風險。審查收斂。

---

## Round 3（2026-07-27，取得生產資料證據後）

攻擊面：Round 1 F4 把「保留下載代理」當成結論。這一輪反過來攻擊那個結論——**如果它其實沒有任何資料可以服務，保留它就只是包袱**。

### F9 ⚠️ 中 — 模糊關鍵字掃描會給出假陽性，差點誤判

第一版掃描用 `lark` 當關鍵字，`test_run_items.execution_results_json` 命中 2 筆，看起來像「還有 Lark 附件，不能關」。逐筆檢視後發現是檔名為 `Lark20260424-164715.mp4`、`Lark20260402-104834.mp4` 的**本機**檔案——使用者用 Lark app 錄的螢幕錄影，上傳到本機附件目錄，metadata 帶 `relative_path`／`absolute_path`，與 Lark Drive 毫無關係。

改用精確標記（`file_token` / `larksuite` / `feishu`）後 test run 側命中 **0**。

**教訓**：判斷「還有沒有 X 資料」時，關鍵字要挑不會出現在使用者資料裡的技術標記。`lark` 會出現在檔名，`file_token` 不會。

### F10 ⚠️ 中 — test case 側確實還有 2 筆真 Lark 附件，但它們不走代理

`test_cases.attachments_json` 有 2 筆帶 `file_token` 與 `open.larksuite.com/open-apis/drive/v1/medias/...` URL。若只看這個數字會得出「不能關」的結論。

實際追前端：`test-case-management/attachments.js:220-222` 對帶 `url` 的附件是直接輸出 `<a href="${url}" target="_blank">`，**從不呼叫本系統的下載代理**；代理只被 `test-run-execution/render.js`（2 處）與 `results.js`（1 處）呼叫，而 test run 側的精確命中是 0。

因此移除代理的 Lark 回退，不會讓任何目前取得得到的附件變成取不到——那 2 筆 test case 附件的取得方式（直連 Lark、需使用者自己有 Lark 登入）完全不變。

### F11 ✅ 意外發現 — cleanup service 的 Lark 分支本來就會拋例外

`_cleanup_item_files()` 執行 `json.loads(upload_history_json).get('uploads', [])`，但生產資料的實際結構是 **list**：`[{"uploaded": 1, "at": "...", "files": [...]}]`。對 list 呼叫 `.get` 會拋 `AttributeError`，被外層 except 吞掉並記為 error log。

也就是說：這個服務不只是「只服務 legacy 資料」，它是**每次刪除帶附件的 item 都在 log 裡製造一筆假錯誤**，且從未真正清理過任何東西。這強化了刪除整個服務（而非只拿掉 Lark 呼叫）的決定。

### F12 ⚠️ 中 — 刪掉 cleanup service 會不會讓本機檔案沒人清？

這是刪服務最該問的問題。逐行檢視 `cleanup_test_run_config_files` / `cleanup_test_run_item_files` / `_cleanup_item_files` / `_remove_files_from_test_case*`：整個服務**沒有任何一行**觸碰本機檔案系統，它從頭到尾只做「解析 upload history → 呼叫 Lark 解除附件關聯」。本機檔案的刪除在 `delete_test_run_config_cascade_sync` 與 team 刪除流程（`teams.py` 的 `shutil.rmtree`）。

另外確認 6 個呼叫點的回傳值只進 log，不進任何 API 回應，前端也沒有讀 `cleaned_files_count` 的地方 → 刪除不改變對外契約。

### Round 3 結論

4 項發現：F9 攔下一個會導致錯誤結論的掃描方法問題，F10 把「有 2 筆 Lark 資料」正確歸類為「不影響本次決策」，F11／F12 支持把整個 cleanup service 刪掉而非局部修補。**Round 1 F4 的保留結論在取得資料證據後被正當地推翻**——這正是當初把它列為「前置條件」而不是「永久保留」的用意。
