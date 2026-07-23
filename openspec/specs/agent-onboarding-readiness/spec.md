# agent-onboarding-readiness Specification

## Purpose
TBD - created by archiving change consolidate-agent-onboarding-docs. Update Purpose after archive.
## Requirements
### Requirement: Single canonical "from zero to running" start path

文件 SHALL 提供唯一一條 canonical 的「從零到可執行」啟動路徑，且該啟動指令在 `README.md`、`AGENTS.md` 與 agent memory（`.serena/memories/suggested_commands.md`）三處互相一致。canonical 啟動指令 SHALL 為 `./start.sh`，套件安裝 SHALL 使用 `uv sync`。

#### Scenario: Agent follows the documented start path

- **WHEN** agent 從 `README.md` 的快速開始（或 `AGENTS.md` 的本機開發標準流程）依序執行
- **THEN** 流程為 `uv sync` → 複製 `config.yaml` 並設定 `JWT_SECRET_KEY` → `./start.sh`
- **AND** 不存在第二條與之衝突、被同等推薦的啟動指令（手動 `uvicorn` 若保留，須明確標為進階替代並指回 canonical）

#### Scenario: Start command consistent across sources

- **WHEN** 以 `rg` 在 `README.md`、`AGENTS.md`、`.serena/memories/suggested_commands.md` 搜尋啟動指令
- **THEN** 三處對「如何啟動服務」給出的 canonical 指令一致（皆為 `./start.sh`）
- **AND** 三處對「如何安裝依賴」給出的指令一致（皆為 `uv sync`，無 `pip install -r requirements.txt`）

### Requirement: All mandated CLI tools have a documented install step

文件 SHALL 為 `AGENTS.md` 工具規則所要求的每一項 CLI 工具（`fd`、`rg`、`ast-grep`、`fzf`、`jq`、`yq`）提供至少一行安裝指令，集中於一個「Prerequisites / 前置工具」段落。

#### Scenario: Agent looks up how to install a mandated tool

- **WHEN** agent 讀到 `AGENTS.md` 要求必須使用 `fd`/`rg`/`ast-grep`/`fzf`/`jq`/`yq`
- **THEN** 在 canonical 文件的 Prerequisites 段落可找到上述每一項工具對應的安裝指令
- **AND** 該段落說明這些工具不在 `pyproject.toml`、需另行安裝

### Requirement: No documented command references a retired flag or nonexistent file

文件與 agent memory 中作為「建議指令」記載的內容 SHALL NOT 引用已退役的旗標或不存在的檔案。具體而言：SHALL NOT 出現 `database_init.py --auto-fix`（已退役、schema 由 Alembic 管理），SHALL NOT 引用 `test_usm_parser.py`（repo 根目錄不存在此檔）。

#### Scenario: Agent reads database init guidance

- **WHEN** agent 讀取任何文件或 agent memory 中關於資料庫初始化的建議指令
- **THEN** 指令為 `uv run python database_init.py`（或經 `./start.sh` 間接執行）
- **AND** 不出現 `--auto-fix` 旗標

#### Scenario: Agent reads test guidance

- **WHEN** agent 讀取任何文件或 agent memory 中關於測試的建議指令
- **THEN** 不出現對 `test_usm_parser.py` 的引用
- **AND** 後端測試指引為 `pytest app/testsuite -q`

### Requirement: System map answers where-to-add-X and the three-DB relationship

文件 SHALL 提供一份 canonical 系統地圖（`llms.txt` 或 `AGENTS.md` 內的系統地圖段落），其內容 SHALL 涵蓋架構總覽、三庫（main / audit / usm）關係、API surface 索引，以及一張「我要新增 X 該改哪裡」對照表。

#### Scenario: Agent asks where to add an endpoint

- **WHEN** agent 查閱系統地圖以決定新增 endpoint / DB 欄位 / 翻譯 / 權限 應改哪些檔案
- **THEN** 對照表為上述四類各給出對應的修改位置（至少含 API router 掛載點、`database_init.py` 與 Alembic、`app/static/locales/`、`config/permissions/`）

#### Scenario: Agent asks about the database layout

- **WHEN** agent 查閱系統地圖中的三庫關係
- **THEN** 文件說明 main（`app/database.py`）、audit、usm（`app/models/user_story_map_db.py`）各自用途
- **AND** 列出三庫各自的 Alembic 設定（`alembic.ini` / `alembic_audit.ini` / `alembic_usm.ini`）與 migration 目錄

### Requirement: Active-change status is consistent across agent-facing docs

文件 SHALL 使 `AGENTS.md` 與 `openspec/project.md` 對「未封存 change」的描述一致，且以 `openspec list` 的實況為準；SHALL NOT 同時出現「目前無 active change」與另一處列出多個未封存 change 的矛盾。

#### Scenario: Agent checks current OpenSpec status

- **WHEN** agent 分別讀 `AGENTS.md` 與 `openspec/project.md` 的 OpenSpec 現況
- **THEN** 兩者對未封存 change 是否存在、以及大致清單的描述彼此一致
- **AND** 不存在一處宣稱「無 active change」、另一處卻列出多個 change 的衝突

### Requirement: Permission model and i18n workflow are documented

文件 SHALL 為 `config/permissions/`（Casbin `model.conf`、`policy.csv`、`constraints.yaml`、`ui_capabilities.yaml`）提供散文說明，並 SHALL 提供 i18n 工作流文件，說明 `app/static/locales/` 三語系檔的新增與同步步驟。

#### Scenario: Agent needs to add a permission rule

- **WHEN** agent 查閱權限文件
- **THEN** 文件說明 `model.conf` 的 request/policy/matcher 定義，以及 `policy.csv`、`constraints.yaml`、`ui_capabilities.yaml` 各自角色

#### Scenario: Agent needs to add a translation

- **WHEN** agent 查閱 i18n 工作流文件
- **THEN** 文件說明需同步更新 `app/static/locales/` 的 `en-US.json` / `zh-CN.json` / `zh-TW.json`，以及與前端 i18n lifecycle 的串接步驟

### Requirement: docs directory has an index

文件 SHALL 在 `docs/README.md` 提供 `docs/` 目錄索引，使 `docs/` 下每一份 `.md` 文件都能由索引找到對應條目。

#### Scenario: Agent browses available docs

- **WHEN** agent 開啟 `docs/README.md`
- **THEN** 可看到依主題分組的文件清單，涵蓋 `docs/` 下現有的各份 `.md`

### Requirement: Agent-config commands have a single source of truth

文件與 repo 結構 SHALL 使 `opsx-*` 命令具備單一來源（single source）並消除 `.cursor` / `.gemini` / `.qwen` / `.opencode` 之間的內容分歧；版控雜訊 SHALL 被排除——`.codex/.venv-skillcreator/` SHALL 列入 `.gitignore`，空的 `QWEN.md` SHALL 被移除或於文件明確記載其用途。

#### Scenario: Agent-config opsx commands stay in sync

- **WHEN** 比對 `.cursor` / `.gemini` / `.qwen` / `.opencode` 中同名的 `opsx-*` 命令
- **THEN** 各目錄同名命令內容一致（由單一來源產生或有明確的同步機制與記載）

#### Scenario: Repo search surface excludes vendored clutter

- **WHEN** agent 以 `rg`/`fd` 在 repo 搜尋
- **THEN** `.codex/.venv-skillcreator/`（約 922 個檔案）已被 `.gitignore` 排除
- **AND** 不存在空的 `QWEN.md` 作為無用占位（或文件已明確記載其保留用途）

