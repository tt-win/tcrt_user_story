## 1. P0 — 確立單一 canonical 啟動路徑

- [ ] 1.1 將 `./start.sh` 訂為唯一 canonical「從零到可執行」啟動指令，並在系統地圖/主文件明確標註其為單一真相來源
- [ ] 1.2 更新 `README.md` 快速開始，使本地開發流程改為 `uv sync` → `cp config.yaml.example config.yaml`（設 `JWT_SECRET_KEY`）→ `./start.sh`，並移除與 `./start.sh` 重複/衝突的手動 `uvicorn` 啟動步驟（或標註其為進階替代並指回 canonical）
- [ ] 1.3 確認 `AGENTS.md`「本機開發標準流程」與上述 canonical 路徑逐字一致（安裝用 `uv sync`、啟動用 `./start.sh`、停止用 `./stop.sh`、健康檢查 `GET /health`）
- [ ] 1.4 驗證三處來源（`README.md`、`AGENTS.md`、`.serena/memories/suggested_commands.md`）的啟動指令完全一致：用 `rg` 搜尋三檔，確認啟動指令僅有一種寫法

## 2. P0 — 修除過時／已退役內容

- [ ] 2.1 改寫 `.serena/memories/suggested_commands.md`：把 `pip install -r requirements.txt` 改為 `uv sync`
- [ ] 2.2 移除 `.serena/memories/suggested_commands.md` 中的 `database_init.py --auto-fix`（該旗標已於 `database_init.py:766-767` 退役、schema 改由 Alembic 管理），改為 `uv run python database_init.py`
- [ ] 2.3 移除 `.serena/memories/suggested_commands.md` 中對 `test_usm_parser.py` 的引用（repo 根目錄無此檔）
- [ ] 2.4 移除 `AGENTS.md` 測試章節中「USM parser 測試：`python test_usm_parser.py`」一段（該檔不存在）
- [ ] 2.5 全庫掃描確認無殘留：`rg -uu -- "--auto-fix|test_usm_parser\.py|pip install -r requirements"` 在文件/agent memory 中不再出現作為「建議指令」

## 3. P0 — 補上 Prerequisites（強制工具安裝）

- [ ] 3.1 在 canonical 文件（`README.md` 與/或 `AGENTS.md`）新增「Prerequisites / 前置工具」段落，列出 `fd`、`rg`、`ast-grep`、`fzf`、`jq`、`yq`
- [ ] 3.2 為每項工具附至少一行安裝指令（例如 macOS Homebrew 與 Linux 套件管理器對應），並說明這些工具為 `AGENTS.md` 工具規則所要求、且不在 `pyproject.toml`
- [ ] 3.3 驗證 `AGENTS.md` 工具規則所列的每一項 CLI 都能在 Prerequisites 段落找到對應安裝步驟（逐項比對）

## 4. P1 — Canonical 系統地圖工件

- [ ] 4.1 建立 canonical 系統地圖（`llms.txt` 或 `AGENTS.md` 內的「系統地圖」段落），作為 agent 入口
- [ ] 4.2 在系統地圖加入「架構總覽」：後端入口 `app/main.py`、API 組裝 `app/api/__init__.py`、服務 `app/services/`、資料存取邊界 `app/db_access/`、前端模板/靜態資產分離
- [ ] 4.3 在系統地圖加入「三庫關係」：main（`app/database.py`）/ audit / usm（`app/models/user_story_map_db.py`）各自用途、各自 Alembic 設定（`alembic.ini` / `alembic_audit.ini` / `alembic_usm.ini`）與 migration 目錄
- [ ] 4.4 在系統地圖加入「API surface 索引」：列出主要 router 與其掛載點（`app/api/__init__.py` / `app/main.py` include）
- [ ] 4.5 在系統地圖加入「我要新增 X 該改哪裡」對照表，至少涵蓋：新增 endpoint、新增 DB 欄位/資料表、新增翻譯（i18n）、新增權限
- [ ] 4.6 確認系統地圖明確標示 canonical 啟動指令（指回 task 1.1）

## 5. P1 — 調解 active change 矛盾

- [ ] 5.1 以 `openspec list`（或 `openspec list --json`）取得未封存 change 的實況
- [ ] 5.2 更新 `AGENTS.md` OpenSpec 章節，使其與 `openspec/project.md` 對「未封存 change」的描述一致（不再出現「目前無 active change」與 project.md 列出多個 change 的矛盾）

## 6. P1 — 權限（Casbin）與 i18n 工作流文件

- [ ] 6.1 新增 `config/permissions/` 說明文件，解釋 `model.conf` 的 request/policy/matcher 定義
- [ ] 6.2 在該文件說明 `policy.csv`、`constraints.yaml`、`ui_capabilities.yaml` 各自角色與彼此關係
- [ ] 6.3 新增 i18n 工作流文件：說明 `app/static/locales/` 三語系檔（`en-US.json` / `zh-CN.json` / `zh-TW.json`）新增與同步文案的步驟，及與前端 i18n lifecycle 的串接
- [ ] 6.4 從 `docs/README.md` 或系統地圖連結到上述權限與 i18n 文件

## 7. P1 — docs 目錄索引

- [ ] 7.1 新增 `docs/README.md`，索引 `docs/` 下現有檔案（依主題分組：Automation Hub、AI Helper、資料庫/遷移、MCP、smoke setup、使用手冊等）
- [ ] 7.2 確認 `docs/` 下每一份 `.md`（除子目錄樣板外）都能在索引中找到對應條目

## 8. P2 — agent 設定去碎片化

- [ ] 8.1 為 `opsx-*` 命令建立單一來源（single source）與產生器，或在 repo 文件明確記載「以哪個目錄為準、其餘由何方式同步」
- [ ] 8.2 用單一來源重新產生/對齊 `.cursor` / `.gemini` / `.qwen` / `.opencode` 的 `opsx-*` 命令，消除內容分歧（以 `rg`/diff 驗證各目錄同名命令內容一致）
- [ ] 8.3 在 `.gitignore` 新增 `.codex/.venv-skillcreator/`，使其約 922 個檔案不再進入版控搜尋面
- [ ] 8.4 移除空的 `QWEN.md`（0 bytes），或在文件中明確記載其保留用途

## 9. 驗證

- [ ] 9.1 逐項對照 `specs/agent-onboarding-readiness/spec.md` 的每條 Requirement 與 Scenario，確認文件現況均可觀察地滿足
- [ ] 9.2 模擬 agent 路徑：依 canonical 啟動段落從零執行（`uv sync` → 設定 → `./start.sh`）可成功起服務並通過 `GET /health`
- [ ] 9.3 確認本變更未編輯 `openspec/specs/` 與任何 app 程式碼（`git diff --name-only` 僅含文件與 agent 設定/`.gitignore`）
