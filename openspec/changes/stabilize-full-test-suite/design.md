## Context

2026-07-16 的全套測試結果為 780 passed、8 failed、30 skipped。重新單獨執行後可分成四類：

1. 六個可獨立重現的 baseline 失敗：5 筆 DB guardrail violation、QA model placeholder 測試受 process environment override、scheduled-service registry 固定筆數斷言、兩個 Helper analytics API retirement 測試，以及一個仍殘留 Helper tab marker 的 template 測試。
2. 一個只在全套出現、單獨通過的 container warning 測試，屬 process-global state 或執行順序污染。
3. 一個被開發機既有 port 9999 server 持有 production leader lock 影響的跨行程測試。
4. Helper analytics 的主 spec 仍要求提供 tab/API，但測試已要求 legacy UI 退役與 API `410`，屬規格與驗收相互矛盾。

本 change 跨越測試 fixture、設定載入、FastAPI route/UI、scheduler registry 與 DB transaction boundary，因此需要先確立「產品行為」與「測試隔離」的分界。資料庫 schema 與既有 telemetry 資料皆不變。

## Goals / Non-Goals

**Goals:**

- 讓目標失敗與 `uv run pytest app/testsuite -q` 在不干擾開發機既有 server 的前提下穩定通過。
- 以 spec 決定 Helper analytics 的退役行為，保留權限檢查與可辨識的 `410` tombstone。
- 將 runtime transaction ownership 收回 DB boundary，並對真正的離線 maintenance CLI 建立最小 policy 例外。
- 使設定、lock、singleton app state 與 registry 測試對 ambient state 和新增合法項目具有韌性。

**Non-Goals:**

- 不恢復 Helper analytics dashboard 或資料 payload，不建立 V3 替代 dashboard。
- 不新增 migration、不刪除 telemetry 資料、不改 scheduled-service registry 內容。
- 不為測試停止、重啟或修改使用者已啟動的 TCRT server。
- 不以 skip、xfail 或放寬安全／權限斷言處理失敗，也不順手清理全 repo 其他技術債。

## Decisions

### D1. 先依產品契約分類，再修實作或測試

每個失敗先回答「正式行為錯誤」或「測試前提錯誤」：

| 失敗 | 判定 | 處理方向 |
|---|---|---|
| Helper analytics API/UI | spec 漂移與 legacy marker 未完成退役 | 更新 delta spec；保留 V3 dashboard、移除 legacy marker/pipeline，新增先授權後 `410` 的 tombstone route |
| DB guardrail 5 violations | 2 筆 runtime 違規、3 筆 offline CLI 未分類 | runtime rollback 移至 boundary；offline CLI 經逐檔 review 後加入最小 policy 例外或改用 boundary |
| QA model placeholder | 測試未隔離合法 ambient env override | 測試明確清除 `QA_AI_HELPER_MODEL_SEED*`、`SEED_REFINE*`、`TESTCASE*` 後再設定案例值 |
| scheduled-service count | 測試違反可擴充 registry 契約 | 比對 service key membership／registry，不固定 `len == 1` |
| container warning | suite-only state leakage | 以完整 suite 順序定位污染來源，修復 fixture teardown 或 logger/config global state |
| leader lock | 測試與 production lock namespace 衝突 | 所有測試子行程使用同一個 per-test temp lock namespace |

替代方案是直接把現況程式碼當真相並改斷言；拒絕此方案，因為 Helper analytics 會失去可辨識退役回應，DB guardrail 也會被形式化放寬。

### D2. Helper analytics 採「V3 dashboard 保留 + legacy marker 移除 + authenticated tombstone」

使用者旅程收斂為：管理者開啟團隊統計頁時仍可使用現行 `qa-ai-helper-tab`／`qa-ai-helper-pane` V3 dashboard 與 `/qa-ai-helper/*` API，但頁面不再含 legacy `helper-ai-*` marker、`helper_ai_analytics` pipeline 或舊 tab translation key；舊 client 若呼叫 legacy endpoint，route 先走既有 current-user 與 admin role check，拒絕者回 `403`，授權者回結構化 `410`。tombstone route 不開 session 查 telemetry，也不寫入資料。

實作須清除 template 中包含 commented markup 的 forbidden markers，並將 V3 tab 改用新的三語系專用 key；現有 `loadQaAiHelperDashboard()`、helperDash renderers 與 V3 pane 必須保留。tombstone 應留在既有 admin team-statistics router，使 auth dependency 與 permission service 不另開旁路。

替代方案一是完全移除 route 並接受 `404`；舊 client 無法辨認功能退役，且繞過了「仍須管理員權限」的既定安全驗收，因此不採用。替代方案二是恢復 analytics payload；這會重新引入已退役資料管線，超出本 change。

### D3. Runtime conflict recovery 由 boundary 擁有，offline CLI 以 policy 明確分類

`AutomationEnvironmentService` 目前在 `flush()` 的 `IntegrityError` 分支直接 rollback injected session。實作時由呼叫端的 `MainAccessBoundary.run_write`（或等價受管 transaction wrapper）負責 rollback；service 只保留 domain mutation、flush 與 409 error mapping。若現有 boundary 會在 callback 丟出 `HTTPException` 時 rollback，優先沿用，不新增第二套 transaction abstraction。

兩支維護腳本先逐一確認執行入口與 transaction ownership。像 SQLite-only cleanup、一次性 attachment metadata normalization 這類不在 web runtime 執行且自行擁有 connection/session 的 CLI，可加入 `config/db_access_policy.yaml` 的精確 `offline_maintenance` 例外；不得用整個 `scripts/` 目錄放行。若某腳本已有適合的 boundary，則改用 boundary 而不加例外。

替代方案是把 `environment_service.py` 加入 allowlist；這會掩蓋正式 runtime 違規，拒絕採用。

### D4. Process lock 測試隔離 lock identity，不觸碰外部程序

SQLite leader-lock 測試的 holder／contender／release-check 子行程需共享 pytest `tmp_path` 對應的 temp namespace。優先讓子行程透過專用環境變數或 `TMPDIR` 解析到該 namespace；若 production helper 不適合由 `TMPDIR` 控制，則對 `_lock_file_path` 增加僅供明確環境覆寫的 root-dir 設定，production 未設定時仍回到 `tempfile.gettempdir()` 與固定檔名。

驗證必須同時涵蓋「外部 production lock 已被持有時測試 holder 仍成功」以及「本案例兩子行程仍互斥」，避免隔離後每個子行程各拿不同鎖而產生假陽性。

### D5. 測試 fixture 明確擁有 ambient env 與 module-global state

QA placeholder 案例只隔離會覆蓋該 YAML 路徑的 stage env keys，保留 production 的「process env 優先於 YAML」契約。container warning 的 suite-only failure 先用原始 suite order、相鄰測試縮小與重複執行找出污染者，再在污染來源 teardown 還原 logger flags、dependency overrides、singleton 或 env；不可在被害測試中用全域 reset 掩蓋來源。

所有使用 `app.dependency_overrides` 的 fixture 以 `try/finally` 或 yield teardown 還原自己新增的 key，不能 `clear()` 刪除別的 fixture 狀態。permission cache 與 scheduler singleton 同理。

### D6. Registry 測試以 key set 與 payload contract 驗證

`TaskScheduler` 已合法註冊 `lark_org_sync` 與 `audit_cleanup`。list API 測試應以 response service keys 對照 fixture scheduler registry，並針對 `lark_org_sync` 驗證 disabled/runtime fields；除非 spec 定義上限，不斷言固定總數。這只改驗收，不改 registry 或 API payload。

## Risks / Trade-offs

- [Risk] tombstone route 的順序或 dependency 設定錯誤，讓未授權者看到 `410` → 以 `403` 與 `410` 兩條 API 測試同時守門，且沿用既有 admin dependency。
- [Risk] 清理 legacy marker 時誤刪 V3 dashboard → 以 forbidden-marker 測試加上 `qa-ai-helper-tab`、`loadQaAiHelperDashboard()` 與 V3 API 既有測試守門，並跑 JavaScript syntax、三語系 key 與 lint 驗證。
- [Risk] transaction rollback 從 service 移除後，IntegrityError 使 session 停留 failed state → 由 boundary integration test 同時驗證 409、rollback 與後續 session 可用。
- [Risk] offline policy 例外變成逃生門 → 每筆只允許精確檔案，不允許目錄級 wildcard，guardrail 測試仍要求零未核准違規。
- [Risk] lock 隔離只在單一子行程有效 → 將相同 env 顯式傳給三個子行程並保留競爭、釋放後重取的負向／正向驗證。
- [Trade-off] 完整 suite 約需五分鐘；先跑六個可重現目標與 state-leak reproduction，再跑全套，減少迭代成本但最終 gate 不省略。

## Migration Plan

1. 先固定目標失敗清單與 suite-only reproduction，避免把新回歸混入 baseline。
2. 依 D2 完成 Helper analytics UI/API 退役並跑相關前後端測試與 i18n/JS 檢查。
3. 依 D3 收斂 DB boundary 與 policy，跑 guardrail 及 automation environment API/service 測試。
4. 依 D4–D6 修正測試隔離與 registry 斷言，先在既有 server 持鎖狀態下跑 leader test。
5. 連續跑目標測試與 `uv run pytest app/testsuite -q`；若 full suite 仍有 order-only failure，回到污染來源修復，不新增 skip。

無資料 migration 或部署順序需求。回退可按上述項目逐組還原；若回退 tombstone，主 spec 必須同步回退，不能留下 spec／route 不一致。

## Open Questions

- container warning 的確切污染來源需在 apply 階段以 full-suite order 縮小後確認；本 design 不先假定是 logger、env 或 app singleton。
- 兩支 offline maintenance CLI 經 review 後是改用 boundary 或加入 policy 例外，依其既有 transaction ownership 與跨引擎需求逐檔決定。
