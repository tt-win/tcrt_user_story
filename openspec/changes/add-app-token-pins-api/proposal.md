## Why

現有 Pin（釘選）功能（`/api/pins`、`UserPin` 表）僅供人類 JWT 使用者使用，是 per-user 個人書籤，`/api/app/*` app-token API 完全無法存取。使用者要求把 Pin 功能也納入 `tcrt-app-token` skill；但機器憑證（app token / legacy machine credential）沒有「個人使用者」身分，無法套用現有 per-user 語意。因此需要先在後端新增一個 team-scoped、app-token 可用的 Pin API，再串接到 skill。

## What Changes

- 新增 `app_token_pins` 資料表：team-scoped 共享釘選清單，與既有 `user_pins`（per-user）為完全獨立的表格；兩者的建立／刪除互不寫入或刪除對方資料列。
- 新增 `/api/app/teams/{team_id}/pins` API surface（list / create / delete），使用既有 app-token principal 驗證與 team scope guard；write 依 `entity_type` 對應到 `test_case:write`（`test_case_set`）或 `test_run:write`（`test_run_set` / `test_run` / `adhoc_run`），read 只需具備 `test_case:read` 或 `test_run:read` 任一 scope。
- 建立與刪除皆為冪等操作（已釘選視為成功、刪除不存在項目回報 `deleted=0`），語意與既有人類 Pin API 一致。
- 所有 allow / deny / mutation 皆寫入既有 app-token audit helper，遵循相同 redaction 規則。
- **人類可見性**：既有 `/api/pins`（JWT）的 list 回應改為合併回傳個人釘選與該 team 的 app-token 團隊共用釘選（並以 `token_pinned` 標示來源），使 app-token 釘選能在既有人類 UI（Test Case Set 列表、Test Run 管理頁）置頂顯示；`/api/pins` 的建立／刪除端點本身不變，仍只操作 `UserPin`。前端 `pin-store.js` 與兩個消費頁面的釘選按鈕，對 app-token 來源的項目改為唯讀置頂（無法在此取消）。
- 更新 `tcrt-app-token` skill 文件，暴露新的 pin 端點與所需 scope。

## Capabilities

### New Capabilities
- `app-token-pins-api`: 定義 `/api/app/*` 下 team-scoped pin 的 list / create / delete 契約、scope 對應、冪等行為與 audit 要求。

## Impact

- Database：新增非破壞性 migration 建立 `app_token_pins`（新表，不修改既有 `user_pins`）；更新 `database_init.py` 的 `MAIN_REQUIRED_TABLES`。
- Backend API：新增 `app/api/app_pins.py`，於 `app/api/__init__.py` 註冊 router；修改既有 `app/api/pins.py` 的 `list_pins`，合併 `AppTokenPin` 資料並回傳 `token_pinned` 標示（`create_pin`/`delete_pin` 不變，仍只操作 `UserPin`）。
- Frontend：修改 `app/static/js/common/pin-store.js`（新增 `isTokenPinned`、`token_pinned` 合併邏輯）、`app/static/js/test-case-set-list/main.js`、`app/static/js/test-run-management/render.js`（app-token 釘選顯示為唯讀置頂），以及對應 `test-case-set-list.css` / `test-run-management.css` 的 `.pin-toggle.token-pinned` 樣式。
- i18n：新增 `common.pinnedByAppToken`，同步 `en-US` / `zh-CN` / `zh-TW`。
- Tests：新增 `app/testsuite/test_app_token_pins_api.py`，覆蓋 list / create / idempotent create / delete / scope deny / team scope deny / cross-team isolation / 無效 entity_type；擴充既有 `/api/pins` 測試覆蓋 merge 行為。
- Docs：更新 `tools/skills/tcrt-app-token/SKILL.md` 與 `references/api-reference.md`。
- Rollback：新表為 additive migration，downgrade 可直接 drop table；`list_pins` 的合併邏輯可還原為只查 `UserPin`（單一函式內的邏輯回退，無需額外 migration）；同時移除 router 註冊即可完全回滾，不影響既有功能。
