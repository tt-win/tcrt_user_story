## Why

目前 TCRT 的外部非互動式存取集中在 `/api/mcp/*`，定位是 MCP 專用唯讀 API；新的整合需求需要 by team 的 app token 能執行完整 test case / test run 操作，包含建立、更新、刪除、執行與狀態回寫等既有使用者 API 承載的工作流。

直接讓 app token 冒充 user 呼叫既有 JWT API 會模糊 audit actor、role / team permission 邊界與敏感資料外洩責任；本 change 將 MCP machine-token 能力升級並改名為正式的 app-token API surface，讓外部存取可被 team scope、operation scope、audit 與回滾機制明確控管。

## What Changes

- 新增 team-owned app token 概念，取代「MCP 專用 machine token」作為正式外部 API 憑證；token 仍採 opaque raw token + server-side hash 儲存，只在建立時顯示一次。raw token 採 `tcrt_app_` 可識別前綴，另存 `token_prefix` 供列表識別與 secret scanning；未指定到期日時預設 90 天，不到期需明確選擇。
- 新增 `/api/app/*` 命名空間作為正式 app-token API；既有 `/api/mcp/*` 保留唯讀相容期，並由相同 app-token principal 驗證邏輯支援。
- 擴展外部 API 能力，使 app token 可覆蓋 test case / test run 的完整操作面；包含目前 read API 已有的查詢能力，以及既有 TCRT UI/API 可做的 test case、test case set/section、test data、attachments、test run config、test run set、test run item / execution、report / automation trigger 等 team-scoped 操作。
- 新增 app-token scope / permission 模型，至少區分 read / write / admin 類操作，並以 team scope 作為第一層強制授權；所有寫入預設拒絕，需明確 scope 才可執行。
- 新增 team 管理介面與 API，讓授權使用者可在 team 範圍內建立、列出、撤銷與輪替 app tokens；Super Admin 仍可跨 team 稽核與撤銷。
- 更新 audit 行為：所有 app-token allow / deny / write operation 都必須以 app principal 記錄，不得偽裝成人類 user；寫入 audit detail 不可包含 raw token、token hash 或 test data credential 明文。
- 更新 `tcrt_mcp` server 消費契約：從 `/api/mcp/*` read-only client 遷移到 `/api/app/*` app-token client，並新增受 scope 控制的 write-capable MCP tools；高風險 mutation tool 必須有清楚 tool name、參數驗證與 audit redaction。
- 不立即移除既有 `/api/mcp/*` read endpoints；本 change 以相容 alias / deprecation path 方式升級，避免現有 MCP client 立刻失效。

## Capabilities

### New Capabilities
- `team-app-token-auth`: 定義 team-owned app token 的建立、hash 儲存、狀態、到期、撤銷、輪替、team scope、operation scope、principal 解析與 allow/deny audit 行為。
- `app-token-test-case-api`: 定義 `/api/app/*` 下 test case 相關外部 API 的讀寫契約，涵蓋 test cases、test case sets、sections、test data、attachments 與批次操作，並要求與既有 UI/JWT 行為保持資料語意一致。
- `app-token-test-run-api`: 定義 `/api/app/*` 下 test run 相關外部 API 的讀寫契約，涵蓋 test run configs、test run sets、run items / execution、status updates、report generation 與既有 test run automation trigger。
- `app-token-management-ui`: 定義 team management / organization management 中 app token 管理體驗、i18n、一次性 token 顯示、metadata-only 列表、撤銷與 scope 呈現。
- `app-token-client-compatibility`: 定義既有 `/api/mcp/*` read API 的相容期、`/api/app/*` 等價 read endpoint、錯誤碼相容與外部 client migration 規則。

### Modified Capabilities
- `mcp-machine-auth`: MCP 專用 machine credential SHALL 被升級為 app-token principal 的相容模式；既有 `mcp_read` token 可在相容期內繼續讀取，但新 token 與新文件以 app token 命名。
- `mcp-read-api`: 既有 MCP read-only namespace SHALL 轉為 `/api/app/*` read surface 的相容 alias；規格需明確列出哪些 endpoint 保留 read-only，哪些 mutation 只存在於 app-token API。
- `test-case-management`: 外部 app-token 寫入 test case 時 SHALL 沿用既有本地 test case 管理語意、驗證規則、team boundary、default set / section 行為與 audit 要求。
- `test-run-multi-set-integrity`: 外部 app-token 修改 test run / test run set membership 時 SHALL 保持既有 multi-set scope、cross-team rejection、cleanup summary 與 destructive-impact preview 規則。
- `test-run-management-ui`: app-token API 暴露的 test run set automation suite membership 與 Run as Automation 行為 SHALL 與既有管理頁契約一致；若 UI/API 行為有差異，需在 spec 中明確標示。
- `automation-hub-run-orchestration`: app-token 觸發 test run automation 時 SHALL 使用現有 orchestration 與 audit / trigger_source 語意，不得新增平行的執行通道。

## Impact

- Backend API：新增或重構 `app/api/mcp.py` / 新增 `app/api/app_tokens*.py`、test case / test run app API routers、router registration 與 shared response schemas。
- Auth / permissions：新增 app-token principal dependency、team scope + operation scope guard、app-token audit helper；避免改動 `get_current_user` 語意與既有 JWT API contract。
- Database：需要非破壞性 migration（例如新增 `team_app_tokens` 或在既有 `mcp_machine_credentials` 上新增 token type / owner team / scopes / rotation metadata）。需同步 Alembic、`database_init.py`、bootstrap 與 SQLite / MySQL / PostgreSQL 相容性。
- Audit：需要更新 audit resource type / action detail 白名單與 redaction，確保 token secret、token hash、credential 類 test data 不進 audit 明文。
- Frontend / i18n：team / organization management 頁新增 app token 管理 UI；所有文案同步 `en-US` / `zh-CN` / `zh-TW`。
- Tests：需要 focused API tests 覆蓋 token lifecycle、scope allow/deny、read/write operation scope、test case CRUD、test run CRUD / execution、audit redaction、migration/bootstrap，以及既有 `/api/mcp/*` read compatibility。
- External system：`/Users/hideman/code/tcrt_mcp` 需要同步更新 config 命名、HTTP client endpoint、tool surface、write tool validation、audit redaction、README / install docs 與 tests；在 TCRT 相容期內可先支援兩種 namespace。
- Compatibility / rollback：既有 user JWT API 不因 app-token API 改變；若發布後需回滾，可停用 `/api/app/*` router 或 feature flag、撤銷 app tokens，並保留 `/api/mcp/*` read-only 行為供現有 MCP client 使用。
