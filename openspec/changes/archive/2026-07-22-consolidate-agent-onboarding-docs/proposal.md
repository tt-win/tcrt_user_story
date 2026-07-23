## Why

目前 TCRT 的「如何設定與啟動」說明散落在多份文件、且彼此矛盾，AI coding agent（或新進工程師）無法靠單一來源從零把專案跑起來。具體現況：

- **三條互相衝突的啟動路徑**：`README.md`（手動 `database_init.py` 後 `uv run uvicorn app.main:app --reload ... --port 9999`）、`AGENTS.md`（`./start.sh`）、`.serena/memories/suggested_commands.md`（`pip install -r requirements.txt` + `database_init.py --auto-fix`）。三者使用不同的套件安裝方式（uv vs pip）與不同的啟動指令。
- **過時／已退役指令仍被寫成 agent 指引**：`database_init.py` 已將 `--auto-fix` 標示為「已退役；schema 變更現在由 Alembic 管理」（`database_init.py:766-767`），但 serena memory 仍叫 agent 使用 `--auto-fix`；serena memory 與 `AGENTS.md`（測試章節）都引用 `test_usm_parser.py`，但該檔在 repo 根目錄並不存在。
- **強制工具缺安裝說明**：`AGENTS.md` 要求 agent 必須使用 `fd`/`rg`/`ast-grep`/`fzf`/`jq`/`yq`，但沒有任何文件說明如何安裝這些 CLI，且它們不在 `pyproject.toml`。
- **缺單一機器可讀的系統地圖**：`openspec/project.md` 是目前最完整的地圖，但沒有一份整合「架構總覽 + 三庫關係 + API surface 索引 + 我要新增 X 該改哪裡」的入口。`AGENTS.md`（OpenSpec 章節）寫「目前無 active change」，但 `openspec/project.md` 列出約十一個尚未封存的 change，兩者矛盾。
- **設定面零文件**：`config/permissions/`（Casbin `model.conf` / `policy.csv` / `constraints.yaml` / `ui_capabilities.yaml`）完全沒有散文說明；i18n 工作流只有一行帶過；`docs/`（約二十份檔案）沒有索引 README。
- **agent 設定目錄碎片化**：`.cursor` / `.gemini` / `.qwen` / `.opencode` 各自重複一份 `opsx-*` 命令且內容已開始分歧；`.codex/.venv-skillcreator/`（約 922 個檔案）未被 gitignore、形成雜訊；`QWEN.md` 為空檔。

本變更不改動任何應用程式行為，僅整併文件，使「從零到可執行」具備單一可信來源（single source of truth），並讓系統地圖能直接回答 agent 最常問的「我要改哪裡」。

## What Changes

### P0 — 單一啟動真相與修除過時內容

- 確立 **唯一**的「從零到可執行」標準路徑，以 `./start.sh` 為 canonical 啟動指令；`README.md` 快速開始指向同一路徑，`AGENTS.md` 與 serena memory 與之對齊（安裝一律 `uv sync`）。
- 修正／移除 `.serena/memories/suggested_commands.md` 的過時內容：移除 `pip install -r requirements.txt`、移除 `database_init.py --auto-fix`、移除不存在的 `test_usm_parser.py`，改用 uv 流程。
- 移除 `AGENTS.md` 測試章節對 `test_usm_parser.py` 的引用（該檔不存在）。
- 新增 **Prerequisites（前置工具）** 段落，列出 `fd` / `rg` / `ast-grep` / `fzf` / `jq` / `yq`，每項附一行安裝指令（例如 macOS Homebrew 與 Linux 對應）。

### P1 — 系統地圖與設定面文件

- 新增一份 canonical 的 **agent 系統地圖**工件（`llms.txt` 或 `AGENTS.md` 內的系統地圖段落），涵蓋：架構總覽、三庫（main / audit / usm）關係、API surface 索引、以及「我要新增 endpoint / DB 欄位 / 翻譯 / 權限 該改哪裡」的對照表。
- 調解「active change 數量」矛盾：`AGENTS.md` 與 `openspec/project.md` 對未封存 change 的描述須一致（以 `openspec list` 實況為準）。
- 補上 `config/permissions/` 的 Casbin 模型說明（`model.conf` 的 request/policy 定義、`policy.csv`、`constraints.yaml`、`ui_capabilities.yaml` 各自角色）與 i18n 工作流文件（`app/static/locales/` 三語系檔的新增／同步步驟）。
- 新增 `docs/README.md` 作為 `docs/` 目錄索引。

### P2 — agent 設定去碎片化

- 為 `opsx-*` 命令建立單一來源 + 產生器（或明確的同步說明），消除 `.cursor` / `.gemini` / `.qwen` / `.opencode` 之間的重複與分歧。
- 將 `.codex/.venv-skillcreator/` 加入 `.gitignore`（移出版控雜訊）。
- 移除空的 `QWEN.md`（或在文件中明確說明其用途）。

非目標（Non-Goals）：

- 不重寫終端使用者操作手冊（`docs/user_manual.md` 等使用面文件）。
- 不改變任何應用程式行為、API、schema 或設定預設值。
- 不新增/移除任何強制工具本身，只補上既有強制工具的安裝說明。
- 不在本變更內編輯 `openspec/specs/`（主規格）或任何 app 程式碼。

## Capabilities

### New Capabilities

- `agent-onboarding-readiness`: 定義「文件已就緒，可讓 AI coding agent 或新進工程師快速理解如何設定與啟動 TCRT，且具備單一可信來源」所需滿足的**可觀察文件屬性**——包含單一 canonical 啟動路徑且跨 README/AGENTS/agent memory 一致、所有強制 CLI 工具皆有安裝步驟、無任何已記載指令引用已退役旗標或不存在檔案、系統地圖能回答「我要改哪裡」與三庫關係、權限與 i18n 工作流有文件、agent 設定具單一來源。

### Modified Capabilities

<!-- 無既有 capability 的需求被變更；本變更僅新增文件就緒性需求，不修改 openspec/specs/ 內任何主規格。 -->

## Impact

- **文件**：
  - `README.md`：快速開始改為指向 canonical `./start.sh` 路徑；新增 Prerequisites 段落。
  - `AGENTS.md`：對齊 canonical 啟動路徑；移除 `test_usm_parser.py` 引用；調解 active change 描述；可能新增/連結系統地圖段落。
  - `.serena/memories/suggested_commands.md`：移除 pip / `--auto-fix` / `test_usm_parser.py`，改用 uv 流程。
  - 新增系統地圖工件（`llms.txt` 或 `AGENTS.md` 段落）、`docs/README.md` 索引、`config/permissions/` 說明文件、i18n 工作流文件。
- **AI agent 設定**：
  - `opsx-*` 命令收斂為單一來源（含產生器或同步說明），`.cursor` / `.gemini` / `.qwen` / `.opencode` 以之為準。
  - `.gitignore` 新增 `.codex/.venv-skillcreator/`；移除空的 `QWEN.md`。
- **相容性**：純文件與 agent 設定整併，不觸及應用程式行為、API 契約、資料庫 schema 或設定預設值；無資料庫 migration、無 rollback 風險。`openspec/specs/` 與 app 程式碼皆不變動。
