# Tasks: add-system-runtime-settings-viewer

## 0. 前置（人工閘，禁止本 change 代 archive）

- [x] 0.1 檢查 main 是否已有 Requirement `Super Admin 專用即時 log 檢視頁面`（例如 `openspec/specs/system-log-viewer` 或等價已合併契約）
- [x] 0.2 若 **沒有**：停止實作，回報使用者，請其另行核准 verify／archive `add-super-admin-log-viewer`（或等價合併）；**不得**在本 change apply 流程中自動 archive 其他 change（2026-07-17 使用者核准後已由另一流程 verify＋archive，`system-log-viewer` spec 已入 main）
- [x] 0.3 若 **有**：確認 MODIFIED 仍使用完全相同 Requirement 名稱後再實作

## 1. Backend

- [x] 1.1 DB URL → `DbEndpoint`：dialect 正規化（`postgres`／`postgres+*` → `postgresql`；`mysql+asyncmy` → mysql／asyncmy；無 `+` 時 driver null）；丟棄 query；SQLite 僅 basename 或 null；禁止輸出任何 URL 字串（`app/services/system_runtime_settings.py`）
- [x] 1.2 `public_base_url`：僅 http(s)+host+合法 port；去 userinfo／query／fragment；相對／非 http(s)／缺 host／非法 port → null
- [x] 1.3 Concurrency（**勿先 strip 再判空**，對齊 shell `-z`）：正整數 → `configured`；未設或精確 `""` → `inferred_default`；純空白 `"   "`／`0`／負／非整數 → `invalid_configured`；`worker_count_note_code` 恒 `not_actual_worker_count`
- [x] 1.4 `worker_instance_id` 僅來自已安裝 log handler，否則 null
- [x] 1.5 `GET /api/admin/system-runtime-settings`：super admin、`include_in_schema=False`、`no-store`、exact allowlist JSON、`generated_at` UTC `Z`
- [x] 1.6 每次 200：audit 一級 `ip_address`／`user_agent`；`details` 恰好 `pid` + `worker_instance_id`；resource_id=`system-runtime-settings`
- [x] 1.7 pytest（至少）：`app/testsuite/test_system_runtime_settings_api.py` 43 passed
  - [x] 401／403 與 OpenAPI 不含 path
  - [x] 根物件與各巢狀物件 **exact key set**
  - [x] MySQL 密碼／query 不外洩；`mysql+asyncmy` driver
  - [x] `postgres://` → engine postgresql 且 inferred default 5（source=inferred_default 時）
  - [x] malformed DB URL → other + null 欄位且仍 200
  - [x] SQLite 完整路徑不外洩
  - [x] `public_base_url`：去 userinfo／query／fragment；相對 URL／非 http(s)／缺 host／非法 port → null
  - [x] `WEB_CONCURRENCY=2` → configured；未設或 `""` → inferred_default；`0`／負／非整數／**純空白 `"   "`** → **invalid_configured**
  - [x] handler 缺失 → instance null
  - [x] audit 成功：IP／UA 一級欄位、details 僅 pid／instance
  - [x] audit 失敗仍 200

## 2. Frontend

- [x] 2.1 Bootstrap 5 tabs + ARIA；tab panel `tabindex="0"`；預設 Logs
- [x] 2.2 窄螢幕可用 tab 列；keyboard 沿用 Bootstrap
- [x] 2.3 首次切入 Settings lazy fetch **一次**；重新整理再 fetch；loading／error／success（狀態機 `createRuntimeSettingsController` 在 system-logs-core.js，DOM-free）
- [x] 2.4 安全 DOM；顯示 pid／instance；`worker_count_note_code` → 三語文案；`invalid_configured` 顯示設定異常（不暗示 fallback 預設）
- [x] 2.5 Worker mismatch：**僅雙端非空 instance 且不同**；instance 缺失不比 PID（`workerMismatchState`）
- [x] 2.6 切 tab 不毀 Logs 狀態；Settings 錯誤不影響 Logs
- [x] 2.7 i18n 三語系 + `i18nReady`／`languageChanged` + `retranslate`
- [x] 2.8 CSS design tokens
- [x] 2.9 **必須**新增／擴充 JS 測試（非可選）：lazy 一次、refresh 再 fetch、錯誤不影響 Logs 狀態模型、mismatch 判定、語系重繪／code→文案映射（`app/testsuite/js/system-runtime-settings.test.mjs` 10 tests）

## 3. Docs & verification matrix

- [x] 3.1 更新 `docs/system-log-viewer.md`（契約摘要、三態 concurrency、結構化 DB、mismatch 規則、audit 一級欄位）
- [x] 3.2 `uv run pytest app/testsuite/test_system_runtime_settings_api.py app/testsuite/test_system_log_api.py -q` → 71 passed（新增 43 + 既有 log viewer 回歸 + 分頁殼層煙霧測試）
- [x] 3.3 `node --test app/testsuite/js/system-logs.test.mjs app/testsuite/js/system-runtime-settings.test.mjs` → 27 passed；`node --check` system-logs.js / system-logs-core.js 通過
- [x] 3.4 `npm run lint` 通過（無 stylelint／inline-style／template guard 回退）
- [x] 3.5 `uv run ruff check` 變更的 Python 路徑通過
- [x] 3.6 `node scripts/check-i18n-coverage.mjs` 通過（no regression；三語系各 +39 keys）
- [x] 3.7 `openspec validate add-system-runtime-settings-viewer --strict` 通過
- [x] 3.8 實作完成後 `graphify update .`（17228 nodes / 34336 edges rebuilt）

## 4. 實作複查修正（verify 回饋）

- [x] 4.1 修正 `public_base_url`：改用 `configured_public_base_url()`（env → config，未設定回 null），不得帶入 `get_base_url()` 的 localhost fallback；補「未設定 → null」與「config-only 值」API 測試
- [x] 4.2 修正 worker 預設推導分歧：新增 `scripts/print_inferred_web_concurrency.py`（由 resolved settings 的 main 引擎輸出預設，與 API 同源）；`docker/app-entrypoint.sh`、`start.sh` 改呼叫 helper（env-pattern case 僅作 helper 不可用時的 fallback）；補 config-only SQLite/MySQL/PostgreSQL 與 env `DATABASE_URL` override 子行程測試（測試以 dotenv stub 隔離 repo `.env`）；同步 README 與 `docs/docker-app-setup.md` 措辭
- [x] 4.3 補語系重繪自動化覆蓋：`applyI18nText` 抽入 system-logs-core.js（DOM-free），頁面共用；Node 測試以 element stub＋retranslate 契約模擬 `languageChanged`，驗證動態 badge／note 以 data-i18n（＋params）重繪為新語系文案
- [x] 4.4 複查 gates：pytest 78 passed、node 30 passed、shell syntax、ruff、npm lint、i18n coverage、OpenSpec strict validation 全過；`uv run python scripts/print_inferred_web_concurrency.py` 與 shell `_default_web_concurrency` 實跑輸出與 API inferred 一致（本機 MySQL → 5）
- [x] 4.5 修正 exported 空字串洩漏（第二輪 verify 回饋）：`docker/app-entrypoint.sh`、`start.sh` 改用獨立 `RESOLVED_WEB_CONCURRENCY` 傳 `--workers`，不覆寫 `WEB_CONCURRENCY` 本身，保留子行程 env 的未設定／空字串狀態（`"" → inferred_default` 契約）；補 shell 子行程測試（fake `uv` 替身；entrypoint：unset／exported-empty／explicit 三例、start.sh：unset／exported-empty 兩例）→ 複查 gates 重跑：pytest 83 passed、node 30 passed、shell syntax、ruff、npm lint、i18n、strict validation 全過
