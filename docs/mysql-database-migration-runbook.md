# SQLite → MySQL 正式 Migration Runbook

本文件是 TCRT 將 `main`、`audit`、`usm` 三套資料庫搬移至既有 MySQL server，並把應用程式切換到 MySQL 的標準操作流程。

**讀者**：工程師或 AI Agent（含低階模型）。  
**執行方式**：嚴格依節號順序；每節都有「目的 / 指令 / 期望 / 失敗動作」。任一步驟未達期望 → **立即 STOP**，不得跳過、不得自行發明旗標、不得切換正式 app。

本文件**不負責安裝或啟動 MySQL server 程序**，但**負責在遷移前檢查並補齊**目標端「三個業務 database 是否存在」與「schema 是否已可搬資料」。  
允許兩種起點（§6 會自動分支）：

| 起點 | 說明 | 遷移前必須補齊 |
|------|------|----------------|
| **A. database 尚未建立** | server 上沒有 `tcrt_main` / `tcrt_audit` / `tcrt_usm`（或工作單指定名稱） | 先 **CREATE DATABASE**（帳號需有權限，或由 DBA 建立空庫後重跑） |
| **B. 空 database 已建立、尚未初始化 schema** | 庫存在但無業務表 / 未到 Alembic head | 先跑 **`database_init.py` bootstrap** 建 schema 到 head |
| **C. 已是本版 managed 且在 head** | preflight `ready=true` 且 revision 對齊 | 可直接進入搬資料（仍受非空防呆約束） |

相關文件（本 runbook 優先於概念說明）：

- 統一 workflow 與 rollback 概念：`docs/database-cutover-readiness.md`
- 本機 disposable MySQL smoke（非正式搬移）：`docs/mysql-smoke-setup.md`

---

## 0. 不可違反的規則

1. 來源資料庫在整個 migration 期間**只讀**；搬移工具不得寫入來源。
2. 正式搬移前必須停止所有會寫入來源 DB 的 app、worker、scheduler、automation job。
3. 密碼只放在 env file；不得貼到命令列歷史可回顧的互動輸入以外的 log、chat、文件或 commit。
4. **禁止**使用 `scripts/db_cross_migrate.yaml` 作正式設定。一律使用 `--source-env-file` 與 `--target-env-file`。
5. 目標若已有業務資料，沒有操作者對「清空這三個指定 databases」的**明確核准**，禁止 `--force-reset-target`。
6. 正式路徑**禁止**加 `--manage-services`（那是 disposable docker 演練用）。
7. 任一步驟失敗 → STOP。不得跳過 preflight、驗證或 smoke。
8. 只使用本文件寫出的指令與旗標；不要改用 `pip install`、不要改 DB URL driver 名稱、不要改 migration 順序。
9. 全程在 **bash** 執行（見 §1）。不要用 `sh` 跑本文件的 script block。
10. 需人確認時（§3 目標環境、§5 來源停寫、§11 cutover、破壞性重跑等）：**Agent 在對話中停下詢問使用者**，得到明確同意後再繼續。不要用 shell 環境變數當確認閘。

---

## 1. 執行環境約定（先做這節）

### 1.1 目的

固定路徑變數與 shell，避免佔位字串被原樣複製、避免 zsh/sh 差異。

### 1.2 指令

先用文字編輯器打開一個**本機工作單**（可放在 repo 外，例如 `~/tcrt-migrate-worksheet.txt`），填入實際值（下面 `CHANGE_ME` 全部換成真值）：

```text
REPO_ROOT=CHANGE_ME_absolute_path_to_tcrt_user_story
SECURE_DIR=CHANGE_ME_absolute_path_outside_or_under_repo_.tmp
SOURCE_MAIN_DB=CHANGE_ME_absolute_path_to_test_case_repo.db
SOURCE_AUDIT_DB=CHANGE_ME_absolute_path_to_audit.db
SOURCE_USM_DB=CHANGE_ME_absolute_path_to_userstorymap.db
MYSQL_HOST=CHANGE_ME
MYSQL_PORT=CHANGE_ME
MYSQL_USER=CHANGE_ME
MYSQL_PASSWORD=CHANGE_ME_raw_password_not_url_encoded
MYSQL_MAIN_DB=tcrt_main
MYSQL_AUDIT_DB=tcrt_audit
MYSQL_USM_DB=tcrt_usm
TCRT_BASE_URL=CHANGE_ME_after_cutover_or_leave_for_section_12
```

然後在終端機**啟動 bash**（macOS 預設可能是 zsh，仍請進入 bash）：

```bash
bash
```

在 bash 中設定變數（把 `CHANGE_ME...` 換成工作單上的值；路徑必須是絕對路徑，不要用 `~` 未展開形式寫進 URL）：

```bash
set -euo pipefail

export REPO_ROOT="CHANGE_ME_absolute_path_to_tcrt_user_story"
export SECURE_DIR="CHANGE_ME_absolute_path"
export SOURCE_MAIN_DB="CHANGE_ME_absolute_path_to_test_case_repo.db"
export SOURCE_AUDIT_DB="CHANGE_ME_absolute_path_to_audit.db"
export SOURCE_USM_DB="CHANGE_ME_absolute_path_to_userstorymap.db"
export MYSQL_HOST="CHANGE_ME"
export MYSQL_PORT="CHANGE_ME"
export MYSQL_USER="CHANGE_ME"
# 原始密碼：僅留在 shell 變數與後續 env file，不要 echo 到螢幕
export MYSQL_PASSWORD='CHANGE_ME_raw_password'
export MYSQL_MAIN_DB="tcrt_main"
export MYSQL_AUDIT_DB="tcrt_audit"
export MYSQL_USM_DB="tcrt_usm"

export SOURCE_ENV="${SECURE_DIR}/source.env"
export TARGET_ENV="${SECURE_DIR}/target.env"
export BACKUP_DIR="${SECURE_DIR}/sqlite-backup-$(date +%Y%m%dT%H%M%S)"
export PREFLIGHT_RAW="/tmp/tcrt-mysql-preflight.json"
export PREFLIGHT_JSON="/tmp/tcrt-mysql-preflight-clean.json"
export MIGRATE_JSON="/tmp/tcrt-mysql-migrate-output.json"
export POST_CUTOVER_RAW="/tmp/tcrt-mysql-post-cutover.json"
export POST_CUTOVER_JSON="/tmp/tcrt-mysql-post-cutover-clean.json"

mkdir -p "${SECURE_DIR}"
cd "${REPO_ROOT}"
pwd
```

### 1.3 期望

- `pwd` 印出的路徑等於 repo root（內含 `database_init.py`、`scripts/run_db_cutover_workflow.py`、`app/`）。
- `SECURE_DIR` 存在且可寫。

### 1.4 失敗動作

STOP。修正路徑後從 §1 重來。不要繼續。

### 1.5 Linux 與 macOS 差異（必讀）

| 項目 | macOS (Darwin) | Linux |
|------|----------------|--------|
| 確認 OS | `uname -s` → `Darwin` | `uname -s` → `Linux` |
| 安裝 `jq`（若缺失） | `brew install jq` | `sudo apt-get install -y jq` 或發行版對等套件 |
| 安裝 `curl`（若缺失） | 通常已有；或 `brew install curl` | 通常已有；或 `sudo apt-get install -y curl` |
| 安裝 `uv`（若缺失） | 依官方安裝方式；不要用系統 pip 當套件管理 | 同左 |
| Shell | 預設常為 zsh；**本 runbook 一律 `bash`** | 伺服器常為 bash；仍建議顯式 `bash` |
| 路徑範例 | `/Users/name/code/tcrt_user_story` | `/home/name/code/tcrt_user_story` 或 `/opt/tcrt` |
| SQLite 檔路徑 | 絕對路徑，例如 `/Users/name/data/test_case_repo.db` | 絕對路徑，例如 `/var/lib/tcrt/test_case_repo.db` |
| 大小寫 | 磁碟常 case-insensitive；仍視路徑大小寫為有意義 | 通常 case-sensitive |
| 本文件使用的指令 | `bash`、`chmod`、`cp`、`sed`、`jq`、`curl`、`uv` | 相同；**不要**使用 `readlink -f` 或 GNU-only `timeout` 作為必要步驟 |
| Docker | 正式搬移**不需要** Docker | 同左；`--manage-services` 僅 disposable 演練 |

若路徑含空白：本 runbook 的變數皆已加引號；**不要**把未加引號的路徑貼進命令。

---

## 2. 完成條件（全部成立才算完成）

1. §3 依賴硬閘通過。
2. §5 來源已停寫並完成備份。
3. **§6 目標就緒硬閘通過**（三庫存在、schema 在 head、非 `legacy_unmanaged`）。
4. §8 workflow：process 成功且 `summary.json` 的 `success` 為 `true`。
5. `migration.row_counts_match` 為 `true`；三個 job 的 `row_counts_match` 皆為 `true`。
6. 三個 target：`ready == true` 且 `current_revision == head_revision`。
7. workflow 內 health：`health_check.ok == true` 且 `status_code == 200`。
8. §10 必要 smoke 全部通過。
9. §11 部署已切到目標四組 URL，重啟後 `/health` 仍 healthy；§12 頁面抽樣完成。

未完成 §6 不得做 §8。未完成 §10 不得做 §11。

---

## 3. 依賴與遷移條件硬閘（必須先過）

### 3.1 目的

確認執行主機工具、Python 依賴、來源檔、DBA 前置都滿足，再碰任何目標寫入。

### 3.2 指令（整段一次貼上執行）

```bash
set -euo pipefail
cd "${REPO_ROOT}"

echo "=== OS ==="
uname -s
uname -m

echo "=== required commands ==="
missing=0
for c in uv jq curl bash; do
  if command -v "$c" >/dev/null 2>&1; then
    echo "OK command: $c -> $(command -v "$c")"
  else
    echo "MISSING command: $c"
    missing=1
  fi
done
test "$missing" -eq 0

echo "=== repo root markers ==="
test -f "${REPO_ROOT}/database_init.py"
test -f "${REPO_ROOT}/scripts/run_db_cutover_workflow.py"
test -d "${REPO_ROOT}/app"
test -f "${REPO_ROOT}/uv.lock"

echo "=== python deps via uv ==="
uv sync --frozen
uv run python -c 'import sys; assert sys.version_info >= (3, 10), sys.version'
uv run python -c 'import asyncmy, pymysql; print("drivers_ok", asyncmy.__name__, pymysql.__name__)'

echo "=== source sqlite files ==="
test -r "${SOURCE_MAIN_DB}"
test -r "${SOURCE_AUDIT_DB}"
test -r "${SOURCE_USM_DB}"
# 非空檔（0 bytes 視為錯誤）
test -s "${SOURCE_MAIN_DB}"
test -s "${SOURCE_AUDIT_DB}"
test -s "${SOURCE_USM_DB}"
ls -la "${SOURCE_MAIN_DB}" "${SOURCE_AUDIT_DB}" "${SOURCE_USM_DB}"

echo "=== mysql tcp reachability ==="
uv run python - <<'PY'
import os, socket, sys
host = os.environ["MYSQL_HOST"]
port = int(os.environ["MYSQL_PORT"])
try:
    with socket.create_connection((host, port), timeout=10):
        print(f"tcp_ok {host}:{port}")
except OSError as exc:
    print(f"tcp_fail {host}:{port} {exc}", file=sys.stderr)
    sys.exit(1)
PY

echo "HARD_GATE_SECTION_3_PASSED"
```

### 3.3 使用者確認（Agent 必須停下）

自動檢查通過後，**Agent 必須停止**，在對話中請使用者確認下列事項，**得到明確同意前不得進入 §4**：

- MySQL `${MYSQL_HOST}:${MYSQL_PORT}` 與帳號是本次遷移要用的
- 三庫已預建空庫，**或**帳號可 `CREATE DATABASE`（§6 會補齊）
- 正式 app **尚未**切到目標 DB
- 允許 §6 建立缺庫 / 初始化 schema

使用者回覆同意後才繼續。不要使用 shell 環境變數當確認閘。

### 3.4 期望

- 輸出 `HARD_GATE_SECTION_3_PASSED`。
- 無 `MISSING command`；`drivers_ok`、`tcp_ok`；三個來源 SQLite 可讀且非空。
- **使用者已在對話中同意**繼續。
- **此時不要求**三個業務 database 已存在；缺庫 / 空庫初始化在 **§6** 處理。

### 3.5 失敗動作

STOP。依錯誤修復：

| 症狀 | 處理 |
|------|------|
| `MISSING command: jq` | macOS: `brew install jq`；Linux: 用發行版套件安裝 `jq` |
| `MISSING command: uv` | 安裝 uv 後重試；不要改用系統 pip 安裝專案 |
| `MISSING command: curl` 或 `bash` | 用 OS 套件安裝後重試 |
| `uv sync --frozen` 失敗 | 先修好 lockfile/網路；不要改刪 `--frozen` 除非使用者明確核准 |
| import asyncmy/pymysql 失敗 | 重新 `uv sync --frozen`；不要 `pip install` 進系統 Python |
| source 檔不存在 | 向使用者要正確絕對路徑；不要用測試副本路徑矇混 |
| `tcp_fail` | 查 firewall、host/port、VPN；未開通前不得繼續 |
| 使用者未同意繼續 | 停在 §3，不要進入 §4 |

### 3.6 帳號權限最低需求（給 DBA / 使用者）

**路徑 A — 三庫已由 DBA 預建（空庫即可）**

- 帳號對三庫：`CREATE`/`ALTER`/`DROP`/`INDEX`/`REFERENCES`（schema）+ `SELECT`/`INSERT`/`UPDATE`/`DELETE`（資料）
- **不需要** `CREATE DATABASE`，也**不需要**存取 `mysql` 系統庫

**路徑 B — 三庫尚未建立（§6 會嘗試建立）**

- 上述 schema/data 權限，**外加** server 級 `CREATE DATABASE`
- 本專案 `create_database_if_missing` 建立 MySQL 庫時，會先連到系統庫名稱 **`mysql`** 再 `CREATE DATABASE`；帳號必須能連 `mysql` 系統庫（或改走路徑 A 由 DBA 預建空庫）

**兩路徑共通**

- 不需要把密碼寫進 chat
- 正式 app 的四組 URL **尚未**切到目標

---

## 4. 建立來源與目標 env file

### 4.1 目的

產生 `source.env` / `target.env`，密碼 URL-encoding 正確，權限為 `600`。

### 4.2 指令（整段一次貼上）

```bash
set -euo pipefail
cd "${REPO_ROOT}"
mkdir -p "${SECURE_DIR}"

# URL-encode password（必要：密碼含 @ : / # % 等字元時）
export MYSQL_PASSWORD_ENC="$(
  uv run python -c 'import os; from urllib.parse import quote_plus; print(quote_plus(os.environ["MYSQL_PASSWORD"]))'
)"

# ---- source.env (SQLite) ----
# sqlite 絕對路徑在 scheme 後需要四個斜線：sqlite:////abs/path.db
cat > "${SOURCE_ENV}" <<EOF
DATABASE_URL=sqlite+aiosqlite:///${SOURCE_MAIN_DB}
SYNC_DATABASE_URL=sqlite:///${SOURCE_MAIN_DB}
AUDIT_DATABASE_URL=sqlite+aiosqlite:///${SOURCE_AUDIT_DB}
USM_DATABASE_URL=sqlite+aiosqlite:///${SOURCE_USM_DB}
EOF

# 上面 heredoc 若 SOURCE_* 已是 /abs/path，結果會是 sqlite+aiosqlite:////abs/path（四個 /）——正確。
# 驗證：
uv run python - <<'PY'
from pathlib import Path
import os
from sqlalchemy.engine import make_url

text = Path(os.environ["SOURCE_ENV"]).read_text(encoding="utf-8")
for line in text.splitlines():
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, _, v = line.partition("=")
    if not v.startswith("sqlite"):
        raise SystemExit(f"source {k} must be sqlite url, got {v[:32]}")
    if ":///" not in v:
        raise SystemExit(f"source {k} missing absolute sqlite form: {v}")
    db_path = make_url(v).database
    if not db_path or not Path(db_path).is_file():
        raise SystemExit(f"source {k} path missing on disk: {db_path!r}")
print("source_env_url_shape_ok")
# 只印 key 與路徑，避免整檔噪音
for line in text.splitlines():
    if "=" in line and not line.startswith("#"):
        k, _, v = line.partition("=")
        print(f"{k} -> {make_url(v).database}")
PY

# ---- target.env (MySQL) ----
cat > "${TARGET_ENV}" <<EOF
DATABASE_URL=mysql+asyncmy://${MYSQL_USER}:${MYSQL_PASSWORD_ENC}@${MYSQL_HOST}:${MYSQL_PORT}/${MYSQL_MAIN_DB}
SYNC_DATABASE_URL=mysql+pymysql://${MYSQL_USER}:${MYSQL_PASSWORD_ENC}@${MYSQL_HOST}:${MYSQL_PORT}/${MYSQL_MAIN_DB}
AUDIT_DATABASE_URL=mysql+asyncmy://${MYSQL_USER}:${MYSQL_PASSWORD_ENC}@${MYSQL_HOST}:${MYSQL_PORT}/${MYSQL_AUDIT_DB}
USM_DATABASE_URL=mysql+asyncmy://${MYSQL_USER}:${MYSQL_PASSWORD_ENC}@${MYSQL_HOST}:${MYSQL_PORT}/${MYSQL_USM_DB}
EOF

chmod 600 "${SOURCE_ENV}" "${TARGET_ENV}"
ls -la "${SOURCE_ENV}" "${TARGET_ENV}"

# 確認不被 git 追蹤
cd "${REPO_ROOT}"
git status --short --untracked-files=all -- "${SOURCE_ENV}" "${TARGET_ENV}" 2>/dev/null || true
# 若 SECURE_DIR 在 repo 外，上面可能無輸出——可接受
# 若在 repo 內，不得出現 "A " / staged；應為 ignored 或未加入

echo "ENV_FILES_CREATED"
```

### 4.3 規則（不得違反）

- `DATABASE_URL` / `AUDIT_DATABASE_URL` / `USM_DATABASE_URL` → **async**：`mysql+asyncmy://...`
- `SYNC_DATABASE_URL` → **sync migration driver**：`mysql+pymysql://...`
- 密碼必須經過 `quote_plus`；禁止手填未編碼密碼到 URL。
- 四組 URL 指向**同一** MySQL server 上**正確的三個** database 名稱。
- 不要 `cat`/`echo` 含密碼的檔案到 chat log；除錯時只看 redacted summary。

### 4.4 期望

- 輸出含 `source_env_url_shape_ok` 與 `ENV_FILES_CREATED`。
- `ls -la` 顯示權限 `-rw-------`（600）。
- `SOURCE_ENV` / `TARGET_ENV` 存在。

### 4.5 失敗動作

STOP。刪除不完整 env 後重做 §4。不要繼續 preflight。

---

## 5. 停止來源寫入並建立 SQLite 備份

### 5.1 目的

保證搬移期間來源不再被寫入，並留下可還原備份。

### 5.2 指令

**步驟 A — 停寫並向使用者確認（Agent 必須停下）**

1. 記錄目前正式環境使用的四組來源 URL 名稱（可寫在工作單；**不要**把密碼寫進 chat）。
2. 停止（或請使用者停止）app、worker、scheduler、automation 等所有寫入來源 DB 的程序。
3. **Agent 必須停止**，在對話中請使用者確認：「來源已停止寫入，可以備份並遷移」。
4. 得到明確同意前，**禁止**進入步驟 B / §6 / §8。

**步驟 B — 備份（僅在使用者確認停寫之後；整段貼上）**

```bash
set -euo pipefail
mkdir -p "${BACKUP_DIR}"

# 優先使用 sqlite3 .backup（若有）；否則用 cp，並一併複製 WAL/SHM
backup_one() {
  local src="$1"
  local base
  base="$(basename "$src")"
  if command -v sqlite3 >/dev/null 2>&1; then
    sqlite3 "$src" ".backup '${BACKUP_DIR}/${base}'"
  else
    cp -p "$src" "${BACKUP_DIR}/${base}"
    if [ -f "${src}-wal" ]; then cp -p "${src}-wal" "${BACKUP_DIR}/${base}-wal"; fi
    if [ -f "${src}-shm" ]; then cp -p "${src}-shm" "${BACKUP_DIR}/${base}-shm"; fi
  fi
}

backup_one "${SOURCE_MAIN_DB}"
backup_one "${SOURCE_AUDIT_DB}"
backup_one "${SOURCE_USM_DB}"

# 還原說明寫入同目錄（無密碼）
cat > "${BACKUP_DIR}/RESTORE.txt" <<EOF
Restore (only if rolling back to these SQLite files):
1. Stop all writers.
2. For each db file, copy backup file over the live path.
3. If *-wal / *-shm exist in backup, copy them too; if using .backup files only, remove live -wal/-shm after restore.
Backup created at: ${BACKUP_DIR}
Host: $(uname -s) $(hostname 2>/dev/null || true)
UTC: $(date -u +%Y-%m-%dT%H:%M:%SZ)
EOF

ls -la "${BACKUP_DIR}"
echo "BACKUP_DIR=${BACKUP_DIR}"
echo "SOURCE_BACKUP_DONE"
```

### 5.3 期望

- 使用者已在對話中確認來源停寫。
- 輸出 `SOURCE_BACKUP_DONE`。
- `${BACKUP_DIR}` 內有三個 DB 備份檔與 `RESTORE.txt`。

### 5.4 失敗動作

STOP。使用者未確認停寫、或備份失敗 → 不得進入 §6。

### 5.5 還原來源（僅 rollback 需要時）

見 `${BACKUP_DIR}/RESTORE.txt`。不要在成功路徑執行還原。

---

## 6. 目標就緒：檢查 → 建立缺庫 → 初始化 schema（遷移前必做）

本節是**資料搬移（§8）之前**的硬閘。  
**禁止**在目標未就緒時直接跑 §8。  
本節會寫入目標（CREATE DATABASE / Alembic schema），但**不搬來源業務資料**。

### 6.0 狀態對照（先讀，再執行）

| `database_state` / `status`（preflight） | 意義 | 遷移前必須做的事 |
|------------------------------------------|------|------------------|
| `missing` / `database_missing` | server 上**沒有**該 database | **建立 database**（§6.3），再 **初始化 schema**（§6.4） |
| `empty` / `empty_ready` | database 存在，**尚無業務表** | **初始化 schema**（§6.4） |
| `managed` 且 `current_revision == head_revision` 且 `ready=true` | schema 已在 head | 可進入 §6.5 最終硬閘（仍受非空防呆約束） |
| `managed` 但 revision 落後（`upgrade_pending` / `ready=false`） | 庫在但未到 head | **初始化/升級 schema**（§6.4） |
| `legacy_unmanaged` | 有表但未納管 Alembic | **STOP**；交人類走 legacy adopt/upgrade，Agent 不得自行處理 |
| `connection_error` / 認證失敗 | 連不上 | **STOP**；修正 host/port/帳密/TLS 後重跑 §6.1 |
| `missing_drivers` | asyncmy/PyMySQL 不可用 | **STOP**；回 §3 |

說明：

- 「初始化」在本 runbook = 對目標執行 `database_init.py --no-backup`（Alembic 建表到 head），**不是**灌入來源資料。
- 來源業務資料只在 **§8** 搬移。
- migrate workflow 本身也會 bootstrap；§6 仍要先做，以便**在搬資料前**暴露缺庫/權限/legacy 問題。

### 6.1 診斷 preflight（允許暫時失敗；用於分類）

#### 目的

讀出三個 target 目前狀態；**此步可不通過**，但必須產出可解析 JSON。

#### 指令（整段一次貼上）

```bash
set -euo pipefail
cd "${REPO_ROOT}"
test -f "${TARGET_ENV}"

set -a
# shellcheck disable=SC1090
source "${TARGET_ENV}"
set +a

set +e
uv run python database_init.py --preflight --json --quiet > "${PREFLIGHT_RAW}"
PREFLIGHT_RC=$?
set -e

unset DATABASE_URL SYNC_DATABASE_URL AUDIT_DATABASE_URL USM_DATABASE_URL

# database_init 在 --json --quiet 時仍會印 banner；必須截出 JSON 物件
sed -n '/^{/,$p' "${PREFLIGHT_RAW}" > "${PREFLIGHT_JSON}"
test -s "${PREFLIGHT_JSON}"

echo "preflight_diag_exit_code=${PREFLIGHT_RC}"
jq '[.targets[] | {
  target, ready, database_state, status, current_revision, head_revision,
  driver_statuses, error, remediation
}]' "${PREFLIGHT_JSON}"

# driver 必須可用；否則 STOP（此條件不可靠補齊）
jq -e '
  ([.targets[].driver_statuses[]? | select(.available != true)] | length) == 0
' "${PREFLIGHT_JSON}" >/dev/null

# legacy 一律 STOP（不可靠本節自動修復）
if jq -e '
  ([.targets[] | select(
    (.database_state // "") == "legacy_unmanaged"
    or (.status // "") == "legacy_unmanaged"
  )] | length) > 0
' "${PREFLIGHT_JSON}" >/dev/null; then
  echo "STOP: legacy_unmanaged detected; hand off to human (database_init legacy flags)"
  exit 1
fi

# 純連線/認證錯誤（且不是 database_missing）→ STOP
if jq -e '
  ([.targets[] | select(
    (.status // "") == "connection_error"
    and (.database_state // "") != "missing"
    and (.status // "") != "database_missing"
  )] | length) > 0
' "${PREFLIGHT_JSON}" >/dev/null; then
  echo "STOP: connection_error (not missing-db); fix credentials/host/TLS, re-run §6.1"
  jq '[.targets[] | select((.status // "") == "connection_error") | {target, error}]' "${PREFLIGHT_JSON}"
  exit 1
fi

echo "PREFLIGHT_DIAG_DONE"
```

#### 期望

- 輸出 `PREFLIGHT_DIAG_DONE`。
- 已印出各 target 的 `database_state` / `status`。
- 無 missing driver、無 `legacy_unmanaged`、無非缺庫的 `connection_error`。

#### 失敗動作

STOP。修正後重跑 §6.1。**不要**跳到 §8。

### 6.2 依診斷決定是否需要補齊

看 §6.1 的 JSON，對**每一個** target（main / audit / usm）套用：

| 若出現… | 下一步 |
|---------|--------|
| 任一 `database_state=missing` 或 `status=database_missing` | **必須**跑 §6.3（建庫），再跑 §6.4 |
| 任一 `database_state=empty` 或 `status=empty_ready` | **必須**跑 §6.4（初始化 schema） |
| 任一 `ready=false` 且 status 像 `upgrade_pending` | **必須**跑 §6.4 |
| 全部已 `ready=true` 且 `database_state` 為 `empty` 或 `managed`/`missing` 已處理完 | 仍跑 §6.3（no-op 安全）+ §6.4（no-op 若已在 head）再 §6.5 |
| 任一 `legacy_unmanaged` | 已在 §6.1 STOP |

**低階模型規則**：不要自行判斷「可以跳過 §6.3/§6.4」。  
**一律依序執行 §6.3 → §6.4 → §6.5**（建庫與 bootstrap 在已就緒時應為 no-op 或快速通過）。

### 6.3 建立缺少的 database（若已存在則跳過）

#### 目的

確保 `TARGET_ENV` 指向的三個業務 database **在 MySQL 上存在**。  
空庫即可；**不**在此灌資料。

#### 指令（整段一次貼上）

```bash
set -euo pipefail
cd "${REPO_ROOT}"
test -f "${TARGET_ENV}"

set -a
# shellcheck disable=SC1090
source "${TARGET_ENV}"
set +a

set +e
uv run python - <<'PY'
"""Create missing MySQL databases named in TARGET_ENV URLs.

Uses app.db_migrations.create_database_if_missing:
- DB already exists -> no-op
- DB missing + account can CREATE (via admin DB `mysql`) -> CREATE DATABASE
- otherwise raises / exits non-zero
"""
from __future__ import annotations

import os
import sys

from app.db_migrations import create_database_if_missing
from app.db_url import normalize_sync_database_url

keys = (
    "DATABASE_URL",
    "SYNC_DATABASE_URL",
    "AUDIT_DATABASE_URL",
    "USM_DATABASE_URL",
)
# Deduplicate by database name (main async+sync share one DB)
seen: set[str] = set()
created_any = False
errors: list[str] = []

for key in keys:
    raw = os.environ.get(key)
    if not raw:
        errors.append(f"missing env {key}")
        continue
    sync_url = normalize_sync_database_url(raw)
    # identity for dedupe: full sync URL without password noise — use database name
    try:
        from sqlalchemy.engine import make_url

        db_name = make_url(sync_url).database
    except Exception as exc:  # noqa: BLE001
        errors.append(f"{key}: bad url ({exc})")
        continue
    if not db_name:
        errors.append(f"{key}: empty database name")
        continue
    if db_name in seen:
        print(f"skip_dup {key} database={db_name}")
        continue
    seen.add(db_name)
    try:
        created = create_database_if_missing(sync_url)
        # Avoid nested quotes inside f-strings (agents/shells often corrupt them).
        status = "created" if created else "exists"
        print(status, "database=" + str(db_name), "from=" + key)
        created_any = created_any or created
    except Exception as exc:  # noqa: BLE001
        errors.append(key + " database=" + str(db_name) + ": " + str(exc))

if errors:
    print("CREATE_DATABASE_FAILED", file=sys.stderr)
    for line in errors:
        print(line, file=sys.stderr)
    print(
        "HINT: either grant CREATE DATABASE + access to system schema `mysql`, "
        "or ask DBA to CREATE empty databases then re-run §6.3",
        file=sys.stderr,
    )
    sys.exit(1)

print(f"databases_ensured count={len(seen)} created_any={created_any}")
print("ENSURE_DATABASES_DONE")
PY
ENSURE_RC=$?
set -e

unset DATABASE_URL SYNC_DATABASE_URL AUDIT_DATABASE_URL USM_DATABASE_URL
test "${ENSURE_RC}" -eq 0
echo "ENSURE_DATABASES_PASSED"
```

#### 期望

- 輸出 `ENSURE_DATABASES_DONE` 與 `ENSURE_DATABASES_PASSED`。
- 每個業務庫印出 `created` 或 `exists`。

#### 失敗動作

STOP。

| 症狀 | 處理 |
|------|------|
| 無權 `CREATE DATABASE` / 不能連系統庫 `mysql` | **路徑 A**：請 DBA 建立三個**空** database（名稱=工作單 `MYSQL_*_DB`），授權後**只重跑 §6.3→§6.5** |
| 認證錯誤 | 修正 `TARGET_ENV` 後重跑 §4 與 §6 |
| 其他 | 把 stderr 給操作者；不要發明手動 SQL 以外的流程 |

**DBA 預建空庫範例**（僅在 §6.3 失敗且操作者核准時，由 DBA/有權帳號執行；Agent 不得把 root 密碼寫進文件）：

```sql
CREATE DATABASE IF NOT EXISTS tcrt_main  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE IF NOT EXISTS tcrt_audit CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE IF NOT EXISTS tcrt_usm   CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
-- 再 GRANT 遷移帳號對三庫的 schema + data 權限
```

### 6.4 初始化 / 升級目標 schema 到 head（不搬業務資料）

#### 目的

對**已存在**的三庫執行 Alembic bootstrap，使 schema 到達 head。  
涵蓋：空庫、缺表、revision 落後。  
**不**從 SQLite 匯入列資料。

#### 指令（整段一次貼上）

```bash
set -euo pipefail
cd "${REPO_ROOT}"
test -f "${TARGET_ENV}"

set -a
# shellcheck disable=SC1090
source "${TARGET_ENV}"
set +a

set +e
# --no-backup：此階段目標應為空庫或可重建演練庫；正式若有重要資料應在進入前 STOP
uv run python database_init.py --no-backup --quiet
INIT_RC=$?
set -e

echo "schema_init_exit_code=${INIT_RC}"
test "${INIT_RC}" -eq 0

# 只讀驗證：三庫 ready 且 revision == head
set +e
uv run python database_init.py --verify-target all --json --quiet > /tmp/tcrt-mysql-schema-verify-raw.json
VERIFY_RC=$?
set -e

sed -n '/^{/,$p' /tmp/tcrt-mysql-schema-verify-raw.json > /tmp/tcrt-mysql-schema-verify.json
echo "schema_verify_exit_code=${VERIFY_RC}"
jq '[.targets[] | {target, ready, database_state, current_revision, head_revision}]' \
  /tmp/tcrt-mysql-schema-verify.json

jq -e '
  ([.targets[] | select(.ready != true or .current_revision != .head_revision)] | length) == 0
' /tmp/tcrt-mysql-schema-verify.json >/dev/null
test "${VERIFY_RC}" -eq 0

unset DATABASE_URL SYNC_DATABASE_URL AUDIT_DATABASE_URL USM_DATABASE_URL
echo "SCHEMA_INIT_PASSED"
```

#### 期望

- `schema_init_exit_code=0`
- `SCHEMA_INIT_PASSED`
- 三庫 `ready=true` 且 `current_revision == head_revision`

#### 失敗動作

STOP。查輸出與權限（缺 CREATE TABLE 等）。  
**不要**用 `--force-reset-target` 當成 schema 初始化手段（那是搬資料流程的清庫旗標）。

### 6.5 最終 preflight 硬閘（必須通過才能 §8）

#### 目的

確認補齊後，三庫皆可進入 migrate。

#### 指令（整段一次貼上）

```bash
set -euo pipefail
cd "${REPO_ROOT}"
test -f "${TARGET_ENV}"

set -a
# shellcheck disable=SC1090
source "${TARGET_ENV}"
set +a

set +e
uv run python database_init.py --preflight --json --quiet > "${PREFLIGHT_RAW}"
PREFLIGHT_RC=$?
set -e

unset DATABASE_URL SYNC_DATABASE_URL AUDIT_DATABASE_URL USM_DATABASE_URL

sed -n '/^{/,$p' "${PREFLIGHT_RAW}" > "${PREFLIGHT_JSON}"
echo "preflight_final_exit_code=${PREFLIGHT_RC}"
jq '[.targets[] | {target, ready, database_state, status, current_revision, head_revision}]' \
  "${PREFLIGHT_JSON}"

# 硬閘：全部 ready；driver OK；非 legacy；非 missing（缺庫必須已在 §6.3 消除）
jq -e '
  (.targets | length) >= 1
  and ([.targets[] | select(.ready != true)] | length) == 0
  and ([.targets[].driver_statuses[]? | select(.available != true)] | length) == 0
  and ([.targets[] | select(
    (.database_state // "") == "legacy_unmanaged"
    or (.status // "") == "legacy_unmanaged"
    or (.database_state // "") == "missing"
    or (.status // "") == "database_missing"
  )] | length) == 0
' "${PREFLIGHT_JSON}" >/dev/null

# 允許 empty（理論上 §6.4 後應為 managed）或 managed；revision 若有值必須等於 head
jq -e '
  ([.targets[] | select(
    (.current_revision != null)
    and (.head_revision != null)
    and (.current_revision != .head_revision)
  )] | length) == 0
' "${PREFLIGHT_JSON}" >/dev/null

test "${PREFLIGHT_RC}" -eq 0
echo "PREFLIGHT_PASSED"
echo "TARGET_READY_FOR_MIGRATE"
```

#### 期望

- `PREFLIGHT_PASSED`
- `TARGET_READY_FOR_MIGRATE`

#### 失敗動作

STOP。回到 §6.1 重新診斷；必要時重跑 §6.3 / §6.4。  
**禁止**進入 §8。

### 6.6 本節允許進入 §8 的狀態摘要

- 三庫 **database 皆存在**（不再 `missing`）。
- Schema 在 **head**（`current_revision == head_revision`，`ready=true`）。
- 非 `legacy_unmanaged`。
- 正式 app **尚未**切到目標 URL。

§8 仍會再做 non-empty 防呆與資料搬移；若目標已有業務列且未核准 `--force-reset-target`，§8 會中止——那是正確行為。

### 6.7 不要做的事

- 不要在 §6 修改正式部署的 DB URL。
- 不要用 `scripts/db_cross_migrate.yaml`。
- 不要把 §6.4 的 bootstrap 當成「資料已遷移完成」。
- 不要跳過 §6.5 最終硬閘。

---

## 7. 可選：disposable 演練（非正式）

### 7.1 目的

在動正式 MySQL 前，用本機 docker MySQL 驗證工具鏈。低階模型**預設跳過**本節，除非操作者明確要求 rehearsal。

### 7.2 指令（僅在操作者要求時）

```bash
set -euo pipefail
cd "${REPO_ROOT}"
uv run python scripts/run_db_cutover_workflow.py --target mysql --mode smoke --manage-services
```

詳見 `docs/mysql-smoke-setup.md`。  
**注意**：這與正式 §8 不同；正式路徑**禁止** `--manage-services`。

---

## 8. 執行一鍵正式 migration

### 8.1 目的

對**既有** MySQL 三庫：schema bootstrap → 搬資料 → row count → verify → 暫時啟動 app 做 health。

### 8.2 前置確認

- §3–§5 全過（含使用者已確認來源停寫）。
- **§6 全過**（含 `TARGET_READY_FOR_MIGRATE`）：缺庫已建立、schema 已在 head。
- 來源仍停寫。
- **不要**加 `--manage-services`。
- **不要**加 `--force-reset-target`（除非 §13 失敗重跑且使用者明確核准清空目標）。

### 8.3 指令（整段一次貼上；exit code 與輸出必須同一段）

```bash
set -euo pipefail
cd "${REPO_ROOT}"

test -f "${SOURCE_ENV}"
test -f "${TARGET_ENV}"

set +e
uv run python scripts/run_db_cutover_workflow.py \
  --mode migrate \
  --target mysql \
  --source-env-file "${SOURCE_ENV}" \
  --target-env-file "${TARGET_ENV}" \
  --health-timeout 120 \
  > "${MIGRATE_JSON}"
MIGRATE_RC=$?
set -e

echo "MIGRATE_RC=${MIGRATE_RC}"
test "${MIGRATE_RC}" -eq 0

# workflow stdout 應為完整 JSON summary（含 run_dir）
jq -e '.success == true' "${MIGRATE_JSON}" >/dev/null

export RUN_DIR
RUN_DIR="$(jq -r '.run_dir' "${MIGRATE_JSON}")"
test -n "${RUN_DIR}"
test -d "${RUN_DIR}"
test -f "${RUN_DIR}/summary.json"

# 以 run_dir/summary.json 為準（與 stdout 應一致）
jq -e '.success == true' "${RUN_DIR}/summary.json" >/dev/null

echo "RUN_DIR=${RUN_DIR}"
echo "MIGRATE_WORKFLOW_EXIT_0"
```

### 8.4 workflow 固定順序（不得手動重排）

1. DB access guardrails  
2. 目標 preflight  
3. 目標非空防呆  
4. 三庫 Alembic schema bootstrap（`--no-backup`）  
5. main → audit → usm：`scripts/db_cross_migrate.py`（含 `--reset-target`）  
6. 逐表 source/target row count  
7. `database_init.py --verify-target all`  
8. 用目標 MySQL URL 啟動 app 並檢查 `/health`  

任一步失敗會短路。不得手動跳過後段。

### 8.5 特殊旗標（預設不要用）

| 旗標 | 何時才用 |
|------|----------|
| `--force-reset-target` | 目標三庫已有業務資料且操作者**書面/明確**核准清空後重跑（見 §13） |
| `--migrate-disable-constraints` | 僅當搬移因來源**循環 FK**失敗，且 log 指出 constraint/order 問題時，經操作者同意後重跑 |
| `--manage-services` | **正式禁止** |

### 8.6 期望

- `MIGRATE_RC=0`
- 輸出 `MIGRATE_WORKFLOW_EXIT_0`
- `RUN_DIR` 指向 `.tmp/db-cutover/...-mysql-migrate/`

### 8.7 失敗動作

STOP。進入 §13。不要切換正式 app。

---

## 9. 驗證 workflow 證據

### 9.1 目的

用 `summary.json` 證明搬移與 revision / health 成功。

### 9.2 指令（整段一次貼上；需已設定 `RUN_DIR`）

```bash
set -euo pipefail
test -d "${RUN_DIR}"
test -f "${RUN_DIR}/summary.json"

jq '{
  success,
  migration_row_counts_match: .migration.row_counts_match,
  jobs: [.migration.jobs[]? | {job, row_counts_match}],
  revisions: [.verification.targets[]? | {
    target, ready, current_revision, head_revision
  }],
  health: {
    ok: .health_check.ok,
    status_code: .health_check.status_code
  },
  error: .error
}' "${RUN_DIR}/summary.json"

jq -e '
  .success == true
  and .migration.row_counts_match == true
  and ([.migration.jobs[]? | select(.row_counts_match != true)] | length) == 0
  and ([.verification.targets[]? | select(.ready != true or .current_revision != .head_revision)] | length) == 0
  and .health_check.ok == true
  and .health_check.status_code == 200
' "${RUN_DIR}/summary.json" >/dev/null

test -f "${RUN_DIR}/logs/migrate-main.log"
test -f "${RUN_DIR}/logs/migrate-audit.log"
test -f "${RUN_DIR}/logs/migrate-usm.log"

echo "SUMMARY_EVIDENCE_PASSED"
```

### 9.3 已知可接受差異（僅下列；其他 row loss 一律失敗）

- `test_run_item_result_history` 指向不存在 `test_run_items` 的孤立列 → `repair_counts.skipped_orphan_item_refs`；`expected_target_rows = source_rows - filtered_rows`。
- SQLite 來源若有 `test_cases.attachment_count` / `test_cases.has_attachments` → 記在 `ignored_source_columns.test_cases`；不搬移。
- SQLite expression index（例如 `uq_users_username_lower`）不靠 reflection 搬移；target 以 Alembic 為準。
- 歷史 revision `7a26d2522198` 在 MySQL 上可能短暫出現 duplicate-index warning；必須跑到 main head（撰寫時為 `8f1b2c3d4e5a`，**以當次 preflight/verify 的 `head_revision` 為準**）。head 後同欄位仍有兩個等價 index → 失敗。

### 9.4 期望

- 輸出 `SUMMARY_EVIDENCE_PASSED`。
- log 與 summary **不應**含明文密碼；若發現 → 立刻限制檔案權限並停止分享。

### 9.5 失敗動作

STOP。查 `${RUN_DIR}/summary.md` 與第一個非零步驟的 log。不要 cutover。

---

## 10. 必要 smoke tests（正式切換前 gate）

§8–§9 通過後仍**必須**跑完本節，才可進入 §11。

### 10.1 Summary / row count / revision / health

```bash
set -euo pipefail
test -f "${RUN_DIR}/summary.json"

jq -e '
  .success == true and
  .migration.row_counts_match == true and
  ([.migration.jobs[]?.row_count_verification[]? | select(.matches != true)] | length == 0) and
  ([.verification.targets[]? |
    select(.ready != true or .current_revision != .head_revision)] | length == 0) and
  .health_check.ok == true and
  .health_check.status_code == 200
' "${RUN_DIR}/summary.json" >/dev/null

# 若有 filtered rows：只允許 orphan repair 解釋
jq -e '
  [.migration.jobs[]?.row_count_verification[]? |
    select((.filtered_rows // 0) > 0) |
    select(
      .filtered_rows != (.repair_counts.skipped_orphan_item_refs // 0) or
      .expected_target_rows != (.source_rows - .filtered_rows)
    )
  ] | length == 0
' "${RUN_DIR}/summary.json" >/dev/null

echo "SMOKE_10_1_PASSED"
```

### 10.2 MySQL schema 與 Automation pending-sync SQL（只讀）

```bash
set -euo pipefail
cd "${REPO_ROOT}"

set -a
# shellcheck disable=SC1090
source "${TARGET_ENV}"
set +a

set +e
uv run python - <<'PY'
import os
import sys

from sqlalchemy import create_engine, inspect, select

from app.models.database_models import AutomationRun
from app.services.automation.run_service import _pending_run_order_clauses

expected_indexes = {
    "active_sessions": {"ix_sessions_expires"},
    "password_reset_tokens": {"ix_reset_tokens_expires"},
    "test_case_sets": {"ix_test_case_sets_team"},
    "user_team_permissions": {
        "ix_user_team_perms_permission",
        "ix_user_team_perms_team",
        "ix_user_team_perms_user",
    },
}
removed_indexes = {
    "ix_active_sessions_expires_at",
    "ix_password_reset_tokens_expires_at",
    "ix_test_case_sets_team_id",
    "ix_user_team_permissions_permission",
    "ix_user_team_permissions_team_id",
    "ix_user_team_permissions_user_id",
}

engine = create_engine(os.environ["SYNC_DATABASE_URL"], future=True)
try:
    inspector = inspect(engine)
    actual_indexes = {
        table: {index["name"] for index in inspector.get_indexes(table)}
        for table in expected_indexes
    }
    for table, expected in expected_indexes.items():
        missing = expected - actual_indexes[table]
        assert not missing, (table, "missing", missing, actual_indexes[table])
    leaked = removed_indexes.intersection(
        index_name
        for indexes in actual_indexes.values()
        for index_name in indexes
    )
    assert not leaked, ("redundant_indexes_still_present", leaked)

    statement = select(AutomationRun.id).order_by(
        *_pending_run_order_clauses()
    ).limit(1)
    with engine.connect() as connection:
        connection.execute(statement).all()
        connection.execute(statement).all()
finally:
    engine.dispose()

print("MySQL schema and Automation sync smoke passed")
PY
SMOKE_RC=$?
set -e

unset DATABASE_URL SYNC_DATABASE_URL AUDIT_DATABASE_URL USM_DATABASE_URL
test "${SMOKE_RC}" -eq 0
echo "SMOKE_10_2_PASSED"
```

### 10.3 期望

- `SMOKE_10_1_PASSED` 與 `SMOKE_10_2_PASSED`。

### 10.4 失敗動作

STOP。禁止 §11 cutover。

---

## 11. 將正式系統切換到 MySQL

**進入條件**：§8、§9、§10 全部通過。

### 11.1 目的

部署環境改指向目標 MySQL，並做 post-cutover 驗證。

### 11.2 指令（逐步；部署系統相關步驟需操作者執行）

1. **保留 rollback 設定**  
   把切換前正式環境的四組 URL（或部署 secret 名稱）記在工作單；不要貼密碼到 chat。

2. **更新部署環境**（操作者依實際部署執行；Agent 不得猜測平台）  
   將下列鍵更新為 `TARGET_ENV` 中**相同**值：  
   `DATABASE_URL`、`SYNC_DATABASE_URL`、`AUDIT_DATABASE_URL`、`USM_DATABASE_URL`  
   可能位置（只改實際在用的那一種）：容器 env、systemd `EnvironmentFile`、編排系統 secret、`.env.docker`（若該環境使用且 gitignored）等。

3. **重啟** app 與 worker（僅新設定實例；不要同時留著仍指向來源且會寫入的舊實例）。

4. **Health（部署後）**

```bash
set -euo pipefail
# 由操作者提供實際 URL，例如 https://tcrt.example.com
export TCRT_BASE_URL="CHANGE_ME_or_from_worksheet"
curl --fail --silent --show-error "${TCRT_BASE_URL}/health" | jq -e '.status == "healthy"'
echo "POST_DEPLOY_HEALTH_PASSED"
```

5. **只讀 verify-target（對目標）**

```bash
set -euo pipefail
cd "${REPO_ROOT}"

set -a
# shellcheck disable=SC1090
source "${TARGET_ENV}"
set +a

set +e
uv run python database_init.py --verify-target all --json --quiet > "${POST_CUTOVER_RAW}"
VERIFY_RC=$?
set -e

unset DATABASE_URL SYNC_DATABASE_URL AUDIT_DATABASE_URL USM_DATABASE_URL

sed -n '/^{/,$p' "${POST_CUTOVER_RAW}" > "${POST_CUTOVER_JSON}"
echo "VERIFY_RC=${VERIFY_RC}"
test "${VERIFY_RC}" -eq 0
jq '[.targets[] | {target, ready, current_revision, head_revision}]' "${POST_CUTOVER_JSON}"
jq -e '
  ([.targets[] | select(.ready != true or .current_revision != .head_revision)] | length) == 0
' "${POST_CUTOVER_JSON}" >/dev/null
echo "POST_CUTOVER_VERIFY_PASSED"
```

6. **切換後 app 抽樣** → 做完 §12 才解除維護狀態。

### 11.3 切換後主機注意（bootstrap 備份）

若正式環境開機會跑 `database_init.py` 升版備份（見 `docs/database-cutover-readiness.md` §7）：

- MySQL 路徑需要主機/容器內有 `mysqldump` 與 `mysql` client。
- `BOOTSTRAP_BACKUP_DIR` 建議持久化 volume。
- 本 migration 成功後若已在 head，平常開機不一定會再升版；但工具鏈仍應備妥。

### 11.4 期望

- `POST_DEPLOY_HEALTH_PASSED`
- `POST_CUTOVER_VERIFY_PASSED`

### 11.5 失敗動作

STOP。依 §13「已切換 app」rollback。不要對來源做雙向合併。

---

## 12. 切換後業務抽樣（必要）

只讀操作；全部由操作者或具 UI 權限者執行並勾選：

- [ ] Test Case 列表與一筆明細可開啟  
- [ ] Test Run 列表與一筆結果可開啟  
- [ ] User Story Map 列表與一張 map 可開啟  
- [ ] audit 可讀取切換後新產生的登入或檢視事件  
- [ ] Automation background sync 至少跨兩個 tick 無 `NULLS FIRST` 或 SQL syntax error  

全部勾選後：

```bash
echo "MIGRATION_COMPLETE"
```

此時才算 §2 完成條件全部滿足。

---

## 13. 失敗與 rollback

### 13.1 尚未切換正式 app（§11 之前失敗）

1. 保持 app 停止或仍指向**來源**。  
2. 來源應未被 migration 工具修改 → 可繼續以來源為正式 DB。  
3. 保留 `RUN_DIR`、`${BACKUP_DIR}`、`${SOURCE_ENV}`、`${TARGET_ENV}`。  
4. 目標可能已有部分 schema/資料；修正原因後重跑會因非空防呆停止。

**僅當**同時滿足才可用 `--force-reset-target` 重跑：

- 目標三庫都是本次失敗留下的；  
- 操作者對「清空 main/audit/usm 三個指定 database 全部業務資料」有明確核准；  
- 來源仍停寫。

```bash
set -euo pipefail
cd "${REPO_ROOT}"

# 需要操作者明確核准後才執行
set +e
uv run python scripts/run_db_cutover_workflow.py \
  --mode migrate \
  --target mysql \
  --source-env-file "${SOURCE_ENV}" \
  --target-env-file "${TARGET_ENV}" \
  --force-reset-target \
  --health-timeout 120 \
  > "${MIGRATE_JSON}"
MIGRATE_RC=$?
set -e
echo "MIGRATE_RC=${MIGRATE_RC}"
test "${MIGRATE_RC}" -eq 0
export RUN_DIR
RUN_DIR="$(jq -r '.run_dir' "${MIGRATE_JSON}")"
# 然後從 §9 重跑驗證與 §10 smoke
```

### 13.2 已切換正式 app（§11 之後失敗）

1. 立即停止指向 MySQL 目標的 app / worker / scheduler。  
2. 部署四組 URL **全部**還原為切換前來源設定。  
3. 重啟來源設定的 app；確認 `/health` 與關鍵頁面。  
4. 記錄切換後目標曾寫入的新資料；**禁止**自行雙向合併來源與目標。  
5. 保留目標 DB 供事故分析，除非另有刪除核准。

### 13.3 來源 SQLite 損毀時

使用 §5 `${BACKUP_DIR}/RESTORE.txt` 還原，再重啟來源 app。

---

## 14. Agent / 低階模型操作清單（逐項打勾）

依序執行；不可重排：

1. [ ] §1 進入 `bash`，設定全部變數，`cd` 到 `REPO_ROOT`  
2. [ ] §3 依賴硬閘 → `HARD_GATE_SECTION_3_PASSED`（**不**要求三庫已存在）  
3. [ ] **停下**：對話請使用者確認 MySQL／帳號／允許建庫與 schema → 同意後才繼續  
4. [ ] §4 建立 env → `ENV_FILES_CREATED`  
5. [ ] **停下**：對話請使用者確認來源已停寫 → 同意後才備份  
6. [ ] §5 備份 → `SOURCE_BACKUP_DONE`  
7. [ ] §6.1 診斷 preflight → `PREFLIGHT_DIAG_DONE`  
8. [ ] §6.3 確保三庫存在 → `ENSURE_DATABASES_PASSED`  
9. [ ] §6.4 初始化 schema 到 head → `SCHEMA_INIT_PASSED`  
10. [ ] §6.5 最終 preflight → `PREFLIGHT_PASSED` + `TARGET_READY_FOR_MIGRATE`  
11. [ ] §7 跳過（除非使用者要求 rehearsal）  
12. [ ] §8 migrate → `MIGRATE_WORKFLOW_EXIT_0`，記下 `RUN_DIR`  
13. [ ] §9 證據 → `SUMMARY_EVIDENCE_PASSED`  
14. [ ] §10 smoke → `SMOKE_10_1_PASSED` 與 `SMOKE_10_2_PASSED`  
15. [ ] §11 cutover + post health/verify（部署變更由使用者／維運執行）  
16. [ ] §12 頁面抽樣 → `MIGRATION_COMPLETE`  

任一項失敗：STOP，進 §13，不要繼續下一項。

---

## 15. 本路徑的實跑證據（僅供參考，非正式完成證明）

此流程於 `2026-07-16` 曾用隔離 SQLite 三庫非空來源與 MySQL 8.4 / 8.0 目標實跑通過（含 orphan history、legacy attachment 欄位、restricted DB 帳號等案例）。

- 實跑 artifacts 位於 `.tmp/db-cutover/`（本機驗證輸出，不應提交 Git）。  
- **正式執行必須以該次新產生的 `RUN_DIR/summary.json` 為準**。  
- 不得引用本節表數量或 revision 字串作為正式環境已完成的證據。  
- main head revision 以當次 `head_revision` 為準（文件撰寫附近曾為 `8f1b2c3d4e5a`）。

---

## 16. 指令速查（正式路徑）

```bash
# 皆在 bash 內，且已 export §1 變數

uv sync --frozen

# §6.1 診斷 → §6.3 建缺庫 → §6.4 schema init → §6.5 最終 preflight
# （完整指令見各小節；不可跳過 §6 直接 migrate）

# migrate（§8）— 僅在 TARGET_READY_FOR_MIGRATE 之後；不要加 --manage-services
uv run python scripts/run_db_cutover_workflow.py \
  --mode migrate \
  --target mysql \
  --source-env-file "${SOURCE_ENV}" \
  --target-env-file "${TARGET_ENV}" \
  --health-timeout 120 \
  > "${MIGRATE_JSON}"
```
