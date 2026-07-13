## Context

App Token 已能透過 `PUT .../items/{item_id}` 更新 execution result，但 canonical
`/api/app/*` 沒有同一 collection 的 read route。`GET /test-runs` 只回傳 config aggregates，
無法識別 item 或保存其既有 result，因此 agent 無法安全完成 bulk-like workflow。

## Goals / Non-Goals

**Goals:**

- 提供 team- and config-scoped、paginated 的 App Token item list。
- 最小化 response，只回傳 result 更新與回復所需的 item metadata。
- 使用既有 App Token principal、team access 與 `test_run:read` scope guard。

**Non-Goals:**

- 不增加批次更新、bulk success 操作或新的 mutation scope。
- 不暴露 test case steps、expected result、attachments、test data 或完整 assignee profile。
- 不改變 JWT item API 與既有單筆 App Token update semantics。

## Decisions

### 以 collection GET 與單筆 update 同一路徑配對

新增 `GET /api/app/teams/{team_id}/test-run-configs/{config_id}/items`，採 `skip` / `limit`
pagination，穩定按 item ID 升冪排序。response 包含 `id`、`test_case_number`、`test_result`、
`executed_at`、`execution_duration`、`assignee_name`、`updated_at` 和 page metadata。

不重用 JWT API 的完整 `TestRunItemResponse`，因其含有不必要的 case snapshot 與附件欄位；
採用 App Token 專用的最小 schema。這讓 skill 能建立 result snapshot 後，以既有 PUT
逐筆更新或 forward recover。

### 使用 read scope 與既有 config/team 驗證

route 先驗證 App Token team scope，再要求 `test_run:read`，最後在 read boundary 中驗證
config 屬於該 team。這與既有 App Token mutation 的 team boundary 一致，避免可猜測的
config ID 洩漏跨 team item metadata。

## Risks / Trade-offs

- [逐筆 bulk workflow 可能部分成功] → skill 必須先 snapshot，失敗時用既有 PUT 逐筆
  forward recover；batch mutation 不在本 change 範圍。
- [讀取 metadata 洩漏] → response 白名單化，不包含 case content / credential data，且套用
  read scope 與 team guard。
- [大量 config items] → pagination 上限限制 response 大小，固定排序讓 client 可安全遍歷。

## Migration Plan

1. 部署新增 GET route 與文件。
2. skill 先讀取所有分頁並保存 execution snapshot，才對每個 item 發送既有 PUT。
3. 若需回滾，停用此 GET route；不涉及 schema 或既有 item data 的轉換。

## Open Questions

無。
