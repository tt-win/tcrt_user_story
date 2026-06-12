# TCRT 自動化測試完整 Workflow

本文件說明 TCRT 自動化測試方案的端到端流程：從「用工具撰寫 test automation
scripts」，到「設定 GitHub Storage / Jenkins CI / Allure Report」，再到「透過
Test Run Set 觸發執行並回收結果」。

> 相關文件：[automation-hub-overview.md](automation-hub-overview.md)、
> [automation-provider-setup.md](automation-provider-setup.md)、
> [automation-webhook.md](automation-webhook.md)、
> [automation-security.md](automation-security.md)。

---

## 1. 整體架構

TCRT 本體是**中樞編排層**——它不寫腳本、不跑 runner、不算報告，而是把
Git（存腳本）、CI（跑腳本）、Allure（產報告）串起來。腳本的產製則由三個
**輔助工具**負責。

```
產製層（authoring）
  ① ai_steps_recorder         錄瀏覽器操作 → AI 產 Playwright「粗胚」腳本
  ② element_locator_generator 手寫/修補時，補單一穩定 locator
  ③ tcrt-automation-pomify    把粗胚「整形」→ POM + TCRT 版面 + marker 連結
                                       │  push、Hub → Rescan
                                       ▼
中樞層  TCRT Automation Hub
  smart-scan 自動發現腳本 → marker-sync 建立 script↔測試案例連結
  Suite 分組 · Coverage · Webhook(進/出) · MCP 唯讀 API · Test Run Set
                                       │  provider 框架（storage / ci / result）
                                       ▼
執行/儲存層（外部系統）
  Git(GitHub / 內網 LocalGit) · CI(Jenkins) · 報告(Allure)
```

### 三個輔助工具一覽

| 工具 | 位置 | 形態 | 輸入 → 輸出 |
|---|---|---|---|
| **ai_steps_recorder** | `~/code/ai_steps_recorder` | Chrome 擴充 | 錄製瀏覽器操作 → AI 產 Playwright 腳本（JS / Python / Pytest），可一鍵匯出 TCRT bundle（zip） |
| **element_locator_generator** | `~/code/element_locator_generator` | Chrome 擴充 | 點選頁面元素 → AI 產 4 種 locator（Playwright / CSS / XPath / Selenium），附穩定度評分與唯一性驗證 |
| **tcrt-automation-pomify** | `tools/skills/tcrt-automation-pomify` | AI agent skill | 粗胚 Python 腳本 → POM 重構 + TCRT 版面 + `@pytest.mark.tcrt` 標記（Python only） |

### 端到端一覽

```
撰寫腳本 → 推上 GitHub → 設定 3 個 Provider → Rescan 掃描 → 建 Suite（自動建 CI job）
        → Test Run Set 綁 Suite → Run as Automation → Jenkins 跑 → 狀態+Allure 回流 → 看結果
```

---

## 2. 前置作業（一次性，部署層）

於 TCRT 伺服器設定以下兩項後重啟服務：

| 設定 | 來源 | 說明 |
|---|---|---|
| `AUTOMATION_PROVIDER_ENCRYPTION_KEY` | 環境變數 | base64 編碼的 32-byte 金鑰，用於加密 provider 憑證（AES-256-GCM） |
| `public_base_url` | `config.yaml`（或環境變數 `PUBLIC_BASE_URL` / `APP_BASE_URL`） | TCRT 對外可達網址，Jenkins 必須能連回。內網請填 LAN IP（如 `http://10.80.1.x:port`） |

> ℹ️ `public_base_url` 設好後，TCRT 會自動產生 inbound webhook URL，並在建立
> Jenkins job 時自動烤進 job XML（`TCRT_WEBHOOK_URL`，於 log 中遮罩）。

---

## 3. 階段一：以工具撰寫 test automation scripts

1. **錄製或產生腳本草稿** — `ai_steps_recorder`
   - 錄下瀏覽器操作 → AI 產出 Playwright 腳本。**要走 pomify 整形，這裡選
     Python / Pytest 格式**。
   - AI 後端可選本地 LM Studio（免金鑰）或 OpenRouter（雲端，Claude/GPT/Gemini…）。
   - 完成後在 result viewer 點 **Download TCRT Bundle** → 取得 zip（含
     `tcrt-automation.yml`、`tests/`、`requirements.txt`、README、`session.json`）。

2. **補強元素定位（手寫或修補時）** — `element_locator_generator`
   - 在實際頁面點選元素 → AI 產出 4 種格式 locator，附穩定度評分與唯一性驗證
     → 複製貼入腳本。

3. **整形 + 連結測試案例** — `tcrt-automation-pomify`（AI agent skill）
   - 在支援 skill 的 agent（Claude Code / Cursor…）對腳本下指令「pomify for TCRT」。
   - skill 會：① 重構成 Page Object Model（selector 進 `pages/`）；② 改檔名/目錄
     符合 smart-scan 規則；③ 加上 `@pytest.mark.tcrt(...)` 標記連結手動測試案例。
   - 若 agent 掛了 **TCRT MCP**，skill 會用 MCP 即時解析 team / 測試案例 / ticket
     對應的 TC ID（不杜撰）。

標記範例（連結到手動測試案例）：

```python
import pytest

@pytest.mark.tcrt("TC-LOGIN-01", link_type="primary")
def test_user_can_log_in(page):
    ...

# 注意：DB 內帶點號的編號 TCG-100558.020.010
#      在 marker 必須改用 dash：TCG-100558-020-010
```

> Python 用 `@pytest.mark.tcrt(...)`；JS/TS 用註解 `// tcrt: TC-001 (primary)`。

整形後的標準版面（TCRT smart-scan 可自動發現）：

```
repo-root/
├── tests/
│   ├── api/        # pytest API             → PYTEST
│   ├── ui/         # Playwright sync+pytest  → PYTEST
│   └── e2e/        # Playwright async        → PLAYWRIGHT_PY_ASYNC
├── pages/          # Page Object（被 smart-scan 排除）
├── conftest.py     # 註冊 tcrt marker（排除）
└── tcrt-automation.yml   # manifest（可選但建議，可覆寫 scan_path）
```

---

## 4. 階段二：設定 GitHub repo（Storage Provider）

1. 將整形後的 repo（`tests/`、`pages/`、`tcrt-automation.yml`、`conftest.py`）
   推上 GitHub。
2. TCRT → **Automation Provider Settings** → 新增 **Storage Provider**：
   - 類型選 `storage:github`。
   - 填 owner、repo、default_branch、scan_path。
   - 認證二選一：
     - **PAT**（fine-grained）：read Contents + write Pull requests + read/write Actions。
     - **GitHub App**：app_id、installation_id、private_key（PEM）。
3. 點 **Test connection**（呼叫 `health_check`）確認綠燈。

> 💡 氣隙 / 內網環境可改用 `storage:local_git`（內部 git / Gitea / GitLab），以本機
> 工作目錄 + SSH key 操作。

---

## 5. 階段三：設定 Jenkins（CI Provider）

1. TCRT → **Automation Provider Settings** → 新增 **CI Provider**：
   - 類型選 `ci:jenkins`。
   - 填 base_url、認證（api_token + username，或 trigger_token）。
   - 視需要開啟 csrf_protection_enabled、auto_manage_views，設定
     job_name_template / view_name_template。
   - `view_name_template` 可用 `{team_name}`、`{team_slug}`、`{team_id}`；TCRT
     會在建立或重新整理 suite job 時依當前 team 展開，並把 job 加進該 view。
2. 點 **Test connection** 確認綠燈。

> ⚠️ **Jenkins node label 陷阱**：程式預設的 Jenkins 執行 label fallback 是
> `any`（見 `run_service.py`）。但若你的 Jenkins 只有 **Built-In node**（例如
> 內網 10.80.1.49 這台），label 必須是 `built-in`，用 `any` 或留空會讓 build
> 卡在「Still waiting to schedule task」永遠不執行。建立 Suite job 前請確認
> 範本/設定使用 `built-in`。

---

## 6. 階段四：設定 Allure（Result Provider）

1. TCRT → **Automation Provider Settings** → 新增 **Result Provider**：
   - 類型選 `result:allure`。
   - 填 base_url、project、run_url_template、embed_mode（link 或 iframe）、dashboard_url。
2. 點 **Test connection** 確認綠燈。

> ℹ️ TCRT 扮演 **Allure proxy**：首次 CI run 時自動建立 Allure project；CI 產出的
> `allure-results` 由 TCRT 代為轉發給 Allure 產報告，CI 端不需直連 Allure。

---

## 7. 階段五：掃描腳本 + 建立 Suite

1. 進 **Automation Hub → Suites 分頁 → Rescan**。
   - smart-scan 依 `tcrt-automation.yml` 的 scan_path 掃描，辨識每支腳本的
     `script_format`。
   - **marker-sync** 自動依 `@pytest.mark.tcrt` 建立 script 與測試案例的連結
     （`created_by=marker-sync`，是 `automation_script_case_links` 的唯一寫入路徑）。
2. （可選）Smart Scan 依目錄提出 suite 分組建議（規則式，可選 LLM 加強命名）。
3. 建立 **Suite**（把多支腳本打包成測試套件）。
   - 建立當下，TCRT 會**自動在 Jenkins 建對應 Pipeline job**：以 Jinja2 範本
     `app/services/automation/templates/jenkins-suite-config.xml.j2` 透過
     `createItem` 產生。
   - 若 Jenkins provider 開啟 `auto_manage_views`，同一步會建立/補齊 team view
     並把 suite job 加入 view。
   - job XML 會烤入 `GIT_URL`、`GIT_BRANCH`、`GIT_TOKEN` 與 `TCRT_WEBHOOK_URL`，
     並在 post-build 封存 `allure-results/**`、回呼狀態 webhook。

---

## 8. 階段六：綁定 Test Run Set + 執行 test run

1. 建立或開啟一個 **Test Run Set**。
2. 綁定要跑的自動化 Suite（存於欄位 `automation_suite_ids`）。
3. 在 Test Run Set detail 點 **Run as Automation**。
   - TCRT 逐一觸發各 Suite 的 Jenkins job。
   - 觸發前會重新整理 Jenkins suite job；若 `auto_manage_views=true`，也會補齊
     team view 與 job membership。
   - 每個 Suite 產生一筆 `automation_runs`（狀態 `QUEUED`，帶 `tcrt_correlation_id`
     與 `test_run_set_id`）。
4. Jenkins job 執行：用 `GIT_TOKEN` clone repo → 跑 pytest / playwright → 產出
   `allure-results/` → 封存 artifact。

> 💡 另一種觸發方式：將 inbound webhook 綁定某 Suite，對
> `POST /api/v1/webhooks/ci/{token}/trigger` 發一次請求即可觸發（適合外部排程 /
> CI 串接）。

---

## 9. 階段七：狀態與報告回流

1. **狀態同步**（三種來源，互補）：
   - Inbound webhook：CI 完成後 `POST /api/v1/webhooks/ci/{token}/run-status`
     回報最終狀態（HMAC-SHA256 簽章、冪等、限流）—— 即 `TCRT_WEBHOOK_URL` 指向處。
   - 輪詢：TCRT 背景每 60 秒呼叫 Jenkins `get_run_status`。
   - run 狀態流轉：`QUEUED → RUNNING → SUCCEEDED / FAILED / CANCELLED`。
2. **Allure 報告回收**：TCRT 偵測 run 結束 → 從 Jenkins artifact 下載
   `allure-results.zip` → allure_proxy 解壓 → 轉發 Allure → 產報告 → 把
   `report_url` 寫回 `automation_runs`。
3. **檢視結果**：
   - Test Run Set detail：run 歷史 + Allure 報告連結。
   - Automation Hub → Coverage 分頁：覆蓋率、未涵蓋案例、stale 腳本、趨勢。
   - （AI 助手）可透過 MCP 唯讀 API 查 automation-scripts / runs / coverage。

---

## 10. 一頁速查：三個 Provider

| Slot | 類型 | 關鍵設定 | TCRT 角色 |
|---|---|---|---|
| Storage | `storage:github` / `storage:local_git` | owner/repo/branch/scan_path、PAT 或 App | 讀腳本、建 PR |
| CI | `ci:jenkins` | base_url、token、label=`built-in` | 自動建 job、觸發、查狀態、抓 artifact |
| Result | `result:allure` | base_url、project、template | 當 Allure proxy 代轉報告 |

---

## 11. 已知陷阱與注意事項

- **Jenkins label 必須是 `built-in`**（僅 Built-In node 的環境），否則 build 卡住不跑。
- **marker 連結是唯一寫入路徑**：手動建立連結的 API 與 UI 已移除，測試案例覆蓋
  只能在程式碼用 `@pytest.mark.tcrt(...)` 宣告。
- **帶點號的 TC 編號要改 dash**：`TCG-100558.020.010` → marker 寫 `TCG-100558-020-010`。
- **pomify 僅支援 Python**：recorder 若輸出 JS/TS，無法走 pomify 整形。
- **Runs 已移至 Test Run Set**：Automation Hub 舊的 Runs 分頁已移除，執行歷史看
  Test Run Set detail。
