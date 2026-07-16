# Proposal: optimize-event-loop-and-runtime

## Why

效能量測（2026-07-15）證實 TCRT 的瓶頸不在語言 runtime（app idle 0% CPU、300 併發僅瞬時 ~33%），而在三個具體問題：(1) Lark 整合與附件下載代理在 async 路徑上直接呼叫同步 `requests`＋`time.sleep` 重試，單一慢呼叫會阻塞整個 event loop 上的**所有**請求；(2) ASGI 層跑在最慢組態（純 `uvicorn`，無 uvloop/httptools）；(3) JSON 序列化全用 stdlib。修這三項比任何改寫語言的方案便宜數個量級，且風險可控。

## What Changes

- **Lark 同步呼叫離載**：所有 async 路徑上的 Lark client 同步呼叫，比照既有 Jira pattern 以 `asyncio.to_thread` 離載，event loop 不再被外部 HTTP 阻塞。
- **附件下載代理改 async 串流**：`/api/.../attachments` 的 Lark 代理下載段改用 `aiohttp`（既有依賴）串流，保留全部狀態碼映射、header 傳遞與逾時語意。
- **runtime 加速（新依賴，已獲使用者同意）**：
  - `uvicorn` → `uvicorn[standard]`（帶入 uvloop、httptools、watchfiles 等）
  - 新增 `orjson`：以自訂 response class 作為全域 JSON 回應序列化器，並替換兩處 per-row 解析熱點；**必須保持 stdlib 相容語意**（int dict key 轉字串），其餘 ~293 處 stdlib `json` 用法不動。
- **多 worker 操作文件化**：`WEB_CONCURRENCY` 用法與 per-worker rate-limit 語意補進部署文件（程式已支援，見 `background-service-scaling` spec，純文件補充）。

無 BREAKING 變更：所有對外 API 行為、回應內容與錯誤語意維持不變；本 change 的驗收核心就是「行為不變、只變快」。

## Capabilities

### New Capabilities

- `async-runtime-performance`：web runtime 的 event-loop 不阻塞保證（外部同步 I/O 必須離載）、附件代理 async 串流行為契約、JSON 回應序列化的 stdlib 相容語意、ASGI runtime 加速組態。

### Modified Capabilities

（無——`background-service-scaling` 已涵蓋多 worker 安全性 requirement，本 change 對它只補操作文件，不改其行為要求。）

## Impact

- **受影響程式**：所有已盤點的 async→sync Lark 邊界，包含 `app/api/attachments.py`、`app/api/lark_users.py`、`app/api/lark_groups.py`、`app/api/test_runs.py`、`app/api/test_run_items.py`、`app/api/teams.py`、`app/services/lark_org_sync_service.py`、`app/services/lark_user_service.py`、`app/services/lark_department_service.py`、`app/services/lark_notify_service.py`、`app/services/test_result_file_service.py`、`app/services/test_result_cleanup_service.py`；另含 `app/main.py`（default_response_class）、`app/api/team_statistics.py`、`app/api/mcp.py`（loads 熱點）。
- **依賴**：`pyproject.toml` 三筆變更——`uvicorn[standard]==0.40.0`（extras 帶入 uvloop/httptools/websockets/watchfiles）、新增 `orjson==3.11.9`，以及補宣告既有 runtime lock 已使用但先前漏列的 `portalocker==3.2.0`；`uv.lock` 隨之更新。uvloop 不支援 Windows，本專案部署面（Docker/Linux、macOS dev）不受影響。
- **不受影響**：DB schema（無 migration）、MCP/AI helper 行為契約、排程（scheduler 的 Lark org sync 走同一批服務層，自動受惠於離載）、前端。
- **風險與回退**：全部變更可獨立回退——to_thread 包裝與 aiohttp 代理是純程式碼 revert；依賴升級 revert `pyproject.toml`＋`uv lock` 即可。orjson 的已知相容性風險（int dict key、NaN）在 design.md 有明確緩解方案與回歸測試要求。
