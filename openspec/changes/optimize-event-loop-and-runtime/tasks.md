# Tasks: optimize-event-loop-and-runtime

> 實作前先讀本 change 的 `design.md`——所有 file:line、行為契約、已查證的相容性事實與「不要做」的提醒都在裡面（例：LarkClient 已有鎖不要重複加、不能直接用 FastAPI 內建 ORJSONResponse）。行號若已漂移，以符號名重新定位。

## 1. Lark 同步呼叫離載（design D1）

- [x] 1.1 盤點 async→sync 邊界：`rg -n "lark_client\.|auth_manager\.get_tenant_access_token" app/ --type py`（排除 testsuite 與同步 client 內部）比對 design D1 清單，涵蓋 `lark_users`、`lark_groups`、`test_runs`、`test_run_items`、`teams`、`attachments`、組織同步/通知與 test-result 服務，確認每條鏈的包裝點（一整段連續同步流程包一次；遇到必要的 async DB `await` 才切段）。 → verify: 盤點結果（呼叫點 → 包裝點）列入 PR 描述
- [x] 1.2 以 `await asyncio.to_thread(...)` 包裝上述全部包裝點，照抄 `app/api/jira.py:85,140,175,217,276,399` 的既有 pattern；不修改 `lark_client.py` 介面、不加新鎖（token 快取既有鎖見 `lark_client.py:32,98,518`）。 → verify: `uv run pytest app/testsuite -q -k "lark or attachment or test_run or team"` 全綠
- [x] 1.3 新增 event-loop 不阻塞回歸測試：monkeypatch Lark client 方法為 `time.sleep(2)` 的慢同步呼叫，async 併發發出一個 Lark 請求與一個 `/api/version/` 請求，斷言後者在 <1 秒內完成（證明 loop 未被佔用；修改前此測試會失敗）。 → verify: 新測試綠；暫時還原 to_thread 包裝時測試轉紅（負向驗證）

## 2. 附件下載代理改 aiohttp 串流（design D2）

- [x] 2.1 先寫行為契約測試（改實作前）：以 `aioresponses` 或 monkeypatch 模擬上游，覆蓋——上游 401→401、404→404、500→502、逾時→504、連線錯誤→502；Content-Type 轉發；`filename` 含中文時 Content-Disposition 為 RFC 5987 `filename*=UTF-8''...`；Content-Length 轉發。對照現況 `app/api/attachments.py:668-722` 撰寫預期值。 → verify: 測試對現有 requests 實作全綠（契約基準成立）
- [x] 2.2 將 `app/api/attachments.py:657` 的 `get_tenant_access_token()` 改為 `await asyncio.to_thread(...)` 包裝。 → verify: `uv run pytest app/testsuite -q -k "attachment"` 全綠
- [x] 2.3 將 `:666-713` 的 `requests.get(stream=True)` 段改為 aiohttp：`ClientTimeout(total=30)`、狀態碼檢查與 header 組裝在回傳 StreamingResponse **之前**完成、async generator 內 `iter_chunked(8192)` 並於 `finally` 釋放 response/session（session 生命週期須涵蓋整個 generator，見 design D2 陷阱提醒）；header 組裝邏輯（`:677-702`）原樣搬移不重寫；except 順序 HTTPException → `asyncio.TimeoutError`(504) → `aiohttp.ClientError`(502) → Exception(500)。 → verify: 2.1 契約測試對新實作全綠
- [x] 2.4 清理：移除該路由不再使用的 `requests` import（若檔案他處仍用則保留），`uv run ruff check app/api/attachments.py` 乾淨。 → verify: 該指令

## 3. 多 worker 操作文件（design D3）

- [x] 3.1 以 `rg -l "WEB_CONCURRENCY" docs manual README* docker/` 定位既有部署文件；就近補充：建議值（≤ CPU 核數×2）、多 worker 安全依據（`background-service-scaling` spec 的 leader election）、per-worker rate-limit 語意（N workers 下 per-IP 認證失敗限額為 N×30/min，引用 `openspec/changes/harden-app-token-security/design.md`）。不新開孤立文件。 → verify: 文件 review；`rg "WEB_CONCURRENCY"` 顯示新增內容

## 4. uvicorn[standard]（design D4，Scope B1）

- [x] 4.1 `pyproject.toml`：`"uvicorn==0.40.0"` → `"uvicorn[standard]==0.40.0"`；執行 `uv lock` 與 `uv sync`。 → verify: `uv sync` 成功；`uv run python -c "import uvloop, httptools"` 成功
- [x] 4.2 啟動煙霧驗證：以 `start.sh`（或 preview）啟動，確認服務正常回應 `/api/version/`；以 uvicorn 0.40 的 `Config(...).get_loop_factory()` 驗證 auto 模式建立 `uvloop` loop。乾淨 `uv sync` 若暴露既有 runtime 依賴漏宣告，補齊精確 pin 後重驗。 → verify: disposable SQLite bootstrap＋啟動成功、`/api/version/` 200、loop module 為 `uvloop`，且 `uv run pytest app/testsuite -q` 全綠（測試自建 loop，不受影響，見 design D4）

## 5. orjson（design D5，Scope B2）

- [x] 5.1 `uv add orjson` 並將 `pyproject.toml` 條目改為 `==` 精確 pin（沿 repo 慣例）。 → verify: `uv run python -c "import orjson"` 成功
- [x] 5.2 新增 `ORJSONCompatResponse`（繼承 `JSONResponse`，`render` 用 `orjson.dumps(content, option=orjson.OPT_NON_STR_KEYS)`，程式骨架見 design D5a），放在 utils 層級模組避免與 `app/main.py` 循環 import；`app/main.py:26` 的 `FastAPI(` 加 `default_response_class=ORJSONCompatResponse`。 → verify: `uv run pytest app/testsuite -q` 全綠
- [x] 5.3 新增 int-key 相容回歸測試：測試內臨時 router（手法比照 `app/testsuite/test_app_token_auth.py:384` 的 `_test_router`）回傳 `{1: "a"}`，斷言回應為 `{"1": "a"}` 且 200——證明與 stdlib 語意一致。 → verify: 新測試綠
- [x] 5.4 替換兩處熱點 loads（僅此兩處，其餘 stdlib json 不動）：`app/api/team_statistics.py:173` `_safe_json_loads` 與 `app/api/mcp.py:119` `_parse_json_list` 的 `json.loads` → `orjson.loads`（既有 `except json.JSONDecodeError` 不需改，`orjson.JSONDecodeError` 為其子類，見 design D5b）。 → verify: `uv run pytest app/testsuite -q -k "mcp or statistics"` 全綠（含 credential 遮蔽既有斷言）

## 6. 收尾驗證

- [ ] 6.1 全套測試：`uv run pytest app/testsuite -q` 全綠。 → verify: 該指令

  2026-07-16 實測：本 change 相關測試全綠；全套為 780 passed / 8 failed / 30 skipped。8 項失敗中 leader-lock 因既有 port 9999 server 持鎖，1 項設定測試單獨執行通過（suite state leakage），其餘 6 項在未修改區域單獨執行仍失敗，屬目前 baseline，未於本 change 擴充修正。
- [x] 6.2 Lint：`uv run ruff check <本 change 全部變更檔>` 乾淨（repo 既有未觸碰的 lint 錯誤不在範圍）。 → verify: 該指令
- [x] 6.3 `openspec validate optimize-event-loop-and-runtime --strict` 通過；tasks 勾選狀態與實作一致。 → verify: 該指令
