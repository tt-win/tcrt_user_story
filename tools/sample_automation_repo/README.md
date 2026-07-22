# Sample Automation Repo

可以拿來給 TCRT Automation Hub 連接的範例 git repo 結構。**這不是 TCRT 自己跑的測試**，是給「使用 TCRT 的人」當作他們自動化測試 repo 的最小參考骨架。

## 為什麼存在這個資料夾

- 開發 / demo TCRT 的人需要一個真的存在的 git repo 拿來連 storage provider
- 想驗證 smart-scan 的格式判斷、test 名稱解析、conftest / __init__.py 排除邏輯
- 給新使用者快速理解「我自家的測試 repo 該長什麼樣才 TCRT 抓得到」

## 如何使用

1. 把整個 `tools/sample_automation_repo/` 內容複製或 push 到一個獨立的 GitHub repo
2. 在 TCRT 的 **Automation Hub → Git Sources → Add Git Repo** 設定：
   - `owner` / `repo`：剛剛 push 的 repo
   - `default_branch`：`main`
   - `scan_path`：`tests/`（已對齊 storage provider 預設）
   - `auth_method`：`pat`
   - PAT：填一個有 `repo` scope 的 GitHub Personal Access Token
3. 跑 **Smart Scan**，應該偵測到：
   - PYTEST：4 個（`tests/api/test_user_auth.py`、`test_admin_apis.py`、`ticket_api_test.py`、`user_profile_test.py`）
   - PLAYWRIGHT_JS：3 個（`tests/ui/login.spec.ts`、`homepage.spec.ts`、`checkout.test.js`）
   - PLAYWRIGHT_PY_ASYNC：2 個（`tests/e2e/flow_purchase.py`、`flow_signup.py`）
   - 被排除：`__init__.py` × 3、`conftest.py` × 1

## TCRT storage provider 的格式判斷規則

對應 `app/services/automation/providers/github_storage.py:infer_script_format`：

| 副檔名 / 命名 | 判定格式 |
|---|---|
| `.spec.ts` / `.test.ts` / `.spec.js` / `.test.js` | `PLAYWRIGHT_JS` |
| `.py` 且檔名 `test_*` 或 `*_test.py` | `PYTEST` |
| 其他 `.py` | `PLAYWRIGHT_PY_ASYNC` |
| 其餘 | `OTHER`（不會被 smart-scan 預設 pattern 收）|

Smart-scan 預設 include patterns（`DEFAULT_INCLUDE_PATTERNS`）：

```
^test_.*\.py$
.*_test\.py$
.*\.spec\.(ts|js)$
.*\.test\.(ts|js)$
```

排除：`__init__.py`、`conftest.py`、`conftest.js`、`conftest.ts`。

## 內容說明

```
tests/
├── api/                         # pytest 風格的 API 測試
│   ├── __init__.py              # smart-scan 排除
│   ├── conftest.py              # smart-scan 排除
│   ├── test_user_auth.py        # ✅ test_ 前綴 → PYTEST
│   ├── test_admin_apis.py       # ✅ test_ 前綴 → PYTEST
│   ├── ticket_api_test.py       # ✅ _test 後綴 → PYTEST
│   └── user_profile_test.py     # ✅ _test 後綴 → PYTEST
├── ui/                          # playwright TS / JS
│   ├── login.spec.ts            # ✅ .spec.ts → PLAYWRIGHT_JS
│   ├── homepage.spec.ts         # ✅ .spec.ts → PLAYWRIGHT_JS
│   └── checkout.test.js         # ✅ .test.js → PLAYWRIGHT_JS
└── e2e/                         # playwright python async
    ├── __init__.py              # smart-scan 排除
    ├── flow_purchase.py         # ✅ 純 .py 非 test_* → PLAYWRIGHT_PY_ASYNC
    └── flow_signup.py           # ✅ 同上
```

每個檔案都有真實的 test function / `test('...', ...)` 呼叫，smart-scan 的 `_extract_test_metadata` 可以解析出 test 名稱。
