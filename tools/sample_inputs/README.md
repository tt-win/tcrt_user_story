# Sample inputs for `tcrt-automation-pomify`

這些檔案是「餵給 skill 之前的**原始** messy 程式碼」，用來練習 / 驗證 skill 的 refactor 流程。
每支都涵蓋不同的 framework、anti-pattern 或輸入情境。

## 單檔樣本

| 檔案 | Framework | 用途 / 涵蓋的反模式 |
|---|---|---|
| `messy_signup_login.py` | Playwright async | 1 個 `main()` 塞 4 個情境（signup、登出再登入、錯誤密碼、鎖帳）；`wait_for_timeout`、`assert "... in page.content()"`、重複 selector、無 `test_` 前綴 |
| `messy_checkout_e2e.py` | Playwright async | 4-page 結帳流程（搜尋→購物車→出貨→付款→確認）；happy path + 信用卡拒絕；多頁重複輸入欄位 selector |
| `messy_pytest_sync_login.py` | Playwright sync + pytest | 4 個 `test_*` 在 `class TestLogin:` 內；fixture 寫在檔案裡（應搬到 conftest.py）；`time.sleep`、inline selector |
| `messy_selenium_smoke.py` | Selenium + pytest | `By.XPATH` + `time.sleep`；登入後 admin 流程；3 個 `test_*` 都重複登入 |
| `messy_api_users.py` | Pure API（requests） | **無 UI** — skill 應判定不需 POM，僅 emit `tests/api/test_*.py` |
| `messy_pasted_snippet.py` | Playwright sync | 極短貼上片段、無 `test_` 前綴、函式叫 `smoke`；測試「貼上模式」 |

## 資料夾樣本（batch 模式）

`legacy_e2e_suite/` — 3 個小檔案混在一起，測試 skill 對整個目錄的批次處理：

| 檔案 | Framework | 特殊點 |
|---|---|---|
| `test_old_search.py` | Playwright async | 用 `asyncio.run(__name__ == "__main__")` 直跑 |
| `test_old_profile.py` | Playwright **混用 async + sync** | skill 應判定為 Playwright async，把 sync 那條加 `TODO(pomify): verify async conversion` 註解 |
| `test_old_banner.py` | Selenium | `By.XPATH` + 2018 風格 `time.sleep` |

## 怎麼丟給 skill

```bash
# 單檔
「Pomify tools/sample_inputs/messy_checkout_e2e.py for TCRT」

# 整個資料夾
「Refactor tools/sample_inputs/legacy_e2e_suite/ into POM + TCRT format」

# 純 API（不應生 pages/）
「Pomify tools/sample_inputs/messy_api_users.py for TCRT」

# 貼上模式（無檔案路徑）
# 貼上 messy_pasted_snippet.py 的內容後：「把這段 pomify」
```

## 對應 skill 內 Step 的驗證點

| Skill step | 對應樣本 |
|---|---|
| Step 1（解析輸入）| `messy_pasted_snippet.py`（無檔名）|
| Step 2（detect framework）| 全部 9 支各落一類 |
| Step 3（萃取 page interactions）| `messy_checkout_e2e.py`（4 頁 PO）|
| Step 4（套 TCRT 命名）| `messy_signup_login.py`（單檔無 test_ 前綴 → 重命名 + 加 `__init__.py`）|
| Step 5（生 PO + `__init__.py`）| 全部 |
| Step 7（@pytest.mark.tcrt）| 全部 |
| Step 9（印 summary）| 全部 |
| Step 10（self-validate）| 全部 |
| **無 POM 路徑** | `messy_api_users.py`（偵測「無 UI」分支）|
| **batch 模式** | `legacy_e2e_suite/` |
| **mixed async/sync** | `legacy_e2e_suite/test_old_profile.py` |
