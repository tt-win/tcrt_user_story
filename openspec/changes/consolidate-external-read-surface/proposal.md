## Why

`/api/app/*` 與 `/api/mcp/*` 是**同一組 6 個 read 操作的兩份獨立實作**，共用 `app/models/mcp.py` 的 Pydantic response model 當契約，但查詢與組裝各寫一次。`app/api/app_read.py:1` 的 docstring 自承 `read endpoints equivalent to /api/mcp/*`，並從 `app/api/mcp.py` import 12 個私有符號，卻沒有共用查詢本體。

實測（disposable SQLite、同一份 seed data、同時打兩個 namespace，2026-07-28）在這 6 個操作上找出 **43 項可追蹤分歧（D1–D43）**。其中 **34 項 FIX、9 項 KEEP**（完整表見 `design.md` › Divergence Inventory）。下列 6 項違反已 archive 的 spec 需求：

| # | 情境 | `/api/mcp/*` | `/api/app/*` | 違反的既有需求 | 對應 D |
| --- | --- | --- | --- | --- | --- |
| B3 | `test-cases?search=` 關鍵字在 number 或 tcg 欄位 | 2 筆 | **0 筆**（只搜 `title`） | `mcp-read-api` › App namespace supports the same read filters | D4 |
| B4 | `test-runs?run_type=adhoc` | 0 個 set | **仍回傳全部 set** | `mcp-read-api` › Run filters apply to all categories | D30 |
| B5 | `test-runs`（seed 一個 ARCHIVED set） | 不回傳 | **回傳**；且無 `include_archived` 參數 | `mcp-read-api` › App namespace provides equivalent test run read model | D31 |
| B6 | `test-runs` 的 `summary` keys | 5 個 `*_count` / `total_runs` | **`sets` / `unassigned` / `adhoc`** | 同上 | D40 |
| B5b | `test-runs` 的 set status | `resolve_status_for_response` | **`trs.status` 原值** | 同上 | D32 |
| B4b | `test-case-sections` 排序 | `set_id, level, sort_order, id` | **`sort_order, id`** | Sections deterministic order | D25 |

Lookup 實作缺陷（既有 equivalence 未涵蓋 cross-team lookup）：

| # | 情境 | `/api/mcp/*` | `/api/app/*` | 對應 D |
| --- | --- | --- | --- | --- |
| B1 / B1' | 分頁靜默吞資料 | 正確 offset/limit | 雙重切片 | D14 |
| B2 | `page.total` | DB count | 當頁 `len(items)` | D15 |

**風險最高的三項**：

- **D16（lookup filter 組合）**：MCP 為 AND（scope 在 AND 鏈）；app 為 OR。搬移時若把 scope 放進 OR → **跨 team 繞過**。
- **D5（`set_id` 不存在）**：對齊 MCP 會**放大回傳**（空 → 整 team）；`strict_set` 預設 **false**（已結案）。
- **D36（adhoc 計數）**：app 恆 0，是**回錯資料**。

另：`app/api/mcp.py` 內約 280 行 read helper 困在 router；assistant `tool_executor` 另寫查詢（本變更不併入）。

## What Changes

**新增 `app/services/external_read/`**（唯讀、不開 session、不拋 `HTTPException`）
- `payloads` / `filters` / `counts`：自 mcp 搬 17 helper
- `errors`：**6** 個 domain 例外
- `queries`：6 個 async 讀取；**`allowed_team_ids=None` 不限、`set()` 必須空結果且禁止 `IN ()`**

**Router 薄層化**
- auth / scope 解析 / audit / error map / query 參數（含 limit 上限）
- 消除 app_read / app_pins 對 mcp 的 private import
- **Phase 1 即落地** `AppTokenPrincipal.accessible_team_ids()`（model 單一真相；HTTP 不變）+ 單元測鎖 owner+空 scope
- `mcp_dependencies` 防禦性映射；`queries` 只准 `is None`/`len==0`；D19/D25 防 xpass seed；empty-set 雙測；文件遷移五點可 `rg`

**34 FIX / 9 KEEP**；測試分層（Decision 11），**不**要求每 FIX 一條具名測。

**error shape 不變**（不碰 Stable Error Mapping；歸 `align-app-token-error-envelope`）。

## Capabilities

### New Capabilities
<!-- 無 -->

### Modified Capabilities
- `mcp-read-api`：canonical 語意、lookup 對等、兩層 divergence allowlist、empty scope 契約
- `app-token-client-compatibility`：共用實作義務、`summary` alias、授權 model 契約；**不改** Stable Error Mapping

## Impact

**對 `/api/app/*` client 可觀察（摘要）**

1. 未知 `set_id` → 整 team + `set_not_found`（預設）；`strict_set=true` → 404  
2. lookup number 子字串、多 filter 改 AND、分頁/`total`/排序修正  
3. test-runs：預設藏 archived、`run_type` 生效、set status 動態解析、adhoc 實算、`summary` 5+3 alias  
4. 排序多處改變；`set_id=0` 套用「已提供 set」語意；NULL team status → `"active"`；未知 lookup `team_id` → 404  

**Client 遷移**（docs + skill）：`set_not_found` / `strict_set`、OR→AND、`match_type`、`include_archived`、canonical summary keys。

**明確不變**：error payload 結構；MCP read 語意（mapping 防禦性調整不改變「真實 auth 下的 app token」行為）；model / schema / migration。

**受影響檔案**
- 新增 `app/services/external_read/*`
- 改寫 `app/api/mcp.py`、`app/api/app_read.py`
- 微調 `app/api/app_pins.py`、`app/models/app_token.py`、`app/auth/mcp_dependencies.py`
- 測試：`test_external_read_parity.py`；`test_mcp_api.py` +2；`test_app_token_auth.py` 可加單元斷言（§7.1 若改既有檔）
- 文件：`docs/app_token_api_reference.md`、`docs/mcp_api_interface.md`、`docs/app_token_auth.md`、`tools/skills/tcrt-app/references/api-reference.md`、`openspec/project.md`

**不在範圍**：error envelope 合規、assistant 第四份查詢、D36 count 子查詢優化、其他結構債。

「單一實作」**僅**指兩 namespace 共有的 6 個外部 read。
