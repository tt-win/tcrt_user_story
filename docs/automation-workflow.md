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
  Rescan 同步發現腳本 → marker-sync 建立 script↔測試案例連結
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
     符合 Rescan 掃描規則；③ 加上 `@pytest.mark.tcrt(...)` 標記連結手動測試案例；
     ④ 把寫死的環境設定正規化成 `TCRT_VARS` 宣告 + settings loader（詳見第 10 節）。
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

整形後的標準版面（TCRT Rescan 可自動發現）：

```
repo-root/
├── tests/
│   ├── api/        # pytest API             → PYTEST
│   ├── ui/         # Playwright sync+pytest  → PYTEST
│   └── e2e/        # Playwright async        → PLAYWRIGHT_PY_ASYNC
├── pages/          # Page Object（被掃描規則排除）
├── conftest.py     # 註冊 tcrt marker + tcrt_env 設定 loader（排除）
├── .gitignore      # 忽略 tcrt-env.json + 真實 config（值不進 git）
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
   - 視需要開啟 csrf_protection_enabled，設定 job_name_template / view_name_template。
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
   - Rescan 依 `tcrt-automation.yml` 的 scan_path 掃描，辨識每支腳本的
     `script_format`。
   - **marker-sync** 自動依 `@pytest.mark.tcrt` 建立 script 與測試案例的連結
     （`created_by=marker-sync`，是 `automation_script_case_links` 的唯一寫入路徑）。
2. 建立 **Suite**（把多支腳本打包成測試套件）。
   - 建立當下，TCRT 會**自動在 Jenkins 建對應 Pipeline job**：以 Jinja2 範本
     `app/services/automation/templates/jenkins-suite-config.xml.j2` 透過
     `createItem` 產生。
   - 同一步會建立/補齊 team view（`TCRT_{team_name}`，一律自動、無開關）並把
     suite job 加入該 view。
   - job XML 會烤入 `GIT_URL`、`GIT_BRANCH`、`GIT_TOKEN` 與 `TCRT_WEBHOOK_URL`，
     並在 post-build 封存 `allure-results/**`、回呼狀態 webhook。

---

## 8. 階段六：綁定 Test Run Set + 執行 test run

1. 建立或開啟一個 **Test Run Set**。
2. 綁定要跑的自動化 Suite（存於欄位 `automation_suite_ids`）。
3. 在 Test Run Set detail 點 **Run as Automation**。
   - TCRT 逐一觸發各 Suite 的**主 Jenkins job**（`tcrt_{team}_{suite}`）。
   - 觸發前會重新整理 Jenkins suite job，並一併補齊 team view 與 job membership。
   - 每個 Suite 產生一筆 `automation_runs`（狀態 `QUEUED`，帶 `tcrt_correlation_id`
     與 `test_run_set_id`）。
4. Jenkins job 執行：用 `GIT_TOKEN` clone repo → 跑 pytest / playwright → 產出
   `allure-results/` → 封存 artifact。

> 💡 另一種觸發方式：將 inbound webhook 綁定某 Suite，對
> `POST /api/v1/webhooks/ci/{token}/trigger` 發一次請求即可觸發（適合外部排程 /
> CI 串接）。webhook 觸發走 Suite 的**專屬 webhook job**（`tcrt_{team}_{suite}_hook`，
> 首次觸發時自動建立），與 Test Run Set 用的主 job 分開 build 歷史與佇列；其報告也
> 寫入獨立的 Allure project（`…-webhook`），趨勢不與 Test Run Set 執行混在一起。

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

## 10. 環境與變數設定（Environment & variable config）

腳本常常需要**因環境而異**的設定值（Prod / SIT / dev 各一份的 base URL、API
token…）。TCRT 的做法是：**值統一存在 TCRT，不進 git**；腳本只在原始碼宣告**變數
名稱**，執行時由 TCRT 把當下環境的值注入進去。

### 端到端流程

```
① init / pomify 宣告 TCRT_VARS（只有名稱，無值）
        ▼
② Automation Hub → Settings → Environments 定義環境 + shared params（共用值）
        ▼
③ Scripts tab → Script view → Configure variables 設 per-script override（覆寫值）
        ▼
④ Test Run Set 觸發時選環境（沒選 → set 預設 → team catalog 預設）
        ▼
⑤ TCRT 組 bundle，以單一遮罩參數 TCRT_ENV_BUNDLE 透過 HTTP POST body 傳給 CI
        ▼
⑥ Jenkins suite job 把非空 bundle 寫進 repo/tcrt-env.json（workspace，gitignored）
        ▼
⑦ 腳本的 settings loader 依「當前測試檔的 repo 相對路徑」取出對應 namespace，
   以固定變數名讀值
```

### ① 宣告 `TCRT_VARS`（原始碼，只有名稱）

`tcrt-automation-init`（搭骨架時）與 `tcrt-automation-pomify`（整形既有腳本時）
會在測試模組頂層產生 module-level 的 `TCRT_VARS` 常數。它是一個 list，元素可為
字串（變數名，等同 `secret=False, required=True`）或 dict
（`{"name", "secret", "required", "description"}`）。變數名須符合
`^[A-Za-z_][A-Za-z0-9_]*$`，明顯的機密（token / password / key）標 `secret: True`：

```python
# 只宣告名稱，絕不寫值
TCRT_VARS = ["BASE_URL", {"name": "API_TOKEN", "secret": True, "required": True}]
```

> Rescan 時 TCRT smart-scan 會 AST 解析各檔的 `TCRT_VARS`（**fail-open**：非字面值
> /格式錯 → 警告並略過該檔），把宣告存到該腳本上。沒有 `TCRT_VARS` 的舊腳本不受
> 影響（向後相容）。pomify/init 也會幫忙把真正的 config 檔（`tcrt-env.json`、
> `config/*.yaml`、`.env`）加進 `.gitignore`。

### ②③ 在 TCRT 設值（共用 + per-script 覆寫）

值分兩層，**有效值 = per-script override（若有）否則 environment shared param**：

| 層級 | 設定位置 | 範圍 |
|---|---|---|
| 環境共用 shared params | Automation Hub → **Settings → Environments** | 該 team 目錄下所有腳本，依環境 |
| per-script override | Scripts tab → **Script view → Configure variables** | 單一腳本，依環境 |

機密值（`secret: True`）在 TCRT **加密儲存（encrypted at rest）**。所有值都**只**
存在 TCRT，**絕不 commit 進 git**。

### ④⑤⑥ 觸發、注入、落地

從 **Test Run Set** 觸發 Suite 時選環境（沒選則退回 set 預設、再退回 team catalog
預設）。TCRT 解析每支腳本的有效值，組出一份**依腳本 `ref_path` 命名空間化**的 bundle：

```json
{
  "tests/ui/test_login.py":  { "BASE_URL": "https://sit.example", "API_TOKEN": "…" },
  "tests/api/test_orders.py": { "BASE_URL": "https://sit.example" },
  "__tcrt__": { "environment": "SIT", "secret_keys": ["API_TOKEN"] }
}
```

bundle 另含一個**保留、非 `ref_path`** 的 `__tcrt__` 項，存
`{"environment": "<所選環境名>", "secret_keys": [<宣告為 secret 的名稱>]}`，僅供
loader 在 log 顯示「目前用哪個環境」並遮罩機密（見下方 ⑧）。`ref_path` 一律是 `.py`
路徑，故此 key 不會相撞。

這份 bundle 以**單一遮罩參數 `TCRT_ENV_BUNDLE`**（Jenkins `PasswordParameter`，於
log 遮罩）透過 **HTTP POST body** 傳給 CI。Jenkins suite job 把**非空** bundle 寫進
**`repo/tcrt-env.json`**（workspace，已 gitignored）——**不**把機密 export 進
shell 環境變數。bundle 為空（沒選環境 / 無變數）時則不寫該檔。

### ⑦ 腳本端讀取（settings loader）

腳本端用一個小型 settings loader（pytest fixture 或 helper）讀 `tcrt-env.json`，
依**當前測試檔的 repo 相對路徑**選出對應 namespace，再以**固定變數名**取值。兩種
等價形態，擇一即可（pomify / init 皆會產生）：

```python
# (a) conftest.py 的 tcrt_env fixture
def test_login(page, tcrt_env):
    base_url = tcrt_env["BASE_URL"]          # 固定名稱；值來自 TCRT

# (b) tcrt_env.py helper（適合不吃 fixture 的 async flow）
from tcrt_env import load_tcrt_env
cfg = load_tcrt_env(__file__)
base_url = cfg["BASE_URL"]
```

沒選環境時 `tcrt-env.json` 不存在，loader 回傳空集合並退回 `os.environ`；沒有
`TCRT_VARS` 的測試完全不受影響。

### ⑧ 執行時在 Jenkins log 顯示所用環境

產生的 `conftest.py` 透過 **`pytest_report_header`** hook，在每次執行的**最上方**印出
目前所用環境與各變數的值（**非機密印明文、機密印 `***(secret)`**，依 `__tcrt__.secret_keys`
遮罩），讓操作者在 **Jenkins console** 就能確認這次用的是哪個環境、值是什麼：

```
TCRT automation environment: SIT
  tests/ui/test_login.py: API_TOKEN=***(secret), BASE_URL=https://sit.example
  tests/api/test_orders.py: BASE_URL=https://sit.example
```

> ⚠️ 用 session header 而非 `print`：pytest 預設會 capture `print`，只有**失敗**測試才
> 顯示，綠色測試會什麼都看不到。header 一律顯示（只有 `pytest -q` 會抑制，TCRT 的
> Jenkins job 不使用 `-q`）。沒選環境時印 `(none selected …)`。

> 💡 一句話原則：**名稱在 git，值在 TCRT**。機密在 TCRT 加密儲存，永遠不進 git。

---

## 11. 一頁速查：三個 Provider

| Slot | 類型 | 關鍵設定 | TCRT 角色 |
|---|---|---|---|
| Storage | `storage:github` / `storage:local_git` | owner/repo/branch/scan_path、PAT 或 App | 讀腳本、建 PR |
| CI | `ci:jenkins` | base_url、token、label=`built-in` | 自動建 job、觸發、查狀態、抓 artifact |
| Result | `result:allure` | base_url、project、template | 當 Allure proxy 代轉報告 |

---

## 12. 已知陷阱與注意事項

- **Jenkins label 必須是 `built-in`**（僅 Built-In node 的環境），否則 build 卡住不跑。
- **marker 連結是唯一寫入路徑**：手動建立連結的 API 與 UI 已移除，測試案例覆蓋
  只能在程式碼用 `@pytest.mark.tcrt(...)` 宣告。
- **帶點號的 TC 編號要改 dash**：`TCG-100558.020.010` → marker 寫 `TCG-100558-020-010`。
- **pomify 僅支援 Python**：recorder 若輸出 JS/TS，無法走 pomify 整形。
- **Runs 已移至 Test Run Set**：Automation Hub 舊的 Runs 分頁已移除，執行歷史看
  Test Run Set detail。
