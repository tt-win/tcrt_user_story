## Why

`tools/skills/tcrt-app` 已可呼叫大多數 App Token API，但它的工作流索引、批次搬移指引與最新 API 契約已發生漂移；部分搬移路徑也缺少 impact preview、完整 cleanup 或來源 Test Run Set 狀態重算。AI Agent 若照現有文件操作，可能找不到已存在的 Test Case Set 建立能力、送錯搬移 payload，或在未理解會移除 Test Run Items 的情況下執行跨 Set 搬移。

## What Changes

- 將 `tcrt-app` 定義為受 OpenSpec 與自動化測試保護的正式可攜 AI Agent skill，補齊任務索引、Test Case Set 建立、批次建立、批次搬移、驗證與失敗復原 recipes。
- 新增 App Token Test Case 搬移 preview 與帶 impact fingerprint 的原子 mutation；確認後若案例、Run scope 或 Run Items 已改變，server 以 409 拒絕並零寫入。
- 新增多筆 Test Run Config 的明確 batch move/detach API；外部 membership mutation 必須提供預期來源，所有 production attach/detach call sites 共用同一搬移核心並重算所有實際改變的來源與目標 Test Run Set 狀態。
- 對 skill 明確區分「建立／附加／搬移／移出／複製」語意，禁止把 Test Run Item 建立描述為跨 Test Run 搬移，並列出目前不支援的 section tree 搬移、跨 config item 搬移與批次永久刪除。
- 同步最新 assignee 契約：App Token 可使用 structured Lark `assignee` 或 legacy `assignee_name`，但不得讀寫或推論 local `assignee_user_id`。
- 將 `SKILL.md` 與 references 納入版本控制，建立 skill contract tests，避免 canonical 文件再次與 API、OpenSpec 或安裝副本漂移。
- 本變更不修改資料庫 schema、不搬移既有資料、不改變 endpoint 路徑或刪除語意。新增路徑與 response 欄位為 additive；App Token 的既有 cross-Set generic update 會改為要求 guarded move，membership route 會要求 typed precondition，是刻意的安全強化。

## Capabilities

### New Capabilities

- `tcrt-app-agent-skill`: 定義可攜 skill 的可發現性、操作 recipes、安全確認、批次搬移矩陣、契約同步與可驗證性。

### Modified Capabilities

- `app-token-test-case-api`: 新增案例搬移 impact preview，並統一單筆與批次跨 Test Case Set 搬移的 Section 與 cleanup response 契約。
- `app-token-test-run-api`: 新增 Test Run Config batch move/detach，並要求所有 membership 路徑完整重算受影響 Set 且回傳可驗證摘要。
- `app-token-client-compatibility`: 新增 409 `APP_TOKEN_IMPACT_CHANGED`、`APP_TOKEN_STATE_CHANGED` 與 `APP_TOKEN_INTEGRITY_CONFLICT` 穩定錯誤，供 optimistic precondition 失效或 legacy integrity 沖突時安全停止。
- `test-run-multi-set-integrity`: 明確要求 App Token 單筆／批次案例搬移前可預覽、搬移後回傳 final cleanup，以及 Test Run membership 批次搬移不留下 stale Set status。

## Impact

- API：`app/api/app_test_cases.py`、`app/api/app_test_runs.py` 與既有 Test Case／Test Run 共用 helpers。
- Models／services：新增 request/response model 或純 service helper；無 Alembic migration、無資料格式變更。
- Tests：App Token Test Case、Test Run membership、multi-set integrity 與 skill contract focused tests。
- Skill／文件：`tools/skills/tcrt-app/`、`.gitignore`、`docs/app_token_api_reference.md`、`openspec/project.md`。
- Operational risk：跨 Test Case Set 搬移可能永久移除 out-of-scope Test Run Items；skill 必須先 preview，若影響數大於零則在 mutation 前取得針對案例、目標 Set 與移除數量的明確確認，mutation 並必須驗證同一 impact fingerprint。
- Recovery：membership move 由 response/audit 的 per-config previous→target mapping 可人工 forward-recover；無 schema downgrade。已被 cleanup 的 Run Items（含 results/history/attachments）無法由現有 API 完整還原，不宣稱可 rollback。Timeout/5xx 後的 read-back 只能證明 final placement，不能證明原請求成功或 cleanup 數量。
