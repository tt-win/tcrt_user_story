## Context

`/api/app/teams/{team_id}/test-cases` 與 `/api/mcp/teams/{team_id}/test-cases`
使用相同的 `MCPTeamTestCasesResponse` schema。MCP route 已以 grouped aggregate 計算
每個 Test Case Set 的 case 數；App route 只讀取 set metadata，未傳入同名欄位，造成
schema 的 `0` 預設值被序列化。App Token route 是正式 external API，必須維持與 MCP
read model 相容。

## Goals / Non-Goals

**Goals:**

- 讓 App Token response 的每個 `sets[]` item 回傳 team-scoped、實際的
  `test_case_count`。
- 保留既有的 filter 與 pagination 語意：`page.total` 是目前 filter 後的總數；
  `sets[].test_case_count` 是整個 team 中該 set 的總數，不隨 case-list filter 改變。
- 將行為寫入 regression test 與 agent-facing App Token 文件。

**Non-Goals:**

- 不新增 endpoint、schema 欄位或資料庫 migration。
- 不修改 MCP route、JWT UI API、case 歸屬邏輯或 token scope。
- 不以逐 set N+1 API query 作為 server-side 計數策略。

## Decisions

### 在 App route 使用單次 grouped aggregate

查詢 `TestCaseLocal.test_case_set_id` 並以 `COUNT(id)` 分組，產生 `set_id → count`
map 後組裝 `sets[]`。這與 MCP route 的既有且已驗證實作一致，並保證空 set 回傳 0。

曾考慮讓 client 對每個 set 呼叫一次 `?set_id=` 再讀取 `page.total`；那可作為舊版
server 的暫時 workaround，但會造成 N+1 HTTP requests，且無法修正已宣稱相容的
response contract，因此不採用。

### set-level count 不受 case-list filter 影響

`sets[]` 是 team 的可選 Test Case Set metadata，MCP 的既有語意亦是 team-wide
count。只有 `page.total` 套用 `set_id`、search、priority、result 等當前查詢條件。

## Risks / Trade-offs

- [多一個 aggregate read query] → 使用單一 `GROUP BY`，不載入 case content，也避免
  per-set N+1 queries。
- [App/MCP 邏輯日後再次 drift] → 回歸測試驗證 App route 的 set counts，文件明確指出
  `page.total` 與 `sets[].test_case_count` 的差異。
- [部署相容性] → 僅將原有 response 欄位從錯誤預設值改為實際值，無資料轉換或 migration。

## Migration Plan

1. 部署程式與文件更新。
2. 以 App Token 對既有 team 查詢，確認 `sets[].test_case_count` 與各
   `?set_id=<id>` response 的 `page.total` 一致。
3. 若必須回滾，還原 endpoint 的 aggregate query；資料庫與 token 均不需處理。

## Open Questions

無。
