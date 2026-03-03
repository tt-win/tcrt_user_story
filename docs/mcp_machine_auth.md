# MCP Machine Auth 與 Read API 使用說明

本文件說明如何在 TCRT 啟用 MCP 專用唯讀存取：
- 使用 `machine token`（非互動式）
- 權限必須為 `mcp_read`
- 僅可呼叫 `/api/mcp/*` 讀取端點

## 1. 憑證模型

資料表：`mcp_machine_credentials`

關鍵欄位：
- `name`: 憑證名稱（唯一）
- `token_hash`: token 的 SHA256（不存明文）
- `permission`: 固定使用 `mcp_read`
- `status`: `active` / `revoked`
- `allow_all_teams`: 是否可讀全部團隊
- `team_scope_json`: allow-list team id（JSON 陣列，例如 `[1,3]`）
- `expires_at`: 到期時間（UTC，可空）

## 2. 建立 machine token

先產生隨機 token（只顯示一次，請妥善保存）：

```bash
openssl rand -hex 32
```

假設 token 為 `<RAW_TOKEN>`，計算 SHA256：

```bash
printf '%s' '<RAW_TOKEN>' | shasum -a 256
```

將雜湊值寫入 DB（`token_hash`）：

```sql
INSERT INTO mcp_machine_credentials
  (name, token_hash, permission, status, allow_all_teams, team_scope_json, expires_at, created_at, updated_at)
VALUES
  ('mcp-prod-reader',
   '<SHA256_HEX>',
   'mcp_read',
   'active',
   0,
   '[1,3]',
   '2026-12-31 23:59:59',
   CURRENT_TIMESTAMP,
   CURRENT_TIMESTAMP);
```

## 3. 呼叫 MCP API

使用 `Authorization: Bearer <RAW_TOKEN>`。

### 3.1 團隊列表

```bash
curl -H "Authorization: Bearer <RAW_TOKEN>" \
  "http://127.0.0.1:9999/api/mcp/teams"
```

### 3.2 Team Test Cases（含 filter）

```bash
curl -G -H "Authorization: Bearer <RAW_TOKEN>" \
  "http://127.0.0.1:9999/api/mcp/teams/1/test-cases" \
  --data-urlencode "set_id=10" \
  --data-urlencode "search=login" \
  --data-urlencode "priority=High" \
  --data-urlencode "test_result=Passed" \
  --data-urlencode "assignee=alice" \
  --data-urlencode "skip=0" \
  --data-urlencode "limit=100"
```

### 3.3 Team Test Runs（set / unassigned / adhoc）

```bash
curl -G -H "Authorization: Bearer <RAW_TOKEN>" \
  "http://127.0.0.1:9999/api/mcp/teams/1/test-runs" \
  --data-urlencode "status=active,completed" \
  --data-urlencode "run_type=all" \
  --data-urlencode "include_archived=false"
```

`run_type` 可用值：
- `set`
- `unassigned`
- `adhoc`
- `all`

## 4. 授權與拒絕規則

- token 無效/過期/revoked：`401`
- 憑證非 `mcp_read`：`403`
- 請求 team 不在 scope：`403`
- `allow_all_teams=false` 且 `team_scope_json` 空陣列：無任何 team 存取權限

## 5. 稽核紀錄

每次 MCP 請求皆會寫入 audit（allow/deny）：
- 機器憑證身分（credential id/name）
- endpoint 與 method
- target team 與 scope 判斷結果
- deny reason（例如 `team_scope_denied`）

## 6. 備註

目前版本先支援 `opaque machine token` 流程；如需導入 service account JWT，可在此基礎上擴充簽章驗證與金鑰輪替策略。
