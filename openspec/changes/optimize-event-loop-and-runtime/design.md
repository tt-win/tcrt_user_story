# Design: optimize-event-loop-and-runtime

> 本文件包含實作所需的全部 file:line 線索與已查證事實。實作 agent 不需要原始評估對話的上下文即可照本文件工作。行號以 2026-07-15 的 main（commit 2b8b9bd 之後）為準；若程式碼已漂移，以文中的符號名/函式名重新定位。

## Context

- 量測事實（2026-07-15，macOS dev + 300 併發實測）：app 程序 idle 0% CPU、負載下瞬時 ~33% 即回落。系統為 I/O-bound，瓶頸不在 Python runtime。
- 已找出的實際問題：
  1. `app/services/lark_client.py` 的**所有**方法都是同步 `def`＋`requests`，且內建 `time.sleep` 重試退避（`lark_client.py:248,269,282`）。async 呼叫端直接呼叫它們（未離載），一個慢的 Lark 呼叫（逾時上限可達數十秒）會佔住 event loop，阻塞**全站所有**進行中請求。
  2. `app/api/attachments.py` 的 Lark 代理下載段（`:644-722`）在 async 路由內 inline `requests.get(stream=True, timeout=30)`（`:666`）與同步 token 取得（`:657`），連線與串流全程佔住 loop。
  3. ASGI 層跑最慢組態：依賴是純 `uvicorn==0.40.0`（非 `[standard]`），無 uvloop、無 httptools；JSON 回應全走 stdlib `json`（全 repo ~293 處用法）。
- 對照組（repo 既有正確 pattern）：Jira 整合同樣是同步 client（`app/services/jira_client.py`），但呼叫端**全部**以 `await asyncio.to_thread(...)` 包裝——見 `app/api/jira.py:85,140,175,217,276,399`。本 change 就是把這個 pattern 套到 Lark。

## Goals / Non-Goals

**Goals:**

- Event loop 上不再有同步外部 HTTP 呼叫（Lark、附件代理）。
- ASGI 層升級到 uvloop + httptools；JSON 回應序列化改 orjson。
- **行為完全不變**：API 回應內容、狀態碼、header、錯誤語意與現在逐位元相容（唯一例外是速度）。

**Non-Goals:**

- 不改寫 `lark_client.py` 為 async client（維持同步實作＋呼叫端離載，與 Jira 一致）。
- 不做全域 stdlib `json` → orjson 替換（只動 response class 與兩處熱點 loads）。
- 不改 `WEB_CONCURRENCY` 預設值、不動 `background-service-scaling` 的行為（該 spec 已保證多 worker 安全，本 change 只補操作文件）。
- 不處理 `html_report_service.py` / `team_statistics.py` 的聚合演算法優化（另案；先有 profiling 證據再說）。

## Decisions

### D1 — Lark 同步呼叫以 `asyncio.to_thread` 在呼叫端離載（不改 client）

**選擇**：沿用 Jira pattern（呼叫端 `await asyncio.to_thread(sync_fn, args...)`），不把 `lark_client.py` 改成 async。

**理由**：(a) repo 已有完全相同的先例（`app/api/jira.py:85` 等 6 處），收斂既有慣例；(b) 改 client 為 async 需要改動全部呼叫鏈簽名，血染範圍大得多；(c) `LarkClient` 的共享狀態**已經是執行緒安全設計**——token 快取有 `self._token_lock = threading.Lock()`（`lark_client.py:32`），兩個服務層快取有 `self._cache_lock`（`:98`、`:518`）。**實作 agent 不要再加鎖**，既有鎖已足夠。

**包裝點原則**：在 async→sync 邊界包**一整段**同步流程，不要逐個 client 呼叫包多次。若某 async 函式呼叫一個同步服務函式、而該函式內部打多次 Lark API，正確做法是 `await asyncio.to_thread(該同步服務函式, ...)` 一次；錯誤做法是進到函式裡把每個 client 呼叫各包一層。

**需離載的 async 呼叫點**（2026-07-16 以 `rg -n "lark_client\.|auth_manager\.get_tenant_access_token" app/ --type py` 重新盤點；除 client 內部同步實作與 testsuite 外，以下為已確認清單）：

| 呼叫點 | 說明 |
|---|---|
| `app/api/lark_users.py:get_lark_user_basic` | async 路由直接呼叫同步 Lark 使用者查詢 |
| `app/api/lark_groups.py:get_lark_groups` | async 路由呼叫同步群組查詢服務；整段 `list_groups` 離載一次 |
| `app/api/test_runs.py` | 多個 async CRUD/統計路由直接呼叫同步 client；每段連續 Lark 流程離載一次 |
| `app/api/teams.py:validate_lark_repo,validate_table` | async 驗證路由直接設定 wiki token、查 table fields；各驗證流程離載一次 |
| `app/api/attachments.py` | async 上傳、關聯、移除與代理下載路徑直接呼叫同步 client；連續 Lark 流程各離載一次 |
| `app/services/lark_org_sync_service.py:151` 起 | async 的 `sync_users_only` 等方法內呼叫同步 client；scheduler 的 `_run_lark_org_sync`（`app/services/scheduler.py:285`）走這裡，一併受惠 |
| `app/services/lark_user_service.py:88` | 同步 `requests` 呼叫，上游是 async |
| `app/services/lark_department_service.py:77` | 同上 |
| `app/services/lark_notify_service.py:127` | 同上 |
| `app/services/lark_group_service.py:38,66` | 同上 |
| `app/services/test_result_file_service.py` | async 上傳/關聯流程直接呼叫同步 client |
| `app/services/test_result_cleanup_service.py` | async 清理流程直接呼叫同步 client |

`app/api/test_run_items.py:_get_lark_client_for_team` 也被文字搜尋命中，但 2026-07-16 以 references 盤點確認為未被呼叫的同步 helper；它不是有效 async 執行路徑，本 change 不為死路徑增加包裝。實際上傳整合由 `TestResultFileService` 處理，已列入上表。

**注意**：`app/api/attachments.py:657` 的 `get_tenant_access_token()` 屬於 D2 範圍一併處理。若 async 函式在 Lark I/O 之間必須執行 async DB 操作，無法把整個函式丟進 thread；此時以「每段連續同步 Lark 流程包一次」為邊界，不跨越 `await` 硬併。

### D2 — 附件代理下載改 `aiohttp` 串流（零新依賴）

**選擇**：`app/api/attachments.py:644-722`（「優先級 4：代理 Lark 下載」段）改用 `aiohttp`（`aiohttp==3.13.3` 已在 `pyproject.toml`）。不用 `asyncio.to_thread` 包 `requests` 串流——串流迭代本身也會阻塞，to_thread 只能救連線不能救串流；aiohttp 是唯一乾淨解。

**必須逐項保留的行為契約**（現況行號在括號內）：

1. token 取得（`:657`）：`lark_client.auth_manager.get_tenant_access_token()` 是同步呼叫（刷新時會打 Lark auth API），改為 `await asyncio.to_thread(lark_client.auth_manager.get_tenant_access_token)`。token 為 None → 500（`:658-659`），不變。
2. 狀態碼映射（`:668-675`）：上游 401 → 本地 401；上游 404 → 本地 404；其他非 200 → 502（detail 含上游 HTTP 狀態碼）。
3. 逾時與錯誤（`:717-722`）：總逾時 30 秒。對映關係——`requests.exceptions.Timeout` → 504 對應 aiohttp 的 `asyncio.TimeoutError`（`aiohttp.ClientTimeout(total=30)` 逾時時拋出）；`requests.exceptions.RequestException` → 502 對應 `aiohttp.ClientError`；其餘 Exception → 500。**except 順序必須：HTTPException re-raise → TimeoutError → ClientError → Exception**。
4. Header 傳遞（`:677-702`）：Content-Type 原樣轉發（`:681-683`）；Content-Disposition——有 `filename` 參數時：純 ASCII 用 `attachment; filename="..."`，含非 ASCII 用 RFC 5987 `filename*=UTF-8''<urlencoded>`（`:686-695`）；無 filename 但上游有 content-disposition 時原樣轉發（`:696-697`）；Content-Length 上游有才轉發（`:700-702`）。**這段 header 組裝邏輯與 HTTP client 無關，原樣搬移即可，不要重寫。**
5. 串流（`:705-713`）：8192 bytes chunk，串流結束（含異常）時關閉上游連線。aiohttp 對應寫法：async generator 內 `async for chunk in response.content.iter_chunked(8192): yield chunk`，並讓 `ClientSession`/response 的 `async with` 生命週期涵蓋整個 generator（即 session 在 generator 內部開啟，而非在路由函式 body 開啟後傳入——否則 StreamingResponse 開始消費時 session 已關閉）。

**Session 生命週期**：per-request 建立 `aiohttp.ClientSession`。此端點呼叫頻率低，不值得引入 app 級共享 session 的啟停管理複雜度。

**陷阱提醒**：狀態碼檢查（上述第 2 點）必須在**開始串流之前**完成——即先 `await session.get(...)` 拿到 response、檢查 `response.status`、組 headers，確認 200 才回傳 StreamingResponse。因為 FastAPI 一旦開始送出 response 就無法再改狀態碼。可用 pattern：外層 async 函式負責建立 session＋檢查狀態＋組 header，內部 async generator 負責 yield chunks 與清理（generator 持有 session 的關閉責任，`finally` 內 `await response.release()`＋`await session.close()`）。

### D3 — `WEB_CONCURRENCY` 操作文件化（純文件）

- 程式已支援：`docker/app-entrypoint.sh:9` 預設 `WEB_CONCURRENCY=1`；`:48-50` 當值 >1 時自動附加 `--workers`；`:46-47` 註解已說明 scheduler/automation ticker 有 DB advisory-lock leader election，多 worker 安全（行為 requirement 在 `openspec/specs/background-service-scaling/spec.md`，本 change 不動它）。
- 要補的文件內容：(a) 建議值（CPU 核數或核數×2 以內）；(b) **per-worker 語意註記**——per-IP 認證失敗 rate limiter 是 in-process token bucket（見 `openspec/changes/harden-app-token-security/design.md`），N 個 worker 下有效限額為 N×30 次/分鐘，屬已知且可接受的放寬。
- 位置：先 `rg -l "WEB_CONCURRENCY" docs manual README* docker/` 找既有部署文件；若只有 entrypoint 註解，就近在 `docker/` 相關 README 或 entrypoint 註解區塊擴充，不要新開孤立文件。

### D4 — `uvicorn[standard]`（Scope B1，新依賴 extras：uvloop/httptools/websockets/watchfiles 等）

- `pyproject.toml` 的 `"uvicorn==0.40.0"` 改為 `"uvicorn[standard]==0.40.0"`（版本不動，只加 extras），然後 `uv lock` + `uv sync`。
- **不需改任何啟動指令**：uvicorn 預設 `--loop auto --http auto`，偵測到 uvloop/httptools 即自動採用。涵蓋全部三個啟動入口：`docker/app-entrypoint.sh:40`、`start.sh:41`、`app/main.py:500`。
- 測試不受影響（design 依據）：pytest-asyncio 測試自建 event loop，不經 uvicorn 的 loop 選擇；uvloop 只在 server 程序內生效。
- 附帶效益：目前無 watchfiles 時 `--reload` 落到 StatReload 全樹輪詢（先前 dev watcher 高 CPU 事件的放大因素）；裝了 watchfiles 後 reload 監看改用 FSEvents/inotify。`--reload-dir app` 限縮（`start.sh:35-39`、`.claude/launch.json`）維持不變。
- 平台註記：uvloop 不支援 Windows。本專案部署面為 Docker/Linux 與 macOS dev，不受影響；Windows 上 uvicorn 會自動 fallback 到 asyncio loop，不會壞。
- `uv sync` 後的啟動煙霧另揭露 `app/runtime_locks.py` 已使用 `portalocker`，但原依賴清單未宣告；2026-07-16 經使用者核准補上 `portalocker==3.2.0`，確保乾淨環境可執行 SQLite bootstrap/leader lock。這是既有 runtime 契約的依賴補漏，不改鎖行為。
- uvicorn 0.40 已移除 `Config.setup_event_loop()`；auto loop 驗證使用 `Config(...).get_loop_factory()` 建立 loop，支援平台應輸出 `uvloop` module。

### D5 — orjson 回應序列化與熱點 loads（Scope B2，新依賴 orjson）

**5a. 全域 response class**：

- `app/main.py:26` 的 `app = FastAPI(` 加 `default_response_class=<自訂類>`。
- **不能直接用 `fastapi.responses.ORJSONResponse`**：stdlib `json.dumps` 會靜默把 int dict key 轉成字串，orjson 預設遇到非字串 key 直接拋 `TypeError` ——直接換會讓任何回傳 int-key dict 的既有端點從 200 變 500。必須自訂子類：

```python
import orjson
from fastapi.responses import JSONResponse

class ORJSONCompatResponse(JSONResponse):
    """orjson serialization with stdlib-json-compatible semantics (int keys → string)."""
    media_type = "application/json"

    def render(self, content) -> bytes:
        return orjson.dumps(content, option=orjson.OPT_NON_STR_KEYS)
```

- 放置位置：新增小模組（建議 `app/utils/` 或 `app/models/` 既有慣例處；避免塞進 main.py 造成循環 import 風險——實作時看 `app/` 下最接近的 utils 慣例）。
- **已查證的相容性事實**（實作 agent 可直接引用，不需重新驗證）：
  - FastAPI 的回傳值（含 response_model 路徑與裸 dict）先經 `jsonable_encoder` 處理（datetime/UUID/Decimal 已轉為字串/float）才進 response class 的 `render()`，所以 datetime 序列化差異**不是**風險。
  - 風險只有兩個：non-str dict keys（用 `OPT_NON_STR_KEYS` 解）與 float NaN/Infinity（stdlib 預設輸出非標準 `NaN`，orjson 拋錯）。統計端點（`app/api/team_statistics.py` 的 p95 等計算）需確認空集合防護後不會產生 NaN；若測試中發現有 NaN 路徑，修法是在來源處 guard（回 None/0），不是換序列化選項。
  - 直接回傳 `JSONResponse(...)` 的端點不受 default_response_class 影響（維持 stdlib），行為不變。
- **必附回歸測試**：一個回傳 int-key dict 的最小端點測試（可用測試內臨時 router，比照 `app/testsuite/test_app_token_auth.py:384` 的 `_test_router` 手法），斷言回應 JSON 的 key 是字串——證明與 stdlib 行為一致。

**5b. 熱點 loads 替換（僅以下兩處，其餘 ~293 處 stdlib json 一律不動）**：

- `app/api/team_statistics.py:173` `_safe_json_loads`：per-row 呼叫。`json.loads(raw)` → `orjson.loads(raw)`。
- `app/api/mcp.py:119` `_parse_json_list`：MCP read payload per-row 解析。同上替換。
- **已查證**：`orjson.JSONDecodeError` 繼承自 `json.JSONDecodeError`（進而繼承 `ValueError`），既有 `except json.JSONDecodeError` 子句**不需要改**。注意 orjson.loads 只吃 `bytes | str`，兩處呼叫端都已先做 `isinstance(raw, str)` 檢查，安全。
- 遮蔽相關既有測試（`app/testsuite/test_mcp_api.py` 的 credential 遮蔽斷言）必須維持全綠——`redact_credential_test_data` 在 loads 之後作用，不受影響。

**依賴 pin**：`uv add orjson` 後把 `pyproject.toml` 的條目改為 `==` 精確 pin（跟 repo 既有全部依賴一致的慣例）。

## Risks / Trade-offs

- [to_thread 併發占用 threadpool] 預設 executor 上限（`min(32, cpu+4)`）在 Lark 大量並發時可能排隊 → 可接受：排隊只影響 Lark 呼叫本身，event loop 與其他請求不再受害（現況是全站受害）。不另調 executor 大小，避免無證據的預先優化。
- [aiohttp 代理改寫遺漏行為] 狀態碼/header/檔名邊角行為漂移 → 緩解：design 已逐項列出行為契約（D2 五點），tasks 要求先寫測試覆蓋 401/404/502/504 映射與 RFC 5987 檔名再改實作。
- [orjson int-key/NaN 相容性] 既有端點 500 → 緩解：`OPT_NON_STR_KEYS` 子類＋int-key 回歸測試＋全測試套件必須綠；發現 NaN 路徑時修資料來源。最壞情況 revert `default_response_class` 一行即回穩。
- [uvloop 與 greenlet/SQLAlchemy async 相容性] → 已知安全組合（SQLAlchemy async + uvloop 是主流生產組態），且測試套件不經 uvicorn loop；仍以 4.2 的啟動煙霧測試守門。
- [依賴面擴大] uvicorn[standard] 帶入多個 extras → 皆為 uvicorn 官方維護的標準組合，且 `uv.lock` 鎖定版本。

## Migration Plan

- 部署：一般滾動部署即可，無 schema/資料變更、無設定變更需求。
- 回退：三個獨立回退單元——(1) revert Lark/attachments 程式變更；(2) revert `pyproject.toml` uvicorn extras＋`uv lock`；(3) revert orjson（拿掉 default_response_class 與兩處 loads）＋`uv lock`。互不依賴，可各自單獨回退。

## Open Questions

（無——依賴新增已獲使用者明確同意（2026-07-15），實作決策已全部定案。）
